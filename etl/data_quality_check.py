"""Post-load data quality checks.

Python port of ``scripts/data_quality_check.sh``. Runs row-count, null-key and
duplicate-key checks against the local staging CSVs, and replaces the
decommissioned Snowflake warehouse check with a BigQuery count query. Writes a
dated DQ report and preserves the Bash exit-code semantics:

    0 = ok, 1 = failures, 2 = warnings only
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence, Union

from etl.bigquery_client import BigQueryClient
from etl.config import Settings, get_settings
from etl.logging_util import log_info, setup_logging

PathLike = Union[str, Path]

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_WARN = 2


@dataclass
class CheckResult:
    name: str
    status: str
    details: str


class DataQualityChecker:
    """Accumulates check results and computes summary counts / exit code."""

    def __init__(self) -> None:
        self.results: list[CheckResult] = []

    def record(self, name: str, status: str, details: str) -> None:
        self.results.append(CheckResult(name, status, details))
        log_info("DQ [%s] %s: %s", status, name, details)

    @property
    def run(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.status == PASS)

    @property
    def warned(self) -> int:
        return sum(1 for r in self.results if r.status == WARN)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status == FAIL)

    def exit_code(self) -> int:
        if self.failed > 0:
            return EXIT_FAIL
        if self.warned > 0:
            return EXIT_WARN
        return EXIT_OK


def check_csv_file(filepath: PathLike, delimiter: str = ",") -> list[CheckResult]:
    """Row-count, null-key and duplicate-key checks on a single staging CSV.

    The first column is assumed to be the primary key. Uses the :mod:`csv`
    module so quoted embedded delimiters are parsed correctly.
    """
    path = Path(filepath)
    base = path.name
    results: list[CheckResult] = []

    rows = 0
    null_keys = 0
    seen: set[str] = set()
    dupes: set[str] = set()

    with path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh, delimiter=delimiter)
        for line_no, row in enumerate(reader):
            if line_no == 0:  # header
                continue
            if not row:
                continue
            rows += 1
            key = row[0] if row else ""
            if key == "":
                null_keys += 1
            elif key in seen:
                dupes.add(key)
            else:
                seen.add(key)

    if rows <= 0:
        results.append(CheckResult(f"row_count:{base}", FAIL, "0 data rows"))
    else:
        results.append(CheckResult(f"row_count:{base}", PASS, f"{rows} data rows"))

    if null_keys > 0:
        results.append(
            CheckResult(f"null_key:{base}", WARN, f"{null_keys} rows with empty key column")
        )
    else:
        results.append(CheckResult(f"null_key:{base}", PASS, "no empty keys"))

    if dupes:
        results.append(
            CheckResult(f"dupes:{base}", WARN, f"{len(dupes)} duplicate key values")
        )
    else:
        results.append(CheckResult(f"dupes:{base}", PASS, "no duplicate keys"))

    return results


def check_warehouse(
    checker: DataQualityChecker,
    settings: Settings,
    client: Optional[BigQueryClient] = None,
) -> None:
    """BigQuery row-count check for today's ``fact_store_sales`` load."""
    log_info("Attempting warehouse-side row count check...")
    try:
        client = client or BigQueryClient(settings)
        sql = (
            f"SELECT COUNT(*) FROM `{settings.dataset_ref()}.fact_store_sales` "
            "WHERE _load_date = CURRENT_DATE()"
        )
        count = client.scalar(sql)
        checker.record("warehouse:fact_store_sales", PASS, f"today rows={count or 0}")
    except Exception as exc:  # noqa: BLE001 - connectivity/query failure
        checker.record(
            "warehouse:connectivity",
            FAIL,
            f"BigQuery warehouse check failed: {exc}",
        )


def run_data_quality(
    run_id: Optional[str] = None,
    settings: Optional[Settings] = None,
    client: Optional[BigQueryClient] = None,
    skip_warehouse: bool = False,
) -> int:
    """Run all DQ checks, write the dated report, and return the exit code."""
    settings = settings or get_settings()
    run_id = run_id or f"DQ_{datetime.now():%Y%m%d_%H%M%S}"
    report_file = Path(settings.log_dir) / f"dq_report_{datetime.now():%Y%m%d}.txt"
    report_file.parent.mkdir(parents=True, exist_ok=True)

    checker = DataQualityChecker()

    if not skip_warehouse:
        check_warehouse(checker, settings, client=client)

    staging = Path(settings.data_staging_dir)
    if staging.is_dir():
        for csv_file in sorted(staging.glob("*_clean.csv")):
            for result in check_csv_file(csv_file, settings.csv_delimiter):
                checker.record(result.name, result.status, result.details)

    _write_report(report_file, run_id, checker)
    log_info("DQ report -> %s", report_file)
    return checker.exit_code()


def _write_report(report_file: Path, run_id: str, checker: DataQualityChecker) -> None:
    lines = [
        "=========================================",
        f"Data Quality Report - {run_id}",
        f"Generated: {datetime.now():%Y-%m-%d %H:%M:%S}",
        "=========================================",
    ]
    for result in checker.results:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"[{ts}] [{result.status}] {result.name}: {result.details}")
    lines += [
        "",
        "=========================================",
        f"Summary - {run_id}",
        f"Total: {checker.run}  Passed: {checker.passed}  "
        f"Warn: {checker.warned}  Failed: {checker.failed}",
        "=========================================",
    ]
    report_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    settings = get_settings()
    setup_logging(settings.log_dir, settings.log_level)

    parser = argparse.ArgumentParser(description="Run post-load data quality checks")
    parser.add_argument("run_id", nargs="?", default=None)
    parser.add_argument(
        "--skip-warehouse",
        action="store_true",
        help="Skip the BigQuery warehouse count check (local CSV checks only)",
    )
    args = parser.parse_args(argv)

    return run_data_quality(
        args.run_id, settings=settings, skip_warehouse=args.skip_warehouse
    )


if __name__ == "__main__":
    sys.exit(main())
