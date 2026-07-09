"""Tests for etl.cleanup_old_data local cleanup."""

from __future__ import annotations

import os
import time
from pathlib import Path

from etl.cleanup_old_data import cleanup_local


def _write_old(path: Path, age_days: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    old = time.time() - age_days * 86400
    os.utime(path, (old, old))


def test_stale_staging_files_removed(config):
    stale = config.data_staging_dir / "pos_store_sales_clean.csv"
    fresh = config.data_staging_dir / "inventory_clean.csv"
    _write_old(stale, age_days=3)
    _write_old(fresh, age_days=0)

    cleanup_local(config)

    assert not stale.exists()
    assert fresh.exists()  # younger than the 1-day staging window


def test_old_processed_and_logs_removed(config):
    old_out = config.data_output_dir / "old.csv"
    old_log = config.log_dir / "etl_old.log"
    _write_old(old_out, age_days=config.retention_days + 5)
    _write_old(old_log, age_days=config.log_retention_days + 5)

    deleted = cleanup_local(config)

    assert not old_out.exists()
    assert not old_log.exists()
    assert deleted >= 2
