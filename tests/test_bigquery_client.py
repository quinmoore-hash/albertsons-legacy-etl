"""Tests for etl.warehouse.bigquery_client using an injected fake client."""

from __future__ import annotations

import csv

import pytest

from etl.warehouse import BigQueryClient


class FakeField:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeRow:
    def __init__(self, mapping: dict) -> None:
        self._mapping = mapping

    def __getitem__(self, idx):
        return list(self._mapping.values())[idx]

    def values(self):
        return list(self._mapping.values())

    def items(self):
        return self._mapping.items()


class FakeRowIterator:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = [FakeRow(r) for r in rows]
        self.schema = [FakeField(k) for k in (rows[0].keys() if rows else [])]

    def __iter__(self):
        return iter(self._rows)


class FakeQueryJob:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def result(self):
        return FakeRowIterator(self._rows)


class FakeLoadJob:
    def __init__(self, output_rows: int) -> None:
        self.output_rows = output_rows

    def result(self):
        return None


class FakeTable:
    num_rows = 42


class FakeBQClient:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self._rows = rows or [{"n": 1}]
        self.loaded: list[tuple] = []

    def query(self, sql, **kwargs):
        return FakeQueryJob(self._rows)

    def load_table_from_file(self, fh, table, job_config=None):
        data = fh.read()
        self.loaded.append((table, data, job_config))
        # count data rows (minus header) for output_rows
        lines = data.decode("utf-8").splitlines()
        return FakeLoadJob(max(len(lines) - 1, 0))

    def get_table(self, table):
        return FakeTable()


@pytest.fixture
def bq(config):
    return BigQueryClient(config=config, client=FakeBQClient(rows=[{"c": 7}]))


def test_table_ref_qualification(config):
    client = BigQueryClient(config=config, client=FakeBQClient())
    assert client.table_ref("FACT_STORE_SALES") == (
        f"{config.gcp_project}.{config.bq_dataset}.FACT_STORE_SALES"
    )
    assert client.table_ref("store_ops.dim_store") == (
        f"{config.gcp_project}.store_ops.dim_store"
    )
    assert client.table_ref("proj.ds.tbl") == "proj.ds.tbl"


def test_query_scalar(bq):
    assert bq.query_scalar("SELECT 7") == 7


def test_query_rows(bq):
    assert bq.query_rows("SELECT c") == [{"c": 7}]


def test_query_to_csv(config, tmp_path):
    client = BigQueryClient(
        config=config,
        client=FakeBQClient(rows=[{"store_id": "0412", "n": 3}, {"store_id": "0731", "n": 5}]),
    )
    out = tmp_path / "dims.csv"
    written = client.query_to_csv("SELECT store_id, n FROM t", out)
    assert written == 2
    with out.open(newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == ["store_id", "n"]
    assert rows[1] == ["0412", "3"]


def test_load_csv(config, tmp_path):
    fake = FakeBQClient()
    client = BigQueryClient(config=config, client=fake)
    src = tmp_path / "data.csv"
    src.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    loaded = client.load_csv(src, "FACT_STORE_SALES")
    assert loaded == 2
    table, _data, job_config = fake.loaded[0]
    assert table.endswith("FACT_STORE_SALES")
    assert job_config.skip_leading_rows == 1


def test_load_csv_empty_raises(config, tmp_path):
    client = BigQueryClient(config=config, client=FakeBQClient())
    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        client.load_csv(empty, "FACT_STORE_SALES")


def test_check_connection_ok(bq):
    assert bq.check_connection() is True
