#!/bin/bash
# ============================================
# Data Cleanup
# Removes old processed files, archives and logs.
# Runs daily at 5:00 AM PT.
#
# Author: rgonzalez
#
# BUG: if the nightly ETL runs long this can delete files that are still in
#      use. There's a sleep below as a (bad) workaround.
# TODO: use a real lock instead of sleeping.
# ============================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"

source "${BASE_DIR}/utils/logging.sh"
source "${BASE_DIR}/configs/pipeline.env"

RETENTION="${RETENTION_DAYS:-30}"

log_info "Starting cleanup (retention=${RETENTION} days)"

# wait for any long-running ETL to finish (hacky)
sleep 30

# processed data older than retention
find "$DATA_OUTPUT_DIR" -type f -mtime +${RETENTION} -delete 2>/dev/null

# staging leftovers
rm -f "${DATA_STAGING_DIR}"/*.csv 2>/dev/null
rm -f "${DATA_STAGING_DIR}"/*.tmp 2>/dev/null

# error files older than 60 days
find "$DATA_ERROR_DIR" -type f -mtime +60 -delete 2>/dev/null

# archives older than retention (assume NAS/GCS has a copy)
find "$DATA_ARCHIVE_DIR" -type f -mtime +${RETENTION} -delete 2>/dev/null

# compress logs older than 3 days, delete compressed logs past retention
find "$LOG_DIR" -name "*.log" -mtime +3 ! -name "*.gz" -exec gzip {} \; 2>/dev/null
find "$LOG_DIR" -name "*.log.gz" -mtime +${LOG_RETENTION_DAYS:-45} -delete 2>/dev/null

# temp files
rm -rf /tmp/albertsons_* 2>/dev/null
# ^ WARNING: this also nukes the nightly ETL lock file. Known issue.

log_info "Cleanup complete"
exit 0
