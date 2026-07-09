"""Tests for the BigQuery client wrapper (external calls mocked)."""

from __future__ import annotations

from unittest.mock import MagicMock

from google.cloud import bigquery
from google.cloud.exceptions import GoogleCloudError, NotFound

from etl.bigquery_client import BigQueryClient


def _make(settings):
    return BigQueryClient(settings=settings, client=MagicMock(name="bq_client"))


def test_query_returns_result_rows(settings):
    bq = _make(settings)
    bq.client.query.return_value.result.return_value = ["r1", "r2"]
    rows = bq.query("SELECT 1")
    bq.client.query.assert_called_once_with("SELECT 1")
    assert list(rows) == ["r1", "r2"]


def test_scalar(settings):
    bq = _make(settings)
    bq.client.query.return_value.result.return_value = [[42]]
    assert bq.scalar("SELECT COUNT(*) FROM t") == 42


def test_load_table_from_csv_builds_job_config(settings, tmp_path):
    csv_path = tmp_path / "pos_store_sales_clean.csv"
    csv_path.write_text("store_id,v\n0412,1\n", encoding="utf-8")

    bq = _make(settings)
    job = MagicMock()
    job.output_rows = 1
    bq.client.load_table_from_file.return_value = job

    bq.load_table_from_csv(csv_path, "fact_store_sales")

    args, kwargs = bq.client.load_table_from_file.call_args
    table_ref = args[1]
    job_config = kwargs["job_config"]
    assert table_ref == "albertsons-retail-analytics.store_ops.fact_store_sales"
    assert job_config.source_format == bigquery.SourceFormat.CSV
    assert job_config.skip_leading_rows == 1
    job.result.assert_called_once()


def test_check_connection_success(settings):
    bq = _make(settings)
    bq.client.query.return_value.result.return_value = [[1]]
    assert bq.check_connection() is True


def test_check_connection_failure(settings):
    bq = _make(settings)
    bq.client.query.side_effect = GoogleCloudError("boom")
    assert bq.check_connection() is False


def test_check_dataset_missing(settings):
    bq = _make(settings)
    bq.client.get_dataset.side_effect = NotFound("nope")
    assert bq.check_dataset() is False


def test_check_dataset_ok(settings):
    bq = _make(settings)
    bq.client.get_dataset.return_value = object()
    assert bq.check_dataset() is True


def test_resolve_table(settings):
    bq = _make(settings)
    assert bq._resolve_table("fact_store_sales") == "albertsons-retail-analytics.store_ops.fact_store_sales"
    assert bq._resolve_table("store_ops.dim_store") == "albertsons-retail-analytics.store_ops.dim_store"
    assert bq._resolve_table("proj.ds.tbl") == "proj.ds.tbl"
