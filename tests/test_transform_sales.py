"""Tests for the transform/cleaning logic."""

from __future__ import annotations

import csv

import pytest

from etl.transform_sales import normalize_date, transform_rows, transform_sales


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("07/07/2026", "2026-07-07"),  # US MM/DD/YYYY
        ("7/7/2026", "2026-07-07"),  # single-digit
        ("2026-07-07", "2026-07-07"),  # already ISO -> unchanged
        ("2026/07/07", "2026-07-07"),  # ISO with slashes
        ("25/12/2026", "2026-12-25"),  # unambiguous DD/MM (day > 12)
        ("13/06/2026", "2026-06-13"),  # day > 12 -> day-first
        ("not-a-date", "not-a-date"),  # untouched
        ("SKU-0098213", "SKU-0098213"),  # untouched
        ("3.49", "3.49"),  # untouched
        ("13/13/2026", "13/13/2026"),  # invalid month/day -> unchanged
    ],
)
def test_normalize_date(raw, expected):
    assert normalize_date(raw) == expected


def test_normalize_date_ambiguous_dayfirst():
    # Both components <= 12 => ambiguous; honor dayfirst flag.
    assert normalize_date("03/04/2026") == "2026-03-04"  # month-first default
    assert normalize_date("03/04/2026", dayfirst=True) == "2026-04-03"


def test_transform_rows_appends_metadata_and_cleans():
    rows = [
        ["store_id", "sku", "transaction_date", "loyalty_id"],
        [" 0412 ", "SKU-1", "07/07/2026", "NULL"],
        ["0731", "SKU-2", "2026-07-08", "N/A"],
    ]
    out = transform_rows(rows, run_date="2026-07-09", source_file="src.csv")

    assert out[0] == ["store_id", "sku", "transaction_date", "loyalty_id", "_load_date", "_source_file"]
    # trimmed whitespace, normalized date, blanked NULL token, metadata appended
    assert out[1] == ["0412", "SKU-1", "2026-07-07", "", "2026-07-09", "src.csv"]
    assert out[2] == ["0731", "SKU-2", "2026-07-08", "", "2026-07-09", "src.csv"]


def test_transform_rows_drops_blank_lines():
    rows = [
        ["a", "b"],
        [],
        ["", "   "],
        ["1", "2"],
    ]
    out = transform_rows(rows, run_date="2026-07-09", source_file="s.csv")
    # header + one data row (blank rows dropped)
    assert len(out) == 2
    assert out[1] == ["1", "2", "2026-07-09", "s.csv"]


def test_transform_file_handles_bom_and_embedded_commas(tmp_path):
    src = tmp_path / "in.csv"
    # UTF-8 BOM + a quoted field containing a comma
    content = '\ufeffstore_id,product_name,transaction_date\n'
    content += '0412,"Milk, 1gal",07/07/2026\r\n'
    src.write_text(content, encoding="utf-8")

    out = tmp_path / "out.csv"
    rc = transform_sales(src, out, run_date="2026-07-09")
    assert rc == 0

    with out.open(newline="") as fh:
        rows = list(csv.reader(fh))

    assert rows[0][0] == "store_id"  # BOM stripped
    assert rows[0][-2:] == ["_load_date", "_source_file"]
    # embedded comma preserved as a single field
    assert rows[1][1] == "Milk, 1gal"
    assert rows[1][2] == "2026-07-07"
    assert rows[1][-2:] == ["2026-07-09", "in.csv"]


def test_transform_file_missing_input(tmp_path):
    assert transform_sales(tmp_path / "nope.csv", tmp_path / "out.csv") == 1
