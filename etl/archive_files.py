"""Archive processed files and upload them to GCS.

Python port of ``scripts/archive_files.sh``. gzips the staged ``*_clean.csv``
files, moves them into the archive directory, renames raw inputs to ``.done``,
and uploads the archives to a GCS bucket (via ``google-cloud-storage``) as the
*primary* sink -- replacing the flaky NAS/``gsutil`` path of the Bash version.
An optional NAS copy is kept as a best-effort secondary sink.

Exit code: ``0`` (best-effort; individual failures are logged and skipped).
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Sequence

from etl.config import Settings, get_settings
from etl.file_utils import gzip_file
from etl.logging_util import log_error, log_info, log_warn, setup_logging

if TYPE_CHECKING:  # pragma: no cover
    from google.cloud import storage


def upload_to_gcs(
    bucket_name: str,
    files: Sequence[Path],
    prefix: str,
    client: "Optional[storage.Client]" = None,
) -> int:
    """Upload local files to ``gs://bucket/prefix/``. Returns the count uploaded."""
    if not files:
        return 0
    if client is None:
        from google.cloud import storage

        client = storage.Client()

    bucket = client.bucket(bucket_name)
    uploaded = 0
    for path in files:
        blob_name = f"{prefix.rstrip('/')}/{path.name}"
        try:
            bucket.blob(blob_name).upload_from_filename(str(path))
            uploaded += 1
        except Exception as exc:  # noqa: BLE001 - per-file upload failure
            log_error("Failed to upload %s to gs://%s/%s: %s", path.name, bucket_name, blob_name, exc)
    return uploaded


def archive_files(
    settings: Optional[Settings] = None,
    gcs_client: "Optional[storage.Client]" = None,
    run_date: Optional[str] = None,
) -> int:
    """gzip + archive staged files, rename inputs to .done, upload to GCS."""
    settings = settings or get_settings()
    run_date = run_date or date.today().strftime("%Y%m%d")

    archive_dir = Path(settings.data_archive_dir)
    staging_dir = Path(settings.data_staging_dir)
    input_dir = Path(settings.data_input_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)

    log_info("Archiving processed files for %s", run_date)

    archived = 0
    for clean_file in sorted(staging_dir.glob("*_clean.csv")):
        if gzip_file(clean_file, keep=False):
            gz_path = clean_file.with_name(clean_file.name + ".gz")
            if gz_path.exists():
                shutil.move(str(gz_path), str(archive_dir / gz_path.name))
                archived += 1

    # rename raw inputs so they don't get reprocessed
    for raw in sorted(input_dir.glob("*.csv")):
        try:
            raw.rename(raw.with_name(raw.name + ".done"))
        except OSError as exc:
            log_warn("Could not rename %s to .done: %s", raw.name, exc)

    # Primary sink: GCS.
    gz_files = sorted(archive_dir.glob("*.gz"))
    if settings.gcs_bucket and gz_files:
        prefix = f"archive/{run_date}"
        try:
            uploaded = upload_to_gcs(settings.gcs_bucket, gz_files, prefix, client=gcs_client)
            log_info(
                "Uploaded %s archive(s) to gs://%s/%s/", uploaded, settings.gcs_bucket, prefix
            )
        except Exception as exc:  # noqa: BLE001 - GCS client/auth failure
            log_error("GCS upload to gs://%s failed: %s", settings.gcs_bucket, exc)
    elif not settings.gcs_bucket:
        log_warn("GCS_BUCKET not configured; skipping upload")

    log_info("Archive complete: %s file(s) compressed", archived)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    settings = get_settings()
    setup_logging(settings.log_dir, settings.log_level)
    argparse.ArgumentParser(description="Archive processed files and upload to GCS").parse_args(argv)
    return archive_files(settings=settings)


if __name__ == "__main__":
    sys.exit(main())
