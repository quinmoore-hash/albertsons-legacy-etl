"""Slack + email notifications for the Albertsons ETL pipeline.

Python replacement for ``utils/notify.sh``. Parses ``configs/alerting.conf``
(an INI file) for routing/thresholds, posts JSON to a Slack incoming webhook
via :mod:`requests`, sends email via :mod:`smtplib`, and exposes an ``alert()``
convenience that logs, Slacks, and (on WARNING/CRITICAL) emails.

The Slack webhook URL itself is resolved from Secret Manager via
:class:`etl.config.Settings`, not from the plaintext value in
``configs/alerting.conf`` / ``configs/pipeline.env``.
"""

from __future__ import annotations

import configparser
import smtplib
import socket
import time
from email.message import EmailMessage
from pathlib import Path
from typing import Optional

import requests

from etl.config import Settings, get_settings
from etl.logging_util import log_error, log_info, log_warn

DEFAULT_ALERTING_CONF = Path(__file__).resolve().parent.parent / "configs" / "alerting.conf"

_SEVERITY_COLORS = {
    "INFO": "good",
    "WARNING": "warning",
    "CRITICAL": "danger",
}


def load_alerting_config(path: Optional[Path | str] = None) -> configparser.ConfigParser:
    """Parse ``alerting.conf`` into a :class:`configparser.ConfigParser`.

    Unlike the brittle ``sed``/``grep`` parser in the Bash version, this handles
    values containing ``=`` correctly.
    """
    parser = configparser.ConfigParser()
    conf_path = Path(path) if path else DEFAULT_ALERTING_CONF
    if conf_path.is_file():
        parser.read(conf_path)
    return parser


class Notifier:
    """Sends Slack and email alerts using pipeline settings + alerting.conf."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        alerting_conf: Optional[Path | str] = None,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.config = load_alerting_config(alerting_conf)
        self.session = session or requests.Session()

    # -- config helpers -------------------------------------------------
    def _conf(self, section: str, key: str, fallback: str = "") -> str:
        return self.config.get(section, key, fallback=fallback)

    def _conf_bool(self, section: str, key: str, fallback: bool = True) -> bool:
        return self.config.getboolean(section, key, fallback=fallback)

    # -- Slack ----------------------------------------------------------
    def send_slack(self, message: str, severity: str = "INFO") -> bool:
        """POST an attachment-formatted message to the Slack webhook.

        Returns ``True`` on success. Mirrors the color/severity mapping and the
        ``@here`` critical mention behavior of the Bash ``send_slack``.
        """
        severity = severity.upper()
        if not self._conf_bool("slack", "enabled", True):
            log_info("Slack disabled in alerting.conf; skipping notification")
            return False

        try:
            webhook = self.settings.slack_webhook_url
        except Exception as exc:  # secret fetch failure should not be fatal
            log_error("Could not resolve Slack webhook: %s", exc)
            return False
        if not webhook:
            log_warn("Slack webhook not configured, skipping notification")
            return False

        color = _SEVERITY_COLORS.get(severity, "good")
        channel = self._conf("slack", "channel")

        if severity == "CRITICAL":
            mention = self._conf("slack", "mention_on_critical")
            if mention:
                message = f"{mention} {message}"

        attachment = {
            "color": color,
            "title": f"Albertsons ETL Alert [{severity}]",
            "text": message,
            "footer": f"albertsons-etl | {socket.gethostname()}",
            "ts": int(time.time()),
        }
        payload = {"attachments": [attachment]}
        if channel:
            payload["channel"] = channel

        try:
            resp = self.session.post(webhook, json=payload, timeout=10)
            resp.raise_for_status()
        except requests.RequestException as exc:
            log_error("Failed to send Slack notification: %s", exc)
            return False
        return True

    # -- Email ----------------------------------------------------------
    def send_email(self, subject: str, body: str, to: Optional[str] = None) -> bool:
        """Send an email alert via SMTP (STARTTLS)."""
        if not self._conf_bool("email", "enabled", True):
            log_info("Email disabled in alerting.conf; skipping notification")
            return False

        smtp_host = self._conf("email", "smtp_host")
        smtp_port = self.config.getint("email", "smtp_port", fallback=587)
        from_addr = self._conf("email", "from", "store-etl-alerts@albertsons.com")
        to_addr = to or self._conf("email", "to") or self.settings.alert_email
        cc_addr = self._conf("email", "cc")

        if not smtp_host or not to_addr:
            log_warn("Email not fully configured (smtp_host/to missing); skipping")
            return False

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to_addr
        recipients = [to_addr]
        if cc_addr:
            msg["Cc"] = cc_addr
            recipients.extend(a.strip() for a in cc_addr.split(",") if a.strip())
        msg.set_content(body)

        try:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
                server.ehlo()
                try:
                    server.starttls()
                    server.ehlo()
                except smtplib.SMTPException:
                    # Server without STARTTLS support; proceed unencrypted
                    # (matches the legacy mailx behavior on the internal relay).
                    pass
                server.send_message(msg, from_addr=from_addr, to_addrs=recipients)
        except (smtplib.SMTPException, OSError) as exc:
            log_warn("Email send failed: %s", exc)
            return False
        return True

    # -- Convenience ----------------------------------------------------
    def alert(self, message: str, severity: str = "INFO") -> None:
        """Log, Slack, and (on WARNING/CRITICAL) email an alert."""
        severity = severity.upper()
        log_info("Sending alert [%s]: %s", severity, message)
        self.send_slack(message, severity)
        if severity in ("CRITICAL", "WARNING"):
            self.send_email(f"[{severity}] Albertsons ETL Alert", message)


_default_notifier: Optional[Notifier] = None


def get_notifier() -> Notifier:
    """Return a process-wide cached :class:`Notifier`."""
    global _default_notifier
    if _default_notifier is None:
        _default_notifier = Notifier()
    return _default_notifier


def send_slack(message: str, severity: str = "INFO") -> bool:
    return get_notifier().send_slack(message, severity)


def send_email(subject: str, body: str, to: Optional[str] = None) -> bool:
    return get_notifier().send_email(subject, body, to)


def alert(message: str, severity: str = "INFO") -> None:
    get_notifier().alert(message, severity)
