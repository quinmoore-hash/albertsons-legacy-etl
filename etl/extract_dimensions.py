"""Extract reference/dimension data from BigQuery.

Python port of the legacy ``scripts/extract_from_snowflake.sh`` (renamed away
from "snowflake"). Builds a single wide reference extract by joining the
``dim_store`` and ``dim_region`` tables in the BigQuery ``store_ops`` dataset
and writes it to a CSV that the nightly sales feed is joined against
downstream.

Exit codes: ``0`` success, ``1`` failure.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import date
from pathlib import Path
from typing import Optional, Sequence, Union

from etl.bigquery_client import BigQueryClient
from etl.config import Settings, get_settings
from etl.logging_util import log_error, log_info, setup_logging

PathLike = Union[str, Path]

EXTRACT_COLUMNS = [
    "store_id",
    "store_name",
    "region_code",
    "region_name",
    "banner",
    "timezone",
]


def _build_sql(settings: Settings) -> str:
    dataset = settings.dataset_ref()
    return f"""
SELECT s.store_id,
       s.store_name,
       s.region_code,
       r.region_name,
       s.banner,
       s.timezone
FROM   `{dataset}.dim_store`  AS s
JOIN   `{dataset}.dim_region` AS r
  ON   s.region_code = r.region_code
WHERE  s.active = TRUE
ORDER  BY s.store_id
""".strip()


def extract_dimensions(
    output_file: PathLike,
    settings: Optional[Settings] = None,
    client: Optional[BigQueryClient] = None,
) -> int:
    """Query the BigQuery dimension tables and write the reference CSV."""
    settings = settings or get_settings()
    client = client or BigQueryClient(settings)

    out_path = Path(output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    log_info("Extracting reference dimensions from BigQuery -> %s", out_path)

    if not client.check_connection():
        log_error("BigQuery unreachable. Cannot extract dimensions.")
        return 1

    try:
        rows = client.query(_build_sql(settings))
        written = 0
        with out_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(EXTRACT_COLUMNS)
            for row in rows:
                writer.writerow([row[col] for col in EXTRACT_COLUMNS])
                written += 1
    except Exception as exc:  # noqa: BLE001 - surface any query/IO failure
        log_error("Dimension extract query failed: %s", exc)
        return 1

    log_info("Extracted %s dimension rows -> %s", written, out_path)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    settings = get_settings()
    setup_logging(settings.log_dir, settings.log_level)

    parser = argparse.ArgumentParser(description="Extract store/region dimensions from BigQuery")
    default_out = os.path.join(
        settings.data_input_dir, f"dim_reference_{date.today():%Y%m%d}.csv"
    )
    parser.add_argument("output_file", nargs="?", default=default_out)
    args = parser.parse_args(argv)

    return extract_dimensions(args.output_file, settings=settings)


if __name__ == "__main__":
    sys.exit(main())
