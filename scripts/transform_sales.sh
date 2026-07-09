#!/bin/bash
# ============================================
# Sales CSV Transformation
# Cleans and standardizes store-sales CSV data before warehouse load.
# awk/sed based - no schema validation, best-effort.
#
# Author: pkaur
# Modified: 2022-10-03 (added date normalization)
# ============================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"

source "${BASE_DIR}/utils/logging.sh"
source "${BASE_DIR}/utils/file_utils.sh"
source "${BASE_DIR}/configs/pipeline.env"

INPUT_FILE="$1"
OUTPUT_FILE="$2"

if [[ -z "$INPUT_FILE" ]] || [[ -z "$OUTPUT_FILE" ]]; then
    echo "Usage: $0 <input_csv> <output_csv>"
    exit 1
fi

check_file "$INPUT_FILE" || exit 1

log_info "Transforming: $(basename "$INPUT_FILE")"

TEMP_FILE=$(mktemp)

# Step 1: strip UTF-8 BOM if present
sed '1s/^\xEF\xBB\xBF//' "$INPUT_FILE" > "$TEMP_FILE"

# Step 2: normalize CRLF -> LF (GNU sed on the VMs)
sed -i 's/\r$//' "$TEMP_FILE"

# Step 3: drop blank lines
sed -i '/^[[:space:]]*$/d' "$TEMP_FILE"

# Step 4: trim whitespace around each field
awk -F"${CSV_DELIMITER:-,}" 'BEGIN{OFS=","} {
    for (i=1; i<=NF; i++) {
        gsub(/^[[:space:]]+|[[:space:]]+$/, "", $i)
    }
    print
}' "$TEMP_FILE" > "${TEMP_FILE}.trim"
mv "${TEMP_FILE}.trim" "$TEMP_FILE"

# Step 5: normalize dates MM/DD/YYYY -> YYYY-MM-DD
# NOTE: brittle - assumes US format, silently mangles DD/MM/YYYY.
awk -F, 'BEGIN{OFS=","} NR>1 {
    for (i=1; i<=NF; i++) {
        if ($i ~ /^[0-9]{1,2}\/[0-9]{1,2}\/[0-9]{4}$/) {
            split($i, d, "/")
            $i = sprintf("%04d-%02d-%02d", d[3], d[1], d[2])
        }
    }
} { print }' "$TEMP_FILE" > "${TEMP_FILE}.dated"
mv "${TEMP_FILE}.dated" "$TEMP_FILE"

# Step 6: uppercase region codes and blank out NULL-like tokens
sed -i 's/\bNULL\b//gI; s/\bN\/A\b//gI; s/\bnone\b//gI' "$TEMP_FILE"

# Step 7: append load metadata columns
awk -v run_date="$(date +%Y-%m-%d)" -v src="$(basename "$INPUT_FILE")" \
    -F, 'BEGIN{OFS=","}
    NR==1 { print $0, "_load_date", "_source_file" }
    NR>1  { print $0, run_date, src }' "$TEMP_FILE" > "$OUTPUT_FILE"

rm -f "$TEMP_FILE"

ROWS=$(count_data_rows "$OUTPUT_FILE")
log_info "Transform complete: $(basename "$OUTPUT_FILE") (${ROWS} rows)"
exit 0
