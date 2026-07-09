"""Tests for etl.data_quality_check."""

from __future__ import annotations

from pathlib import Path

from etl.data_quality_check import run_dq_checks
from etl.load_warehouse import detect_target_table
from tests.test_bigquery_client import FakeBQClient

from etl.warehouse import BigQueryClient


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_local_checks_pass(config):
    _write(
        config.data_staging_dir / "pos_store_sales_clean.csv",
        "store_id,units\n0412,10\n0731,20\n",
    )
    report = run_dq_checks("DQ_TEST", config=config, check_warehouse=False)
    assert report.failed == 0
    assert report.exit_code() == 0
    assert report.report_file.exists()


def test_null_key_and_dupes_warn(config):
    _write(
        config.data_staging_dir / "inventory_clean.csv",
        "store_id,units\n0412,10\n0412,20\n,30\n",
    )
    report = run_dq_checks("DQ_TEST", config=config, check_warehouse=False)
    # duplicate 0412 + one empty key => two warnings, no failures
    assert report.failed == 0
    assert report.warned == 2
    assert report.exit_code() == 2


def test_empty_file_fails(config):
    _write(config.data_staging_dir / "pos_store_sales_clean.csv", "store_id,units\n")
    report = run_dq_checks("DQ_TEST", config=config, check_warehouse=False)
    assert report.failed == 1
    assert report.exit_code() == 1


def test_warehouse_assertion_pass(config):
    _write(
        config.data_staging_dir / "pos_store_sales_clean.csv",
        "store_id,units\n0412,10\n",
    )
    client = BigQueryClient(config=config, client=FakeBQClient(rows=[{"c": 123}]))
    report = run_dq_checks("DQ_TEST", config=config, client=client, check_warehouse=True)
    assert report.failed == 0
    assert any("warehouse:fact_store_sales" in line for line in report.lines)


def test_warehouse_assertion_zero_rows_fails(config):
    _write(
        config.data_staging_dir / "pos_store_sales_clean.csv",
        "store_id,units\n0412,10\n",
    )
    client = BigQueryClient(config=config, client=FakeBQClient(rows=[{"c": 0}]))
    report = run_dq_checks("DQ_TEST", config=config, client=client, check_warehouse=True)
    assert report.failed == 1


def test_detect_target_table():
    assert detect_target_table("pos_store_sales_20260708_clean.csv") == "FACT_STORE_SALES"
    assert detect_target_table("inventory_20260708_clean.csv") == "FACT_INVENTORY"
    assert detect_target_table("dim_reference_20260708_clean.csv") == "DIM_REFERENCE"
    assert detect_target_table("product_catalog_clean.csv") == "DIM_PRODUCT"
    assert detect_target_table("random_file.csv") is None
