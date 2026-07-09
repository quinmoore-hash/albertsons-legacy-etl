"""Cloud Composer (Airflow) DAG for the Albertsons nightly store ETL.

This is the preferred, migration-target replacement for cron-on-a-VM
scheduling (``scripts/install_cron.sh``). Each of the six pipeline steps is a
``PythonOperator`` task wired into the same order the Bash orchestrator ran
them; the transform/DQ/archive tasks always run so local-only work still
completes even if the warehouse steps error, mirroring the legacy behavior.

Deploy by dropping this file into the Composer environment's ``dags/`` GCS
folder (the ``etl`` package must be installed in the environment via its
``requirements.txt``). Configuration is read from environment variables /
Secret Manager exactly as the CLI entrypoints do.

If you prefer per-step Cloud Run jobs instead of Composer, each task below maps
1:1 to a Cloud Run job that runs ``python -m etl.<module>``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import pendulum
from airflow import DAG
from airflow.operators.python import PythonOperator

from etl import (
    archive_files,
    data_quality_check,
    extract_dimensions,
    fetch_pos_data,
    load_warehouse,
    transform_sales,
)
from etl.config import get_settings

LOCAL_TZ = pendulum.timezone("America/Los_Angeles")

default_args = {
    "owner": "store-data-ops",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "email": ["store-data-ops@albertsons.com"],
    "email_on_failure": True,
}


def _run_date() -> str:
    return date.today().strftime("%Y%m%d")


def _fetch(**_) -> None:
    settings = get_settings()
    out = Path(settings.data_input_dir) / f"pos_store_sales_{_run_date()}.csv"
    rc = fetch_pos_data.fetch_pos_data(out, settings=settings)
    if rc != 0:
        raise RuntimeError("POS fetch failed")


def _extract(**_) -> None:
    settings = get_settings()
    out = Path(settings.data_input_dir) / f"dim_reference_{_run_date()}.csv"
    rc = extract_dimensions.extract_dimensions(out, settings=settings)
    if rc != 0:
        raise RuntimeError("Dimension extract failed")


def _transform(**_) -> None:
    settings = get_settings()
    staging = Path(settings.data_staging_dir)
    staging.mkdir(parents=True, exist_ok=True)
    failures = 0
    for csv_file in sorted(Path(settings.data_input_dir).glob("*.csv")):
        out = staging / f"{csv_file.stem}_clean.csv"
        if transform_sales.transform_sales(csv_file, out) != 0:
            failures += 1
    if failures:
        raise RuntimeError(f"{failures} transform(s) failed")


def _load(**_) -> None:
    settings = get_settings()
    failures = 0
    for data_file in sorted(Path(settings.data_staging_dir).glob("*_clean.csv")):
        if load_warehouse.load_warehouse(data_file, settings=settings) != 0:
            failures += 1
    if failures:
        raise RuntimeError(f"{failures} load(s) failed")


def _dq(**_) -> None:
    settings = get_settings()
    rc = data_quality_check.run_data_quality(settings=settings)
    if rc == 1:
        raise RuntimeError("Data quality checks failed")


def _archive(**_) -> None:
    settings = get_settings()
    archive_files.archive_files(settings=settings)


with DAG(
    dag_id="albertsons_nightly_etl",
    description="Nightly Albertsons store ETL (POS -> BigQuery)",
    schedule="30 1 * * *",
    start_date=datetime(2026, 1, 1, tzinfo=LOCAL_TZ),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["albertsons", "etl", "bigquery"],
) as dag:
    fetch_task = PythonOperator(task_id="fetch_pos_data", python_callable=_fetch)
    extract_task = PythonOperator(
        task_id="extract_dimensions",
        python_callable=_extract,
        trigger_rule="all_done",  # non-fatal, like the legacy pipeline
    )
    transform_task = PythonOperator(
        task_id="transform_sales", python_callable=_transform, trigger_rule="all_done"
    )
    load_task = PythonOperator(task_id="load_warehouse", python_callable=_load)
    dq_task = PythonOperator(
        task_id="data_quality_check", python_callable=_dq, trigger_rule="all_done"
    )
    archive_task = PythonOperator(
        task_id="archive_files", python_callable=_archive, trigger_rule="all_done"
    )

    fetch_task >> extract_task >> transform_task >> load_task >> dq_task >> archive_task
