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


def slugify(text: str) -> str:
    """ASCII, lowercase, hyphenated slug. ``Então`` -> ``entao``."""
    norm = unicodedata.normalize("NFKD", text)
    ascii_text = norm.encode("ascii", "ignore").decode("ascii")
    ascii_text = ascii_text.lower().strip()
    ascii_text = re.sub(r"[^a-z0-9]+", "-", ascii_text)
    return ascii_text.strip("-") or "word"


# --- Scaffold --------------------------------------------------------------

def ensure_scaffold(interface_language: str | None = None) -> None:
    """Create the course/journal skeleton if it does not exist yet."""
    paths.ensure_dirs()
    lang = interface_language or "—"
    if not paths.COURSE_INDEX.exists():
        _write(
            paths.COURSE_INDEX,
            f"# Курс бразильского португальского — индекс\n\n"
            f"- Язык интерфейса: **{lang}**\n"
            f"- [[plan|План обучения]]\n"
            f"- [[progress|Прогресс]]\n\n"
            f"## Слова\n\n_пока пусто_\n\n"
            f"## Грамматика\n\n_пока пусто_\n\n"
            f"## Темы\n\n_пока пусто_\n",
        )
    if not paths.COURSE_PLAN.exists():
        _write(
            paths.COURSE_PLAN,
            "# План обучения\n\n_Согласуйте план с учеником и заполните этапы._\n\n"
            "Связано: [[index]], [[progress]]\n",
        )
    if not paths.COURSE_PROGRESS.exists():
        _write(
            paths.COURSE_PROGRESS,
            "# Прогресс\n\n- Текущий этап: —\n- Выучено слов: 0\n- В процессе: 0\n\n"
            "Связано: [[index]], [[plan]]\n",
        )
    if not paths.PROFILE_MD.exists():
        _write(
            paths.PROFILE_MD,
            f"# Профиль ученика\n\n- Язык интерфейса: {lang}\n- Город/штат: —\n"
            f"- Как давно в Бразилии: —\n- Регион/диалект: —\n- Темп: —\n"
            f"- Цели: —\n\n## Зоны паники\n\n- —\n",
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

def append_session(markdown: str, when: date | None = None) -> Path:
    when = when or date.today()
    path = paths.SESSIONS_DIR / f"{when.isoformat()}.md"
    header = f"# Занятие {when.isoformat()}\n\n" if not path.exists() else "\n---\n\n"
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
    lang = interface_language or "—"

    def section(title: str, prefix: str, stems: list[str]) -> str:
        if not stems:
            return f"## {title}\n\n_пока пусто_\n"
        items = "\n".join(f"- [[{prefix}/{s}]]" for s in stems)
        return f"## {title}\n\n{items}\n"

    body = (
        f"# Курс бразильского португальского — индекс\n\n"
        f"- Язык интерфейса: **{lang}**\n"
        f"- [[plan|План обучения]]\n"
        f"- [[progress|Прогресс]]\n\n"
        + section("Слова", "words", _list_stems(paths.WORDS_DIR))
        + "\n"
        + section("Грамматика", "grammar", _list_stems(paths.GRAMMAR_DIR))
        + "\n"
        + section("Темы", "themes", _list_stems(paths.THEMES_DIR))
    )
    _write(paths.COURSE_INDEX, body)
    return paths.COURSE_INDEX


def update_progress(stage: str, known: int, learning: int, due_today: int) -> Path:
    body = (
        f"# Прогресс\n\n"
        f"- Текущий этап: {stage or '—'}\n"
        f"- Выучено слов: {known}\n"
        f"- В процессе: {learning}\n"
        f"- К повторению сегодня: {due_today}\n\n"
        f"Связано: [[index]], [[plan]]\n"
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
