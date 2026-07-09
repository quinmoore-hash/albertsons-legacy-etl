#!/bin/bash
# ============================================
# Nightly Store ETL Orchestrator
# ============================================
# Primary pipeline orchestration script. Runs nightly at 1:30 AM PT on the
# on-prem/GCE Linux VM (retail-etl-01). Coordinates POS ingestion, Snowflake
# dimension extract, transform, warehouse load, DQ checks and archiving.
#
# Author: rgonzalez
# Created: 2019-11-20
# Modified: 2026-02-11 (bumped POS API to v2)
#
# CRON: 30 1 * * * /opt/albertsons/etl/scripts/run_nightly_etl.sh >> /var/log/albertsons/etl/run_nightly_etl.log 2>&1
#
# NOTE(migration): This orchestrator still calls extract_from_snowflake.sh and
# the Snowflake-based load_warehouse.sh. Both now fail because the Snowflake
# warehouse was decommissioned after the 2026-Q2 BigQuery migration. The
# intended target is a Cloud Composer (Airflow) DAG invoking Python tasks that
# use the BigQuery client. See README "Migration Status / Technical Debt".
# ============================================

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"

# Source shared utilities
source "${BASE_DIR}/utils/logging.sh"
source "${BASE_DIR}/utils/notify.sh"
source "${BASE_DIR}/utils/file_utils.sh"

# Load environment
source "${BASE_DIR}/configs/pipeline.env"

RUN_ID="ETL_$(date +%Y%m%d_%H%M%S)"
START_TIME=$(date +%s)

# Simple file lock (no proper lock manager - see Known Issues)
LOCKFILE="/tmp/albertsons_nightly_etl.lock"

STEPS_COMPLETED=0
STEPS_FAILED=0
TOTAL_ROWS_PROCESSED=0
ERRORS=()

