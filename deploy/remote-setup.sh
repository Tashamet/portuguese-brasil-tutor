#!/usr/bin/env bash
# Runs ON the remote host (invoked by `tutor.py deploy --ssh`).
# Code and data are separate: this dir is the CODE; the student DATA is cloned
# from a private git repo. Installs a venv + light deps and a daily cron that
# runs `tutor.py notify` against the data dir. Idempotent.
#
#   remote-setup.sh <send_time HH:MM> <data_repo_url> [timezone]
set -euo pipefail

SEND_TIME="${1:-09:00}"
DATA_REPO="${2:?data repo URL required}"
TZ_NAME="${3:-}"   # e.g. America/Sao_Paulo; empty = server local time
CODE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA="$HOME/ptb-tutor-data"
PY="${CODE}/.venv/bin/python"

echo "[remote-setup] code=${CODE} data=${DATA} send_time=${SEND_TIME} tz=${TZ_NAME:-server-local}"

# Light venv — the notifier sends by Telegram file_id, so no TTS/Piper needed.
[ -d "${CODE}/.venv" ] || python3 -m venv "${CODE}/.venv"
"${CODE}/.venv/bin/pip" install -q --upgrade pip
"${CODE}/.venv/bin/pip" install -q -r "${CODE}/requirements.txt"

# Clone (or update) the student's private data repo.
if [ -d "${DATA}/.git" ]; then
  git -C "${DATA}" pull --ff-only
else
  git clone "${DATA_REPO}" "${DATA}"
fi

HOUR="${SEND_TIME%%:*}"
MIN="${SEND_TIME##*:}"
CRON_LINE="${MIN} ${HOUR} * * * . \$HOME/.ptb_env 2>/dev/null; TUTOR_DATA_DIR=${DATA} ${PY} ${CODE}/cli/tutor.py notify >> \$HOME/ptb-tutor.log 2>&1"

# Interpret the time in the learner's timezone, not the server's (most VPSes are
# UTC). CRON_TZ is honoured by Vixie cron (Debian/Ubuntu); falls back to a
# TZ= prefix on the command for other crons.
TZ_HEADER=""
if [ -n "${TZ_NAME}" ]; then
  TZ_HEADER="CRON_TZ=${TZ_NAME}"
  CRON_LINE="${MIN} ${HOUR} * * * . \$HOME/.ptb_env 2>/dev/null; TZ=${TZ_NAME} TUTOR_DATA_DIR=${DATA} ${PY} ${CODE}/cli/tutor.py notify >> \$HOME/ptb-tutor.log 2>&1"
fi

# Replace any prior tutor cron lines (incl. a previous CRON_TZ), keep the rest.
( crontab -l 2>/dev/null | grep -v 'cli/tutor.py notify' | grep -v '^CRON_TZ=' ; \
  [ -n "${TZ_HEADER}" ] && echo "${TZ_HEADER}" ; echo "${CRON_LINE}" ) | crontab -

echo "[remote-setup] cron installed:"
echo "  ${CRON_LINE}"
echo "[remote-setup] put the bot token in ~/.ptb_env:  export TELEGRAM_BOT_TOKEN=..."
