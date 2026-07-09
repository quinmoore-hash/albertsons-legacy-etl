"""Configuration loader for the Albertsons ETL pipeline.

Replaces the legacy ``configs/pipeline.env`` file that every Bash script used
to ``source``. Configuration now comes from environment variables (a
``Settings`` object), and the two secrets the pipeline needs -- ``POS_API_KEY``
and ``SLACK_WEBHOOK_URL`` -- are pulled from Google Secret Manager instead of
being stored in plaintext.

All ``SNOWFLAKE_*`` configuration has been dropped: the Snowflake warehouse was
decommissioned in the 2026-Q2 migration and the pipeline now targets BigQuery.

Local development / tests may set ``POS_API_KEY`` / ``SLACK_WEBHOOK_URL``
directly in the environment, which takes precedence over Secret Manager so the
pipeline can run without GCP credentials.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


def _get_env(name: str, default: Optional[str] = None, required: bool = False) -> str:
    value = os.environ.get(name, default)
    if required and (value is None or value == ""):
        raise ConfigError(f"Required environment variable {name} is not set")
    return value if value is not None else ""


def _get_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"Environment variable {name}={raw!r} is not an integer") from exc


def access_secret(
    project: str,
    secret_id: str,
    version: str = "latest",
    env_override: Optional[str] = None,
) -> str:
    """Return a secret value from Google Secret Manager.

    If ``env_override`` names an environment variable that is set, its value is
    returned instead (handy for local development and tests, and to avoid a
    round-trip to Secret Manager when a value is already available).
    """
    if env_override:
        override = os.environ.get(env_override)
        if override:
            return override

    # Imported lazily so that importing this module (e.g. in unit tests that
    # only exercise the plain config values) does not require the GCP client.
    from google.cloud import secretmanager

    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project}/secrets/{secret_id}/versions/{version}"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8")


@dataclass
class Settings:
    """Typed, immutable-ish view of the pipeline configuration."""

    # --- GCP / BigQuery / GCS ---
    gcp_project: str
    gcp_region: str
    bq_dataset: str
    bq_location: str
    gcs_bucket: str

    # --- Filesystem staging paths ---
    etl_home: str
    data_input_dir: str
    data_output_dir: str
    data_staging_dir: str
    data_archive_dir: str
    data_error_dir: str

    # --- Logging ---
    log_dir: str
    log_level: str
    log_retention_days: int

    # --- Vendor POS API ---
    pos_api_base_url: str
    pos_api_timeout: int
    pos_api_retry_count: int

    # --- Alerting ---
    alert_email: str

    # --- Processing knobs ---
    csv_delimiter: str
    batch_size: int
    retention_days: int

    # --- Secret Manager wiring ---
    pos_api_key_secret: str
    slack_webhook_secret: str

    # Cached secret values (populated lazily).
    _pos_api_key: Optional[str] = field(default=None, repr=False, compare=False)
    _slack_webhook_url: Optional[str] = field(default=None, repr=False, compare=False)

    @classmethod
    def from_env(cls) -> "Settings":
        """Build a ``Settings`` instance from the process environment."""
        return cls(
            gcp_project=_get_env("GCP_PROJECT", required=True),
            gcp_region=_get_env("GCP_REGION", "us-central1"),
            bq_dataset=_get_env("BQ_DATASET", required=True),
            bq_location=_get_env("BQ_LOCATION", "US"),
            gcs_bucket=_get_env("GCS_BUCKET", required=True),
            etl_home=_get_env("ETL_HOME", os.getcwd()),
            data_input_dir=_get_env("DATA_INPUT_DIR", required=True),
            data_output_dir=_get_env("DATA_OUTPUT_DIR", required=True),
            data_staging_dir=_get_env("DATA_STAGING_DIR", required=True),
            data_archive_dir=_get_env("DATA_ARCHIVE_DIR", required=True),
            data_error_dir=_get_env("DATA_ERROR_DIR", required=True),
            log_dir=_get_env("LOG_DIR", "/var/log/albertsons/etl"),
            log_level=_get_env("LOG_LEVEL", "INFO").upper(),
            log_retention_days=_get_int_env("LOG_RETENTION_DAYS", 45),
            pos_api_base_url=_get_env("POS_API_BASE_URL", required=True),
            pos_api_timeout=_get_int_env("POS_API_TIMEOUT", 30),
            pos_api_retry_count=_get_int_env("POS_API_RETRY_COUNT", 3),
            alert_email=_get_env("ALERT_EMAIL", "store-data-ops@albertsons.com"),
            csv_delimiter=_get_env("CSV_DELIMITER", ","),
            batch_size=_get_int_env("BATCH_SIZE", 20000),
            retention_days=_get_int_env("RETENTION_DAYS", 30),
            pos_api_key_secret=_get_env("POS_API_KEY_SECRET", "pos-api-key"),
            slack_webhook_secret=_get_env("SLACK_WEBHOOK_SECRET", "slack-webhook-url"),
        )

    @property
    def pos_api_key(self) -> str:
        """POS vendor API key, resolved from Secret Manager (cached)."""
        if self._pos_api_key is None:
            self._pos_api_key = access_secret(
                self.gcp_project,
                self.pos_api_key_secret,
                env_override="POS_API_KEY",
            )
        return self._pos_api_key

    @property
    def slack_webhook_url(self) -> str:
        """Slack incoming-webhook URL, resolved from Secret Manager (cached)."""
        if self._slack_webhook_url is None:
            self._slack_webhook_url = access_secret(
                self.gcp_project,
                self.slack_webhook_secret,
                env_override="SLACK_WEBHOOK_URL",
            )
        return self._slack_webhook_url

    def dataset_ref(self) -> str:
        """Fully qualified ``project.dataset`` reference."""
        return f"{self.gcp_project}.{self.bq_dataset}"

    def data_dirs(self) -> list[str]:
        """All filesystem staging directories, in creation order."""
        return [
            self.data_input_dir,
            self.data_output_dir,
            self.data_staging_dir,
            self.data_archive_dir,
            self.data_error_dir,
        ]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached ``Settings`` instance."""
    return Settings.from_env()
