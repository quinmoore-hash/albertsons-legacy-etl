"""Tests for the file utilities."""

from __future__ import annotations

import gzip

from etl.file_utils import (
    ERROR,
    OK,
    WARN,
    archive_file,
    check_file,
    count_data_rows,
    file_size_hr,
    gzip_file,
    move_file,
    validate_csv,
)


def test_check_file(tmp_path):
    missing = tmp_path / "nope.csv"
    empty = tmp_path / "empty.csv"
    good = tmp_path / "good.csv"
    empty.write_text("")
    good.write_text("a,b\n1,2\n")

    assert check_file(missing) == ERROR
    assert check_file(empty) == WARN
    assert check_file(good) == OK


def test_count_data_rows(tmp_path):
    f = tmp_path / "f.csv"
    f.write_text("header\n1\n2\n3\n")
    assert count_data_rows(f) == 3
    assert count_data_rows(f, has_header=False) == 4


def test_validate_csv(tmp_path):
    good = tmp_path / "g.csv"
    good.write_text("a,b,c\n1,2,3\n4,5,6\n")
    assert validate_csv(good) == OK
    assert validate_csv(good, expected_cols=3) == OK
    assert validate_csv(good, expected_cols=5) == ERROR

    bad = tmp_path / "b.csv"
    bad.write_text("a,b,c\n1,2\n")
    assert validate_csv(bad) == WARN


def test_validate_csv_handles_quoted_commas(tmp_path):
    f = tmp_path / "q.csv"
    f.write_text('a,b\n"x, y",2\n')
    # quoted embedded comma must not be counted as an extra column
    assert validate_csv(f) == OK


def test_gzip_file(tmp_path):
    f = tmp_path / "f.csv"
    f.write_text("hello\n")
    assert gzip_file(f, keep=True) is True
    gz = tmp_path / "f.csv.gz"
    assert gz.exists()
    assert f.exists()
    with gzip.open(gz, "rt") as fh:
        assert fh.read() == "hello\n"


def test_gzip_file_no_keep(tmp_path):
    f = tmp_path / "f.csv"
    f.write_text("data\n")
    assert gzip_file(f, keep=False) is True
    assert not f.exists()
    assert (tmp_path / "f.csv.gz").exists()


def test_file_size_hr(tmp_path):
    f = tmp_path / "f.bin"
    f.write_bytes(b"x" * 2048)
    assert file_size_hr(f) == "2.0K"
    assert file_size_hr(tmp_path / "missing") == "0"


def test_move_file(tmp_path):
    src = tmp_path / "s.txt"
    dst = tmp_path / "d.txt"
    src.write_text("x")
    assert move_file(src, dst) is True
    assert dst.exists() and not src.exists()


def test_move_file_failure(tmp_path):
    assert move_file(tmp_path / "missing", tmp_path / "d.txt", retries=1) is False


def test_archive_file(tmp_path):
    src = tmp_path / "data.csv"
    src.write_text("a,b\n1,2\n")
    dest_dir = tmp_path / "arch"
    result = archive_file(src, dest_dir)
    assert result is not None
    assert dest_dir.exists()
    assert list(dest_dir.glob("data_*.csv"))
