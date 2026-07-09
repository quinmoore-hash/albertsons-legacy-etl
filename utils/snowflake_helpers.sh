#!/bin/bash
# ============================================
# Snowflake Helper Functions
# Wraps `snowsql` CLI calls with connection management
# Author: rgonzalez
# NOTE: requires the `snowsql` client installed on the VM
# ============================================
#
# ####################################################################
# # FIXME (MIGRATION): This entire module is the #1 thing to replace.
# #
# # The data warehouse was migrated from Snowflake to BigQuery in the
# # 2026 Q2 "Blue Sky" migration. The DATA now lives in BigQuery
# # (project: ${GCP_PROJECT}, dataset: ${BQ_DATASET}), but these
# # operational scripts were intentionally deferred and were NEVER
# # repointed. Every function below still shells out to `snowsql`
# # against the OLD account, which has since been decommissioned.
# #
# # As a result all of these calls now FAIL at runtime with:
# #   250001 (08001): Failed to connect to DB. Verify the account name
# #   is correct: ALB_PROD.us-east-1.snowflakecomputing.com
# #
# # TARGET STATE:
# #   Replace this file with a Python module using the official
# #   BigQuery client (`google-cloud-bigquery`), e.g.
# #
# #       from google.cloud import bigquery
# #       client = bigquery.Client(project=GCP_PROJECT)
# #       rows = client.query(sql).result()
# #
# #   ...invoked from Cloud Run jobs / Cloud Composer (Airflow) DAGs
# #   instead of cron-driven Bash on GCE VMs.
# #
# # There is no committed migration plan yet - see README
# # "Migration Status / Technical Debt".
# ####################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/logging.sh"

# These are sourced from configs/pipeline.env in the calling script.
# Kept here as fallbacks so standalone invocation "works" (it doesn't
# anymore - the account is gone).
SNOWFLAKE_ACCOUNT="${SNOWFLAKE_ACCOUNT:-alb_prod.us-east-1}"
SNOWFLAKE_USER="${SNOWFLAKE_USER:-ETL_SVC}"
SNOWFLAKE_WAREHOUSE="${SNOWFLAKE_WAREHOUSE:-ETL_WH}"
SNOWFLAKE_DATABASE="${SNOWFLAKE_DATABASE:-RETAIL_PROD}"
SNOWFLAKE_ROLE="${SNOWFLAKE_ROLE:-ETL_ROLE}"

# Path to the legacy snowsql config file (also decommissioned creds)
SNOWSQL_CONFIG="${SNOWSQL_CONFIG:-/opt/albertsons/etl/.snowsql/config}"

# Check that snowsql exists and is on PATH
_check_snowsql() {
    if ! command -v snowsql &>/dev/null; then
        log_error "snowsql CLI not found on PATH. Was it removed after the BigQuery migration?"
        return 1
    fi
    return 0
}

# Run a single query and print tab-separated results to stdout
snow_query() {
    local query="$1"
    local output_file="$2"

    _check_snowsql || return 1

    log_info "[snowsql] Running query against ${SNOWFLAKE_ACCOUNT}/${SNOWFLAKE_WAREHOUSE}"

    # FIXME: --accountname points at the decommissioned Snowflake instance.
    #        Convert to: bq query --use_legacy_sql=false '<sql>'  (or the
    #        google-cloud-bigquery Python client).
    local snow_cmd=(snowsql
        --config "$SNOWSQL_CONFIG"
        --accountname "$SNOWFLAKE_ACCOUNT"
        --username "$SNOWFLAKE_USER"
        --warehouse "$SNOWFLAKE_WAREHOUSE"
        --dbname "$SNOWFLAKE_DATABASE"
        --rolename "$SNOWFLAKE_ROLE"
        --option friendly=false
        --option header=false
        --option timing=false
        --option output_format=tsv
        -q "$query")

    if [[ -n "$output_file" ]]; then
        "${snow_cmd[@]}" > "$output_file" 2>&1
    else
        "${snow_cmd[@]}" 2>&1
    fi

    local rc=$?
    if [[ $rc -ne 0 ]]; then
        log_error "snowsql query failed (rc=${rc}). Warehouse likely decommissioned post-migration."
    fi
    return $rc
}

# Run a .sql file through snowsql
snow_run_file() {
    local sql_file="$1"

    _check_snowsql || return 1

    if [[ ! -f "$sql_file" ]]; then
        log_error "SQL file not found: $sql_file"
        return 1
    fi

    # FIXME: same decommissioned account problem as snow_query().
    snowsql \
        --config "$SNOWSQL_CONFIG" \
        --accountname "$SNOWFLAKE_ACCOUNT" \
        --username "$SNOWFLAKE_USER" \
        --warehouse "$SNOWFLAKE_WAREHOUSE" \
        --dbname "$SNOWFLAKE_DATABASE" \
        --rolename "$SNOWFLAKE_ROLE" \
        -f "$sql_file" 2>&1

    return $?
}

# Bulk load a local file into a Snowflake stage + table via PUT / COPY INTO
snow_stage_and_copy() {
    local local_file="$1"
    local target_table="$2"
    local stage="${3:-@~/etl_stage}"

    _check_snowsql || return 1

    check_file() { [[ -s "$1" ]]; }
    if ! check_file "$local_file"; then
        log_error "Cannot load empty/missing file: $local_file"
        return 1
    fi

    log_info "[snowsql] PUT ${local_file} -> ${stage}; COPY INTO ${target_table}"

    # TODO(migration): replace PUT + COPY INTO with a BigQuery load job:
    #   bq load --source_format=CSV --skip_leading_rows=1 \
    #       ${BQ_DATASET}.${target_table} ${local_file}
    #   ...or client.load_table_from_file() in Python.
    snow_query "PUT file://${local_file} ${stage} OVERWRITE=TRUE AUTO_COMPRESS=TRUE;"
    snow_query "COPY INTO ${target_table}
                FROM ${stage}
                FILE_FORMAT = (TYPE = CSV FIELD_OPTIONALLY_ENCLOSED_BY='\"' SKIP_HEADER=1)
                ON_ERROR = 'CONTINUE';"

    return $?
}

# Sanity check that we can reach the warehouse at all
snow_check_connection() {
    _check_snowsql || return 1
    snow_query "SELECT CURRENT_VERSION();" > /dev/null 2>&1
    if [[ $? -eq 0 ]]; then
        log_info "Snowflake connection OK"
        return 0
    fi
    log_error "Cannot connect to Snowflake (account=${SNOWFLAKE_ACCOUNT}). Decommissioned after BigQuery migration?"
    return 1
}
