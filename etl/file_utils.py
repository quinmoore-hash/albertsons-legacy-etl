"""File helpers, ported from ``utils/file_utils.sh``.

Uses ``pathlib``, ``csv`` and ``gzip`` in place of the old shell/awk plumbing.
"""

from __future__ import annotations

import csv
import gzip
import shutil
from datetime import datetime
from pathlib import Path

from etl.logging_setup import get_logger

logger = get_logger(__name__)


class FileState:
    """Result of :func:`check_file`."""

    OK = 0
    MISSING = 1
    EMPTY = 2


def check_file(filepath: str | Path) -> int:
    """Return OK/MISSING/EMPTY for ``filepath`` (mirrors the old return codes)."""
    path = Path(filepath)
    if not path.is_file():
        logger.error("File not found: %s", filepath)
        return FileState.MISSING
    if path.stat().st_size == 0:
        logger.warning("File is empty: %s", filepath)
        return FileState.EMPTY
    return FileState.OK


def count_data_rows(filepath: str | Path, has_header: bool = True) -> int:
    """Count data rows in a text/CSV file, optionally excluding the header."""
    path = Path(filepath)
    with path.open("r", encoding="utf-8", newline="") as fh:
        total = sum(1 for _ in fh)
    if has_header:
        return max(total - 1, 0)
    return total


def archive_file(filepath: str | Path, archive_dir: str | Path) -> Path:
    """Copy ``filepath`` into ``archive_dir`` with a timestamped name."""
    path = Path(filepath)
    archive_dir = Path(archive_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = archive_dir / f"{path.stem}_{stamp}{path.suffix}"
    shutil.copy2(path, dest)
    logger.info("Archived: %s -> %s", path, dest)
    return dest


def gzip_file(filepath: str | Path, keep: bool = True) -> Path:
    """Gzip ``filepath`` -> ``filepath.gz``. Removes the original if ``keep`` is False."""
    path = Path(filepath)
    if check_file(path) != FileState.OK:
        raise FileNotFoundError(f"Cannot gzip missing/empty file: {filepath}")

    gz_path = path.with_suffix(path.suffix + ".gz")
    with path.open("rb") as src, gzip.open(gz_path, "wb") as dst:
        shutil.copyfileobj(src, dst)
    if not keep:
        path.unlink()
    logger.info("Compressed: %s -> %s", path, gz_path)
    return gz_path


def validate_csv(
    filepath: str | Path,
    expected_cols: int | None = None,
    delimiter: str = ",",
    sample_rows: int = 100,
) -> bool:
    """Validate CSV column consistency using a real CSV parser.

    Returns True if the header (and the first ``sample_rows`` rows) have a
    consistent column count matching ``expected_cols`` when provided.
    """
    if check_file(filepath) != FileState.OK:
        return False

    path = Path(filepath)
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh, delimiter=delimiter)
        try:
            header = next(reader)
        except StopIteration:
            logger.error("CSV has no header: %s", filepath)
            return False

        header_cols = len(header)
        if expected_cols is not None and header_cols != expected_cols:
            logger.error(
                "CSV column mismatch: expected %d, got %d in %s",
                expected_cols,
                header_cols,
                filepath,
            )
            return False

        for i, row in enumerate(reader, start=2):
            if i > sample_rows + 1:
                break
            if len(row) != header_cols:
                logger.warning(
                    "Inconsistent column count at line %d in %s (%d != %d)",
                    i,
                    filepath,
                    len(row),
                    header_cols,
                )
                return False

    logger.info("CSV validation passed: %s (%d columns)", filepath, header_cols)
    return True


def file_size_hr(filepath: str | Path) -> str:
    """Human-readable file size."""
    path = Path(filepath)
    if not path.is_file():
        return "0B"
    size = float(path.stat().st_size)
    for unit in ("B", "K", "M", "G", "T"):
        if size < 1024 or unit == "T":
            return f"{size:.1f}{unit}" if unit != "B" else f"{int(size)}B"
        size /= 1024
    return f"{size:.1f}T"
