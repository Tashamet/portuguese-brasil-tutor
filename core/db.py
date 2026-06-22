"""SQLite engine for the spaced-repetition state.

This is the authoritative store for *queryable* data: words, variations, the
review schedule (Ebbinghaus 2/7/30), audio assets and settings. The rich,
human-readable content (word cards, plan, progress) lives in Markdown under
``data/course`` — see :mod:`core.wiki`.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Iterator

from . import paths
from .models import AudioAsset, Review, Variation, Word

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS words (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    slug         TEXT UNIQUE NOT NULL,
    target_lemma TEXT NOT NULL,
    gloss        TEXT NOT NULL,
    pos          TEXT DEFAULT '',
    topic        TEXT DEFAULT '',
    priority     INTEGER DEFAULT 3,
    status       TEXT DEFAULT 'new',
    card_path    TEXT DEFAULT '',
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS variations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id       INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    idx           INTEGER NOT NULL,
    pt_sentence   TEXT NOT NULL,
    gloss_sentence TEXT NOT NULL,
    context_label TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS audio_assets (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id          INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    lang             TEXT DEFAULT '',
    file_path        TEXT DEFAULT '',
    kind             TEXT DEFAULT 'lesson',
    duration         REAL DEFAULT 0,
    telegram_file_id TEXT DEFAULT '',
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id      INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    due_date     TEXT NOT NULL,
    interval_day INTEGER NOT NULL,
    status       TEXT DEFAULT 'pending',
    sent_at      TEXT,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_reviews_due ON reviews(due_date, status);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    paths.ensure_dirs()
    conn = sqlite3.connect(paths.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


# --- Settings --------------------------------------------------------------

def set_setting(key: str, value: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )


def get_setting(key: str, default: str | None = None) -> str | None:
    with connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


# --- Words & variations ----------------------------------------------------

def add_word(word: Word, intervals: list[int], today: date | None = None) -> int:
    """Insert a word + its variations and schedule its reviews.

    Returns the new word id. Reviews are scheduled at ``today + n`` for each
    interval (Ebbinghaus 2/7/30 by default).
    """
    today = today or date.today()
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO words(slug, target_lemma, gloss, pos, topic, priority, "
            "status, card_path, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                word.slug,
                word.target_lemma,
                word.gloss,
                word.pos,
                word.topic,
                word.priority,
                word.status,
                word.card_path,
                today.isoformat(),
            ),
        )
        word_id = int(cur.lastrowid)
        for v in word.variations:
            conn.execute(
                "INSERT INTO variations(word_id, idx, pt_sentence, gloss_sentence, "
                "context_label) VALUES(?,?,?,?,?)",
                (word_id, v.idx, v.pt_sentence, v.gloss_sentence, v.context_label),
            )
        for n in intervals:
            due = (today + timedelta(days=int(n))).isoformat()
            conn.execute(
                "INSERT INTO reviews(word_id, due_date, interval_day, status) "
                "VALUES(?,?,?, 'pending')",
                (word_id, due, int(n)),
            )
    return word_id


def get_word_by_slug(slug: str) -> Word | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM words WHERE slug = ?", (slug,)).fetchone()
        if not row:
            return None
        return _word_from_row(conn, row)


def list_words(status: str | None = None) -> list[Word]:
    q = "SELECT * FROM words"
    params: tuple = ()
    if status:
        q += " WHERE status = ?"
        params = (status,)
    q += " ORDER BY created_at"
    with connect() as conn:
        rows = conn.execute(q, params).fetchall()
        return [_word_from_row(conn, r) for r in rows]


def set_word_status(slug: str, status: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE words SET status = ? WHERE slug = ?", (status, slug))


def _word_from_row(conn: sqlite3.Connection, row: sqlite3.Row) -> Word:
    vrows = conn.execute(
        "SELECT * FROM variations WHERE word_id = ? ORDER BY idx", (row["id"],)
    ).fetchall()
    return Word(
        id=row["id"],
        slug=row["slug"],
        target_lemma=row["target_lemma"],
        gloss=row["gloss"],
        pos=row["pos"],
        topic=row["topic"],
        priority=row["priority"],
        status=row["status"],
        card_path=row["card_path"],
        variations=[
            Variation(v["idx"], v["pt_sentence"], v["gloss_sentence"], v["context_label"])
            for v in vrows
        ],
    )


# --- Audio assets ----------------------------------------------------------

def save_audio(asset: AudioAsset, today: date | None = None) -> int:
    today = today or date.today()
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO audio_assets(word_id, lang, file_path, kind, duration, "
            "telegram_file_id, created_at) VALUES(?,?,?,?,?,?,?)",
            (
                asset.word_id,
                asset.lang,
                asset.file_path,
                asset.kind,
                asset.duration,
                asset.telegram_file_id,
                today.isoformat(),
            ),
        )
        return int(cur.lastrowid)


def set_audio_file_id(word_id: int, file_id: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE audio_assets SET telegram_file_id = ? WHERE word_id = ? "
            "AND id = (SELECT MAX(id) FROM audio_assets WHERE word_id = ?)",
            (file_id, word_id, word_id),
        )


def latest_audio(word_id: int) -> AudioAsset | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM audio_assets WHERE word_id = ? ORDER BY id DESC LIMIT 1",
            (word_id,),
        ).fetchone()
        if not row:
            return None
        return AudioAsset(
            id=row["id"],
            word_id=row["word_id"],
            lang=row["lang"],
            file_path=row["file_path"],
            kind=row["kind"],
            duration=row["duration"],
            telegram_file_id=row["telegram_file_id"],
        )


# --- Reviews (the Ebbinghaus engine) --------------------------------------

def due_reviews(on: date | None = None) -> list[dict]:
    """Pending reviews due on/before ``on`` (default today), joined with word."""
    on = on or date.today()
    with connect() as conn:
        rows = conn.execute(
            "SELECT r.id AS review_id, r.due_date, r.interval_day, w.* "
            "FROM reviews r JOIN words w ON w.id = r.word_id "
            "WHERE r.status = 'pending' AND r.due_date <= ? "
            "ORDER BY r.due_date, w.priority",
            (on.isoformat(),),
        ).fetchall()
        return [dict(r) for r in rows]


def mark_review(review_id: int, status: str, when: date | None = None) -> None:
    when = (when or date.today()).isoformat()
    col = "sent_at" if status == "sent" else "completed_at"
    with connect() as conn:
        conn.execute(
            f"UPDATE reviews SET status = ?, {col} = ? WHERE id = ?",
            (status, when, review_id),
        )


def stats() -> dict:
    with connect() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM words").fetchone()["c"]
        by_status = {
            r["status"]: r["c"]
            for r in conn.execute(
                "SELECT status, COUNT(*) c FROM words GROUP BY status"
            ).fetchall()
        }
        pending = conn.execute(
            "SELECT COUNT(*) c FROM reviews WHERE status = 'pending'"
        ).fetchone()["c"]
        due = len(due_reviews())
        return {
            "total_words": total,
            "by_status": by_status,
            "pending_reviews": pending,
            "due_today": due,
        }
