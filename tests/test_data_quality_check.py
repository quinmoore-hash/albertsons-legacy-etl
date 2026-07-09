"""Tests for the data quality checks."""

from __future__ import annotations

from etl.data_quality_check import (
    EXIT_FAIL,
    EXIT_OK,
    EXIT_WARN,
    DataQualityChecker,
    check_csv_file,
    run_data_quality,
)


def _write_csv(path, rows):
    path.write_text("\n".join(",".join(r) for r in rows) + "\n", encoding="utf-8")


def test_check_csv_file_all_pass(tmp_path):
    f = tmp_path / "pos_store_sales_clean.csv"
    _write_csv(f, [["store_id", "v"], ["0412", "1"], ["0731", "2"]])
    results = {r.name.split(":")[0]: r.status for r in check_csv_file(f)}
    assert results == {"row_count": "PASS", "null_key": "PASS", "dupes": "PASS"}


def test_check_csv_file_null_and_dupe_warn(tmp_path):
    f = tmp_path / "x_clean.csv"
    _write_csv(f, [["store_id", "v"], ["", "1"], ["0412", "2"], ["0412", "3"]])
    by_kind = {r.name.split(":")[0]: r for r in check_csv_file(f)}
    assert by_kind["null_key"].status == "WARN"
    assert "1 rows" in by_kind["null_key"].details
    assert by_kind["dupes"].status == "WARN"
    assert "1 duplicate" in by_kind["dupes"].details


def test_check_csv_file_empty_fails(tmp_path):
    f = tmp_path / "empty_clean.csv"
    _write_csv(f, [["store_id", "v"]])  # header only
    row_count = next(r for r in check_csv_file(f) if r.name.startswith("row_count"))
    assert row_count.status == "FAIL"


def test_checker_exit_codes():
    c = DataQualityChecker()
    c.record("a", "PASS", "")
    assert c.exit_code() == EXIT_OK
    c.record("b", "WARN", "")
    assert c.exit_code() == EXIT_WARN
    c.record("c", "FAIL", "")
    assert c.exit_code() == EXIT_FAIL


def test_run_data_quality_writes_report(settings):
    staging = settings.data_staging_dir
    f = f"{staging}/pos_store_sales_clean.csv"
    with open(f, "w", encoding="utf-8") as fh:
        fh.write("store_id,v\n0412,1\n0731,2\n")

    rc = run_data_quality("DQ_TEST", settings=settings, skip_warehouse=True)
    assert rc == EXIT_OK

    report = list(__import__("pathlib").Path(settings.log_dir).glob("dq_report_*.txt"))
    assert report, "expected a dated DQ report file"
    text = report[0].read_text()
    assert "DQ_TEST" in text
    assert "row_count:pos_store_sales_clean.csv" in text
