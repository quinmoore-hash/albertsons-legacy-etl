"""Archive processed files to GCS.

Ported from ``scripts/archive_files.sh``. Gzips staged ``*_clean.csv`` files
and uploads them to Google Cloud Storage via ``google-cloud-storage``. GCS is
now the primary (and only required) sink; the flaky NAS copy has been dropped.
"""

from __future__ import annotations

import argparse
from datetime import date
from typing import TYPE_CHECKING

from etl.config import Config, load_config
from etl.file_utils import gzip_file
from etl.logging_setup import configure_logging, get_logger

if TYPE_CHECKING:  # pragma: no cover
    from google.cloud import storage

logger = get_logger(__name__)


def _bucket(config: Config, client: "storage.Client | None"):
    from google.cloud import storage

    client = client or storage.Client(project=config.gcp_project)
    return client.bucket(config.gcs_bucket)


def archive_files(
    config: Config | None = None,
    run_date: str | None = None,
    storage_client: "storage.Client | None" = None,
    mark_inputs_done: bool = True,
) -> list[str]:
    """Gzip staged clean CSVs, upload to GCS, and return the GCS object URIs."""
    config = config or load_config()
    run_date = run_date or date.today().strftime("%Y%m%d")

    config.data_archive_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Archiving processed files for %s", run_date)

    uploaded: list[str] = []
    clean_files = sorted(config.data_staging_dir.glob("*_clean.csv"))
    if not clean_files:
        logger.warning("No *_clean.csv files found in %s", config.data_staging_dir)
        return uploaded

    bucket = _bucket(config, storage_client)

    for path in clean_files:
        if not path.is_file():
            continue
        gz_path = gzip_file(path, keep=False)
        local_archive = config.data_archive_dir / gz_path.name
        gz_path.replace(local_archive)

        blob_name = f"archive/{run_date}/{local_archive.name}"
        blob = bucket.blob(blob_name)
        blob.upload_from_filename(str(local_archive))
        uri = f"gs://{config.gcs_bucket}/{blob_name}"
        uploaded.append(uri)
        logger.info("Uploaded %s -> %s", local_archive.name, uri)

    if mark_inputs_done:
        for path in config.data_input_dir.glob("*.csv"):
            if path.is_file():
                path.rename(path.with_suffix(path.suffix + ".done"))

    logger.info("Archive complete: %d file(s) uploaded to GCS", len(uploaded))
    return uploaded


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Archive processed files to GCS")
    parser.add_argument("--run-date", help="YYYYMMDD, default today")
    args = parser.parse_args(argv)

    config = load_config()
    configure_logging(config.log_dir, config.log_level)
    try:
        archive_files(config=config, run_date=args.run_date)
    except Exception as exc:
        logger.error("Archive failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
