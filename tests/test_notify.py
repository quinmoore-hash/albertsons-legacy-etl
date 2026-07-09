"""Tests for Slack/email notifications (network + SMTP mocked)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from etl import notify
from etl.notify import Notifier, load_alerting_config

ALERTING_CONF = """
[slack]
enabled=true
channel=#store-etl-alerts
mention_on_critical=@here

[email]
enabled=true
smtp_host=smtp.albertsons.internal
smtp_port=587
from=store-etl-alerts@albertsons.com
to=store-data-ops@albertsons.com
cc=retail-data-eng@albertsons.com
"""


@pytest.fixture
def conf_file(tmp_path):
    path = tmp_path / "alerting.conf"
    path.write_text(ALERTING_CONF, encoding="utf-8")
    return path


def test_load_alerting_config_handles_url_with_equals(tmp_path):
    path = tmp_path / "a.conf"
    path.write_text("[slack]\nwebhook=https://x/y?a=b&c=d\n", encoding="utf-8")
    cfg = load_alerting_config(path)
    # value containing '=' is preserved (the sed/grep parser would truncate it)
    assert cfg.get("slack", "webhook") == "https://x/y?a=b&c=d"


def test_send_slack_payload(settings, conf_file):
    session = MagicMock()
    session.post.return_value.raise_for_status.return_value = None
    n = Notifier(settings=settings, alerting_conf=conf_file, session=session)

    assert n.send_slack("hello", "INFO") is True
    url, kwargs = session.post.call_args
    payload = kwargs["json"]
    att = payload["attachments"][0]
    assert att["color"] == "good"
    assert att["text"] == "hello"
    assert payload["channel"] == "#store-etl-alerts"


def test_send_slack_critical_mention(settings, conf_file):
    session = MagicMock()
    n = Notifier(settings=settings, alerting_conf=conf_file, session=session)
    n.send_slack("db down", "CRITICAL")
    att = session.post.call_args.kwargs["json"]["attachments"][0]
    assert att["color"] == "danger"
    assert att["text"].startswith("@here ")


def test_send_slack_disabled(settings, tmp_path):
    path = tmp_path / "a.conf"
    path.write_text("[slack]\nenabled=false\n", encoding="utf-8")
    session = MagicMock()
    n = Notifier(settings=settings, alerting_conf=path, session=session)
    assert n.send_slack("hi") is False
    session.post.assert_not_called()


def test_send_email(settings, conf_file, monkeypatch):
    smtp_instance = MagicMock()
    smtp_ctx = MagicMock()
    smtp_ctx.__enter__.return_value = smtp_instance
    smtp_factory = MagicMock(return_value=smtp_ctx)
    monkeypatch.setattr(notify.smtplib, "SMTP", smtp_factory)

    n = Notifier(settings=settings, alerting_conf=conf_file, session=MagicMock())
    assert n.send_email("subj", "body") is True

    smtp_factory.assert_called_once_with("smtp.albertsons.internal", 587, timeout=30)
    smtp_instance.send_message.assert_called_once()


def test_alert_warning_slacks_and_emails(settings, conf_file, monkeypatch):
    n = Notifier(settings=settings, alerting_conf=conf_file, session=MagicMock())
    n.send_slack = MagicMock(return_value=True)
    n.send_email = MagicMock(return_value=True)

    n.alert("something", "WARNING")
    n.send_slack.assert_called_once_with("something", "WARNING")
    n.send_email.assert_called_once()


def test_alert_info_only_slacks(settings, conf_file):
    n = Notifier(settings=settings, alerting_conf=conf_file, session=MagicMock())
    n.send_slack = MagicMock(return_value=True)
    n.send_email = MagicMock(return_value=True)

    n.alert("ok", "INFO")
    n.send_slack.assert_called_once()
    n.send_email.assert_not_called()
