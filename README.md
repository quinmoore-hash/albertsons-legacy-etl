# Albertsons Store ETL (Legacy)

> **⚠️ Legacy System — pending migration.** This is a collection of Bash
> scripts that run nightly on on-prem / GCE Linux VMs via cron. They were
> **left behind by the 2026-Q2 Snowflake → BigQuery data-warehouse migration**
> and still point at the now-decommissioned Snowflake warehouse. They are
> slated to be rewritten as Python jobs on GCP. See
> [Migration Status / Technical Debt](#migration-status--technical-debt).

## Overview

Nightly ETL for Albertsons store operations: it ingests point-of-sale (POS)
store-sales data from a vendor API, joins it against store/product/region
reference dimensions, cleans and standardizes the CSVs, loads the results into
the data warehouse, runs post-load data quality checks, and archives the
processed files.

The system has been in production since 2019 and processes ~48K store-sales
rows/night across the store fleet. It is entirely Bash + cron: there is no
orchestrator, no CI/CD, and no tests.

## Architecture

```
                          on-prem / GCE Linux VM (retail-etl-01)
                          cron @ 01:30 PT
                                 │
                                 ▼
   Vendor POS API ─── curl ──► fetch_pos_data.sh ─┐
                                                  │
   Snowflake DW ─── snowsql ─► extract_from_    ──┤
   (DECOMMISSIONED)            snowflake.sh  ✗     │
                                                  ▼
                                          transform_sales.sh   (awk/sed clean)
                                                  │
                                                  ▼
                                          load_warehouse.sh ──► Snowflake staging + COPY INTO  ✗
                                                  │                (DECOMMISSIONED)
                                                  ▼
                                          data_quality_check.sh  (row/null/dupe)
                                                  │
                                                  ▼
                                          archive_files.sh ──► gzip ──► NAS share  /  gs:// bucket

   ✗ = step currently fails: the Snowflake warehouse was decommissioned after
       the BigQuery migration and these scripts were never repointed.

   TARGET STATE (not yet built):
       Cloud Composer (Airflow) DAG ──► Python tasks (google-cloud-bigquery)
                                        running on Cloud Run / GCE, loading
                                        into BigQuery (albertsons-retail-analytics.store_ops)
```

## Repository Structure

```
albertsons-legacy-etl/
├── scripts/                     # Pipeline scripts (cron-invoked)
│   ├── run_nightly_etl.sh       # Main nightly orchestrator (01:30 PT)
│   ├── fetch_pos_data.sh        # Pull POS store-sales via curl (retries)
│   ├── extract_from_snowflake.sh# snowsql dimension extract  [BROKEN: Snowflake gone]
│   ├── transform_sales.sh       # awk/sed CSV cleaning + date/null normalization
│   ├── load_warehouse.sh        # Snowflake staging + COPY INTO  [BROKEN: Snowflake gone]
│   ├── data_quality_check.sh    # Post-load row-count / null / dupe checks
│   ├── archive_files.sh         # gzip + copy to NAS share / gs:// bucket
│   ├── cleanup_old_data.sh      # Delete files older than N days
│   ├── check_dependencies.sh    # Verify required CLI tools are installed
│   └── install_cron.sh          # (Re)install the pipeline crontab
│
├── utils/                       # Shared helpers (sourced by scripts)
│   ├── logging.sh               # log_info / log_warn / log_error / log_debug
│   ├── notify.sh                # Slack + email alerts
│   ├── file_utils.sh            # File checks, archiving, gzip, CSV validation
│   └── snowflake_helpers.sh     # snowsql wrapper  ←── #1 thing to replace with BigQuery
│
├── configs/                     # Environment and connection config
│   ├── pipeline.env             # Env vars (stale SNOWFLAKE_*, new unused GCP_*/BQ_*)
│   ├── warehouse.conf           # snowflake_* profiles (dead) + unused [bigquery] profile
│   └── alerting.conf            # Slack/email routing + thresholds
│
├── data/                        # Sample data
│   ├── store_sales_sample.csv
│   ├── inventory_sample.csv
│   └── product_catalog_sample.json
│
└── logs/                        # Sample run output
    ├── etl_20260708.log         # Full run showing the snowsql failure
    └── dq_report_20260708.txt
```

## Cron Schedule

Installed by `scripts/install_cron.sh`. All times `America/Los_Angeles` (VM TZ).

| Schedule | Script | Description |
|---|---|---|
| `30 1 * * *` | `run_nightly_etl.sh` | Nightly full ETL (fetch → extract → transform → load → DQ → archive) |
| `0 9 * * *` | `fetch_pos_data.sh` | Mid-morning POS re-pull for late-reporting stores |
| `0 6 * * *` | `data_quality_check.sh` | Standalone data quality sweep |
| `0 5 * * *` | `cleanup_old_data.sh` | Delete processed/archive/log files older than retention |
| `0 7 * * 1` | `check_dependencies.sh` | Weekly dependency check |

## Dependencies

Installed ad-hoc on each VM (no manifest, no version pinning):

- **bash** 4.x
- **curl** — POS API calls
- **jq** — JSON parsing (product catalog)
- **awk**, **sed**, **grep** — CSV transformation
- **gzip** — archive compression
- **snowsql** — Snowflake CLI **(warehouse decommissioned; calls now fail)**
- **gcloud / bq / gsutil** — GCP tooling, **only partially installed** on the
  legacy VMs; needed for the intended BigQuery/GCP target state
- **mailx** / **sendmail** — email alerts

## Usage

```bash
# One-off full run (normally cron does this)
bash scripts/run_nightly_etl.sh

# Individual steps
bash scripts/fetch_pos_data.sh /tmp/pos_$(date +%F).csv
bash scripts/transform_sales.sh data/store_sales_sample.csv /tmp/clean.csv
bash scripts/data_quality_check.sh

# (Re)install the crontab
bash scripts/install_cron.sh
```

Configuration is driven by `configs/pipeline.env`, which every script sources.

## Migration Status / Technical Debt

**The data is already in BigQuery. These scripts are not.**

In **2026-Q2** Albertsons migrated its store-operations data warehouse from
**Snowflake to BigQuery** (`albertsons-retail-analytics.store_ops`). The
migration moved the **data**, but these operational shell scripts were
explicitly **out of scope** and were **never touched**. As a result they still:

- shell out to the **`snowsql`** CLI (`utils/snowflake_helpers.sh`,
  `scripts/extract_from_snowflake.sh`, `scripts/load_warehouse.sh`);
- read stale **`SNOWFLAKE_ACCOUNT` / `SNOWFLAKE_USER` / `SNOWFLAKE_WAREHOUSE`**
  env vars from `configs/pipeline.env` and `snowflake_*` profiles in
  `configs/warehouse.conf`;
- depend on a **`.snowsql/config`** file and an **ODBC DSN** (`SF_RETAIL_PROD`);
- point at the account **`alb_prod.us-east-1`**, which was **turned off** as
  part of the migration.

Because of this, the **extract** and **load** steps fail every night with a
Snowflake connection error (see `logs/etl_20260708.log`). The pipeline limps
along: POS fetch, transform, local DQ checks and archiving still run, but
nothing lands in the warehouse.

New `GCP_PROJECT`, `BQ_DATASET`, `GCS_BUCKET` and a `[bigquery]` profile were
added to the config during the migration, but **nothing sources them yet** —
they were added in anticipation of the rewrite.

### Intended target (the demo goal)

Rewrite these Bash scripts as **Python jobs on GCP**:

- Replace `snowsql` PUT/COPY INTO and `snow_query` with the
  **`google-cloud-bigquery`** client (BigQuery load jobs and query jobs).
- Replace cron-on-a-VM scheduling with **Cloud Composer (Airflow)** DAGs, or
  package individual steps as **Cloud Run jobs**.
- Move credential handling off plaintext `pipeline.env` into **Secret Manager**.
- Add tests (there are none today).

`utils/snowflake_helpers.sh` is the single highest-value thing to replace — it
is the choke point every warehouse interaction flows through. Search the tree
for `FIXME(migration)` / `TODO(migration)` for the specific breadcrumbs.

> **There is no committed migration plan yet.** This is on the roadmap only; no
> design doc or migration PR has been opened.

### Other known issues / tech debt

- **Plaintext credentials** in `configs/pipeline.env` and
  `configs/warehouse.conf` (Snowflake password, POS API key, Slack webhook).
- **Hardcoded paths** everywhere (`/opt/albertsons/etl`, `/mnt/nas/...`).
- **No CI/CD, no tests** — changes are edited directly on the VM.
- **Crude file lock** in `run_nightly_etl.sh`; `cleanup_old_data.sh` can delete
  the lock (and in-flight files) via `rm -rf /tmp/albertsons_*`.
- **Brittle transforms** — `transform_sales.sh` assumes US `MM/DD/YYYY` dates
  and mangles other formats; TSV→CSV conversion breaks on embedded commas.
- **Inconsistent error handling** — some steps are fatal, others are swallowed;
  partial output files are sometimes left behind, sometimes cleaned up.
- **Flaky sinks** — `archive_files.sh` depends on an NFS mount that is often
  absent, and `gsutil` isn't installed on all VMs.

## Contacts

| Role | Name | Email |
|---|---|---|
| Pipeline Lead | R. Gonzalez | rgonzalez@albertsons.com |
| Data Engineer | P. Kaur | pkaur@albertsons.com |
| Store Data Ops (on-call) | Team | store-data-ops@albertsons.com |
