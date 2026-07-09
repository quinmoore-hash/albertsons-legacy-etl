"""Load transformed CSV files into BigQuery.

Python port of ``scripts/load_warehouse.sh``. Auto-detects the target table
from the filename, then runs a BigQuery load job (replacing the ``snowsql`` PUT
+ COPY INTO flow) into ``${BQ_DATASET}.<table>``.

Exit codes: ``0`` success, ``1`` failure.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Optional, Sequence, Union

from etl.bigquery_client import BigQueryClient
from etl.config import Settings, get_settings
from etl.file_utils import check_file
from etl.logging_util import log_error, log_info, setup_logging

PathLike = Union[str, Path]

# filename prefix -> BigQuery table name (in the configured dataset)
TABLE_MAP = {
    "pos_store_sales": "fact_store_sales",
    "inventory": "fact_inventory",
    "dim_reference": "dim_reference",
    "product_catalog": "dim_product",
}


def detect_target_table(filepath: PathLike) -> Optional[str]:
    """Infer the BigQuery table name from a staged filename.

    Strips a trailing ``_clean.csv`` and any ``_<digits>`` datestamp, then
    matches the known prefixes. Returns ``None`` if no prefix matches.
    """
    name = Path(filepath).name
    base = name[: -len(".csv")] if name.endswith(".csv") else name
    base = base[: -len("_clean")] if base.endswith("_clean") else base
    base = re.sub(r"_\d+$", "", base)

    for prefix, table in TABLE_MAP.items():
        if base == prefix or base.startswith(prefix):
            return table
    return None


def load_warehouse(
    input_file: PathLike,
    target_table: Optional[str] = None,
    settings: Optional[Settings] = None,
    client: Optional[BigQueryClient] = None,
) -> int:
    """Load ``input_file`` into a BigQuery table (auto-detected if not given)."""
    settings = settings or get_settings()

    if check_file(input_file) != 0:
        return 1

    if not target_table:
        target_table = detect_target_table(input_file)
        if not target_table:
            log_error("Cannot determine target table for: %s", Path(input_file).name)
            return 1

    client = client or BigQueryClient(settings)
    log_info("Loading %s -> %s.%s", Path(input_file).name, settings.bq_dataset, target_table)

    if not client.check_connection():
        log_error("Warehouse unreachable; aborting load of %s", Path(input_file).name)
        return 1

    try:
        client.load_table_from_csv(input_file, target_table, skip_leading_rows=1)
    except Exception as exc:  # noqa: BLE001 - load job failure
        log_error(
            "Load failed for %s -> %s (%s)", Path(input_file).name, target_table, exc
        )
        return 1

    log_info("Load complete: %s -> %s.%s", Path(input_file).name, settings.bq_dataset, target_table)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    settings = get_settings()
    setup_logging(settings.log_dir, settings.log_level)

    parser = argparse.ArgumentParser(description="Load a CSV into BigQuery")
    parser.add_argument("input_file")
    parser.add_argument("target_table", nargs="?", default=None)
    args = parser.parse_args(argv)

    return load_warehouse(args.input_file, args.target_table, settings=settings)


if __name__ == "__main__":
    sys.exit(main())
