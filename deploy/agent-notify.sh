#!/usr/bin/env bash
# Deliver due reviews from a scheduled Claude agent (or any cron) — no personal
# server. Each run: clone/pull your PRIVATE repo (code + committed learning
# data), install deps, and run `tutor.py notify` (pull -> import -> send-due).
#
# The agent's environment must provide:
#   TUTOR_SYNC_REPO   git URL of YOUR private repo that holds the committed data
#   TELEGRAM_BOT_TOKEN the bot token (use a dedicated bot)
# Optional: TUTOR_DIR (checkout location, default ~/tutor-data-repo)
set -euo pipefail

: "${TUTOR_SYNC_REPO:?set TUTOR_SYNC_REPO to your private data repo URL}"
: "${TELEGRAM_BOT_TOKEN:?set TELEGRAM_BOT_TOKEN}"
DIR="${TUTOR_DIR:-$HOME/tutor-data-repo}"

if [ -d "$DIR/.git" ]; then
  git -C "$DIR" pull --ff-only
else
  git clone "$TUTOR_SYNC_REPO" "$DIR"
fi

python3 -m pip install --user -q -r "$DIR/requirements.txt"
cd "$DIR"
python3 cli/tutor.py notify
