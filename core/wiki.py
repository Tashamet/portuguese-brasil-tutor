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
            f"# Brazilian Portuguese course — index\n\n"
            f"- Interface language: **{lang}**\n"
            f"- [[plan|Learning plan]]\n"
            f"- [[progress|Progress]]\n\n"
            f"## Words\n\n_empty_\n\n"
            f"## Grammar\n\n_empty_\n\n"
            f"## Themes\n\n_empty_\n",
        )
    if not paths.COURSE_PLAN.exists():
        _write(
            paths.COURSE_PLAN,
            "# Learning plan\n\n_Agree the plan with the learner and fill in the stages._\n\n"
            "Related: [[index]], [[progress]]\n",
        )
    if not paths.COURSE_PROGRESS.exists():
        _write(
            paths.COURSE_PROGRESS,
            "# Progress\n\n- Current stage: —\n- Words known: 0\n- Words in progress: 0\n\n"
            "Related: [[index]], [[plan]]\n",
        )
    if not paths.PROFILE_MD.exists():
        _write(
            paths.PROFILE_MD,
            f"# Learner profile\n\n- Interface language: {lang}\n- City/state: —\n"
            f"- Time in Brazil: —\n- Region/dialect: —\n- Pace: —\n"
            f"- Goals: —\n\n## Panic zones\n\n- —\n",
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
    header = f"# Session {when.isoformat()}\n\n" if not path.exists() else "\n---\n\n"
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
            return f"## {title}\n\n_empty_\n"
        items = "\n".join(f"- [[{prefix}/{s}]]" for s in stems)
        return f"## {title}\n\n{items}\n"

    body = (
        f"# Brazilian Portuguese course — index\n\n"
        f"- Interface language: **{lang}**\n"
        f"- [[plan|Learning plan]]\n"
        f"- [[progress|Progress]]\n\n"
        + section("Words", "words", _list_stems(paths.WORDS_DIR))
        + "\n"
        + section("Grammar", "grammar", _list_stems(paths.GRAMMAR_DIR))
        + "\n"
        + section("Themes", "themes", _list_stems(paths.THEMES_DIR))
    )
    _write(paths.COURSE_INDEX, body)
    return paths.COURSE_INDEX


def update_progress(stage: str, known: int, learning: int, due_today: int) -> Path:
    body = (
        f"# Progress\n\n"
        f"- Current stage: {stage or '—'}\n"
        f"- Words known: {known}\n"
        f"- Words in progress: {learning}\n"
        f"- Due today: {due_today}\n\n"
        f"Related: [[index]], [[plan]]\n"
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
