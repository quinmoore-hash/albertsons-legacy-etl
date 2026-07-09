"""Tests for the BigQuery dimension extract step (BigQuery mocked)."""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import MagicMock

from etl.extract_dimensions import _build_sql, extract_dimensions


def test_build_sql_targets_bigquery_dataset(settings):
    sql = _build_sql(settings)
    assert "albertsons-retail-analytics.store_ops.dim_store" in sql
    assert "albertsons-retail-analytics.store_ops.dim_region" in sql
    assert "snowflake" not in sql.lower()


def test_extract_dimensions_writes_csv(settings):
    out = Path(settings.data_input_dir) / "dim_reference.csv"

    client = MagicMock()
    client.check_connection.return_value = True
    client.query.return_value = [
        {
            "store_id": "0412",
            "store_name": "Store 412",
            "region_code": "PNW",
            "region_name": "Pacific NW",
            "banner": "Albertsons",
            "timezone": "America/Los_Angeles",
        }
    ]

    rc = extract_dimensions(out, settings=settings, client=client)
    assert rc == 0

    with out.open(newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == ["store_id", "store_name", "region_code", "region_name", "banner", "timezone"]
    assert rows[1][0] == "0412"


def test_extract_dimensions_unreachable(settings):
    out = Path(settings.data_input_dir) / "dim_reference.csv"
    client = MagicMock()
    client.check_connection.return_value = False
    assert extract_dimensions(out, settings=settings, client=client) == 1
