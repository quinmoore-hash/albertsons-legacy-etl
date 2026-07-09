"""Central configuration for the Albertsons store ETL.

Reads settings from a ``pipeline.env``-style file (simple ``KEY=value`` lines,
optionally quoted) and from the process environment. Environment variables
always take precedence over the file so the same code runs unchanged on a
workstation, in a Cloud Run job, or inside a Cloud Composer worker.

All Snowflake settings have been removed as part of the 2026-Q2 BigQuery
migration; the warehouse now lives in
``albertsons-retail-analytics.store_ops`` on BigQuery.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Repository root (two levels up from this file: etl/config.py -> repo root).
REPO_ROOT = Path(__file__).resolve().parent.parent

# Default config file shipped in the repo.
DEFAULT_CONFIG_FILE = REPO_ROOT / "configs" / "pipeline.env"


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a ``KEY=value`` file, ignoring comments and blank lines.

    Surrounding single/double quotes are stripped. ``export KEY=value`` is
    supported. This intentionally does not evaluate shell expansions.
    """
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        values[key] = val
    return values


@dataclass(frozen=True)
class Config:
    """Resolved ETL configuration."""

    # GCP / BigQuery
    gcp_project: str
    gcp_region: str
    bq_dataset: str
    bq_location: str
    gcs_bucket: str

    # Vendor POS API
    pos_api_base_url: str
    pos_api_timeout: int
    pos_api_retry_count: int

    # Local working directories
    data_input_dir: Path
    data_output_dir: Path
    data_staging_dir: Path
    data_archive_dir: Path
    data_error_dir: Path

    # Logging
    log_dir: Path
    log_level: str
    log_retention_days: int

    # Processing knobs
    batch_size: int
    retention_days: int

    # Secret Manager secret ids (resolved lazily at runtime, never stored here)
    pos_api_key_secret: str
    slack_webhook_secret: str

    # Alerting routing (non-secret)
    alert_email: str
    smtp_host: str
    smtp_port: int
    smtp_from: str

    raw: dict[str, str] = field(default_factory=dict, repr=False)

    def get(self, key: str, default: str | None = None) -> str | None:
        return self.raw.get(key, default)


def _lookup(file_values: dict[str, str], key: str, default: str = "") -> str:
    """Environment variable wins, then the config file, then the default."""
    if key in os.environ and os.environ[key] != "":
        return os.environ[key]
    return file_values.get(key, default)


def load_config(config_file: str | os.PathLike[str] | None = None) -> Config:
    """Load configuration from ``config_file`` (default ``configs/pipeline.env``).

    Missing values fall back to sensible defaults so the modules can be
    imported and unit-tested without a fully provisioned environment.
    """
    path = Path(config_file) if config_file else DEFAULT_CONFIG_FILE
    file_values = _parse_env_file(path)

    def val(key: str, default: str = "") -> str:
        return _lookup(file_values, key, default)

    def as_path(key: str, default: str) -> Path:
        return Path(val(key, default)).expanduser()

    def as_int(key: str, default: int) -> int:
        try:
            return int(val(key, str(default)))
        except (TypeError, ValueError):
            return default

    return Config(
        gcp_project=val("GCP_PROJECT", "albertsons-retail-analytics"),
        gcp_region=val("GCP_REGION", "us-central1"),
        bq_dataset=val("BQ_DATASET", "store_ops"),
        bq_location=val("BQ_LOCATION", "US"),
        gcs_bucket=val("GCS_BUCKET", "albertsons-etl-landing"),
        pos_api_base_url=val("POS_API_BASE_URL", "https://api.retailfeed-vendor.com/v2"),
        pos_api_timeout=as_int("POS_API_TIMEOUT", 30),
        pos_api_retry_count=as_int("POS_API_RETRY_COUNT", 3),
        data_input_dir=as_path("DATA_INPUT_DIR", str(REPO_ROOT / "data" / "incoming")),
        data_output_dir=as_path("DATA_OUTPUT_DIR", str(REPO_ROOT / "data" / "processed")),
        data_staging_dir=as_path("DATA_STAGING_DIR", str(REPO_ROOT / "data" / "staging")),
        data_archive_dir=as_path("DATA_ARCHIVE_DIR", str(REPO_ROOT / "data" / "archive")),
        data_error_dir=as_path("DATA_ERROR_DIR", str(REPO_ROOT / "data" / "errors")),
        log_dir=as_path("LOG_DIR", str(REPO_ROOT / "logs")),
        log_level=val("LOG_LEVEL", "INFO"),
        log_retention_days=as_int("LOG_RETENTION_DAYS", 45),
        batch_size=as_int("BATCH_SIZE", 20000),
        retention_days=as_int("RETENTION_DAYS", 30),
        pos_api_key_secret=val("POS_API_KEY_SECRET", "pos-api-key"),
        slack_webhook_secret=val("SLACK_WEBHOOK_SECRET", "slack-webhook-url"),
        alert_email=val("ALERT_EMAIL", "store-data-ops@albertsons.com"),
        smtp_host=val("SMTP_HOST", "smtp.albertsons.internal"),
        smtp_port=as_int("SMTP_PORT", 587),
        smtp_from=val("SMTP_FROM", "store-etl-alerts@albertsons.com"),
        raw=file_values,
    )
