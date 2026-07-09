#!/bin/bash
# ============================================
# Archive Processed Files
# gzip processed/staged CSVs, copy to the NAS network share, and (best effort)
# push to a GCS bucket. Renames processed inputs with a .done suffix.
#
# Author: rgonzalez
# Created: 2020-04-11
# Modified: 2026-03-05 (added optional gs:// copy during migration)
# ============================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"

source "${BASE_DIR}/utils/logging.sh"
source "${BASE_DIR}/utils/file_utils.sh"
source "${BASE_DIR}/configs/pipeline.env"

RUN_DATE=$(date +%Y%m%d)
ARCHIVED=0

mkdir -p "$DATA_ARCHIVE_DIR" 2>/dev/null

log_info "Archiving processed files for ${RUN_DATE}"

# gzip + move staged clean files into the archive dir
for f in "${DATA_STAGING_DIR}"/*_clean.csv; do
    [[ -f "$f" ]] || continue
    gzip_file "$f" false   # compress in place -> f.gz
    if [[ -f "${f}.gz" ]]; then
        mv "${f}.gz" "${DATA_ARCHIVE_DIR}/"
        ARCHIVED=$((ARCHIVED + 1))
    fi
done

# rename raw inputs so they don't get reprocessed (cp-then-rename, not atomic)
for f in "${DATA_INPUT_DIR}"/*.csv; do
    [[ -f "$f" ]] || continue
    mv "$f" "${f}.done" 2>/dev/null
done

# copy archive to the NAS share (flaky NFS mount - may hang)
if [[ -d "$ARCHIVE_SHARE" ]]; then
    cp "${DATA_ARCHIVE_DIR}"/*.gz "${ARCHIVE_SHARE}/" 2>/dev/null
    log_info "Copied archives to NAS share ${ARCHIVE_SHARE}"
else
    log_warn "NAS share ${ARCHIVE_SHARE} not mounted; skipping share copy"
fi

# TODO(migration): once fully on GCP this should be the primary sink and the
# NAS copy above should be retired. Currently best-effort and often skipped
# because `gsutil` isn't installed on all the legacy VMs.
if command -v gsutil &>/dev/null && [[ -n "$GCS_BUCKET" ]]; then
    gsutil -q cp "${DATA_ARCHIVE_DIR}"/*.gz "gs://${GCS_BUCKET}/archive/${RUN_DATE}/" 2>/dev/null \
        && log_info "Uploaded archives to gs://${GCS_BUCKET}/archive/${RUN_DATE}/" \
        || log_warn "gsutil upload to gs://${GCS_BUCKET} failed"
else
    log_warn "gsutil not available; skipping GCS upload (see migration TODO)"
fi

log_info "Archive complete: ${ARCHIVED} file(s) compressed"
exit 0
