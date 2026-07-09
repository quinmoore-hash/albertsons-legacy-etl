"""File manipulation utilities for the ETL pipeline.

Python replacement for ``utils/file_utils.sh`` built on :mod:`pathlib`,
:mod:`csv`, :mod:`gzip` and :mod:`shutil`. Integer return codes mirror the Bash
originals so callers keep comparable branching:

* :func:`check_file` / :func:`validate_csv`: ``0`` ok, ``1`` error, ``2`` warn.
"""

from __future__ import annotations

import csv
import gzip
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

from etl.logging_util import log_error, log_info, log_warn

PathLike = Union[str, Path]

# Return-code constants matching the Bash helpers.
OK = 0
ERROR = 1
WARN = 2


def check_file(filepath: PathLike) -> int:
    """Return ``0`` if the file exists and is non-empty, ``1`` missing, ``2`` empty."""
    path = Path(filepath)
    if not path.is_file():
        log_error("File not found: %s", path)
        return ERROR
    if path.stat().st_size == 0:
        log_warn("File is empty: %s", path)
        return WARN
    return OK


def count_data_rows(filepath: PathLike, has_header: bool = True) -> int:
    """Count newline-terminated lines, excluding the header when present.

    Matches the line-based ``wc -l`` semantics of the Bash helper.
    """
    path = Path(filepath)
    lines = 0
    with path.open("rb") as fh:
        for _ in fh:
            lines += 1
    if has_header:
        return max(lines - 1, 0)
    return lines


def archive_file(filepath: PathLike, archive_dir: Optional[PathLike] = None) -> Optional[str]:
    """Copy ``filepath`` into ``archive_dir`` with a timestamp; return the new path."""
    src = Path(filepath)
    dest_dir = Path(archive_dir) if archive_dir else Path("/opt/albertsons/etl/data/archive")
    datestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_path = dest_dir / f"{src.stem}_{datestamp}{src.suffix}"

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, archive_path)
    except OSError as exc:
        log_error("Failed to archive: %s (%s)", src, exc)
        return None

    log_info("Archived: %s -> %s", src, archive_path)
    return str(archive_path)


def move_file(src: PathLike, dest: PathLike, retries: int = 3) -> bool:
    """Move ``src`` to ``dest`` with retries. Returns ``True`` on success."""
    for attempt in range(1, retries + 1):
        try:
            shutil.move(str(src), str(dest))
            log_info("Moved: %s -> %s", src, dest)
            return True
        except OSError:
            log_warn("Move failed (attempt %s/%s): %s -> %s", attempt, retries, src, dest)
            if attempt < retries:
                time.sleep(2)
    log_error("Failed to move file after %s attempts: %s", retries, src)
    return False


def validate_csv(
    filepath: PathLike,
    expected_cols: Optional[int] = None,
    delimiter: str = ",",
    sample_rows: int = 100,
) -> int:
    """Validate CSV column consistency.

    Returns ``0`` ok, ``1`` fatal (missing file / column-count mismatch against
    ``expected_cols``), ``2`` warning (inconsistent column counts in the
    sampled rows). Uses the :mod:`csv` module so quoted embedded delimiters are
    handled correctly (unlike the ``awk -F`` version).
    """
    status = check_file(filepath)
    if status != OK:
        return ERROR

    path = Path(filepath)
    with path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh, delimiter=delimiter)
        try:
            header = next(reader)
        except StopIteration:
            log_error("CSV has no header: %s", path)
            return ERROR

        header_cols = len(header)
        if expected_cols is not None and header_cols != expected_cols:
            log_error(
                "CSV column mismatch: expected %s, got %s in %s",
                expected_cols,
                header_cols,
                path,
            )
            return ERROR

        inconsistent: list[int] = []
        for line_no, row in enumerate(reader, start=2):
            if line_no - 1 > sample_rows:
                break
            if len(row) != header_cols:
                inconsistent.append(line_no)

    if inconsistent:
        log_warn("Inconsistent column counts at lines: %s", inconsistent)
        return WARN

    log_info("CSV validation passed: %s (%s columns)", path, header_cols)
    return OK


def gzip_file(filepath: PathLike, keep: bool = True) -> bool:
    """gzip a file. When ``keep`` is ``True`` the original is preserved."""
    if check_file(filepath) != OK:
        return False

    src = Path(filepath)
    gz_path = src.with_name(src.name + ".gz")
    try:
        with src.open("rb") as f_in, gzip.open(gz_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        if not keep:
            src.unlink()
    except OSError as exc:
        log_error("gzip failed for: %s (%s)", src, exc)
        return False

    log_info("Compressed: %s -> %s", src, gz_path)
    return True


def file_size_hr(filepath: PathLike) -> str:
    """Return a human-readable file size (e.g. ``1.2K``, ``3.4M``), or ``0``."""
    path = Path(filepath)
    if not path.is_file():
        return "0"
    size = float(path.stat().st_size)
    for unit in ("", "K", "M", "G", "T", "P"):
        if size < 1024.0:
            if unit == "":
                return f"{int(size)}"
            return f"{size:.1f}{unit}"
        size /= 1024.0
    return f"{size:.1f}E"
