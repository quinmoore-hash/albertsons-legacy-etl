#!/bin/bash
# ============================================
# POS Data Fetcher
# Pulls point-of-sale / store sales data from the vendor API via curl.
# Supports a simple retry loop.
# Author: pkaur
# Created: 2020-01-08
# ============================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"

source "${BASE_DIR}/utils/logging.sh"
source "${BASE_DIR}/configs/pipeline.env"

OUTPUT_FILE="${1:-${DATA_INPUT_DIR}/pos_store_sales_$(date +%Y%m%d).csv}"
FETCH_DATE="${2:-$(date +%Y-%m-%d)}"

RETRIES="${POS_API_RETRY_COUNT:-3}"
TIMEOUT="${POS_API_TIMEOUT:-30}"

mkdir -p "$(dirname "$OUTPUT_FILE")" 2>/dev/null

if [[ -z "$POS_API_KEY" ]]; then
    log_warn "POS_API_KEY is not set; requests will likely 401"
fi

log_info "Fetching POS store-sales for ${FETCH_DATE} -> ${OUTPUT_FILE}"

URL="${POS_API_BASE_URL}/store-sales/daily?date=${FETCH_DATE}&format=csv"

ATTEMPT=0
while [[ $ATTEMPT -lt $RETRIES ]]; do
    ATTEMPT=$((ATTEMPT + 1))

    HTTP_CODE=$(curl -s -o "$OUTPUT_FILE" -w "%{http_code}" \
        -H "X-Api-Key: ${POS_API_KEY}" \
        -H "Accept: text/csv" \
        --connect-timeout "$TIMEOUT" \
        --max-time 180 \
        "$URL" 2>/dev/null)

    if [[ "$HTTP_CODE" == "200" ]]; then
        ROWS=$(( $(wc -l < "$OUTPUT_FILE") - 1 ))
        log_info "POS fetch OK (HTTP 200), ${ROWS} rows -> ${OUTPUT_FILE}"
        exit 0
    fi

    log_warn "POS fetch attempt ${ATTEMPT}/${RETRIES} failed (HTTP ${HTTP_CODE}), retrying in 10s..."
    sleep 10
done

log_error "POS fetch failed after ${RETRIES} attempts (last HTTP ${HTTP_CODE})"
# leave the partial file for debugging (inconsistent with other scripts, oh well)
exit 1
