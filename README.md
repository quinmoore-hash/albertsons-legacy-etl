# Albertsons Store ETL

Nightly ETL for Albertsons store operations, implemented as a Python package
targeting **Google BigQuery** and **Google Cloud Storage**. It ingests
point-of-sale (POS) store-sales data from a vendor API, joins it against
store/region reference dimensions in BigQuery, cleans and standardizes the
CSVs, loads the results into BigQuery, runs post-load data quality checks, and
archives the processed files to GCS.

> Migrated in **2026-Q2** from a legacy Bash + cron pipeline that targeted the
> now-decommissioned Snowflake warehouse. See the git history / the PR that
> introduced the `etl/` package for the before state.

## Architecture

```
   Vendor POS API ──requests──► fetch_pos_data ─┐
                                                │
   BigQuery store_ops ─────────► extract_       ─┤
   (dim_store ⋈ dim_region)     dimensions      │
                                                ▼
                                        transform_sales   (csv/pandas clean)
                                                │
                                                ▼
                                        load_warehouse ──► BigQuery load job
                                                │          (store_ops.*)
                                                ▼
                                        data_quality_check (local CSV + BQ assertion)
                                                │
                                                ▼
                                        archive_files ──► gzip ──► gs:// bucket

   Orchestration: Cloud Composer (Airflow) DAG  etl/dags/nightly_etl_dag.py
                  (or the plain Python orchestrator etl/run_nightly_etl.py)
```

The warehouse lives at `albertsons-retail-analytics.store_ops` in BigQuery.

## Repository Structure

```
albertsons-legacy-etl/
├── etl/                          # Python package
│   ├── config.py                 # Config loader (pipeline.env + env vars)
│   ├── secrets.py                # Secret Manager access (POS key, Slack webhook)
│   ├── logging_setup.py          # stdlib logging (file + console)
│   ├── notify.py                 # Slack (requests) + email (smtplib); alert()
│   ├── file_utils.py             # check/count/gzip/validate helpers (pathlib/csv/gzip)
│   ├── warehouse/
│   │   └── bigquery_client.py    # BigQuery client wrapper (query + load jobs)
│   ├── fetch_pos_data.py         # POS CSV feed pull (requests + tenacity retries)
│   ├── extract_dimensions.py     # dim_store ⋈ dim_region -> CSV (BigQuery)
│   ├── transform_sales.py        # CSV cleaning + robust date/null handling
│   ├── load_warehouse.py         # BigQuery load job + filename→table mapping
│   ├── data_quality_check.py     # local CSV checks + BigQuery assertion
│   ├── archive_files.py          # gzip + upload to GCS
│   ├── cleanup_old_data.py       # retention-based local/GCS cleanup
│   ├── run_nightly_etl.py        # Python orchestrator
│   └── dags/
│       └── nightly_etl_dag.py    # Cloud Composer (Airflow) DAG
│
├── configs/
│   ├── pipeline.env              # GCP/BQ/GCS settings + Secret Manager ids
│   ├── warehouse.conf            # BigQuery profile (reference)
│   └── alerting.conf             # Slack/email routing + thresholds
│
├── data/                         # Sample data (used as test fixtures)
├── tests/                        # pytest suite
├── pyproject.toml                # Package metadata + pinned dependencies
└── requirements.txt              # Pinned dependencies
```

## Installation

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# or, for an editable install with console entry points:
pip install -e .[dev]
```

## Configuration

Settings are read from `configs/pipeline.env` (simple `KEY=value`), and any
matching environment variable overrides the file value. Key settings:

| Variable | Purpose |
|---|---|
| `GCP_PROJECT` | BigQuery/GCS project (`albertsons-retail-analytics`) |
| `BQ_DATASET` | BigQuery dataset (`store_ops`) |
| `BQ_LOCATION` | BigQuery location (`US`) |
| `GCP_REGION` | GCP region (`us-central1`) |
| `GCS_BUCKET` | Archive bucket (`albertsons-etl-landing`) |
| `POS_API_BASE_URL` | Vendor POS API base URL |
| `POS_API_KEY_SECRET` | Secret Manager id for the POS API key |
| `SLACK_WEBHOOK_SECRET` | Secret Manager id for the Slack webhook |

Working directories default to repo-relative `data/*` and logs to `./logs`;
override `DATA_*_DIR` / `LOG_DIR` for on-prem/GCE layouts.

### Credentials

- **GCP auth**: Application Default Credentials — the attached service account
  on Cloud Composer / Cloud Run, or `GOOGLE_APPLICATION_CREDENTIALS` locally.
- **POS API key & Slack webhook**: stored in **Secret Manager** and fetched at
  runtime (`etl/secrets.py`). For local dev/tests you can export the value as an
  env var named after the secret id (uppercased, `-`→`_`), e.g. `POS_API_KEY`
  for the `pos-api-key` secret. **No plaintext credentials live in the repo.**

## Usage

```bash
# Full nightly run (Python orchestrator)
python -m etl.run_nightly_etl

# Individual steps
python -m etl.fetch_pos_data /tmp/pos_$(date +%F).csv
python -m etl.extract_dimensions /tmp/dim_reference.csv
python -m etl.transform_sales data/store_sales_sample.csv /tmp/clean.csv
python -m etl.load_warehouse /tmp/clean.csv            # table auto-detected
python -m etl.data_quality_check
python -m etl.archive_files
python -m etl.cleanup_old_data
```

Equivalent console entry points (`etl-run-nightly`, `etl-transform-sales`, …)
are installed with `pip install -e .`.

## Scheduling

Production scheduling is handled by **Cloud Composer (Airflow)**. Deploy
`etl/dags/nightly_etl_dag.py` to the Composer environment's `dags/` folder; it
runs `fetch → extract → transform → load → dq → archive` at 01:30 PT with a
single active run (`max_active_runs=1`), replacing the old cron + `/tmp` lock
file. Steps can alternatively be packaged as individual Cloud Run jobs.

## Testing

```bash
pytest
```

Tests cover the transform (including embedded-comma and robust-date fixes), the
data quality checks (local + BigQuery assertion via an injected fake client),
and the BigQuery client wrapper. The files in `data/` are used as fixtures.

## Contacts

| Role | Name | Email |
|---|---|---|
| Pipeline Lead | R. Gonzalez | rgonzalez@albertsons.com |
| Data Engineer | P. Kaur | pkaur@albertsons.com |
| Store Data Ops (on-call) | Team | store-data-ops@albertsons.com |
