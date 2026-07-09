"""Clean and standardize store-sales CSV files before warehouse load.

Python port of ``scripts/transform_sales.sh``, using the :mod:`csv` module so
embedded commas in quoted fields are handled correctly (the awk/sed version
mangled them). It also fixes the brittle US-only ``MM/DD/YYYY`` date assumption
by disambiguating day/month where possible and leaving already-ISO dates
untouched.

Pipeline steps (mirroring the Bash original):
  1. strip a UTF-8 BOM
  2. normalize CRLF -> LF line endings
  3. drop blank lines
  4. trim whitespace around each field
  5. normalize dates to ``YYYY-MM-DD``
  6. blank out NULL-like tokens (``NULL`` / ``N/A`` / ``NONE``)
  7. append ``_load_date`` and ``_source_file`` metadata columns

Exit codes: ``0`` success, ``1`` failure.
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
from datetime import date
from pathlib import Path
from typing import Iterable, Optional, Sequence, Union

from etl.config import get_settings
from etl.file_utils import check_file, count_data_rows
from etl.logging_util import log_info, setup_logging

PathLike = Union[str, Path]

NULL_TOKENS = {"NULL", "N/A", "NONE"}

# Numeric date with '/' or '-' separators, e.g. 7/8/2026, 07-08-2026, 2026/07/08.
_DATE_RE = re.compile(r"^(\d{1,4})[/-](\d{1,2})[/-](\d{1,4})$")


def normalize_date(token: str, dayfirst: bool = False) -> str:
    """Normalize a numeric date token to ``YYYY-MM-DD``.

    Unlike the Bash version this does not blindly assume ``MM/DD/YYYY``:

    * already-ISO ``YYYY-MM-DD`` / ``YYYY/MM/DD`` values pass through unchanged;
    * ``DD/MM/YYYY`` vs ``MM/DD/YYYY`` is disambiguated when one component is
      > 12; when genuinely ambiguous it falls back to ``dayfirst`` (default
      US-style month-first);
    * anything that is not a valid numeric date is returned unchanged.
    """
    match = _DATE_RE.match(token)
    if not match:
        return token

    a, b, c = match.groups()
    ai, bi, ci = int(a), int(b), int(c)

    if len(a) == 4:  # YYYY(-|/)MM(-|/)DD
        year, month, day = ai, bi, ci
    elif len(c) == 4:  # (DD|MM)(-|/)(MM|DD)(-|/)YYYY
        year = ci
        if ai > 12 and bi <= 12:
            day, month = ai, bi
        elif bi > 12 and ai <= 12:
            month, day = ai, bi
        elif dayfirst:
            day, month = ai, bi
        else:
            month, day = ai, bi
    else:
        return token

    if not (1 <= month <= 12 and 1 <= day <= 31):
        return token
    return f"{year:04d}-{month:02d}-{day:02d}"


def _clean_field(value: str, dayfirst: bool = False) -> str:
    stripped = value.strip()
    if stripped.upper() in NULL_TOKENS:
        return ""
    return normalize_date(stripped, dayfirst=dayfirst)


def transform_rows(
    rows: Iterable[Sequence[str]],
    run_date: str,
    source_file: str,
    dayfirst: bool = False,
) -> list[list[str]]:
    """Apply the cleaning pipeline to parsed CSV rows (header + data).

    Blank rows are dropped. The header gains ``_load_date`` / ``_source_file``
    columns; data rows gain the corresponding values.
    """
    result: list[list[str]] = []
    header_seen = False
    for row in rows:
        # Step 3: drop blank lines (empty row, or all fields blank).
        if not row or all(cell.strip() == "" for cell in row):
            continue

        if not header_seen:
            header = [cell.strip() for cell in row]
            header.extend(["_load_date", "_source_file"])
            result.append(header)
            header_seen = True
            continue

        cleaned = [_clean_field(cell, dayfirst=dayfirst) for cell in row]
        cleaned.extend([run_date, source_file])
        result.append(cleaned)

    return result


def transform_sales(
    input_file: PathLike,
    output_file: PathLike,
    run_date: Optional[str] = None,
    dayfirst: bool = False,
) -> int:
    """Transform ``input_file`` into a cleaned ``output_file``."""
    if check_file(input_file) != 0:
        return 1

    in_path = Path(input_file)
    out_path = Path(output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    run_date = run_date or date.today().isoformat()

    log_info("Transforming: %s", in_path.name)

    # Step 1+2: decode with utf-8-sig (strips BOM) and universal newlines.
    text = in_path.read_bytes().decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text, newline=""))
    cleaned_rows = transform_rows(reader, run_date, in_path.name, dayfirst=dayfirst)

    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerows(cleaned_rows)

    rows = count_data_rows(out_path)
    log_info("Transform complete: %s (%s rows)", out_path.name, rows)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    settings = get_settings()
    setup_logging(settings.log_dir, settings.log_level)

    parser = argparse.ArgumentParser(description="Clean and standardize a store-sales CSV")
    parser.add_argument("input_file")
    parser.add_argument("output_file")
    parser.add_argument(
        "--dayfirst",
        action="store_true",
        help="Interpret ambiguous DD/MM vs MM/DD dates as day-first",
    )
    args = parser.parse_args(argv)

    return transform_sales(args.input_file, args.output_file, dayfirst=args.dayfirst)


if __name__ == "__main__":
    sys.exit(main())
