"""Nightly store ETL orchestrator.

Python port of ``scripts/run_nightly_etl.sh``. Coordinates the six pipeline
steps (fetch -> extract -> transform -> load -> DQ -> archive), tracks steps
completed/failed and total rows processed, holds a proper advisory file lock
(replacing the crude PID lockfile), and emits a run-summary alert on exit.

Exit codes: ``0`` if no step failed, ``1`` otherwise.
"""

from __future__ import annotations

import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Sequence

from etl import archive_files as archive_mod
from etl import data_quality_check as dq_mod
from etl import extract_dimensions as extract_mod
from etl import fetch_pos_data as fetch_mod
from etl import load_warehouse as load_mod
from etl import transform_sales as transform_mod
from etl.config import Settings, get_settings
from etl.file_utils import count_data_rows
from etl.lock import FileLock, LockError, default_lock_path
from etl.logging_util import log_error, log_info, log_warn, setup_logging
from etl.notify import Notifier


class NightlyETL:
    """Runs the nightly pipeline and accumulates run statistics."""

    def __init__(self, settings: Optional[Settings] = None, notifier: Optional[Notifier] = None) -> None:
        self.settings = settings or get_settings()
        self.notifier = notifier or Notifier(self.settings)
        self.run_id = f"ETL_{datetime.now():%Y%m%d_%H%M%S}"
        self.run_date = date.today().strftime("%Y%m%d")
        self.steps_completed = 0
        self.steps_failed = 0
        self.total_rows = 0
        self.errors: list[str] = []

    def _ensure_dirs(self) -> None:
        for directory in self.settings.data_dirs():
            Path(directory).mkdir(parents=True, exist_ok=True)

    def run(self) -> int:
        start = time.time()
        exit_code = 0
        try:
            self._ensure_dirs()
            log_info("==========================================")
            log_info("Starting Nightly Store ETL: %s", self.run_id)
            log_info("Date: %s", datetime.now())
            log_info("==========================================")

            self._step_fetch()
            self._step_extract()
            self._step_transform()
            self._step_load()
            self._step_dq()
            self._step_archive()

            exit_code = 1 if self.steps_failed > 0 else 0
        except Exception as exc:  # noqa: BLE001 - unexpected orchestration error
            log_error("Unhandled error in nightly ETL: %s", exc)
            self.errors.append(f"ORCHESTRATOR: {exc}")
            exit_code = 1
        finally:
            self._emit_summary(start, exit_code)
        return exit_code

    # -- steps ----------------------------------------------------------
    def _step_fetch(self) -> None:
        log_info("[Step 1/6] Fetching POS store-sales data...")
        out = Path(self.settings.data_input_dir) / f"pos_store_sales_{self.run_date}.csv"
        rc = fetch_mod.fetch_pos_data(out, settings=self.settings)
        if rc != 0:
            log_error("POS fetch failed")
            self.errors.append("FETCH: POS store-sales fetch failed")
            self.steps_failed += 1
        else:
            self.steps_completed += 1

    def _step_extract(self) -> None:
        log_info("[Step 2/6] Extracting reference dimensions from BigQuery...")
        out = Path(self.settings.data_input_dir) / f"dim_reference_{self.run_date}.csv"
        rc = extract_mod.extract_dimensions(out, settings=self.settings)
        if rc != 0:
            log_error("BigQuery dimension extract failed")
            self.errors.append("EXTRACT: dimension extract failed")
            self.steps_failed += 1
            log_warn("Continuing with last-known dimension cache (if present)")
        else:
            self.steps_completed += 1

    def _step_transform(self) -> None:
        log_info("[Step 3/6] Transforming sales data...")
        staging = Path(self.settings.data_staging_dir)
        for csv_file in sorted(Path(self.settings.data_input_dir).glob("*.csv")):
            out = staging / f"{csv_file.stem}_clean.csv"
            rc = transform_mod.transform_sales(csv_file, out)
            if rc == 0:
                self.total_rows += count_data_rows(out)
            else:
                self.errors.append(f"TRANSFORM: {csv_file.name} failed")
                self.steps_failed += 1
        self.steps_completed += 1

    def _step_load(self) -> None:
        log_info("[Step 4/6] Loading data into BigQuery...")
        for data_file in sorted(Path(self.settings.data_staging_dir).glob("*_clean.csv")):
            rc = load_mod.load_warehouse(data_file, settings=self.settings)
            if rc != 0:
                self.errors.append(f"LOAD: {data_file.name} failed")
                self.steps_failed += 1
        self.steps_completed += 1

    def _step_dq(self) -> None:
        log_info("[Step 5/6] Running data quality checks...")
        rc = dq_mod.run_data_quality(self.run_id, settings=self.settings)
        if rc != 0:
            self.errors.append("DQ: data quality check reported issues")
        self.steps_completed += 1

    def _step_archive(self) -> None:
        log_info("[Step 6/6] Archiving processed files...")
        rc = archive_mod.archive_files(settings=self.settings)
        if rc != 0:
            self.errors.append("ARCHIVE: archive step reported issues")
        self.steps_completed += 1

    # -- summary --------------------------------------------------------
    def _emit_summary(self, start: float, exit_code: int) -> None:
        duration = int(time.time() - start)
        log_info("==========================================")
        log_info("ETL Run Summary: %s", self.run_id)
        log_info("Duration: %ss", duration)
        log_info("Steps Completed: %s", self.steps_completed)
        log_info("Steps Failed: %s", self.steps_failed)
        log_info("Total Rows: %s", self.total_rows)
        log_info("==========================================")

        if self.errors:
            summary = "\n".join(self.errors)
            self.notifier.alert(
                f"ETL {self.run_id} completed with errors:\n{summary}\nDuration: {duration}s",
                "WARNING",
            )
        elif exit_code != 0:
            self.notifier.alert(
                f"ETL {self.run_id} FAILED (exit={exit_code}). "
                f"Steps completed: {self.steps_completed}",
                "CRITICAL",
            )
        else:
            self.notifier.send_slack(
                f"ETL {self.run_id} completed OK. {self.total_rows} rows in {duration}s.",
                "INFO",
            )


def main(argv: Optional[Sequence[str]] = None) -> int:
    settings = get_settings()
    setup_logging(settings.log_dir, settings.log_level)

    etl = NightlyETL(settings)
    lock = FileLock(default_lock_path())
    try:
        lock.acquire()
    except LockError as exc:
        etl.notifier.alert(f"ETL {etl.run_id}: {exc}", "CRITICAL")
        return 1

    try:
        return etl.run()
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
