#!/bin/bash
# ============================================
# Snowflake Reference/Dimension Extract
# ============================================
# Runs snowsql queries against the Snowflake warehouse to extract reference
# and dimension data (stores, products, regions) that the nightly sales feed
# is joined against downstream.
#
# Author: rgonzalez
# Created: 2020-02-14
# Modified: 2023-07-01 (added region_dim)
#
# ####################################################################
# # FIXME (MIGRATION): SNOWFLAKE IS DECOMMISSIONED.
# #
# # The warehouse was migrated to BigQuery in 2026-Q2. The reference
# # tables (DIM_STORE, DIM_PRODUCT, DIM_REGION) now live in BigQuery:
# #     ${GCP_PROJECT}.${BQ_DATASET}.dim_store   (etc.)
# #
# # Every snowsql call below now fails with a connection error because
# # the account alb_prod.us-east-1 no longer exists. This script must be
# # rewritten as a Python job using google-cloud-bigquery, e.g.
# #
# #     from google.cloud import bigquery
# #     client = bigquery.Client(project=GCP_PROJECT)
# #     df = client.query("SELECT * FROM store_ops.dim_store").to_dataframe()
# #     df.to_csv(output_file, index=False)
# #
# # ...scheduled from Cloud Composer instead of cron. No migration PR
# # has been opened yet (roadmap only).
# ####################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"

source "${BASE_DIR}/utils/logging.sh"
source "${BASE_DIR}/utils/snowflake_helpers.sh"
source "${BASE_DIR}/configs/pipeline.env"

OUTPUT_FILE="${1:-${DATA_INPUT_DIR}/dim_reference_$(date +%Y%m%d).csv}"

log_info "Extracting reference dimensions from Snowflake -> ${OUTPUT_FILE}"

# Pre-flight connectivity check. This is where it dies post-migration.
if ! snow_check_connection; then
    log_error "Snowflake unreachable. Cannot extract dimensions."
    # TODO(migration): fall back to BigQuery here instead of failing:
    #   bq query --format=csv --use_legacy_sql=false \
    #     "SELECT * FROM ${BQ_DATASET}.dim_store" > "$OUTPUT_FILE"
    exit 1
fi

# Build a single wide reference extract from the STORE_OPS dimensions.
# FIXME: fully qualified Snowflake identifiers - repoint at BigQuery dataset.
EXTRACT_SQL="
SELECT s.store_id,
       s.store_name,
       s.region_code,
       r.region_name,
       s.banner,
       s.timezone
FROM   RETAIL_PROD.STORE_OPS.DIM_STORE  s
JOIN   RETAIL_PROD.STORE_OPS.DIM_REGION r
  ON   s.region_code = r.region_code
WHERE  s.active = TRUE
ORDER  BY s.store_id;
"

# Write header (the raw snowsql tsv output has none in our config)
echo "store_id,store_name,region_code,region_name,banner,timezone" > "$OUTPUT_FILE"

TMP_TSV=$(mktemp)
snow_query "$EXTRACT_SQL" "$TMP_TSV"
RC=$?

if [[ $RC -ne 0 ]]; then
    log_error "Dimension extract query failed (rc=${RC})"
    rm -f "$TMP_TSV"
    exit 1
fi

# Convert TSV -> CSV (naive; breaks if any field contains a comma)
awk -F'\t' 'BEGIN{OFS=","} {$1=$1; print}' "$TMP_TSV" >> "$OUTPUT_FILE"
rm -f "$TMP_TSV"

ROWS=$(( $(wc -l < "$OUTPUT_FILE") - 1 ))
log_info "Extracted ${ROWS} dimension rows -> ${OUTPUT_FILE}"
exit 0
