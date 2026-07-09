"""Logging configuration for the ETL, ported from ``utils/logging.sh``.

Preserves the legacy behaviour: INFO/WARNING/ERROR/DEBUG levels written to
both a dated log file and the console (stderr), using the stdlib ``logging``
module. Call :func:`configure_logging` once at process startup; use
:func:`get_logger` everywhere else.
"""

from __future__ import annotations

import logging
import sys
from datetime import date
from pathlib import Path

_CONFIGURED = False

_FILE_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
_CONSOLE_FORMAT = "[%(asctime)s] [%(levelname)s] %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging(
    log_dir: str | Path | None = None,
    level: str = "INFO",
    log_file: str | Path | None = None,
) -> logging.Logger:
    """Configure the root logger with file + console handlers.

    Idempotent: repeated calls reconfigure handlers rather than stacking them.
    """
    global _CONFIGURED

    root = logging.getLogger()
    numeric_level = getattr(logging, str(level).upper(), logging.INFO)
    root.setLevel(numeric_level)

    # Drop any handlers we previously installed so re-configuration is clean.
    for handler in list(root.handlers):
        root.removeHandler(handler)

    console = logging.StreamHandler(stream=sys.stderr)
    console.setFormatter(logging.Formatter(_CONSOLE_FORMAT, datefmt=_DATE_FORMAT))
    root.addHandler(console)

    if log_file is None and log_dir is not None:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"etl_{date.today():%Y%m%d}.log"

    if log_file is not None:
        log_file = Path(log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(_FILE_FORMAT, datefmt=_DATE_FORMAT))
        root.addHandler(file_handler)

    _CONFIGURED = True
    return root


def get_logger(name: str) -> logging.Logger:
    """Return a named logger, configuring a default console handler if needed."""
    if not _CONFIGURED:
        # Minimal console-only setup so library imports never crash if the
        # application forgot to call configure_logging().
        logging.basicConfig(
            level=logging.INFO,
            format=_CONSOLE_FORMAT,
            datefmt=_DATE_FORMAT,
            stream=sys.stderr,
        )
    return logging.getLogger(name)
