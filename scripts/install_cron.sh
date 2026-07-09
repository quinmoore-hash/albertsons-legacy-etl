#!/bin/bash
# ============================================
# Cron Installer
# Installs the pipeline's crontab entries for the etl service user.
# Run once during VM provisioning (and after every edit, manually).
#
# Author: rgonzalez
# NOTE: this clobbers the existing crontab. There is no backup. Be careful.
# ============================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ETL_HOME="${ETL_HOME:-/opt/albertsons/etl}"
LOG_DIR="${LOG_DIR:-/var/log/albertsons/etl}"

CRON_TMP=$(mktemp)

cat > "$CRON_TMP" <<EOF
# Albertsons Store ETL - managed by install_cron.sh (do not edit by hand)
# All times America/Los_Angeles (VM TZ)

# Nightly full ETL
30 1 * * *   ${ETL_HOME}/scripts/run_nightly_etl.sh >> ${LOG_DIR}/run_nightly_etl.log 2>&1

# Mid-morning POS re-pull for late-reporting stores
0 9 * * *    ${ETL_HOME}/scripts/fetch_pos_data.sh >> ${LOG_DIR}/fetch_pos_data.log 2>&1

# Standalone data quality sweep
0 6 * * *    ${ETL_HOME}/scripts/data_quality_check.sh >> ${LOG_DIR}/dq.log 2>&1

# Daily cleanup
0 5 * * *    ${ETL_HOME}/scripts/cleanup_old_data.sh >> ${LOG_DIR}/cleanup.log 2>&1

# Weekly dependency check (emails ops if something is missing)
0 7 * * 1    ${ETL_HOME}/scripts/check_dependencies.sh >> ${LOG_DIR}/deps.log 2>&1
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
