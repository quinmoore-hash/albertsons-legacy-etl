"""Extract store/region reference dimensions from BigQuery.

Ported from ``scripts/extract_from_snowflake.sh``. Replaces the ``snowsql``
dimension extract with a BigQuery query joining ``store_ops.dim_store`` to
``store_ops.dim_region``, writing CSV output. The decommissioned Snowflake
account is no longer referenced.
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from etl.config import Config, load_config
from etl.logging_setup import configure_logging, get_logger
from etl.warehouse import BigQueryClient

logger = get_logger(__name__)


def _extract_sql(dataset: str) -> str:
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


def _default_output(config: Config) -> Path:
    return config.data_input_dir / f"dim_reference_{date.today():%Y%m%d}.csv"


def extract_dimensions(
    output_file: str | Path | None = None,
    config: Config | None = None,
    client: BigQueryClient | None = None,
) -> Path:
    """Run the dimension extract query and write CSV to ``output_file``."""
    config = config or load_config()
    client = client or BigQueryClient(config)
    output_file = Path(output_file) if output_file else _default_output(config)

    dataset = f"{config.gcp_project}.{config.bq_dataset}"
    logger.info("Extracting reference dimensions from BigQuery -> %s", output_file)

    rows = client.query_to_csv(_extract_sql(dataset), output_file, header=True)
    logger.info("Extracted %d dimension rows -> %s", rows, output_file)
    return output_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract reference dimensions from BigQuery")
    parser.add_argument("output_file", nargs="?", help="Destination CSV path")
    args = parser.parse_args(argv)

    config = load_config()
    configure_logging(config.log_dir, config.log_level)
    try:
        extract_dimensions(args.output_file, config=config)
    except Exception as exc:
        logger.error("Dimension extract failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
