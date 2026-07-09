"""BigQuery client wrapper for the Albertsons ETL pipeline.

Python replacement for ``utils/snowflake_helpers.sh`` -- the single
highest-value module to port. Every warehouse interaction (dimension extracts,
warehouse loads, DQ count queries) flows through here.

The legacy module shelled out to the ``snowsql`` CLI against the decommissioned
``alb_prod.us-east-1`` Snowflake account. This replaces ``snow_query`` with
BigQuery query jobs (``client.query(sql).result()`` / ``.to_dataframe()``) and
``snow_stage_and_copy`` (PUT + COPY INTO) with a BigQuery load job
(``client.load_table_from_file(...)`` with a CSV ``LoadJobConfig``).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional, Union

from google.cloud import bigquery
from google.cloud.exceptions import GoogleCloudError, NotFound

from etl.config import Settings, get_settings
from etl.logging_util import log_error, log_info

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd

PathLike = Union[str, Path]


class BigQueryClient:
    """Thin wrapper around :class:`google.cloud.bigquery.Client`."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        client: Optional[bigquery.Client] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client or bigquery.Client(
            project=self.settings.gcp_project,
            location=self.settings.bq_location,
        )

    @property
    def client(self) -> bigquery.Client:
        return self._client

    # -- query ----------------------------------------------------------
    def query(self, sql: str, **job_kwargs) -> "bigquery.table.RowIterator":
        """Run a query job and block for the result rows.

        Equivalent to ``snow_query`` -- returns the completed
        ``RowIterator`` (``client.query(sql).result()``).
        """
        log_info("[bigquery] Running query in %s", self.settings.dataset_ref())
        job = self._client.query(sql, **job_kwargs)
        return job.result()

    def query_to_dataframe(self, sql: str, **job_kwargs) -> "pd.DataFrame":
        """Run a query and return the results as a pandas DataFrame."""
        log_info("[bigquery] Running query -> DataFrame in %s", self.settings.dataset_ref())
        job = self._client.query(sql, **job_kwargs)
        return job.result().to_dataframe()

    def scalar(self, sql: str, **job_kwargs) -> Optional[object]:
        """Run a query expected to return a single row/column and return it."""
        for row in self.query(sql, **job_kwargs):
            return row[0]
        return None

    # -- load -----------------------------------------------------------
    def load_table_from_csv(
        self,
        file_path: PathLike,
        table: str,
        *,
        skip_leading_rows: int = 1,
        write_disposition: str = bigquery.WriteDisposition.WRITE_APPEND,
        autodetect: bool = True,
        schema: Optional[list] = None,
        field_delimiter: str = ",",
        allow_quoted_newlines: bool = True,
    ) -> "bigquery.LoadJob":
        """Load a local CSV file into ``dataset.table`` via a BigQuery load job.

        Replaces the ``snowsql`` PUT + COPY INTO flow. ``table`` may be a bare
        table name (resolved against the configured dataset) or a fully
        qualified ``project.dataset.table`` reference.
        """
        table_ref = self._resolve_table(table)
        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.CSV,
            skip_leading_rows=skip_leading_rows,
            write_disposition=write_disposition,
            field_delimiter=field_delimiter,
            allow_quoted_newlines=allow_quoted_newlines,
        )
        if schema is not None:
            job_config.schema = schema
            job_config.autodetect = False
        else:
            job_config.autodetect = autodetect

        path = Path(file_path)
        log_info("[bigquery] Loading %s -> %s", path.name, table_ref)
        with path.open("rb") as fh:
            job = self._client.load_table_from_file(
                fh, table_ref, job_config=job_config
            )
        job.result()  # wait for completion; raises on failure
        log_info(
            "[bigquery] Loaded %s rows into %s", job.output_rows, table_ref
        )
        return job

    # -- connectivity / dataset checks ----------------------------------
    def check_connection(self) -> bool:
        """Return ``True`` if BigQuery is reachable (``SELECT 1``)."""
        try:
            self.scalar("SELECT 1")
        except GoogleCloudError as exc:
            log_error("Cannot connect to BigQuery (project=%s): %s",
                      self.settings.gcp_project, exc)
            return False
        log_info("BigQuery connection OK (project=%s)", self.settings.gcp_project)
        return True

    def check_dataset(self, dataset: Optional[str] = None) -> bool:
        """Return ``True`` if the target dataset exists."""
        dataset_id = dataset or self.settings.dataset_ref()
        try:
            self._client.get_dataset(dataset_id)
        except NotFound:
            log_error("BigQuery dataset not found: %s", dataset_id)
            return False
        except GoogleCloudError as exc:
            log_error("Error checking dataset %s: %s", dataset_id, exc)
            return False
        log_info("BigQuery dataset OK: %s", dataset_id)
        return True

    # -- helpers --------------------------------------------------------
    def _resolve_table(self, table: str) -> str:
        """Expand a bare table name to ``project.dataset.table``."""
        if table.count(".") >= 2:
            return table
        if table.count(".") == 1:
            # dataset.table -> prepend project
            return f"{self.settings.gcp_project}.{table}"
        return f"{self.settings.dataset_ref()}.{table}"
