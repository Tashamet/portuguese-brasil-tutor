"""Centralised filesystem paths for the tutor package.

Everything is resolved relative to the package root (the directory that
contains ``core/``), so the package is relocatable: copy the folder, run the
CLI, and all data lands inside ``data/`` next to the code.
"""
from __future__ import annotations

import os
from pathlib import Path

# Package root = parent of the ``core`` directory.
PKG_ROOT = Path(__file__).resolve().parents[1]


def _data_root() -> Path:
    # Allow an override so a remote notifier can point at a synced checkout.
    override = os.environ.get("TUTOR_DATA_DIR")
    return Path(override).expanduser().resolve() if override else PKG_ROOT / "data"


DATA = _data_root()

# SQLite engine (spaced-repetition state). Binary, git-ignored.
DB_PATH = DATA / "tutor.db"

# Generated audio lessons. Git-ignored (audio travels via Telegram file_id).
AUDIO_DIR = DATA / "audio"

# Human-readable wiki course (committed / synced).
COURSE_DIR = DATA / "course"
COURSE_INDEX = COURSE_DIR / "index.md"
COURSE_PLAN = COURSE_DIR / "plan.md"
COURSE_PROGRESS = COURSE_DIR / "progress.md"
WORDS_DIR = COURSE_DIR / "words"
GRAMMAR_DIR = COURSE_DIR / "grammar"
THEMES_DIR = COURSE_DIR / "themes"

# Claude's working memory (committed / synced).
JOURNAL_DIR = DATA / "journal"
PROFILE_MD = JOURNAL_DIR / "profile.md"
SESSIONS_DIR = JOURNAL_DIR / "sessions"
COMMANDS_MD = JOURNAL_DIR / "commands.md"

# Git sync bundle (committed).
SYNC_DIR = PKG_ROOT / "sync"
SYNC_BUNDLE = SYNC_DIR / "words.ndjson"

# Config. The example + profiles live in the package; the active config.yaml is
# per-instance — it follows the data dir when TUTOR_DATA_DIR is overridden, so a
# relocated instance (or a sandboxed selftest) keeps its own config.
CONFIG_DIR = PKG_ROOT / "config"
CONFIG_EXAMPLE = CONFIG_DIR / "config.example.yaml"
CONFIG_PATH = (DATA / "config.yaml") if os.environ.get("TUTOR_DATA_DIR") \
    else CONFIG_DIR / "config.yaml"


def ensure_dirs() -> None:
    """Create every data directory the package writes to."""
    for d in (
        AUDIO_DIR,
        WORDS_DIR,
        GRAMMAR_DIR,
        THEMES_DIR,
        SESSIONS_DIR,
        SYNC_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)
