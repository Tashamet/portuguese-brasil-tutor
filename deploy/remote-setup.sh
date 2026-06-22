#!/usr/bin/env bash
# Runs ON the remote host (invoked by `tutor.py deploy --ssh`).
# Creates a venv, installs deps, and installs a daily cron job that pulls +
# imports + delivers due reviews. Idempotent.
set -euo pipefail

SEND_TIME="${1:-09:00}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${DIR}/.venv/bin/python"

echo "[remote-setup] dir=${DIR} send_time=${SEND_TIME}"

if [ ! -d "${DIR}/.venv" ]; then
  python3 -m venv "${DIR}/.venv"
fi
"${DIR}/.venv/bin/pip" install -q --upgrade pip
"${DIR}/.venv/bin/pip" install -q -r "${DIR}/requirements.txt"

HOUR="${SEND_TIME%%:*}"
MIN="${SEND_TIME##*:}"
CRON_LINE="${MIN} ${HOUR} * * * cd ${DIR} && ${PY} notifier/send_due.py >> ${DIR}/data/notifier.log 2>&1"

# Replace any prior tutor cron line, keep the rest.
( crontab -l 2>/dev/null | grep -v 'notifier/send_due.py' ; echo "${CRON_LINE}" ) | crontab -

echo "[remote-setup] cron installed:"
echo "  ${CRON_LINE}"
echo "[remote-setup] set TELEGRAM_BOT_TOKEN in the environment for the cron user."
