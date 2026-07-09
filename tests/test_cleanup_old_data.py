"""Tests for retention-based cleanup + lock behavior."""

from __future__ import annotations

import os
import time
from pathlib import Path

from etl.cleanup_old_data import cleanup_old_data
from etl.lock import FileLock, default_lock_path


def _age(path: Path, days: int) -> None:
    old = time.time() - days * 86400
    os.utime(path, (old, old))


def test_cleanup_removes_old_and_keeps_new(settings):
    processed = Path(settings.data_output_dir)
    old_file = processed / "old.csv"
    new_file = processed / "new.csv"
    old_file.write_text("x")
    new_file.write_text("y")
    _age(old_file, settings.retention_days + 5)

    staging = Path(settings.data_staging_dir)
    (staging / "leftover.csv").write_text("z")

    rc = cleanup_old_data(settings=settings)
    assert rc == 0
    assert not old_file.exists()
    assert new_file.exists()
    assert not (staging / "leftover.csv").exists()


def test_cleanup_skips_when_locked(settings):
    # Hold the shared lock; cleanup should skip (return 0) without deleting.
    processed = Path(settings.data_output_dir)
    old_file = processed / "old.csv"
    old_file.write_text("x")
    _age(old_file, settings.retention_days + 5)

    held = FileLock(default_lock_path()).acquire()
    try:
        rc = cleanup_old_data(settings=settings)
        assert rc == 0
        assert old_file.exists()  # not deleted because cleanup skipped
    finally:
        held.release()
