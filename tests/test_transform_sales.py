"""Tests for etl.transform_sales, including the two fixed legacy bugs."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from etl.transform_sales import normalize_date, transform_file


def _read_rows(path: Path) -> list[list[str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.reader(fh))


def test_transform_sample_appends_metadata_columns(sample_sales_csv, tmp_path):
    out = tmp_path / "pos_store_sales_clean.csv"
    rows = transform_file(sample_sales_csv, out, load_date="2026-07-08")

    assert rows == 15  # 16 lines - header
    data = _read_rows(out)
    header = data[0]
    assert header[-2:] == ["_load_date", "_source_file"]
    # Every data row carries the load date and source file name.
    for row in data[1:]:
        assert row[-2] == "2026-07-08"
        assert row[-1] == "store_sales_sample.csv"


def test_dates_normalized_to_iso(sample_sales_csv, tmp_path):
    out = tmp_path / "clean.csv"
    transform_file(sample_sales_csv, out, load_date="2026-07-08")
    data = _read_rows(out)
    header = data[0]
    tx_idx = header.index("transaction_date")
    assert all(row[tx_idx] == "2026-07-07" for row in data[1:])


def test_null_tokens_blanked(sample_sales_csv, tmp_path):
    out = tmp_path / "clean.csv"
    transform_file(sample_sales_csv, out, load_date="2026-07-08")
    data = _read_rows(out)
    header = data[0]
    rev_idx = header.index("revenue")
    # The sample has one revenue cell of "N/A" which must become blank.
    assert "" in [row[rev_idx] for row in data[1:]]
    assert "N/A" not in [row[rev_idx] for row in data[1:]]


def test_embedded_comma_not_split(tmp_path):
    """Bug #1: a quoted field with an embedded comma must stay one column."""
    src = tmp_path / "in.csv"
    src.write_text(
        'store_id,product_name,transaction_date\n'
        '0412,"Milk, Whole 1gal",07/07/2026\n',
        encoding="utf-8",
    )
    out = tmp_path / "out.csv"
    transform_file(src, out, load_date="2026-07-08")
    data = _read_rows(out)
    # 3 original cols + 2 metadata cols.
    assert len(data[1]) == 5
    assert data[1][1] == "Milk, Whole 1gal"


def test_bom_stripped(tmp_path):
    src = tmp_path / "in.csv"
    src.write_bytes(b"\xef\xbb\xbfstore_id,x\n0412,1\n")
    out = tmp_path / "out.csv"
    transform_file(src, out, load_date="2026-07-08")
    data = _read_rows(out)
    assert data[0][0] == "store_id"  # no BOM prefix


def test_blank_rows_dropped(tmp_path):
    src = tmp_path / "in.csv"
    src.write_text("store_id,x\n0412,1\n\n , \n0731,2\n", encoding="utf-8")
    out = tmp_path / "out.csv"
    rows = transform_file(src, out, load_date="2026-07-08")
    assert rows == 2


@pytest.mark.parametrize(
    "value,expected",
    [
        ("07/07/2026", "2026-07-07"),
        ("13/07/2026", "2026-07-13"),  # Bug #2: day-first, not mangled
        ("2026-07-07", "2026-07-07"),
        ("not-a-date", "not-a-date"),
        ("495.58", "495.58"),  # numeric untouched
    ],
)
def test_normalize_date(value, expected):
    assert normalize_date(value) == expected


def test_missing_input_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        transform_file(tmp_path / "nope.csv", tmp_path / "out.csv")
