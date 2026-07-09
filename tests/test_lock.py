"""Tests for the advisory file lock."""

from __future__ import annotations

import pytest

from etl.lock import FileLock, LockError


def test_acquire_and_release(tmp_path):
    path = tmp_path / "x.lock"
    lock = FileLock(path)
    lock.acquire()
    assert path.exists()
    assert path.read_text().strip() == str(__import__("os").getpid())
    lock.release()
    assert not path.exists()


def test_contention(tmp_path):
    path = tmp_path / "x.lock"
    first = FileLock(path).acquire()
    try:
        with pytest.raises(LockError):
            FileLock(path).acquire()
    finally:
        first.release()


def test_context_manager(tmp_path):
    path = tmp_path / "x.lock"
    with FileLock(path):
        assert path.exists()
    assert not path.exists()
