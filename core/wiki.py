"""Markdown wiki-course read/write helpers.

The course (``data/course``) and Claude's working memory (``data/journal``) are
plain Markdown, cross-linked with ``[[wiki-links]]``. This module is the only
writer the CLI uses for those files, so link conventions stay consistent.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from pathlib import Path

from . import paths

WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")

# Localized labels for the scaffold so the wiki is written in the learner's
# chosen interface language. Word cards / session bodies are authored by Claude
# directly in that language; these are the structural labels.
LABELS = {
    "index_title": {"en": "Brazilian Portuguese course — index",
                    "ru": "Курс бразильского португальского — индекс",
                    "uk": "Курс бразильської португальської — індекс"},
    "interface_language": {"en": "Interface language", "ru": "Язык интерфейса",
                           "uk": "Мова інтерфейсу"},
    "learning_plan": {"en": "Learning plan", "ru": "План обучения",
                      "uk": "План навчання"},
    "progress": {"en": "Progress", "ru": "Прогресс", "uk": "Прогрес"},
    "words": {"en": "Words", "ru": "Слова", "uk": "Слова"},
    "grammar": {"en": "Grammar", "ru": "Грамматика", "uk": "Граматика"},
    "themes": {"en": "Themes", "ru": "Темы", "uk": "Теми"},
    "empty": {"en": "_empty_", "ru": "_пусто_", "uk": "_порожньо_"},
    "plan_placeholder": {
        "en": "_Agree the plan with the learner and fill in the stages._",
        "ru": "_Согласуйте план с учеником и заполните этапы._",
        "uk": "_Узгодьте план з учнем і заповніть етапи._"},
    "related": {"en": "Related", "ru": "Связано", "uk": "Пов'язано"},
    "current_stage": {"en": "Current stage", "ru": "Текущий этап",
                      "uk": "Поточний етап"},
    "words_known": {"en": "Words known", "ru": "Выучено слов",
                    "uk": "Вивчено слів"},
    "words_in_progress": {"en": "Words in progress", "ru": "В процессе",
                          "uk": "У процесі"},
    "due_today": {"en": "Due today", "ru": "К повторению сегодня",
                  "uk": "До повторення сьогодні"},
    "profile_title": {"en": "Learner profile", "ru": "Профиль ученика",
                      "uk": "Профіль учня"},
    "city_state": {"en": "City/state", "ru": "Город/штат", "uk": "Місто/штат"},
    "time_in_brazil": {"en": "Time in Brazil", "ru": "Как давно в Бразилии",
                       "uk": "Як давно в Бразилії"},
    "region_dialect": {"en": "Region/dialect", "ru": "Регион/диалект",
                       "uk": "Регіон/діалект"},
    "pace": {"en": "Pace", "ru": "Темп", "uk": "Темп"},
    "goals": {"en": "Goals", "ru": "Цели", "uk": "Цілі"},
    "panic_zones": {"en": "Panic zones", "ru": "Зоны паники", "uk": "Зони паніки"},
    "session": {"en": "Session", "ru": "Занятие", "uk": "Заняття"},
    "audio_phrases": {"en": "Phrases (from the audio)", "ru": "Фразы из аудио",
                      "uk": "Фрази з аудіо"},
    "meaning": {"en": "Meaning", "ru": "Значение", "uk": "Значення"},
}


def _lang(interface_language: str | None) -> str:
    lang = (interface_language or "en").lower()
    return lang if lang in ("en", "ru", "uk") else "en"


def t(key: str, interface_language: str | None) -> str:
    """Translate a scaffold label into the interface language (en fallback)."""
    entry = LABELS.get(key, {})
    return entry.get(_lang(interface_language)) or entry.get("en") or key


# Cyrillic (ru + uk) -> Latin, so interface-language topics get usable slugs.
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "ґ": "g", "д": "d", "е": "e", "ё": "e",
    "є": "ye", "ж": "zh", "з": "z", "и": "i", "і": "i", "ї": "yi", "й": "y",
    "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s",
    "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh",
    "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def slugify(text: str) -> str:
    """ASCII, lowercase, hyphenated slug. ``Então`` -> ``entao``;
    ``Кафе и пекарня`` -> ``kafe-i-pekarnya``."""
    lowered = (text or "").lower()
    translit = "".join(_TRANSLIT.get(ch, ch) for ch in lowered)
    norm = unicodedata.normalize("NFKD", translit)
    ascii_text = norm.encode("ascii", "ignore").decode("ascii")
    ascii_text = re.sub(r"[^a-z0-9]+", "-", ascii_text)
    return ascii_text.strip("-") or "word"


# --- Scaffold --------------------------------------------------------------

def ensure_scaffold(interface_language: str | None = None) -> None:
    """Create the course/journal skeleton (in the interface language) if missing."""
    paths.ensure_dirs()
    lng = interface_language or "—"
    if not paths.COURSE_INDEX.exists():
        rebuild_index(interface_language)
    if not paths.COURSE_PLAN.exists():
        _write(
            paths.COURSE_PLAN,
            f"# {t('learning_plan', interface_language)}\n\n"
            f"{t('plan_placeholder', interface_language)}\n\n"
            f"{t('related', interface_language)}: [[index]], [[progress]]\n",
        )
    if not paths.COURSE_PROGRESS.exists():
        update_progress("", 0, 0, 0, interface_language)
    if not paths.PROFILE_MD.exists():
        _write(
            paths.PROFILE_MD,
            f"# {t('profile_title', interface_language)}\n\n"
            f"- {t('interface_language', interface_language)}: {lng}\n"
            f"- {t('city_state', interface_language)}: —\n"
            f"- {t('time_in_brazil', interface_language)}: —\n"
            f"- {t('region_dialect', interface_language)}: —\n"
            f"- {t('pace', interface_language)}: —\n"
            f"- {t('goals', interface_language)}: —\n\n"
            f"## {t('panic_zones', interface_language)}\n\n- —\n",
        )


# --- Word cards ------------------------------------------------------------

def word_card_path(slug: str) -> Path:
    return paths.WORDS_DIR / f"{slug}.md"


def write_word_card(slug: str, markdown: str) -> Path:
    path = word_card_path(slug)
    _write(path, markdown.rstrip() + "\n")
    return path


def read_word_card(slug: str) -> str | None:
    path = word_card_path(slug)
    return path.read_text(encoding="utf-8") if path.exists() else None


# --- Sessions --------------------------------------------------------------

def append_session(markdown: str, when: date | None = None,
                   interface_language: str | None = None) -> Path:
    when = when or date.today()
    path = paths.SESSIONS_DIR / f"{when.isoformat()}.md"
    label = t("session", interface_language)
    header = f"# {label} {when.isoformat()}\n\n" if not path.exists() else "\n---\n\n"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(header + markdown.rstrip() + "\n")
    return path


def recent_sessions(limit: int = 3) -> list[str]:
    if not paths.SESSIONS_DIR.exists():
        return []
    files = sorted(paths.SESSIONS_DIR.glob("*.md"), reverse=True)[:limit]
    return [f.read_text(encoding="utf-8") for f in files]


# --- Index regeneration ----------------------------------------------------

def _list_stems(directory: Path) -> list[str]:
    if not directory.exists():
        return []
    return sorted(p.stem for p in directory.glob("*.md"))


def rebuild_index(interface_language: str | None = None) -> Path:
    """Regenerate ``index.md`` from what exists on disk (no broken links)."""
    lng = interface_language or "—"

    def section(key: str, prefix: str, stems: list[str]) -> str:
        title = t(key, interface_language)
        if not stems:
            return f"## {title}\n\n{t('empty', interface_language)}\n"
        items = "\n".join(f"- [[{prefix}/{s}]]" for s in stems)
        return f"## {title}\n\n{items}\n"

    body = (
        f"# {t('index_title', interface_language)}\n\n"
        f"- {t('interface_language', interface_language)}: **{lng}**\n"
        f"- [[plan|{t('learning_plan', interface_language)}]]\n"
        f"- [[progress|{t('progress', interface_language)}]]\n\n"
        + section("words", "words", _list_stems(paths.WORDS_DIR))
        + "\n"
        + section("grammar", "grammar", _list_stems(paths.GRAMMAR_DIR))
        + "\n"
        + section("themes", "themes", _list_stems(paths.THEMES_DIR))
    )
    _write(paths.COURSE_INDEX, body)
    return paths.COURSE_INDEX


def update_progress(stage: str, known: int, learning: int, due_today: int,
                    interface_language: str | None = None) -> Path:
    body = (
        f"# {t('progress', interface_language)}\n\n"
        f"- {t('current_stage', interface_language)}: {stage or '—'}\n"
        f"- {t('words_known', interface_language)}: {known}\n"
        f"- {t('words_in_progress', interface_language)}: {learning}\n"
        f"- {t('due_today', interface_language)}: {due_today}\n\n"
        f"{t('related', interface_language)}: [[index]], [[plan]]\n"
    )
    _write(paths.COURSE_PROGRESS, body)
    return paths.COURSE_PROGRESS


# --- Link checking (for verification) -------------------------------------

def find_broken_links() -> list[tuple[str, str]]:
    """Return ``(source_file, target)`` pairs whose ``[[target]]`` has no file."""
    broken: list[tuple[str, str]] = []
    md_files = list(paths.COURSE_DIR.rglob("*.md")) + list(paths.JOURNAL_DIR.rglob("*.md"))
    for f in md_files:
        text = f.read_text(encoding="utf-8")
        for m in WIKILINK_RE.findall(text):
            target = m.split("|")[0].strip()  # strip display alias
            if not _link_exists(target):
                broken.append((str(f.relative_to(paths.DATA)), target))
    return broken


def _link_exists(target: str) -> bool:
    # Bare name resolves against course root; nested like ``words/entao``.
    candidates = [
        paths.COURSE_DIR / f"{target}.md",
        paths.COURSE_DIR / target / "index.md",
    ]
    return any(c.exists() for c in candidates)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
