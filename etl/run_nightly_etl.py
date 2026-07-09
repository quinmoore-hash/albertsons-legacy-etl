"""Python orchestrator for the nightly store ETL.

Ported from ``scripts/run_nightly_etl.sh``. Runs the steps in order:
fetch -> extract -> transform -> load -> DQ -> archive.

The crude ``/tmp`` lock file and the manual step-counter bookkeeping are gone:
concurrency is handled by the scheduler (Cloud Composer / Cloud Run), which
guarantees a single active run. This module is intentionally import-safe so
the Airflow DAG in ``etl/dags/nightly_etl_dag.py`` can call the same functions
as discrete tasks.
"""

from __future__ import annotations

import argparse
import time
from datetime import date
from pathlib import Path

from etl.archive_files import archive_files
from etl.config import Config, load_config
from etl.data_quality_check import run_dq_checks
from etl.extract_dimensions import extract_dimensions
from etl.fetch_pos_data import fetch_pos_data
from etl.load_warehouse import detect_target_table, load_warehouse
from etl.logging_setup import configure_logging, get_logger
from etl.notify import alert, send_slack
from etl.transform_sales import transform_file
from etl.warehouse import BigQueryClient

logger = get_logger(__name__)


def _run_id() -> str:
    return f"ETL_{date.today():%Y%m%d}_{time.strftime('%H%M%S')}"


def transform_all(config: Config) -> int:
    """Transform every CSV in the input dir into the staging dir."""
    total_rows = 0
    for csv_file in sorted(config.data_input_dir.glob("*.csv")):
        out = config.data_staging_dir / f"{csv_file.stem}_clean.csv"
        total_rows += transform_file(csv_file, out)
    return total_rows


def load_all(config: Config, client: BigQueryClient | None = None) -> int:
    """Load every staged clean CSV into BigQuery. Returns files loaded."""
    client = client or BigQueryClient(config)
    loaded = 0
    for clean_file in sorted(config.data_staging_dir.glob("*_clean.csv")):
        if detect_target_table(clean_file.name) is None:
            logger.warning("Skipping %s: no target table mapping", clean_file.name)
            continue
        load_warehouse(clean_file, config=config, client=client)
        loaded += 1
    return loaded


def run_nightly_etl(config: Config | None = None) -> int:
    """Run the full nightly pipeline. Returns process exit code (0 ok, 1 errors)."""
    config = config or load_config()
    for directory in (
        config.data_input_dir,
        config.data_output_dir,
        config.data_staging_dir,
        config.data_archive_dir,
        config.data_error_dir,
    ):
        Path(directory).mkdir(parents=True, exist_ok=True)

    run_id = _run_id()
    start = time.time()
    errors: list[str] = []
    total_rows = 0

    logger.info("Starting Nightly Store ETL: %s", run_id)
    client = BigQueryClient(config)

    run_date = date.today().strftime("%Y%m%d")

    # Step 1: fetch POS data
    try:
        fetch_pos_data(
            config.data_input_dir / f"pos_store_sales_{run_date}.csv", config=config
        )
    except Exception as exc:
        logger.error("POS fetch failed: %s", exc)
        errors.append(f"FETCH: {exc}")

    # Step 2: extract dimensions from BigQuery
    try:
        extract_dimensions(
            config.data_input_dir / f"dim_reference_{run_date}.csv",
            config=config,
            client=client,
        )
    except Exception as exc:
        logger.error("Dimension extract failed: %s", exc)
        errors.append(f"EXTRACT: {exc}")

    # Step 3: transform
    try:
        total_rows = transform_all(config)
    except Exception as exc:
        logger.error("Transform failed: %s", exc)
        errors.append(f"TRANSFORM: {exc}")

    # Step 4: load into BigQuery
    try:
        load_all(config, client=client)
    except Exception as exc:
        logger.error("Load failed: %s", exc)
        errors.append(f"LOAD: {exc}")

    # Step 5: data quality checks
    try:
        report = run_dq_checks(run_id, config=config, client=client)
        if report.exit_code() == 1:
            errors.append("DQ: data quality check reported failures")
    except Exception as exc:
        logger.error("DQ checks failed: %s", exc)
        errors.append(f"DQ: {exc}")

    # Step 6: archive
    try:
        archive_files(config=config, run_date=run_date)
    except Exception as exc:
        logger.error("Archive failed: %s", exc)
        errors.append(f"ARCHIVE: {exc}")

    duration = int(time.time() - start)
    logger.info("ETL Run Summary: %s duration=%ds rows=%d", run_id, duration, total_rows)

    if errors:
        alert(
            f"ETL {run_id} completed with errors:\n"
            + "\n".join(errors)
            + f"\nDuration: {duration}s",
            "WARNING",
            config=config,
        )
        return 1

    send_slack(
        f"ETL {run_id} completed OK. {total_rows} rows in {duration}s.",
        "INFO",
        config=config,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description="Run the nightly store ETL").parse_args(argv)
    config = load_config()
    configure_logging(config.log_dir, config.log_level)
    return run_nightly_etl(config)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
