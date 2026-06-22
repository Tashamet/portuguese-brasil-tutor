"""Filesystem layout — separates the skill *code* from each student's *data*.

The code (this package) lives wherever the skill is installed, e.g.
``~/.claude/skills/portuguese-brasil-tutor``. It is read-only as far as the
learner is concerned. **No student data is ever written next to the code.**

Student data lives under a home directory, one self-contained folder per
student profile, so several learners (e.g. a couple) stay fully isolated —
separate config, database, wiki, plan, schedule and bot:

    ~/.portuguese-brasil-tutor/                 (TUTOR_HOME)
      active_profile                            (pointer to the default profile)
      students/
        nikolai/                                (a profile = one student)
          config.yaml  tutor.db  audio/  course/  journal/  sync/
        maria/
          ...

Resolution order for the active data dir:
  1. ``TUTOR_DATA_DIR``  — an explicit full path (power users, sync checkouts, tests)
  2. ``TUTOR_HOME``/students/``TUTOR_PROFILE``   — profile by env var
  3. ``TUTOR_HOME``/students/<active_profile file>   — last selected profile
  4. ``TUTOR_HOME``/students/default
"""
from __future__ import annotations

import os
import re
from pathlib import Path

# Package root = parent of the ``core`` directory (the skill code).
PKG_ROOT = Path(__file__).resolve().parents[1]

# Where all student data lives (never inside the skill code).
TUTOR_HOME = Path(os.environ.get("TUTOR_HOME", "~/.portuguese-brasil-tutor")).expanduser()
STUDENTS_DIR = TUTOR_HOME / "students"
ACTIVE_POINTER = TUTOR_HOME / "active_profile"


def slug_profile(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return s or "default"


def active_profile() -> str:
    env = os.environ.get("TUTOR_PROFILE")
    if env:
        return slug_profile(env)
    if ACTIVE_POINTER.exists():
        return ACTIVE_POINTER.read_text(encoding="utf-8").strip() or "default"
    return "default"


def set_active_profile(name: str) -> str:
    prof = slug_profile(name)
    TUTOR_HOME.mkdir(parents=True, exist_ok=True)
    ACTIVE_POINTER.write_text(prof + "\n", encoding="utf-8")
    return prof


def list_profiles() -> list[str]:
    if not STUDENTS_DIR.exists():
        return []
    return sorted(p.name for p in STUDENTS_DIR.iterdir() if p.is_dir())


def profile_dir(name: str) -> Path:
    return STUDENTS_DIR / slug_profile(name)


def _data_root() -> Path:
    override = os.environ.get("TUTOR_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return STUDENTS_DIR / active_profile()


DATA = _data_root()

# SQLite engine (spaced-repetition state). Binary, git-ignored.
DB_PATH = DATA / "tutor.db"

# Generated audio lessons. Git-ignored (audio travels via Telegram file_id).
AUDIO_DIR = DATA / "audio"

# Human-readable wiki course (open as an Obsidian vault to browse it).
COURSE_DIR = DATA / "course"
COURSE_INDEX = COURSE_DIR / "index.md"
COURSE_PLAN = COURSE_DIR / "plan.md"
COURSE_PROGRESS = COURSE_DIR / "progress.md"
WORDS_DIR = COURSE_DIR / "words"
GRAMMAR_DIR = COURSE_DIR / "grammar"
THEMES_DIR = COURSE_DIR / "themes"

# Claude's working memory.
JOURNAL_DIR = DATA / "journal"
PROFILE_MD = JOURNAL_DIR / "profile.md"
SESSIONS_DIR = JOURNAL_DIR / "sessions"
COMMANDS_MD = JOURNAL_DIR / "commands.md"

# Git sync bundle — lives inside the student's data dir, so that dir is the
# self-contained unit you can push to a private repo.
SYNC_DIR = DATA / "sync"
SYNC_BUNDLE = SYNC_DIR / "words.ndjson"

# Config: the example + deployment presets ship with the code; the active
# config.yaml lives next to the student's data (clear, per-student location).
CONFIG_DIR = PKG_ROOT / "config"
CONFIG_EXAMPLE = CONFIG_DIR / "config.example.yaml"
CONFIG_PATH = DATA / "config.yaml"


def ensure_dirs() -> None:
    """Create every directory the student's data dir needs."""
    for d in (
        AUDIO_DIR,
        WORDS_DIR,
        GRAMMAR_DIR,
        THEMES_DIR,
        SESSIONS_DIR,
        SYNC_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)
