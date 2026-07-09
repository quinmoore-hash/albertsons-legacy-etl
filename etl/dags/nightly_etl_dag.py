"""Cloud Composer (Airflow) DAG for the nightly store ETL.

Replaces the cron-on-a-VM orchestration (``scripts/run_nightly_etl.sh`` +
``scripts/install_cron.sh``). Each pipeline step is a discrete task so
Airflow provides retries, alerting, backfills, and — importantly — a single
active run, which removes the need for the old ``/tmp`` lock file.

Tasks: fetch -> extract -> transform -> load -> dq -> archive.

Deploy by dropping this file into the Composer environment's ``dags/`` GCS
folder. Pipeline configuration (``GCP_PROJECT``, ``BQ_DATASET`` etc.) is read
from the environment / ``configs/pipeline.env`` by :func:`etl.config.load_config`.
"""

from __future__ import annotations

from datetime import datetime, timedelta

# Airflow is only available in the Composer runtime; guard the import so the
# rest of the package (and the test suite) can be imported without it.
try:
    from airflow import DAG
    from airflow.operators.python import PythonOperator

    _AIRFLOW_AVAILABLE = True
except ImportError:  # pragma: no cover - Airflow not installed locally
    _AIRFLOW_AVAILABLE = False


def _fetch(**_):
    from etl.config import load_config
    from etl.fetch_pos_data import fetch_pos_data

    fetch_pos_data(config=load_config())


def _extract(**_):
    from etl.config import load_config
    from etl.extract_dimensions import extract_dimensions

    extract_dimensions(config=load_config())


def _transform(**_):
    from etl.config import load_config
    from etl.run_nightly_etl import transform_all

    transform_all(load_config())


def _load(**_):
    from etl.config import load_config
    from etl.run_nightly_etl import load_all

    load_all(load_config())


def _dq(**_):
    from etl.config import load_config
    from etl.data_quality_check import run_dq_checks

    report = run_dq_checks(config=load_config())
    if report.exit_code() == 1:
        raise RuntimeError("Data quality checks failed")


def _archive(**_):
    from etl.config import load_config
    from etl.archive_files import archive_files

    archive_files(config=load_config())


_TASKS = [
    ("fetch_pos_data", _fetch),
    ("extract_dimensions", _extract),
    ("transform_sales", _transform),
    ("load_warehouse", _load),
    ("data_quality_check", _dq),
    ("archive_files", _archive),
]


if _AIRFLOW_AVAILABLE:
    default_args = {
        "owner": "store-data-ops",
        "retries": 2,
        "retry_delay": timedelta(minutes=5),
        "email": ["store-data-ops@albertsons.com"],
        "email_on_failure": True,
    }

    with DAG(
        dag_id="albertsons_nightly_etl",
        description="Nightly Albertsons store ETL (BigQuery/GCS)",
        default_args=default_args,
        # 01:30 America/Los_Angeles, matching the legacy cron schedule.
        schedule_interval="30 1 * * *",
        start_date=datetime(2026, 7, 1),
        catchup=False,
        max_active_runs=1,
        tags=["etl", "bigquery", "store-ops"],
    ) as dag:
        previous = None
        for task_id, callable_ in _TASKS:
            task = PythonOperator(task_id=task_id, python_callable=callable_)
            if previous is not None:
                previous >> task
            previous = task
