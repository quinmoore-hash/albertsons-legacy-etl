"""A proper advisory file lock for the ETL pipeline.

Replaces the crude ``echo $$ > /tmp/albertsons_nightly_etl.lock`` PID file used
by ``run_nightly_etl.sh`` (which ``cleanup_old_data.sh`` could blindly delete
via ``rm -rf /tmp/albertsons_*``). Uses :func:`fcntl.flock` for a real advisory
lock that is released automatically if the holding process dies, so a stale
lock never wedges the pipeline.
"""

from __future__ import annotations

import errno
import fcntl
import os
from pathlib import Path
from typing import Optional


def default_lock_path() -> str:
    """Shared lock path for the nightly ETL and the cleanup job.

    Overridable via ``$ETL_LOCK_PATH``. The two jobs use the *same* lock so
    cleanup never runs concurrently with an in-flight nightly ETL.
    """
    return os.environ.get("ETL_LOCK_PATH", "/tmp/albertsons_nightly_etl.lock")


class LockError(RuntimeError):
    """Raised when the lock is already held by another live process."""


class FileLock:
    """Advisory ``flock``-based lock, usable as a context manager."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._fd: Optional[int] = None

    def acquire(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                other = self._read_holder()
                raise LockError(
                    f"Lock {self.path} already held"
                    + (f" by pid {other}" if other else "")
                ) from exc
            raise
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        os.fsync(fd)
        self._fd = fd
        return self

    def _read_holder(self) -> Optional[str]:
        try:
            content = self.path.read_text().strip()
            return content or None
        except OSError:
            return None

    def release(self) -> None:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None
            try:
                self.path.unlink()
            except OSError:
                pass

    def __enter__(self) -> "FileLock":
        return self.acquire()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()
