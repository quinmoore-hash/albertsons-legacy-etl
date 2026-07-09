"""Tests for the configuration loader."""

from __future__ import annotations

import pytest

from etl import config
from etl.config import ConfigError, Settings, access_secret


def test_settings_from_env(settings: Settings):
    assert settings.gcp_project == "albertsons-retail-analytics"
    assert settings.bq_dataset == "store_ops"
    assert settings.bq_location == "US"
    assert settings.gcs_bucket == "albertsons-etl-landing"
    assert settings.pos_api_retry_count == 2
    assert settings.dataset_ref() == "albertsons-retail-analytics.store_ops"
    assert len(settings.data_dirs()) == 5


def test_missing_required_raises(monkeypatch):
    monkeypatch.delenv("GCP_PROJECT", raising=False)
    monkeypatch.delenv("BQ_DATASET", raising=False)
    monkeypatch.delenv("GCS_BUCKET", raising=False)
    monkeypatch.delenv("DATA_INPUT_DIR", raising=False)
    with pytest.raises(ConfigError):
        Settings.from_env()


def test_no_snowflake_attributes(settings: Settings):
    # SNOWFLAKE_* must be gone from the config surface.
    for name in vars(settings):
        assert "snowflake" not in name.lower()


def test_secret_env_override_short_circuits(monkeypatch):
    monkeypatch.setenv("POS_API_KEY", "override-value")
    # env_override is honored without touching Secret Manager
    value = access_secret("proj", "pos-api-key", env_override="POS_API_KEY")
    assert value == "override-value"


def test_pos_api_key_property_uses_override(settings: Settings):
    assert settings.pos_api_key == "test-pos-key"
    assert settings.slack_webhook_url.endswith("/HOOK/URL")


def test_get_settings_cached(env_settings):
    config.get_settings.cache_clear()
    a = config.get_settings()
    b = config.get_settings()
    assert a is b
