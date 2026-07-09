"""Slack + email alerting, ported from ``utils/notify.sh``.

Slack notifications go to the incoming webhook (loaded from Secret Manager);
email goes out over SMTP. :func:`alert` preserves the legacy convenience
behaviour: it always posts to Slack and additionally emails on ``WARNING`` /
``CRITICAL``.
"""

from __future__ import annotations

import smtplib
import time
from email.message import EmailMessage
from enum import Enum

import requests

from etl.config import Config, load_config
from etl.logging_setup import get_logger
from etl.secrets import get_secret

logger = get_logger(__name__)

_SLACK_COLORS = {"INFO": "good", "WARNING": "warning", "CRITICAL": "danger"}
_EMAIL_SEVERITIES = {"WARNING", "CRITICAL"}


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


def _slack_webhook(config: Config) -> str | None:
    try:
        return get_secret(config.slack_webhook_secret, config.gcp_project)
    except Exception as exc:  # pragma: no cover - depends on GCP env
        logger.warning("Could not load Slack webhook secret: %s", exc)
        return None


def send_slack(
    message: str,
    severity: str = "INFO",
    config: Config | None = None,
    timeout: int = 10,
) -> bool:
    """Post ``message`` to the Slack incoming webhook. Returns success."""
    config = config or load_config()
    webhook = _slack_webhook(config)
    if not webhook:
        logger.warning("Slack webhook not configured, skipping notification")
        return False

    severity = severity.upper()
    color = _SLACK_COLORS.get(severity, "good")
    text = f"<!here> {message}" if severity == "CRITICAL" else message

    payload = {
        "attachments": [
            {
                "color": color,
                "title": f"Albertsons ETL Alert [{severity}]",
                "text": text,
                "footer": "albertsons-etl",
                "ts": int(time.time()),
            }
        ]
    }

    try:
        resp = requests.post(webhook, json=payload, timeout=timeout)
        resp.raise_for_status()
        return True
    except requests.RequestException as exc:
        logger.error("Failed to send Slack notification: %s", exc)
        return False


def send_email(
    subject: str,
    body: str,
    to: str | None = None,
    config: Config | None = None,
    timeout: int = 30,
) -> bool:
    """Send an email alert over SMTP. Returns success."""
    config = config or load_config()
    recipient = to or config.alert_email

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = config.smtp_from
    msg["To"] = recipient
    msg.set_content(body)

    try:
        with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=timeout) as smtp:
            # Upgrade to TLS so alert contents aren't sent in cleartext. Skip
            # only if the server doesn't advertise STARTTLS.
            smtp.ehlo()
            if smtp.has_extn("starttls"):
                smtp.starttls()
                smtp.ehlo()
            smtp.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError) as exc:
        logger.warning("Email send failed (%s): %s", config.smtp_host, exc)
        return False


def alert(message: str, severity: str = "INFO", config: Config | None = None) -> None:
    """Convenience alert: Slack always; email on WARNING/CRITICAL."""
    config = config or load_config()
    severity = severity.upper()
    logger.info("Sending alert [%s]: %s", severity, message)

    send_slack(message, severity, config=config)

    if severity in _EMAIL_SEVERITIES:
        send_email(f"[{severity}] Albertsons ETL Alert", message, config=config)
