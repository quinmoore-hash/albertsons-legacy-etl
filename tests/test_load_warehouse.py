"""Tests for warehouse-load target-table detection and load flow."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from etl.load_warehouse import detect_target_table, load_warehouse


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("pos_store_sales_20260709_clean.csv", "fact_store_sales"),
        ("inventory_20260709_clean.csv", "fact_inventory"),
        ("dim_reference_20260709_clean.csv", "dim_reference"),
        ("product_catalog_clean.csv", "dim_product"),
        ("mystery_file_clean.csv", None),
    ],
)
def test_detect_target_table(filename, expected):
    assert detect_target_table(filename) == expected


def test_load_warehouse_success(settings, tmp_path):
    f = tmp_path / "pos_store_sales_20260709_clean.csv"
    f.write_text("store_id,v\n0412,1\n")

    client = MagicMock()
    client.check_connection.return_value = True
    rc = load_warehouse(f, settings=settings, client=client)
    assert rc == 0
    client.load_table_from_csv.assert_called_once()


def test_load_warehouse_unreachable(settings, tmp_path):
    f = tmp_path / "pos_store_sales_clean.csv"
    f.write_text("store_id,v\n0412,1\n")

    client = MagicMock()
    client.check_connection.return_value = False
    rc = load_warehouse(f, settings=settings, client=client)
    assert rc == 1
    client.load_table_from_csv.assert_not_called()


def test_load_warehouse_unknown_table(settings, tmp_path):
    f = tmp_path / "weird_clean.csv"
    f.write_text("k,v\n1,2\n")
    client = MagicMock()
    rc = load_warehouse(f, settings=settings, client=client)
    assert rc == 1
