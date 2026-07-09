"""Clean and standardize store-sales CSV data before warehouse load.

Ported from ``scripts/transform_sales.sh``. Preserves the original cleaning
steps:

  * strip a UTF-8 BOM,
  * normalize CRLF -> LF,
  * drop blank rows,
  * trim whitespace around each field,
  * blank out NULL-like tokens (``NULL`` / ``N/A`` / ``none``),
  * append ``_load_date`` and ``_source_file`` columns.

Two known legacy bugs are fixed here:

  1. A real CSV parser (:mod:`csv`) is used, so fields containing embedded
     commas / quotes no longer corrupt the row (the old awk/sed split on every
     comma).
  2. Dates are parsed robustly instead of blindly assuming US ``MM/DD/YYYY``:
     unambiguous values like ``13/07/2026`` are read as ``DD/MM/YYYY`` rather
     than being silently mangled.
"""

from __future__ import annotations

import argparse
import csv
import re
from datetime import date, datetime
from pathlib import Path

from etl.config import load_config
from etl.logging_setup import configure_logging, get_logger

logger = get_logger(__name__)

# Tokens that should be treated as empty/null.
_NULL_TOKENS = {"null", "n/a", "none", "na"}

# A field that looks like a date: digits sep digits sep digits.
_DATE_RE = re.compile(r"^\d{1,4}[/-]\d{1,2}[/-]\d{1,4}$")

# Format attempts, US-first, then day-first, then ISO variants. Because
# strptime rejects impossible months/days, trying %m/%d before %d/%m
# disambiguates values like 13/07/2026 (only day-first is valid) without
# mangling them.
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
    "%Y/%m/%d",
    "%m-%d-%Y",
    "%d-%m-%Y",
)


def normalize_date(value: str) -> str:
    """Return ``value`` as an ISO ``YYYY-MM-DD`` date if it is a date, else unchanged."""
    if not _DATE_RE.match(value):
        return value
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    # Looked like a date but matched no known format; leave it untouched.
    return value


def _clean_field(value: str) -> str:
    trimmed = value.strip()
    if trimmed.lower() in _NULL_TOKENS:
        return ""
    return normalize_date(trimmed)


def transform_file(
    input_file: str | Path,
    output_file: str | Path,
    load_date: str | None = None,
) -> int:
    """Transform ``input_file`` -> ``output_file``. Returns data row count."""
    input_file = Path(input_file)
    output_file = Path(output_file)
    if not input_file.is_file() or input_file.stat().st_size == 0:
        raise FileNotFoundError(f"Missing or empty input file: {input_file}")

    load_date = load_date or date.today().isoformat()
    source_file = input_file.name
    output_file.parent.mkdir(parents=True, exist_ok=True)

    rows_written = 0
    # utf-8-sig transparently strips a BOM; newline="" lets csv handle CRLF.
    with input_file.open("r", encoding="utf-8-sig", newline="") as src, output_file.open(
        "w", encoding="utf-8", newline=""
    ) as dst:
        reader = csv.reader(src)
        writer = csv.writer(dst)

        try:
            header = next(reader)
        except StopIteration:
            raise ValueError(f"Input file has no header: {input_file}")

        header = [h.strip() for h in header]
        writer.writerow(header + ["_load_date", "_source_file"])

        for row in reader:
            # Drop fully blank rows.
            if not any(cell.strip() for cell in row):
                continue
            cleaned = [_clean_field(cell) for cell in row]
            writer.writerow(cleaned + [load_date, source_file])
            rows_written += 1

    logger.info("Transform complete: %s (%d rows)", output_file.name, rows_written)
    return rows_written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clean/standardize a sales CSV")
    parser.add_argument("input_file")
    parser.add_argument("output_file")
    args = parser.parse_args(argv)

    config = load_config()
    configure_logging(config.log_dir, config.log_level)
    try:
        transform_file(args.input_file, args.output_file)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("Transform failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
