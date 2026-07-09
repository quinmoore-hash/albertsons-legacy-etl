# Albertsons Store ETL

> **Migrated to Python + BigQuery (2026-Q3).** The nightly ETL is now a Python
> package (`etl/`) that loads into **BigQuery** and reads secrets from **Secret
> Manager**. The legacy Bash scripts in `scripts/` and `utils/` are **retained
> temporarily** for reference/validation and will be deleted once the Python
> pipeline has run cleanly in production. See
> [Migration Status](#migration-status).

## Overview

Nightly ETL for Albertsons store operations: it ingests point-of-sale (POS)
store-sales data from a vendor API, joins it against store/product/region
reference dimensions, cleans and standardizes the CSVs, loads the results into
BigQuery, runs post-load data quality checks, and archives the processed files
to Google Cloud Storage.

The pipeline processes ~48K store-sales rows/night across the store fleet.

## Architecture

```
                          Cloud Composer (Airflow) DAG   (or per-step Cloud Run jobs)
                          schedule @ 01:30 America/Los_Angeles
                                 │
                                 ▼
   Vendor POS API ─── requests ──► etl.fetch_pos_data ─┐
                                                       │
   BigQuery DW ─── google-cloud- ─► etl.extract_    ───┤
   (store_ops)     bigquery         dimensions         │
                                                       ▼
                                          etl.transform_sales   (csv module clean)
                                                       │
                                                       ▼
                                          etl.load_warehouse ──► BigQuery load job
                                                       │            (store_ops.<table>)
                                                       ▼
                                          etl.data_quality_check (row/null/dupe + BQ count)
                                                       │
                                                       ▼
                                          etl.archive_files ──► gzip ──► gs:// bucket (primary)
```

Warehouse target: `albertsons-retail-analytics.store_ops` (BigQuery).

## Repository Structure

```
albertsons-legacy-etl/
├── etl/                         # Python ETL package (current pipeline)
│   ├── config.py                # Settings from env + Secret Manager (no plaintext creds)
│   ├── logging_util.py          # log_info/log_warn/log_error/log_debug
│   ├── notify.py                # Slack + email alerts (parses configs/alerting.conf)
│   ├── file_utils.py            # File checks, archiving, gzip, CSV validation
│   ├── bigquery_client.py       # BigQuery query + load helpers  (replaces snowflake_helpers.sh)
│   ├── lock.py                  # Advisory flock-based lock (replaces the PID lockfile)
│   ├── fetch_pos_data.py        # Pull POS store-sales via the vendor API
│   ├── extract_dimensions.py    # Query BigQuery dim_store ⨝ dim_region
│   ├── transform_sales.py       # CSV cleaning + robust date/null normalization
│   ├── load_warehouse.py        # BigQuery load job into store_ops.<table>
│   ├── data_quality_check.py    # Row-count / null / dupe + BigQuery count check
│   ├── archive_files.py         # gzip + upload to GCS (primary sink)
│   ├── cleanup_old_data.py      # Retention cleanup (proper lock, no /tmp nuking)
│   ├── run_nightly_etl.py       # Orchestrator (fetch→extract→transform→load→DQ→archive)
│   ├── check_dependencies.py    # Verify Python/GCP deps import
│   └── dags/nightly_etl_dag.py  # Cloud Composer (Airflow) DAG
│
├── tests/                       # pytest unit tests (mock all external calls)
├── scripts/                     # LEGACY Bash pipeline (retained; see Migration Status)
│   └── install_cron_python.sh   # Thin cron wrapper for the Python entrypoints
├── utils/                       # LEGACY Bash helpers (retained)
├── configs/
│   ├── pipeline.env             # LEGACY env file (no longer sourced by Python)
│   ├── warehouse.conf           # LEGACY warehouse profiles (no longer used)
│   └── alerting.conf            # Slack/email routing + thresholds (still used)
├── data/                        # Sample data
├── logs/                        # Sample run output
├── pyproject.toml               # Package metadata, entrypoints, ruff/pytest config
├── requirements.txt             # Pinned runtime dependencies
└── requirements-dev.txt         # Dev/test dependencies (pytest, ruff, pandas)
```

## Configuration

Configuration comes from **environment variables** (loaded into
`etl.config.Settings`), not the old `configs/pipeline.env`. Required:

| Variable | Example |
|---|---|
| `GCP_PROJECT` | `albertsons-retail-analytics` |
| `GCP_REGION` | `us-central1` |
| `BQ_DATASET` | `store_ops` |
| `BQ_LOCATION` | `US` |
| `GCS_BUCKET` | `albertsons-etl-landing` |
| `DATA_INPUT_DIR` / `DATA_OUTPUT_DIR` / `DATA_STAGING_DIR` / `DATA_ARCHIVE_DIR` / `DATA_ERROR_DIR` | staging paths |
| `LOG_DIR`, `LOG_LEVEL`, `LOG_RETENTION_DAYS` | logging |
| `POS_API_BASE_URL`, `POS_API_TIMEOUT`, `POS_API_RETRY_COUNT` | vendor API |
| `RETENTION_DAYS`, `CSV_DELIMITER`, `BATCH_SIZE` | processing knobs |

**Secrets** (`POS_API_KEY`, `SLACK_WEBHOOK_URL`) are pulled from **Google
Secret Manager** (`POS_API_KEY_SECRET` / `SLACK_WEBHOOK_SECRET`, default
`pos-api-key` / `slack-webhook-url`). For local development / tests you may
export `POS_API_KEY` / `SLACK_WEBHOOK_URL` directly and they take precedence.

## Installation

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt        # runtime
pip install -r requirements-dev.txt    # + pytest, ruff, pandas
pip install -e .                       # install the etl package + console scripts
```

## Usage

```bash
# Full nightly run
python -m etl.run_nightly_etl

# Individual steps
python -m etl.fetch_pos_data /path/pos.csv 2026-07-09
python -m etl.transform_sales data/store_sales_sample.csv /tmp/clean.csv
python -m etl.load_warehouse /tmp/pos_store_sales_clean.csv
python -m etl.data_quality_check --skip-warehouse
python -m etl.check_dependencies
```

Console entrypoints (`albertsons-etl`, `albertsons-etl-fetch`, ...) are also
installed by `pip install -e .`.

## Scheduling

Two options (the DAG is preferred per the migration plan):

1. **Cloud Composer (Airflow) DAG** — `etl/dags/nightly_etl_dag.py`. Drop into
   the Composer environment's `dags/` GCS folder; the `etl` package must be
   installed in the environment. Runs `30 1 * * *` `America/Los_Angeles`. Each
   step is a task and maps 1:1 to a **Cloud Run job** (`python -m etl.<module>`)
   if you prefer Cloud Run over Composer.
2. **Thin cron wrapper** — `scripts/install_cron_python.sh` installs a crontab
   that invokes the Python entrypoints, preserving the legacy schedule.

## Testing & Linting

```bash
pytest            # unit tests (external calls are mocked)
ruff check etl tests
```

## Migration Status

The 2026-Q2 Snowflake → BigQuery data migration moved the **data**; this repo
completes the operational-pipeline half by rewriting the Bash scripts as the
Python `etl/` package above.

**Removed / replaced:**

- **Snowflake** — `utils/snowflake_helpers.sh` (snowsql wrapper),
  `scripts/extract_from_snowflake.sh` and the Snowflake path in
  `scripts/load_warehouse.sh` are replaced by `etl/bigquery_client.py` +
  `etl/extract_dimensions.py` + `etl/load_warehouse.py` (BigQuery query/load
  jobs). All `SNOWFLAKE_*` env vars and the `[snowflake_*]` / `[odbc]`
  profiles in `configs/warehouse.conf` are **no longer read** by the pipeline.
- **Plaintext credentials** — secrets now come from Secret Manager, not
  `configs/pipeline.env` / `configs/warehouse.conf`.
- **Crude PID lockfile / `rm -rf /tmp/albertsons_*`** — replaced by a proper
  `flock`-based lock (`etl/lock.py`) shared by the orchestrator and cleanup.
- **Brittle transforms** — the awk/sed US-only `MM/DD/YYYY` date logic and the
  TSV→CSV comma mangling are replaced by the `csv` module and a date
  normalizer that disambiguates day/month and leaves ISO dates untouched.
- **Flaky NAS/gsutil archival** — GCS (`google-cloud-storage`) is now the
  primary archive sink.

**Retained temporarily:** the legacy `scripts/*.sh` and `utils/*.sh` (and
`configs/pipeline.env`, `configs/warehouse.conf`) remain in the tree for
reference and side-by-side validation. They will be deleted in a follow-up once
the Python pipeline has run cleanly in production.

## Contacts

| Role | Name | Email |
|---|---|---|
| Pipeline Lead | R. Gonzalez | rgonzalez@albertsons.com |
| Data Engineer | P. Kaur | pkaur@albertsons.com |
| Store Data Ops (on-call) | Team | store-data-ops@albertsons.com |