cleanup() {
    local exit_code=$?
    local end_time=$(date +%s)
    local duration=$(( end_time - START_TIME ))

    log_info "=========================================="
    log_info "ETL Run Summary: ${RUN_ID}"
    log_info "Duration: ${duration}s"
    log_info "Steps Completed: ${STEPS_COMPLETED}"
    log_info "Steps Failed: ${STEPS_FAILED}"
    log_info "Total Rows: ${TOTAL_ROWS_PROCESSED}"
    log_info "=========================================="

    if [[ ${#ERRORS[@]} -gt 0 ]]; then
        local error_summary=$(printf '%s\n' "${ERRORS[@]}")
        alert "ETL ${RUN_ID} completed with errors:\n${error_summary}\nDuration: ${duration}s" "WARNING"
    elif [[ $exit_code -ne 0 ]]; then
        alert "ETL ${RUN_ID} FAILED (exit=${exit_code}). Steps completed: ${STEPS_COMPLETED}" "CRITICAL"
    else
        send_slack "ETL ${RUN_ID} completed OK. ${TOTAL_ROWS_PROCESSED} rows in ${duration}s." "INFO"
    fi

    rm -f "$LOCKFILE"
    exit $exit_code
}
trap cleanup EXIT

# ---- crude lock ----
if [[ -f "$LOCKFILE" ]]; then
    OTHER_PID=$(cat "$LOCKFILE" 2>/dev/null)
    if [[ -n "$OTHER_PID" ]] && kill -0 "$OTHER_PID" 2>/dev/null; then
        alert "ETL ${RUN_ID}: another run (pid=${OTHER_PID}) is already in progress" "CRITICAL"
        exit 1
    fi
    log_warn "Removing stale lock file (pid=${OTHER_PID} not running)"
fi
echo $$ > "$LOCKFILE"

# ---- working dirs ----
for dir in "$DATA_INPUT_DIR" "$DATA_OUTPUT_DIR" "$DATA_STAGING_DIR" "$DATA_ARCHIVE_DIR" "$DATA_ERROR_DIR"; do
    mkdir -p "$dir" 2>/dev/null
done

log_info "=========================================="
log_info "Starting Nightly Store ETL: ${RUN_ID}"
log_info "Host: $(hostname)"
log_info "Date: $(date)"
log_info "=========================================="

RUN_DATE=$(date +%Y%m%d)

# ---- Step 1: Fetch POS / store sales data ----
log_info "[Step 1/6] Fetching POS store-sales data..."
"${SCRIPT_DIR}/fetch_pos_data.sh" "${DATA_INPUT_DIR}/pos_store_sales_${RUN_DATE}.csv"
if [[ $? -ne 0 ]]; then
    log_error "POS fetch failed"
    ERRORS+=("FETCH: POS store-sales fetch failed")
    STEPS_FAILED=$((STEPS_FAILED + 1))
else
    STEPS_COMPLETED=$((STEPS_COMPLETED + 1))
fi

# ---- Step 2: Extract reference/dimension data from Snowflake ----
# NOTE(migration): expected to fail - Snowflake warehouse decommissioned.
log_info "[Step 2/6] Extracting reference dimensions from Snowflake..."
"${SCRIPT_DIR}/extract_from_snowflake.sh" "${DATA_INPUT_DIR}/dim_reference_${RUN_DATE}.csv"
if [[ $? -ne 0 ]]; then
    log_error "Snowflake extract failed (warehouse decommissioned post-migration?)"
    ERRORS+=("EXTRACT: snowflake dimension extract failed")
    STEPS_FAILED=$((STEPS_FAILED + 1))
    # Historically non-fatal: we press on with yesterday's cached dims.
    log_warn "Continuing with last-known dimension cache (if present)"
else
    STEPS_COMPLETED=$((STEPS_COMPLETED + 1))
fi

# ---- Step 3: Transform / clean sales CSVs ----
log_info "[Step 3/6] Transforming sales data..."
for csvfile in "${DATA_INPUT_DIR}"/*.csv; do
    [[ -f "$csvfile" ]] || continue
    outfile="${DATA_STAGING_DIR}/$(basename "${csvfile%.*}")_clean.csv"
    "${SCRIPT_DIR}/transform_sales.sh" "$csvfile" "$outfile"
    if [[ $? -eq 0 ]]; then
        rows=$(count_data_rows "$outfile")
        TOTAL_ROWS_PROCESSED=$((TOTAL_ROWS_PROCESSED + rows))
    else
        ERRORS+=("TRANSFORM: $(basename "$csvfile") failed")
        STEPS_FAILED=$((STEPS_FAILED + 1))
    fi
done
STEPS_COMPLETED=$((STEPS_COMPLETED + 1))

# ---- Step 4: Load into warehouse ----
# NOTE(migration): still targets Snowflake staging + COPY INTO -> fails.
log_info "[Step 4/6] Loading data into warehouse..."
for datafile in "${DATA_STAGING_DIR}"/*_clean.csv; do
    [[ -f "$datafile" ]] || continue
    "${SCRIPT_DIR}/load_warehouse.sh" "$datafile"
    if [[ $? -ne 0 ]]; then
        ERRORS+=("LOAD: $(basename "$datafile") failed")
        STEPS_FAILED=$((STEPS_FAILED + 1))
    fi
done
STEPS_COMPLETED=$((STEPS_COMPLETED + 1))

# ---- Step 5: Post-load data quality checks ----
log_info "[Step 5/6] Running data quality checks..."
"${SCRIPT_DIR}/data_quality_check.sh" "${RUN_ID}" || \
    ERRORS+=("DQ: data quality check reported issues")
STEPS_COMPLETED=$((STEPS_COMPLETED + 1))

# ---- Step 6: Archive processed files ----
log_info "[Step 6/6] Archiving processed files..."
"${SCRIPT_DIR}/archive_files.sh" || \
    ERRORS+=("ARCHIVE: archive step reported issues")
STEPS_COMPLETED=$((STEPS_COMPLETED + 1))

if [[ ${STEPS_FAILED} -gt 0 ]]; then
    exit 1
fi
exit 0
