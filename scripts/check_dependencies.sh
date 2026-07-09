#!/bin/bash
# ============================================
# Dependency Checker
# Verifies the CLI tools the pipeline expects are installed on the VM.
# Author: pkaur
# ============================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"

source "${BASE_DIR}/utils/logging.sh"

MISSING=0

# Core tools still required by the legacy Bash pipeline
for cmd in bash curl jq awk sed grep gzip; do
    if command -v "$cmd" &>/dev/null; then
        log_info "OK: $cmd -> $(command -v "$cmd")"
    else
        log_error "MISSING: $cmd"
        MISSING=$((MISSING + 1))
    fi
done

# Legacy warehouse client - decommissioned but scripts still call it.
# FIXME(migration): remove once extract/load are ported off Snowflake.
if command -v snowsql &>/dev/null; then
    log_warn "snowsql present but the Snowflake warehouse is decommissioned (migration debt)"
else
    log_warn "snowsql NOT installed; extract_from_snowflake.sh / load_warehouse.sh will fail"
fi

# GCP tooling - partially installed on some VMs, needed for the target state.
for cmd in gcloud bq gsutil; do
    if command -v "$cmd" &>/dev/null; then
        log_info "OK (gcp): $cmd -> $(command -v "$cmd")"
    else
        log_warn "gcp tool not installed: $cmd (needed for BigQuery/GCP target)"
    fi
done

if [[ $MISSING -gt 0 ]]; then
    log_error "${MISSING} core dependencies missing"
    exit 1
fi

log_info "All core dependencies present"
exit 0
