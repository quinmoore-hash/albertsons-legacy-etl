"""Tests for the POS fetch step (HTTP mocked)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from etl.fetch_pos_data import fetch_pos_data


def test_fetch_success(settings):
    out = Path(settings.data_input_dir) / "pos.csv"
    session = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.content = b"store_id,v\n0412,1\n0731,2\n"
    session.get.return_value = resp

    rc = fetch_pos_data(out, "2026-07-09", settings=settings, session=session)
    assert rc == 0
    assert out.read_bytes() == resp.content

    _, kwargs = session.get.call_args
    assert kwargs["headers"]["X-Api-Key"] == "test-pos-key"
    assert kwargs["params"] == {"date": "2026-07-09", "format": "csv"}


def test_fetch_retries_then_fails(settings, monkeypatch):
    monkeypatch.setattr("etl.fetch_pos_data.time.sleep", lambda *_: None)
    out = Path(settings.data_input_dir) / "pos.csv"
    session = MagicMock()
    resp = MagicMock()
    resp.status_code = 503
    session.get.return_value = resp

    rc = fetch_pos_data(out, "2026-07-09", settings=settings, session=session)
    assert rc == 1
    # retry count from settings == 2
    assert session.get.call_count == 2
