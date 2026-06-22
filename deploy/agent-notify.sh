#!/usr/bin/env bash
# Deliver due reviews + the lesson nudge from a scheduled Claude agent (or any
# cron) — no personal server. Code and data are SEPARATE: the public code repo
# holds the toolkit, your PRIVATE repo holds one student's data dir.
#
# Each run: clone/pull both, then run `tutor.py notify` against the data dir.
#
# Required environment:
#   TUTOR_SYNC_REPO    git URL of YOUR PRIVATE repo (a student data dir:
#                      config.yaml, course/, journal/, sync/words.ndjson)
#   TELEGRAM_BOT_TOKEN a dedicated bot's token
# Optional:
#   TUTOR_CODE_REPO    code repo URL (default: the public repo)
#   CODE_DIR / DATA_DIR  checkout locations
set -euo pipefail

: "${TUTOR_SYNC_REPO:?set TUTOR_SYNC_REPO to your private data repo URL}"
: "${TELEGRAM_BOT_TOKEN:?set TELEGRAM_BOT_TOKEN}"
CODE_REPO="${TUTOR_CODE_REPO:-https://github.com/Tashamet/portuguese-brasil-tutor.git}"
CODE_DIR="${CODE_DIR:-$HOME/ptb-tutor-code}"
DATA_DIR="${DATA_DIR:-$HOME/ptb-tutor-data}"

clone_or_pull() { # url dir
  if [ -d "$2/.git" ]; then git -C "$2" pull --ff-only; else git clone "$1" "$2"; fi
}

clone_or_pull "$CODE_REPO" "$CODE_DIR"
clone_or_pull "$TUTOR_SYNC_REPO" "$DATA_DIR"

python3 -m pip install --user -q -r "$CODE_DIR/requirements.txt"
TUTOR_DATA_DIR="$DATA_DIR" python3 "$CODE_DIR/cli/tutor.py" notify
