"""Shared pytest fixtures for the Albertsons ETL test suite."""

from __future__ import annotations

import pytest

from etl import config
from etl.config import Settings


@pytest.fixture
def env_settings(tmp_path, monkeypatch):
    """Populate the environment with a valid pipeline config using tmp dirs.

    Also sets the secret env-overrides so no Secret Manager call is made.
    """
    dirs = {
        "DATA_INPUT_DIR": tmp_path / "incoming",
        "DATA_OUTPUT_DIR": tmp_path / "processed",
        "DATA_STAGING_DIR": tmp_path / "staging",
        "DATA_ARCHIVE_DIR": tmp_path / "archive",
        "DATA_ERROR_DIR": tmp_path / "errors",
        "LOG_DIR": tmp_path / "logs",
    }
    for value in dirs.values():
        value.mkdir(parents=True, exist_ok=True)

    env = {
        "GCP_PROJECT": "albertsons-retail-analytics",
        "GCP_REGION": "us-central1",
        "BQ_DATASET": "store_ops",
        "BQ_LOCATION": "US",
        "GCS_BUCKET": "albertsons-etl-landing",
        "POS_API_BASE_URL": "https://api.retailfeed-vendor.com/v2",
        "POS_API_TIMEOUT": "5",
        "POS_API_RETRY_COUNT": "2",
        "LOG_LEVEL": "DEBUG",
        "POS_API_KEY": "test-pos-key",
        "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/TEST/HOOK/URL",
        "ETL_LOCK_PATH": str(tmp_path / "etl.lock"),
    }
    env.update({k: str(v) for k, v in dirs.items()})
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    config.get_settings.cache_clear()
    yield {**env}
    config.get_settings.cache_clear()


@pytest.fixture
def settings(env_settings) -> Settings:
    return Settings.from_env()
