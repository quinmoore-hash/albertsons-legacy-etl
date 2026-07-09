#!/bin/bash
# ============================================
# Cron Installer (Python pipeline)
# ============================================
# Thin cron wrapper for the *Python* ETL entrypoints. This is the fallback
# scheduling option; the preferred target is the Cloud Composer (Airflow) DAG
# in etl/dags/nightly_etl_dag.py (or per-step Cloud Run jobs). See README
# "Scheduling".
#
# Assumes the `etl` package is installed (pip install -e . or the wheel) in the
# Python interpreter referenced by $PYTHON below, and that the pipeline
# environment variables (GCP_PROJECT, BQ_DATASET, GCS_BUCKET, data-dir paths,
# LOG_DIR, ...) are exported for cron (e.g. via /etc/environment or an
# EnvironmentFile). Secrets (POS_API_KEY, SLACK_WEBHOOK_URL) come from Secret
# Manager at runtime.
#
# NOTE: this clobbers the existing crontab. There is no backup. Be careful.

set -euo pipefail

PYTHON="${PYTHON:-python3}"
LOG_DIR="${LOG_DIR:-/var/log/albertsons/etl}"

CRON_TMP=$(mktemp)

cat > "$CRON_TMP" <<EOF
# Albertsons Store ETL (Python) - managed by install_cron_python.sh
# All times America/Los_Angeles (VM TZ)
CRON_TZ=America/Los_Angeles

# Nightly full ETL
30 1 * * *   ${PYTHON} -m etl.run_nightly_etl >> ${LOG_DIR}/run_nightly_etl.log 2>&1

# Mid-morning POS re-pull for late-reporting stores
0 9 * * *    ${PYTHON} -m etl.fetch_pos_data >> ${LOG_DIR}/fetch_pos_data.log 2>&1

# Standalone data quality sweep
0 6 * * *    ${PYTHON} -m etl.data_quality_check >> ${LOG_DIR}/dq.log 2>&1

# Daily cleanup
0 5 * * *    ${PYTHON} -m etl.cleanup_old_data >> ${LOG_DIR}/cleanup.log 2>&1

# Weekly dependency check
0 7 * * 1    ${PYTHON} -m etl.check_dependencies >> ${LOG_DIR}/deps.log 2>&1
EOF

echo "Installing crontab:"
cat "$CRON_TMP"

crontab "$CRON_TMP"
RC=$?
rm -f "$CRON_TMP"

if [[ $RC -eq 0 ]]; then
    echo "Crontab installed."
else
    echo "ERROR: failed to install crontab (rc=${RC})" >&2
fi
exit $RC
