"""Load transformed CSV files into BigQuery.

Ported from ``scripts/load_warehouse.sh``. Replaces the Snowflake
``PUT`` + ``COPY INTO`` with a BigQuery load job, preserving the
filename -> table auto-detection mapping.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from etl.config import Config, load_config
from etl.logging_setup import configure_logging, get_logger
from etl.warehouse import BigQueryClient

logger = get_logger(__name__)

# filename prefix -> BigQuery table (in the configured dataset). These mirror
# the legacy STORE_OPS.* Snowflake targets.
TABLE_MAP: dict[str, str] = {
    "pos_store_sales": "FACT_STORE_SALES",
    "inventory": "FACT_INVENTORY",
    "dim_reference": "DIM_REFERENCE",
    "product_catalog": "DIM_PRODUCT",
}


def detect_target_table(filename: str) -> str | None:
    """Auto-detect the target table from a (clean) CSV filename."""
    base = Path(filename).name
    base = re.sub(r"_clean\.csv$", "", base)
    base = re.sub(r"\.csv$", "", base)
    base = re.sub(r"_\d+$", "", base)  # strip trailing date/id suffix
    for prefix, table in TABLE_MAP.items():
        if base.startswith(prefix):
            return table
    return None


def load_warehouse(
    input_file: str | Path,
    target_table: str | None = None,
    config: Config | None = None,
    client: BigQueryClient | None = None,
) -> int:
    """Load ``input_file`` into ``target_table`` (auto-detected if omitted)."""
    config = config or load_config()
    client = client or BigQueryClient(config)
    input_file = Path(input_file)

    if not input_file.is_file() or input_file.stat().st_size == 0:
        raise ValueError(f"Missing or empty input file: {input_file}")

    if target_table is None:
        target_table = detect_target_table(input_file.name)
        if target_table is None:
            raise ValueError(f"Cannot determine target table for: {input_file.name}")

    logger.info("Loading %s -> %s", input_file.name, target_table)
    rows = client.load_csv(input_file, target_table)
    logger.info("Load complete: %s -> %s (%d rows)", input_file.name, target_table, rows)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load a CSV into BigQuery")
    parser.add_argument("input_file")
    parser.add_argument("target_table", nargs="?", help="Override auto-detected table")
    args = parser.parse_args(argv)

    config = load_config()
    configure_logging(config.log_dir, config.log_level)
    try:
        load_warehouse(args.input_file, args.target_table, config=config)
    except Exception as exc:
        logger.error("Load failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
