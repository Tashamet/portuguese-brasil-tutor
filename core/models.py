"""Lightweight dataclasses mirroring the SQLite rows."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Variation:
    idx: int
    pt_sentence: str
    gloss_sentence: str
    context_label: str = ""


@dataclass
class Word:
    slug: str
    target_lemma: str
    gloss: str
    pos: str = ""
    topic: str = ""
    priority: int = 3
    status: str = "new"  # new | learning | known
    card_path: str = ""
    variations: list[Variation] = field(default_factory=list)
    id: int | None = None


@dataclass
class Review:
    word_id: int
    due_date: str  # ISO date YYYY-MM-DD
    interval_day: int  # 2 | 7 | 30
    status: str = "pending"  # pending | sent | done
    id: int | None = None


@dataclass
class AudioAsset:
    word_id: int
    lang: str
    file_path: str
    kind: str = "lesson"  # lesson | review
    duration: float = 0.0
    telegram_file_id: str = ""
    id: int | None = None
