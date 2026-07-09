#!/bin/bash
# ============================================
# Warehouse Loader
# Loads transformed CSV files into the Snowflake warehouse staging area
# and then COPY INTO the target tables.
#
# Author: rgonzalez
# Created: 2020-03-02
#
# ####################################################################
# # TODO (MIGRATION): CONVERT TO BIGQUERY LOAD JOBS.
# #
# # This still uses snowsql PUT + COPY INTO against the decommissioned
# # Snowflake account, so it fails every night. The target replacement
# # is a BigQuery load job, e.g.
# #
# #   bq load --source_format=CSV --skip_leading_rows=1 \
# #       --replace=false ${BQ_DATASET}.${TARGET_TABLE} ${INPUT_FILE}
# #
# # ...or in Python:
# #   job = client.load_table_from_file(fh, table_ref, job_config=cfg)
# #   job.result()
# #
# # Run from Cloud Run / Composer rather than cron. No migration PR yet.
# ####################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"

source "${BASE_DIR}/utils/logging.sh"
source "${BASE_DIR}/utils/file_utils.sh"
source "${BASE_DIR}/utils/snowflake_helpers.sh"
source "${BASE_DIR}/configs/pipeline.env"

INPUT_FILE="$1"
TARGET_TABLE="$2"

if [[ -z "$INPUT_FILE" ]]; then
    echo "Usage: $0 <csv_file> [target_table]"
    exit 1
fi

check_file "$INPUT_FILE" || exit 1

# Auto-detect target table from filename if not passed
if [[ -z "$TARGET_TABLE" ]]; then
    BASENAME=$(basename "$INPUT_FILE" | sed 's/_clean.csv//' | sed 's/_[0-9]*$//')
    case "$BASENAME" in
        pos_store_sales*) TARGET_TABLE="STORE_OPS.FACT_STORE_SALES" ;;
        inventory*)       TARGET_TABLE="STORE_OPS.FACT_INVENTORY" ;;
        dim_reference*)   TARGET_TABLE="STORE_OPS.DIM_REFERENCE" ;;
        product_catalog*) TARGET_TABLE="STORE_OPS.DIM_PRODUCT" ;;
        *)
            log_error "Cannot determine target table for: $BASENAME"
            exit 1
            ;;
    esac
fi

log_info "Loading $(basename "$INPUT_FILE") -> ${TARGET_TABLE}"

# Pre-flight: is the warehouse even reachable? (No, not since migration.)
if ! snow_check_connection; then
    log_error "Warehouse unreachable; aborting load of $(basename "$INPUT_FILE")"
    exit 1
fi

# Stage the local file and COPY INTO the target table.
# TODO(migration): replace this whole block with a BigQuery load job.
snow_stage_and_copy "$INPUT_FILE" "$TARGET_TABLE" "@~/etl_stage"
RC=$?

if [[ $RC -ne 0 ]]; then
    log_error "Load failed for $(basename "$INPUT_FILE") -> ${TARGET_TABLE} (rc=${RC})"
    exit 1
fi

log_info "Load complete: $(basename "$INPUT_FILE") -> ${TARGET_TABLE}"
exit 0
