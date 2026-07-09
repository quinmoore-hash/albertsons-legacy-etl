"""Post-load data quality checks.

Ported from ``scripts/data_quality_check.sh``. Keeps the local CSV checks
(row count, null-key rate, duplicate keys) and replaces the Snowflake
warehouse-side check with a BigQuery query assertion against
``store_ops.fact_store_sales``.

Exit codes are preserved: ``0`` = ok, ``1`` = failures, ``2`` = warnings only.
A dated report file is written to ``LOG_DIR``.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from datetime import datetime
from pathlib import Path

from etl.config import Config, load_config
from etl.load_warehouse import TABLE_MAP
from etl.logging_setup import configure_logging, get_logger
from etl.warehouse import BigQueryClient

logger = get_logger(__name__)

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


class DQReport:
    """Accumulates check results and renders the report file."""

    def __init__(self, run_id: str, report_file: Path) -> None:
        self.run_id = run_id
        self.report_file = report_file
        self.lines: list[str] = []
        self.run = self.passed = self.warned = self.failed = 0

    def record(self, name: str, status: str, details: str) -> None:
        self.run += 1
        if status == PASS:
            self.passed += 1
        elif status == WARN:
            self.warned += 1
        elif status == FAIL:
            self.failed += 1
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.lines.append(f"[{stamp}] [{status}] {name}: {details}")
        logger.info("DQ [%s] %s: %s", status, name, details)

    def write(self) -> None:
        self.report_file.parent.mkdir(parents=True, exist_ok=True)
        header = [
            "=========================================",
            f"Data Quality Report - {self.run_id}",
            f"Generated: {datetime.now():%Y-%m-%d %H:%M:%S}",
            "=========================================",
        ]
        summary = [
            "",
            "=========================================",
            f"Summary - {self.run_id}",
            f"Total: {self.run}  Passed: {self.passed}  Warn: {self.warned}  Failed: {self.failed}",
            "=========================================",
        ]
        self.report_file.write_text("\n".join(header + self.lines + summary) + "\n")
        logger.info("DQ report -> %s", self.report_file)

    def exit_code(self) -> int:
        if self.failed > 0:
            return 1
        if self.warned > 0:
            return 2
        return 0


def _check_local_csv(report: DQReport, path: Path) -> None:
    base = path.name
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        try:
            next(reader)  # header
        except StopIteration:
            report.record(f"row_count:{base}", FAIL, "empty file (no header)")
            return
        keys: list[str] = []
        rows = 0
        null_keys = 0
        for row in reader:
            if not row:
                continue
            rows += 1
            key = row[0].strip() if row else ""
            if key == "":
                null_keys += 1
            else:
                keys.append(key)

    if rows <= 0:
        report.record(f"row_count:{base}", FAIL, "0 data rows")
    else:
        report.record(f"row_count:{base}", PASS, f"{rows} data rows")

    if null_keys > 0:
        report.record(f"null_key:{base}", WARN, f"{null_keys} rows with empty key column")
    else:
        report.record(f"null_key:{base}", PASS, "no empty keys")

    dupes = sum(1 for _, c in Counter(keys).items() if c > 1)
    if dupes > 0:
        report.record(f"dupes:{base}", WARN, f"{dupes} duplicate key values")
    else:
        report.record(f"dupes:{base}", PASS, "no duplicate keys")


def _check_warehouse(
    report: DQReport, config: Config, client: BigQueryClient | None
) -> None:
    client = client or BigQueryClient(config)
    # Reuse the loader's mapping so the DQ target can't drift from the load
    # target. BigQuery table names are case-sensitive, so this must match the
    # name data is actually loaded into (FACT_STORE_SALES).
    fact_table = TABLE_MAP["pos_store_sales"]
    table = f"{config.gcp_project}.{config.bq_dataset}.{fact_table}"
    sql = (
        f"SELECT COUNT(*) FROM `{table}` "
        "WHERE _load_date = CURRENT_DATE()"
    )
    try:
        count = client.query_scalar(sql)
        count = int(count or 0)
        if count > 0:
            report.record("warehouse:fact_store_sales", PASS, f"today rows={count}")
        else:
            report.record(
                "warehouse:fact_store_sales",
                FAIL,
                "0 rows loaded for today in fact_store_sales",
            )
    except Exception as exc:
        report.record("warehouse:connectivity", FAIL, f"BigQuery check failed: {exc}")


def run_dq_checks(
    run_id: str | None = None,
    config: Config | None = None,
    client: BigQueryClient | None = None,
    check_warehouse: bool = True,
) -> DQReport:
    """Run all DQ checks and return the populated :class:`DQReport`."""
    config = config or load_config()
    run_id = run_id or f"DQ_{datetime.now():%Y%m%d_%H%M%S}"
    report_file = config.log_dir / f"dq_report_{datetime.now():%Y%m%d}.txt"
    report = DQReport(run_id, report_file)

    if check_warehouse:
        logger.info("Running warehouse-side row count check...")
        _check_warehouse(report, config, client)

    for path in sorted(config.data_staging_dir.glob("*_clean.csv")):
        if path.is_file():
            _check_local_csv(report, path)

    report.write()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run post-load data quality checks")
    parser.add_argument("run_id", nargs="?", help="Optional run id")
    parser.add_argument(
        "--no-warehouse",
        action="store_true",
        help="Skip the BigQuery warehouse-side assertion",
    )
    args = parser.parse_args(argv)

    config = load_config()
    configure_logging(config.log_dir, config.log_level)
    report = run_dq_checks(
        args.run_id, config=config, check_warehouse=not args.no_warehouse
    )
    return report.exit_code()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
