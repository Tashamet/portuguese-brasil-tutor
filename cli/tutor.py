#!/usr/bin/env python3
"""portuguese-brasil-tutor — command-line tool.

The skill (SKILL.md) drives a learning session in Claude and calls these
subcommands via Bash to persist words, render audio, schedule reviews
(Ebbinghaus 2/7/30), keep the wiki-course in sync and deliver Telegram
reminders. See ``--help`` on any subcommand.

Word payload (for ``add-word``), JSON:
    {
      "lemma": "então",
      "gloss": "well / then / so",
      "pos": "adverb", "topic": "small-talk", "priority": 2,
      "card": "# ENTÃO\\n...markdown card...",
      "variations": [
        {"pt": "Então, o que você acha?",
         "gloss": "Well, what do you think?",
         "context": "Morning at work"},
        ... up to 10 ...
      ]
    }
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

# Allow running as a script (no package install).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import config, db, paths, sync, wiki  # noqa: E402
from core.content import build_segments  # noqa: E402
from core.models import AudioAsset, Variation, Word  # noqa: E402


def _load_payload(args) -> dict:
    if args.stdin:
        return json.loads(sys.stdin.read())
    if args.json:
        return json.loads(Path(args.json).read_text(encoding="utf-8"))
    raise SystemExit("provide --json PATH or --stdin")


def _parse_date(s: str | None) -> date:
    return date.fromisoformat(s) if s else date.today()


def _interface_lang() -> str:
    return (db.get_setting("interface_language") or config.interface_language()
            or "ru")


# --- Commands --------------------------------------------------------------

def cmd_setup(args) -> None:
    """Write/merge config + init DB and wiki scaffold."""
    import yaml
    paths.ensure_dirs()
    cfg = {}
    if paths.CONFIG_PATH.exists():
        cfg = yaml.safe_load(paths.CONFIG_PATH.read_text(encoding="utf-8")) or {}
    elif paths.CONFIG_EXAMPLE.exists():
        cfg = yaml.safe_load(paths.CONFIG_EXAMPLE.read_text(encoding="utf-8")) or {}

    if args.interface:
        cfg["interface_language"] = args.interface
    if args.tts:
        cfg.setdefault("tts", {})["provider"] = args.tts
    if args.profile:
        cfg["deployment_profile"] = args.profile
    if args.telegram_chat:
        cfg.setdefault("telegram", {})["chat_id"] = args.telegram_chat
    if args.enable_telegram:
        cfg.setdefault("telegram", {})["enabled"] = True

    paths.CONFIG_PATH.write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    config.reload()

    db.init()
    if args.interface:
        db.set_setting("interface_language", args.interface)
    wiki.ensure_scaffold(db.get_setting("interface_language"))
    print(f"Config written to {paths.CONFIG_PATH}")
    print("Telegram setup: get a bot token from @BotFather, set it as the env var")
    print("  TELEGRAM_BOT_TOKEN, and your chat_id via @userinfobot.")


def cmd_add_word(args) -> None:
    db.init()
    payload = _load_payload(args)
    today = _parse_date(args.today)
    lang = _interface_lang()

    slug = wiki.slugify(payload["lemma"])
    # 1. Write the wiki card (or a minimal one).
    card_md = payload.get("card") or _minimal_card(payload, slug)
    card_path = wiki.write_word_card(slug, card_md)

    # 2. Persist the word + variations + schedule.
    variations = [
        Variation(i, v["pt"], v.get("gloss", ""), v.get("context", ""))
        for i, v in enumerate(payload.get("variations", []))
    ]
    word = Word(
        slug=slug,
        target_lemma=payload["lemma"],
        gloss=payload.get("gloss", ""),
        pos=payload.get("pos", ""),
        topic=payload.get("topic", ""),
        priority=int(payload.get("priority", 3)),
        status=payload.get("status", "learning"),
        card_path=str(card_path.relative_to(paths.DATA)),
        variations=variations,
    )
    word_id = db.add_word(word, config.review_intervals(), today=today)
    word.id = word_id

    # 3. Render audio (unless suppressed).
    if not args.no_audio:
        _render_and_store_audio(word, lang, send_to_telegram=not args.no_telegram)

    # 4. Refresh wiki index + progress.
    _refresh_wiki(lang)
    print(json.dumps({"slug": slug, "word_id": word_id,
                      "card": str(card_path), "scheduled": config.review_intervals()},
                     ensure_ascii=False))


def cmd_gen_audio(args) -> None:
    db.init()
    word = db.get_word_by_slug(args.slug)
    if not word:
        raise SystemExit(f"no word '{args.slug}'")
    _render_and_store_audio(word, _interface_lang(),
                            send_to_telegram=not args.no_telegram)
    print(f"audio regenerated for {args.slug}")


def cmd_due_today(args) -> None:
    db.init()
    on = _parse_date(args.on)
    rows = db.due_reviews(on)
    if not rows:
        print("Nothing to review today." if not args.json_out else "[]")
        return
    if args.json_out:
        print(json.dumps(rows, ensure_ascii=False, default=str))
        return
    for r in rows:
        print(f"- [{r['interval_day']}d] {r['target_lemma']} — {r['gloss']} "
              f"(due {r['due_date']}) → course/words/{r['slug']}.md")


def cmd_send_due(args) -> None:
    db.init()
    from core import telegram
    on = _parse_date(args.on)
    chat_id = config.telegram_chat_id()
    if not config.telegram_enabled() or not chat_id:
        raise SystemExit("Telegram is disabled or chat_id missing (see /setup)")

    rows = db.due_reviews(on)
    sent = 0
    for r in rows:
        card = wiki.read_word_card(r["slug"]) or f"{r['target_lemma']} — {r['gloss']}"
        audio = db.latest_audio(r["id"])
        file_id = audio.telegram_file_id if audio else None
        ogg = None
        if not file_id and audio and audio.file_path:
            p = paths.DATA / audio.file_path
            ogg = p if p.exists() else None
        new_file_id = telegram.send_card_post(chat_id, card, ogg_path=ogg,
                                              file_id=file_id)
        if new_file_id and not file_id:
            db.set_audio_file_id(r["id"], new_file_id)
        db.mark_review(r["review_id"], "sent", when=on)
        sent += 1
    print(f"sent {sent} review(s)")


def cmd_context(args) -> None:
    """Dump the learner context for the skill to read at session start."""
    db.init()
    set_lang = db.get_setting("interface_language") or config.interface_language()
    has_words = bool(db.list_words())
    first_run = (not paths.PROFILE_MD.exists()) and (not has_words) and (not set_lang)
    lang = set_lang or "unset"
    out = [
        f"first_run: {'true' if first_run else 'false'}",
        f"interface_language: {lang}",
        "",
    ]
    if first_run:
        out.append("# No saved learner yet — run ONBOARDING (ask interface language first).")
        print("\n".join(out))
        return
    out += [f"# Tutor context (interface: {lang})", ""]
    if paths.PROFILE_MD.exists():
        out += ["## profile.md", paths.PROFILE_MD.read_text(encoding="utf-8"), ""]
    if paths.COURSE_PROGRESS.exists():
        out += ["## progress.md", paths.COURSE_PROGRESS.read_text(encoding="utf-8"), ""]
    sessions = wiki.recent_sessions(3)
    if sessions:
        out += ["## recent sessions", *sessions, ""]
    learned = [w.target_lemma for w in db.list_words("known")]
    learning = [w.target_lemma for w in db.list_words("learning")]
    out += ["## words", f"known: {', '.join(learned) or '—'}",
            f"learning: {', '.join(learning) or '—'}",
            f"due today: {len(db.due_reviews())}"]
    print("\n".join(out))


def cmd_log_session(args) -> None:
    text = sys.stdin.read() if args.stdin else (
        Path(args.file).read_text(encoding="utf-8") if args.file else args.text or "")
    if not text.strip():
        raise SystemExit("nothing to log (use --stdin, --file, or --text)")
    path = wiki.append_session(text)
    print(f"logged to {path}")


def cmd_stats(args) -> None:
    db.init()
    print(json.dumps(db.stats(), ensure_ascii=False, indent=2))


def cmd_commands(args) -> None:
    """Manage user hotkeys stored in journal/commands.md."""
    paths.ensure_dirs()
    md = paths.COMMANDS_MD
    lines = md.read_text(encoding="utf-8").splitlines() if md.exists() else \
        ["# Custom commands", "", "| alias | action |", "|---|---|"]
    if args.action == "add":
        lines.append(f"| {args.alias} | {args.target} |")
        md.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"added {args.alias} -> {args.target}")
    elif args.action == "remove":
        lines = [ln for ln in lines if not ln.startswith(f"| {args.alias} ")]
        md.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"removed {args.alias}")
    else:  # list
        print("\n".join(lines))


def cmd_export(args) -> None:
    db.init()
    path = sync.export_bundle()
    print(f"exported bundle -> {path}")


def cmd_import(args) -> None:
    n = sync.import_bundle(Path(args.file) if args.file else None)
    print(f"imported {n} word(s)")


def cmd_deploy(args) -> None:
    from deploy import remote
    remote.deploy_ssh(args.ssh, send_time=args.send_time)


# --- Helpers ---------------------------------------------------------------

def _render_and_store_audio(word: Word, lang: str, send_to_telegram: bool) -> None:
    from core.tts.factory import get_adapter
    adapter = get_adapter()
    out = paths.AUDIO_DIR / f"{word.slug}.ogg"
    segments = build_segments(word, lang)
    dur = adapter.synthesize(segments, out)
    asset = AudioAsset(word_id=word.id, lang=lang,
                       file_path=str(out.relative_to(paths.DATA)),
                       kind="lesson", duration=dur)
    db.save_audio(asset)
    if send_to_telegram and config.telegram_enabled() and config.telegram_chat_id():
        from core import telegram
        file_id = telegram.upload_voice(config.telegram_chat_id(), out,
                                        caption=word.target_lemma)
        db.set_audio_file_id(word.id, file_id)


def _refresh_wiki(lang: str) -> None:
    wiki.rebuild_index(lang)
    s = db.stats()
    known = s["by_status"].get("known", 0)
    learning = s["by_status"].get("learning", 0)
    stage = db.get_setting("current_stage", "")
    wiki.update_progress(stage, known, learning, s["due_today"])


def _minimal_card(payload: dict, slug: str) -> str:
    lines = [f"# {payload['lemma'].upper()}", "",
             f"**{payload.get('gloss', '')}**", ""]
    for v in payload.get("variations", []):
        ctx = f" _( {v['context']} )_" if v.get("context") else ""
        lines.append(f"- {v['pt']} — {v.get('gloss', '')}{ctx}")
    if payload.get("topic"):
        lines += ["", f"Related: [[themes/{wiki.slugify(payload['topic'])}]], [[index]]"]
    return "\n".join(lines)


# --- Argument parsing ------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tutor", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("setup", help="write config + init db/wiki")
    s.add_argument("--interface", choices=["ru", "en", "uk"])
    s.add_argument("--tts", choices=["system", "local", "cloud"])
    s.add_argument("--profile", choices=["skill-only", "local-notifier", "remote-notifier"])
    s.add_argument("--telegram-chat")
    s.add_argument("--enable-telegram", action="store_true")
    s.set_defaults(func=cmd_setup)

    s = sub.add_parser("add-word", help="add a word (+variations, audio, schedule)")
    s.add_argument("--json"); s.add_argument("--stdin", action="store_true")
    s.add_argument("--today", help="override 'today' (YYYY-MM-DD) for testing")
    s.add_argument("--no-audio", action="store_true")
    s.add_argument("--no-telegram", action="store_true")
    s.set_defaults(func=cmd_add_word)

    s = sub.add_parser("gen-audio", help="regenerate audio for a slug")
    s.add_argument("slug"); s.add_argument("--no-telegram", action="store_true")
    s.set_defaults(func=cmd_gen_audio)

    s = sub.add_parser("due-today", help="list reviews due")
    s.add_argument("--on", help="date (YYYY-MM-DD), default today")
    s.add_argument("--json-out", action="store_true")
    s.set_defaults(func=cmd_due_today)

    s = sub.add_parser("send-due", help="deliver due reviews to Telegram")
    s.add_argument("--on"); s.set_defaults(func=cmd_send_due)

    s = sub.add_parser("context", help="dump learner context for the skill")
    s.set_defaults(func=cmd_context)

    s = sub.add_parser("log-session", help="append to today's session log")
    s.add_argument("--stdin", action="store_true"); s.add_argument("--file")
    s.add_argument("--text"); s.set_defaults(func=cmd_log_session)

    s = sub.add_parser("stats", help="progress stats (json)")
    s.set_defaults(func=cmd_stats)

    s = sub.add_parser("commands", help="manage user hotkeys")
    s.add_argument("action", choices=["list", "add", "remove"], nargs="?", default="list")
    s.add_argument("alias", nargs="?"); s.add_argument("target", nargs="?")
    s.set_defaults(func=cmd_commands)

    s = sub.add_parser("export", help="export git sync bundle")
    s.set_defaults(func=cmd_export)
    s = sub.add_parser("import", help="import git sync bundle")
    s.add_argument("--file"); s.set_defaults(func=cmd_import)

    s = sub.add_parser("deploy", help="provision a remote notifier over SSH")
    s.add_argument("--ssh", required=True, help="user@host")
    s.add_argument("--send-time", default="09:00")
    s.set_defaults(func=cmd_deploy)

    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
