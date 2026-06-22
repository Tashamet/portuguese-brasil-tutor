"""Git-mode sync: export/import a text bundle (NDJSON).

The local Claude session is the only writer. It exports words + variations +
schedule + audio file_id to ``sync/words.ndjson`` (text, git-diffable) and
commits it together with the ``data/course`` cards. A remote notifier pulls and
imports. Import is non-destructive: it never downgrades a review the server has
already marked ``sent``/``done`` — the server owns delivery state locally.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import db, paths, wiki


def export_bundle(out_path: Path | None = None) -> Path:
    paths.ensure_dirs()
    out_path = out_path or paths.SYNC_BUNDLE
    lines: list[str] = []
    with db.connect() as conn:
        words = conn.execute("SELECT * FROM words ORDER BY created_at").fetchall()
        for w in words:
            variations = [
                dict(v) for v in conn.execute(
                    "SELECT idx, pt_sentence, gloss_sentence, context_label "
                    "FROM variations WHERE word_id = ? ORDER BY idx", (w["id"],)
                ).fetchall()
            ]
            reviews = [
                dict(r) for r in conn.execute(
                    "SELECT due_date, interval_day, status FROM reviews "
                    "WHERE word_id = ? ORDER BY interval_day", (w["id"],)
                ).fetchall()
            ]
            audio = conn.execute(
                "SELECT lang, duration, telegram_file_id FROM audio_assets "
                "WHERE word_id = ? ORDER BY id DESC LIMIT 1", (w["id"],)
            ).fetchone()
            record = {
                "slug": w["slug"],
                "target_lemma": w["target_lemma"],
                "gloss": w["gloss"],
                "pos": w["pos"],
                "topic": w["topic"],
                "priority": w["priority"],
                "status": w["status"],
                "card_path": w["card_path"],
                "created_at": w["created_at"],
                # Card text travels in the bundle so the personal course markdown
                # never has to be committed; the importer rewrites it on the other side.
                "card": wiki.read_word_card(w["slug"]) or "",
                "variations": variations,
                "reviews": reviews,
                "audio": dict(audio) if audio else None,
            }
            lines.append(json.dumps(record, ensure_ascii=False))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return out_path


def import_bundle(path: Path | None = None) -> int:
    """Upsert words from the bundle into the local DB. Returns count imported.

    Reviews already present (matched by interval_day) keep their local status —
    so the server's ``sent``/``done`` flags survive a re-import.
    """
    path = path or paths.SYNC_BUNDLE
    if not path.exists():
        return 0
    db.init()
    count = 0
    with db.connect() as conn:
        for raw in path.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            rec = json.loads(raw)
            count += 1
            existing = conn.execute(
                "SELECT id FROM words WHERE slug = ?", (rec["slug"],)
            ).fetchone()
            if existing:
                word_id = existing["id"]
                conn.execute(
                    "UPDATE words SET target_lemma=?, gloss=?, pos=?, topic=?, "
                    "priority=?, status=?, card_path=? WHERE id=?",
                    (rec["target_lemma"], rec["gloss"], rec["pos"], rec["topic"],
                     rec["priority"], rec["status"], rec["card_path"], word_id),
                )
            else:
                cur = conn.execute(
                    "INSERT INTO words(slug, target_lemma, gloss, pos, topic, "
                    "priority, status, card_path, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (rec["slug"], rec["target_lemma"], rec["gloss"], rec["pos"],
                     rec["topic"], rec["priority"], rec["status"], rec["card_path"],
                     rec["created_at"]),
                )
                word_id = int(cur.lastrowid)

            # Rewrite the local course card from the bundle (so the remote/agent
            # has the post text without the markdown being committed anywhere).
            if rec.get("card"):
                wiki.write_word_card(rec["slug"], rec["card"])

            # Replace variations (idempotent content).
            conn.execute("DELETE FROM variations WHERE word_id = ?", (word_id,))
            for v in rec.get("variations", []):
                conn.execute(
                    "INSERT INTO variations(word_id, idx, pt_sentence, gloss_sentence,"
                    " context_label) VALUES(?,?,?,?,?)",
                    (word_id, v["idx"], v["pt_sentence"], v["gloss_sentence"],
                     v.get("context_label", "")),
                )

            # Insert only missing reviews; never clobber local delivery status.
            for r in rec.get("reviews", []):
                has = conn.execute(
                    "SELECT id FROM reviews WHERE word_id=? AND interval_day=?",
                    (word_id, r["interval_day"]),
                ).fetchone()
                if not has:
                    conn.execute(
                        "INSERT INTO reviews(word_id, due_date, interval_day, status)"
                        " VALUES(?,?,?,?)",
                        (word_id, r["due_date"], r["interval_day"], "pending"),
                    )

            # Upsert latest audio file_id.
            audio = rec.get("audio")
            if audio and audio.get("telegram_file_id"):
                existing_audio = conn.execute(
                    "SELECT id FROM audio_assets WHERE word_id=? ORDER BY id DESC LIMIT 1",
                    (word_id,),
                ).fetchone()
                if existing_audio:
                    conn.execute(
                        "UPDATE audio_assets SET telegram_file_id=?, lang=?, duration=?"
                        " WHERE id=?",
                        (audio["telegram_file_id"], audio.get("lang", ""),
                         audio.get("duration", 0), existing_audio["id"]),
                    )
                else:
                    conn.execute(
                        "INSERT INTO audio_assets(word_id, lang, file_path, kind, "
                        "duration, telegram_file_id, created_at) VALUES(?,?,?,?,?,?,?)",
                        (word_id, audio.get("lang", ""), "", "lesson",
                         audio.get("duration", 0), audio["telegram_file_id"],
                         rec["created_at"]),
                    )
    return count
