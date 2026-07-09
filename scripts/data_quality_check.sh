#!/bin/bash
# ============================================
# Data Quality Checks
# ============================================
# Post-load validation: row counts, null rates and duplicate keys.
#
# Historically these ran against the Snowflake warehouse. Since the migration
# the warehouse checks fail, so this now mostly falls back to inspecting the
# local transformed CSVs in the staging dir.
#
# Author: pkaur
# Created: 2021-05-19
#
# TODO(migration): once loads target BigQuery, run these as
#   `bq query` / google-cloud-bigquery assertions against
#   ${BQ_DATASET} tables instead of scraping local CSVs.
#
# Usage: ./data_quality_check.sh [run_id]
# Exit codes: 0 = ok, 1 = failures, 2 = warnings only
# ============================================

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"

source "${BASE_DIR}/utils/logging.sh"
source "${BASE_DIR}/utils/snowflake_helpers.sh"
source "${BASE_DIR}/configs/pipeline.env"

RUN_ID="${1:-DQ_$(date +%Y%m%d_%H%M%S)}"
REPORT_FILE="${LOG_DIR}/dq_report_$(date +%Y%m%d).txt"

CHECKS_RUN=0
CHECKS_PASSED=0
CHECKS_WARNED=0
CHECKS_FAILED=0

record_result() {
    local name="$1" status="$2" details="$3"
    CHECKS_RUN=$((CHECKS_RUN + 1))
    case "$status" in
        PASS) CHECKS_PASSED=$((CHECKS_PASSED + 1)) ;;
        WARN) CHECKS_WARNED=$((CHECKS_WARNED + 1)) ;;
        FAIL) CHECKS_FAILED=$((CHECKS_FAILED + 1)) ;;
    esac
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [${status}] ${name}: ${details}" >> "$REPORT_FILE"
    log_info "DQ [${status}] ${name}: ${details}"
}

echo "=========================================" > "$REPORT_FILE"
echo "Data Quality Report - ${RUN_ID}" >> "$REPORT_FILE"
echo "Generated: $(date)" >> "$REPORT_FILE"
echo "=========================================" >> "$REPORT_FILE"

# --- Warehouse-side checks (attempt, expected to fail post-migration) ---
log_info "Attempting warehouse-side row count check..."
if snow_check_connection; then
    WH_COUNT=$(snow_query "SELECT COUNT(*) FROM STORE_OPS.FACT_STORE_SALES WHERE _load_date = CURRENT_DATE();")
    WH_COUNT=$(echo "$WH_COUNT" | tr -d '[:space:]')
    record_result "warehouse:fact_store_sales" "PASS" "today rows=${WH_COUNT:-0}"
else
    record_result "warehouse:connectivity" "FAIL" \
        "Snowflake warehouse unreachable (decommissioned post-migration). Skipping warehouse checks."
fi

# --- Local CSV checks (the part that still works) ---
DELIM="${CSV_DELIMITER:-,}"

for f in "${DATA_STAGING_DIR}"/*_clean.csv; do
    [[ -f "$f" ]] || continue
    base=$(basename "$f")

    # row count
    rows=$(( $(wc -l < "$f") - 1 ))
    if [[ $rows -le 0 ]]; then
        record_result "row_count:${base}" "FAIL" "0 data rows"
    else
        record_result "row_count:${base}" "PASS" "${rows} data rows"
    fi

    # null rate of first column (assumed to be the primary key)
    null_count=$(awk -F"$DELIM" 'NR>1 && ($1=="" ) {c++} END{print c+0}' "$f")
    if [[ $null_count -gt 0 ]]; then
        record_result "null_key:${base}" "WARN" "${null_count} rows with empty key column"
    else
        record_result "null_key:${base}" "PASS" "no empty keys"
    fi

    # duplicate keys on first column
    dupes=$(awk -F"$DELIM" 'NR>1 {print $1}' "$f" | sort | uniq -d | wc -l | tr -d ' ')
    if [[ $dupes -gt 0 ]]; then
        record_result "dupes:${base}" "WARN" "${dupes} duplicate key values"
    else
        record_result "dupes:${base}" "PASS" "no duplicate keys"
    fi
done

echo "" >> "$REPORT_FILE"
echo "=========================================" >> "$REPORT_FILE"
echo "Summary - ${RUN_ID}" >> "$REPORT_FILE"
echo "Total: ${CHECKS_RUN}  Passed: ${CHECKS_PASSED}  Warn: ${CHECKS_WARNED}  Failed: ${CHECKS_FAILED}" >> "$REPORT_FILE"
echo "=========================================" >> "$REPORT_FILE"

log_info "DQ report -> ${REPORT_FILE}"

if [[ $CHECKS_FAILED -gt 0 ]]; then
    exit 1
elif [[ $CHECKS_WARNED -gt 0 ]]; then
    exit 2
fi
exit 0
