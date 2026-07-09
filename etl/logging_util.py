"""Logging utility for the Albertsons ETL pipeline.

Python replacement for ``utils/logging.sh``. Configures the standard
:mod:`logging` module to write to a dated log file (``etl_YYYYMMDD.log`` under
``LOG_DIR``) *and* stderr, honoring ``LOG_LEVEL``. Provides ``log_info``,
``log_warn``, ``log_error`` and ``log_debug`` helpers matching the Bash API.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

LOGGER_NAME = "albertsons_etl"

_LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Map the Bash "WARN" spelling onto Python's "WARNING".
_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARN": logging.WARNING,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

_configured = False


def _resolve_level(level: Optional[str]) -> int:
    if not level:
        level = os.environ.get("LOG_LEVEL", "INFO")
    return _LEVELS.get(level.upper(), logging.INFO)


def setup_logging(
    log_dir: Optional[str] = None,
    level: Optional[str] = None,
    log_file: Optional[str] = None,
    force: bool = False,
) -> logging.Logger:
    """Configure and return the pipeline logger.

    Idempotent: repeated calls reuse the existing handlers unless ``force`` is
    set. ``log_dir`` defaults to ``$LOG_DIR`` (or ``/var/log/albertsons/etl``);
    ``level`` defaults to ``$LOG_LEVEL``.
    """
    global _configured
    logger = logging.getLogger(LOGGER_NAME)

    if _configured and not force:
        return logger

    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    resolved_level = _resolve_level(level)
    logger.setLevel(resolved_level)
    logger.propagate = False

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # File handler: dated log file, best-effort (a read-only LOG_DIR should not
    # crash the pipeline, matching the Bash `mkdir -p ... 2>/dev/null`).
    resolved_dir = log_dir or os.environ.get("LOG_DIR", "/var/log/albertsons/etl")
    if log_file is None:
        log_file = os.path.join(resolved_dir, f"etl_{date.today():%Y%m%d}.log")
    try:
        Path(resolved_dir).mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        file_handler.setLevel(resolved_level)
        logger.addHandler(file_handler)
    except OSError:
        pass

    stream_handler = logging.StreamHandler()  # stderr
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(resolved_level)
    logger.addHandler(stream_handler)

    _configured = True
    return logger


def get_logger() -> logging.Logger:
    """Return the pipeline logger, configuring it on first use."""
    if not _configured:
        setup_logging()
    return logging.getLogger(LOGGER_NAME)


def log_info(message: str, *args: object) -> None:
    get_logger().info(message, *args)


def log_warn(message: str, *args: object) -> None:
    get_logger().warning(message, *args)


def log_error(message: str, *args: object) -> None:
    get_logger().error(message, *args)


def log_debug(message: str, *args: object) -> None:
    get_logger().debug(message, *args)


def rotate_logs(log_dir: Optional[str] = None, retention_days: Optional[int] = None) -> int:
    """Delete ``*.log`` files older than ``retention_days``.

    Returns the number of files removed. Mirrors ``rotate_logs`` in
    ``utils/logging.sh``.
    """
    resolved_dir = log_dir or os.environ.get("LOG_DIR", "/var/log/albertsons/etl")
    if retention_days is None:
        retention_days = int(os.environ.get("LOG_RETENTION_DAYS", "45"))

    log_info("Rotating logs older than %s days", retention_days)
    cutoff = datetime.now() - timedelta(days=retention_days)
    removed = 0
    base = Path(resolved_dir)
    if not base.is_dir():
        return 0
    for path in base.glob("*.log"):
        try:
            if datetime.fromtimestamp(path.stat().st_mtime) < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed
