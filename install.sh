#!/usr/bin/env bash
# One-line installer for portuguese-brasil-tutor (a Claude skill).
#
#   curl -fsSL https://raw.githubusercontent.com/Tashamet/portuguese-brasil-tutor/main/install.sh | bash
#
# Clones the repo straight into your Claude skills directory, installs the
# Python deps, and checks for ffmpeg. After that, open Claude Code and say
# "teach me Brazilian Portuguese" — the skill handles first-run setup itself.
#
# Override the location with TUTOR_DIR=... and the source with TUTOR_REPO=...
set -euo pipefail

REPO="${TUTOR_REPO:-https://github.com/Tashamet/portuguese-brasil-tutor.git}"
DIR="${TUTOR_DIR:-$HOME/.claude/skills/portuguese-brasil-tutor}"

echo "==> Installing portuguese-brasil-tutor"
echo "    location: $DIR"

command -v git >/dev/null 2>&1 || { echo "!! git is required"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "!! python3 is required"; exit 1; }

mkdir -p "$(dirname "$DIR")"

if [ -L "$DIR" ]; then
  echo "==> Existing dev symlink — updating its target"
  ( cd "$DIR" && git pull --ff-only ) || true
elif [ -d "$DIR/.git" ]; then
  echo "==> Updating existing clone"
  git -C "$DIR" pull --ff-only
else
  echo "==> Cloning"
  git clone "$REPO" "$DIR"
fi

echo "==> Installing Python dependencies"
PIP=(python3 -m pip install --user -q)
if ! "${PIP[@]}" -r "$DIR/requirements.txt" 2>/dev/null; then
  echo "   pip --user unavailable; creating a virtualenv at $DIR/.venv"
  python3 -m venv "$DIR/.venv"
  PY="$DIR/.venv/bin/python"
  PIP=("$PY" -m pip install -q)
  "${PIP[@]}" -r "$DIR/requirements.txt"
else
  PY=python3
fi

echo "==> Installing the default voice engine (Piper)"
# certifi fixes SSL cert failures on python.org macOS builds when downloading voices.
"${PIP[@]}" piper-tts certifi || echo "!! could not install piper-tts (you can switch to --tts system/cloud)"

echo "==> Pre-downloading the Brazilian Portuguese voice"
VOICES_DIR="$HOME/.local/share/piper-tts/voices"
mkdir -p "$VOICES_DIR"
SSL_CERT_FILE="$("$PY" -m certifi 2>/dev/null || true)" \
  "$PY" -m piper.download_voices pt_BR-faber-medium --download-dir "$VOICES_DIR" \
  >/dev/null 2>&1 && echo "   voice ready (others download on first use)" \
  || echo "!! voice pre-download skipped (will download on first lesson)"

if command -v ffmpeg >/dev/null 2>&1; then
  echo "==> ffmpeg found"
else
  echo "!! ffmpeg not found — audio lessons need it."
  echo "   macOS:  brew install ffmpeg     Debian/Ubuntu:  sudo apt install ffmpeg"
fi

cat <<DONE

Done. The skill is installed at:
  $DIR

Use it in Claude Code: start a new session and say
  "teach me Brazilian Portuguese"   (or invoke it by name: portuguese-brasil-tutor)

On first run it asks your interface language (English / Ukrainian / Russian),
explains how it works, lets you choose with-bot or without-bot, and starts.
DONE
