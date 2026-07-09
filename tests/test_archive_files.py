"""Tests for the archive + GCS upload step (GCS client mocked)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from etl.archive_files import archive_files, upload_to_gcs


def test_upload_to_gcs(tmp_path):
    f1 = tmp_path / "a.gz"
    f2 = tmp_path / "b.gz"
    f1.write_bytes(b"1")
    f2.write_bytes(b"2")

    client = MagicMock()
    bucket = MagicMock()
    client.bucket.return_value = bucket

    count = upload_to_gcs("my-bucket", [f1, f2], "archive/20260709", client=client)
    assert count == 2
    client.bucket.assert_called_once_with("my-bucket")
    assert bucket.blob.call_count == 2
    bucket.blob.assert_any_call("archive/20260709/a.gz")


def test_archive_files_flow(settings):
    staging = Path(settings.data_staging_dir)
    inp = Path(settings.data_input_dir)
    (staging / "pos_store_sales_clean.csv").write_text("store_id,v\n0412,1\n")
    (inp / "pos_store_sales_20260709.csv").write_text("store_id,v\n0412,1\n")

    gcs_client = MagicMock()
    gcs_client.bucket.return_value = MagicMock()

    rc = archive_files(settings=settings, gcs_client=gcs_client, run_date="20260709")
    assert rc == 0

    # staged clean file compressed and moved to archive dir
    archive_dir = Path(settings.data_archive_dir)
    assert list(archive_dir.glob("*.gz"))
    # raw input renamed to .done
    assert list(inp.glob("*.done"))
    # uploaded to GCS
    gcs_client.bucket.assert_called_once_with(settings.gcs_bucket)
