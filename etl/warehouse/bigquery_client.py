"""BigQuery warehouse client.

Replacement for the legacy ``utils/snowflake_helpers.sh`` — the single choke
point that every warehouse interaction used to flow through. The Snowflake
warehouse was decommissioned in the 2026-Q2 migration; the data now lives in
BigQuery (``GCP_PROJECT.BQ_DATASET``).

Mapping from the old ``snow_*`` functions:

    snow_query           -> BigQueryClient.query / query_to_csv
    snow_run_file        -> BigQueryClient.run_file
    snow_stage_and_copy  -> BigQueryClient.load_csv (load_table_from_file)
    snow_check_connection-> BigQueryClient.check_connection

Project/dataset are read from config (``GCP_PROJECT`` / ``BQ_DATASET``).
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Iterator

from etl.config import Config, load_config
from etl.logging_setup import get_logger

if TYPE_CHECKING:  # pragma: no cover - type-checking only
    from google.cloud import bigquery

logger = get_logger(__name__)


class BigQueryClient:
    """Thin wrapper around ``google.cloud.bigquery.Client``.

    The underlying client is created lazily so the module can be imported (and
    unit-tested with an injected fake client) without GCP credentials.
    """

    def __init__(
        self,
        config: Config | None = None,
        client: "bigquery.Client | None" = None,
    ) -> None:
        self.config = config or load_config()
        self._client = client

    # -- client management ------------------------------------------------
    @property
    def client(self) -> "bigquery.Client":
        if self._client is None:
            from google.cloud import bigquery

            self._client = bigquery.Client(
                project=self.config.gcp_project,
                location=self.config.bq_location,
            )
        return self._client

    def dataset_ref(self) -> str:
        return f"{self.config.gcp_project}.{self.config.bq_dataset}"

    def table_ref(self, table: str) -> str:
        """Fully qualify ``table`` unless it already contains a dataset/project.

        ``FACT_STORE_SALES`` -> ``project.store_ops.FACT_STORE_SALES``;
        ``store_ops.dim_store`` -> ``project.store_ops.dim_store``.
        """
        parts = table.split(".")
        if len(parts) == 3:
            return table
        if len(parts) == 2:
            return f"{self.config.gcp_project}.{table}"
        return f"{self.config.gcp_project}.{self.config.bq_dataset}.{table}"

    # -- queries (replaces snow_query / snow_run_file) --------------------
    def query(self, sql: str, **job_kwargs: Any) -> "bigquery.table.RowIterator":
        """Run ``sql`` and return the completed row iterator."""
        logger.info("[bigquery] Running query against %s", self.dataset_ref())
        job = self.client.query(sql, **job_kwargs)
        return job.result()

    def query_scalar(self, sql: str) -> Any:
        """Run ``sql`` and return the first column of the first row (or None)."""
        for row in self.query(sql):
            return row[0]
        return None

    def query_rows(self, sql: str) -> list[dict[str, Any]]:
        """Run ``sql`` and return rows as a list of dicts."""
        return [dict(row.items()) for row in self.query(sql)]

    def run_file(self, sql_file: str | Path, **job_kwargs: Any) -> "bigquery.table.RowIterator":
        """Run the SQL contained in ``sql_file`` (replaces ``snow_run_file``)."""
        path = Path(sql_file)
        if not path.is_file():
            raise FileNotFoundError(f"SQL file not found: {sql_file}")
        return self.query(path.read_text(), **job_kwargs)

    def query_to_csv(
        self,
        sql: str,
        output_file: str | Path,
        header: bool = True,
    ) -> int:
        """Run ``sql`` and write the results to ``output_file`` as CSV.

        Returns the number of data rows written.
        """
        rows = self.query(sql)
        output_file = Path(output_file)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        written = 0
        with output_file.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            field_names = [field.name for field in rows.schema]
            if header and field_names:
                writer.writerow(field_names)
            for row in rows:
                writer.writerow([_csv_value(v) for v in row.values()])
                written += 1
        logger.info("[bigquery] Wrote %d rows -> %s", written, output_file)
        return written

    # -- loads (replaces snow_stage_and_copy) -----------------------------
    def load_csv(
        self,
        local_file: str | Path,
        target_table: str,
        write_disposition: str = "WRITE_APPEND",
        skip_leading_rows: int = 1,
        autodetect: bool = True,
        schema: "Iterable[bigquery.SchemaField] | None" = None,
    ) -> int:
        """Load a CSV file into ``target_table`` via a BigQuery load job.

        Replaces the Snowflake ``PUT`` + ``COPY INTO`` two-step. Returns the
        number of rows loaded.
        """
        from google.cloud import bigquery

        local_file = Path(local_file)
        if not local_file.is_file() or local_file.stat().st_size == 0:
            raise ValueError(f"Cannot load empty/missing file: {local_file}")

        table = self.table_ref(target_table)
        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.CSV,
            skip_leading_rows=skip_leading_rows,
            write_disposition=write_disposition,
            allow_quoted_newlines=True,
        )
        if schema is not None:
            job_config.schema = list(schema)
            job_config.autodetect = False
        else:
            job_config.autodetect = autodetect

        logger.info("[bigquery] Load %s -> %s", local_file, table)
        with local_file.open("rb") as fh:
            load_job = self.client.load_table_from_file(
                fh, table, job_config=job_config
            )
        load_job.result()  # wait for completion; raises on failure

        destination = self.client.get_table(table)
        logger.info(
            "[bigquery] Load complete: %s now has %d rows",
            table,
            destination.num_rows,
        )
        return int(load_job.output_rows or 0)

    # -- health check (replaces snow_check_connection) --------------------
    def check_connection(self) -> bool:
        """Return True if BigQuery is reachable."""
        try:
            self.query_scalar("SELECT 1")
            logger.info("BigQuery connection OK")
            return True
        except Exception as exc:  # pragma: no cover - network dependent
            logger.error("Cannot connect to BigQuery: %s", exc)
            return False


def _csv_value(value: Any) -> Any:
    """Render a BigQuery cell value for CSV output."""
    if value is None:
        return ""
    return value


def iter_rows(rows: "bigquery.table.RowIterator") -> Iterator[dict[str, Any]]:
    """Yield BigQuery rows as dicts (convenience helper)."""
    for row in rows:
        yield dict(row.items())
