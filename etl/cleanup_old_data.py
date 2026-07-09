"""Retention-based cleanup of old local and GCS files.

Ported from ``scripts/cleanup_old_data.sh``. Deletes local processed/archive/
error files and log files past their retention, and prunes old GCS archive
objects. The dangerous ``rm -rf /tmp/albertsons_*`` and the ``sleep 30`` lock
workaround are removed — the orchestrator (Composer/Cloud Run) now handles
concurrency, so cleanup no longer races the nightly ETL.
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from etl.config import Config, load_config
from etl.logging_setup import configure_logging, get_logger

if TYPE_CHECKING:  # pragma: no cover
    from google.cloud import storage

logger = get_logger(__name__)


def _delete_older_than(directory: Path, days: int, pattern: str = "*") -> int:
    """Delete files under ``directory`` matching ``pattern`` older than ``days``."""
    if not directory.exists():
        return 0
    cutoff = time.time() - days * 86400
    deleted = 0
    for path in directory.rglob(pattern):
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink()
            deleted += 1
    return deleted


def cleanup_local(config: Config | None = None) -> int:
    """Prune old local files per retention policy. Returns files deleted."""
    config = config or load_config()
    retention = config.retention_days
    total = 0

    total += _delete_older_than(config.data_output_dir, retention)
    total += _delete_older_than(config.data_archive_dir, retention)
    total += _delete_older_than(config.data_error_dir, 60)
    total += _delete_older_than(config.log_dir, config.log_retention_days, "*.log")
    total += _delete_older_than(config.log_dir, config.log_retention_days, "*.log.gz")

    logger.info("Local cleanup complete: %d file(s) deleted (retention=%dd)", total, retention)
    return total


def cleanup_gcs(
    config: Config | None = None,
    storage_client: "storage.Client | None" = None,
) -> int:
    """Delete GCS archive objects older than the retention window."""
    config = config or load_config()
    if not config.gcs_bucket:
        return 0

    from google.cloud import storage

    client = storage_client or storage.Client(project=config.gcp_project)
    cutoff = datetime.now(timezone.utc) - timedelta(days=config.retention_days)

    deleted = 0
    for blob in client.list_blobs(config.gcs_bucket, prefix="archive/"):
        if blob.time_created and blob.time_created < cutoff:
            blob.delete()
            deleted += 1
    logger.info("GCS cleanup complete: %d object(s) deleted", deleted)
    return deleted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Retention-based cleanup")
    parser.add_argument("--skip-gcs", action="store_true", help="Skip GCS cleanup")
    args = parser.parse_args(argv)

    config = load_config()
    configure_logging(config.log_dir, config.log_level)
    logger.info("Starting cleanup (retention=%d days)", config.retention_days)
    cleanup_local(config)
    if not args.skip_gcs:
        try:
            cleanup_gcs(config)
        except Exception as exc:
            logger.warning("GCS cleanup skipped: %s", exc)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
