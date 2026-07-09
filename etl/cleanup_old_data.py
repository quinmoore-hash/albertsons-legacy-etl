"""Retention-based cleanup of old ETL files and logs.

Python port of ``scripts/cleanup_old_data.sh``. Deletes old processed, archive
and error files and rotates logs by retention.

Two bugs from the Bash version are fixed:

* It no longer runs ``rm -rf /tmp/albertsons_*`` (which could nuke the nightly
  ETL lock file and in-flight temp files).
* Instead of a hacky ``sleep 30``, it acquires the *same* advisory lock the
  nightly ETL uses and skips cleanup if the ETL is currently running.

Exit code: ``0`` (best-effort cleanup).
"""

from __future__ import annotations

import argparse
import gzip
import shutil
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Sequence

from etl.config import Settings, get_settings
from etl.lock import FileLock, LockError, default_lock_path
from etl.logging_util import log_info, log_warn, setup_logging

LOG_COMPRESS_AGE_DAYS = 3
ERROR_FILE_RETENTION_DAYS = 60


def _delete_older_than(directory: Path, days: int, pattern: str = "*") -> int:
    """Delete files under ``directory`` matching ``pattern`` older than ``days``."""
    if not directory.is_dir():
        return 0
    cutoff = datetime.now() - timedelta(days=days)
    removed = 0
    for path in directory.glob(pattern):
        if not path.is_file():
            continue
        try:
            if datetime.fromtimestamp(path.stat().st_mtime) < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def _remove_glob(directory: Path, pattern: str) -> int:
    if not directory.is_dir():
        return 0
    removed = 0
    for path in directory.glob(pattern):
        try:
            if path.is_file():
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def _compress_old_logs(log_dir: Path, age_days: int) -> int:
    if not log_dir.is_dir():
        return 0
    cutoff = datetime.now() - timedelta(days=age_days)
    compressed = 0
    for path in log_dir.glob("*.log"):
        try:
            if datetime.fromtimestamp(path.stat().st_mtime) >= cutoff:
                continue
            gz_path = path.with_name(path.name + ".gz")
            with path.open("rb") as f_in, gzip.open(gz_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
            path.unlink()
            compressed += 1
        except OSError:
            continue
    return compressed


def cleanup_old_data(
    settings: Optional[Settings] = None,
    wait_for_lock_seconds: int = 0,
) -> int:
    """Run retention cleanup, guarded by the shared ETL lock."""
    settings = settings or get_settings()
    retention = settings.retention_days

    log_info("Starting cleanup (retention=%s days)", retention)

    lock = FileLock(default_lock_path())
    deadline = time.monotonic() + max(wait_for_lock_seconds, 0)
    while True:
        try:
            lock.acquire()
            break
        except LockError as exc:
            if time.monotonic() >= deadline:
                log_warn("ETL appears to be running (%s); skipping cleanup this run", exc)
                return 0
            time.sleep(2)

    try:
        removed = _delete_older_than(Path(settings.data_output_dir), retention)
        log_info("Removed %s processed file(s) older than %s days", removed, retention)

        staging = Path(settings.data_staging_dir)
        removed = _remove_glob(staging, "*.csv") + _remove_glob(staging, "*.tmp")
        log_info("Removed %s staging leftover(s)", removed)

        removed = _delete_older_than(Path(settings.data_error_dir), ERROR_FILE_RETENTION_DAYS)
        log_info("Removed %s error file(s) older than %s days", removed, ERROR_FILE_RETENTION_DAYS)

        removed = _delete_older_than(Path(settings.data_archive_dir), retention)
        log_info("Removed %s archive(s) older than %s days", removed, retention)

        log_dir = Path(settings.log_dir)
        compressed = _compress_old_logs(log_dir, LOG_COMPRESS_AGE_DAYS)
        removed = _delete_older_than(log_dir, settings.log_retention_days, "*.log.gz")
        log_info("Compressed %s log(s); removed %s old compressed log(s)", compressed, removed)
    finally:
        lock.release()

    log_info("Cleanup complete")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    settings = get_settings()
    setup_logging(settings.log_dir, settings.log_level)
    parser = argparse.ArgumentParser(description="Retention-based cleanup of old ETL files")
    parser.add_argument(
        "--wait-for-lock",
        type=int,
        default=0,
        help="Seconds to wait for the ETL lock before skipping (default: skip immediately)",
    )
    args = parser.parse_args(argv)
    return cleanup_old_data(settings=settings, wait_for_lock_seconds=args.wait_for_lock)


if __name__ == "__main__":
    sys.exit(main())
