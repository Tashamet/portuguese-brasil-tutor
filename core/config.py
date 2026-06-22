"""Load and access the YAML config.

Reads ``config/config.yaml`` if present, otherwise falls back to
``config/config.example.yaml``. Secrets are never read from the file — only
from environment variables (``TELEGRAM_BOT_TOKEN``, ``ELEVENLABS_API_KEY``,
``OPENAI_API_KEY``, ``COACH_SYNC_TOKEN``).
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

import yaml

from . import paths

# Interface languages the tutor can explain in. Target is always pt-BR.
INTERFACE_LANGS = ("ru", "en", "uk")


@lru_cache(maxsize=1)
def load() -> dict[str, Any]:
    path = paths.CONFIG_PATH if paths.CONFIG_PATH.exists() else paths.CONFIG_EXAMPLE
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def get(dotted: str, default: Any = None) -> Any:
    """Fetch a nested value via dotted path, e.g. ``get('tts.provider')``."""
    node: Any = load()
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def reload() -> None:
    load.cache_clear()


# --- Convenience accessors -------------------------------------------------

def interface_language() -> str | None:
    lang = (get("interface_language") or "").strip().lower()
    return lang if lang in INTERFACE_LANGS else None


def review_intervals() -> list[int]:
    raw = get("review_intervals", [2, 7, 30]) or [2, 7, 30]
    return [int(x) for x in raw]


def tts_provider() -> str:
    return (get("tts.provider", "system") or "system").strip().lower()


def telegram_enabled() -> bool:
    return bool(get("telegram.enabled", False))


def telegram_chat_id() -> str | None:
    cid = get("telegram.chat_id")
    return str(cid) if cid not in (None, "", "<your chat_id>") else None


def telegram_token() -> str | None:
    return os.environ.get("TELEGRAM_BOT_TOKEN")


def sync_mode() -> str:
    return (get("sync.mode", "shared") or "shared").strip().lower()


def student_name() -> str:
    return (get("student_name") or "").strip()


_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def lesson_reminders_enabled() -> bool:
    return bool(get("lessons.reminder_enabled", True))


def lesson_time() -> str:
    return str(get("lessons.time", "19:00") or "19:00")


def is_study_day(d) -> bool:
    """True if ``d`` (a date) is a configured study day."""
    days = get("lessons.days", "daily")
    if isinstance(days, str):
        days = days.strip().lower()
        if days in ("daily", "every day", "everyday", ""):
            return True
        wanted = {p.strip()[:3] for p in days.replace(" ", "").split(",") if p.strip()}
    else:  # a YAML list
        wanted = {str(p).strip().lower()[:3] for p in days}
    return _WEEKDAYS[d.weekday()] in wanted
