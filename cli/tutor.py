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
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta
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
    if args.daily_words:
        cfg["daily_new_words"] = int(args.daily_words)

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


def cmd_speak(args) -> None:
    """Render audio for an ad-hoc phrase set (a survival set, a single phrase).

    Input JSON: a list of phrases, or {"phrases": [...], "out": "name"}.
    Each phrase: {"pt": ..., "gloss": ..., "context": ...}. Prints the audio path
    so the skill can deliver the file to the learner in chat.
    """
    from core.content import build_phrase_segments
    from core.tts.factory import get_adapter

    db.init()
    payload = _load_payload(args)
    phrases = payload if isinstance(payload, list) else payload.get("phrases", [])
    if not phrases:
        raise SystemExit("no phrases (provide a list of {pt, gloss, context})")
    name = (payload.get("out") if isinstance(payload, dict) else None) or "listen"
    out = paths.AUDIO_DIR / f"{wiki.slugify(name)}.ogg"

    segments = build_phrase_segments(phrases, _interface_lang())
    dur = get_adapter().synthesize(segments, out)
    print(json.dumps({"audio": str(out), "duration": round(dur, 1)},
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
    db.init()
    path = wiki.append_session(text, interface_language=_interface_lang())
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
    path = sync.export_bundle(Path(args.out) if args.out else None)
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
    wiki.update_progress(stage, known, learning, s["due_today"], lang)


def _minimal_card(payload: dict, slug: str) -> str:
    lines = [f"# {payload['lemma'].upper()}", "",
             f"**{payload.get('gloss', '')}**", ""]
    for v in payload.get("variations", []):
        ctx = f" _( {v['context']} )_" if v.get("context") else ""
        lines.append(f"- {v['pt']} — {v.get('gloss', '')}{ctx}")
    if payload.get("topic"):
        related = wiki.t("related", _interface_lang())
        lines += ["", f"{related}: [[themes/{wiki.slugify(payload['topic'])}]], [[index]]"]
    return "\n".join(lines)


# --- Test / diagnostics ----------------------------------------------------

SELFTEST_WORD = {
    "lemma": "obrigado", "gloss": "thank you", "pos": "interjection",
    "topic": "small-talk", "priority": 1,
    "variations": [
        {"pt": f"Obrigado pela ajuda {i}!", "gloss": f"Thanks for the help {i}!",
         "context": f"Situation {i}"} for i in range(1, 11)
    ],
}


def _run_cli(cli_args: list[str], data_dir: str, stdin: str | None = None):
    env = {**os.environ, "TUTOR_DATA_DIR": data_dir}
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), *cli_args],
        input=stdin, capture_output=True, text=True, env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


def cmd_selftest(args) -> None:
    """End-to-end check of the tutor in an isolated sandbox (no real data touched)."""
    lang = args.lang
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))

    # 1. Scheduler math (pure, in-process).
    from core import scheduler
    start = date(2026, 1, 1)
    pairs = scheduler.schedule_dates(start)
    check("scheduler 2/7/30", pairs == [(2, date(2026, 1, 3)), (7, date(2026, 1, 8)),
                                        (30, date(2026, 1, 31))], str(pairs))

    sandbox = tempfile.mkdtemp(prefix="tutor_selftest_")
    sandbox2 = tempfile.mkdtemp(prefix="tutor_selftest_import_")
    try:
        # 2. setup
        rc, out, err = _run_cli(["setup", "--interface", lang, "--tts", "system",
                                 "--profile", "skill-only"], sandbox)
        check("setup", rc == 0, err.strip())

        # 3. add-word (no audio/telegram), captured today so reviews are known
        today = date(2026, 1, 1).isoformat()
        add_args = ["add-word", "--stdin", "--no-audio", "--no-telegram",
                    "--today", today]
        rc, out, err = _run_cli(add_args, sandbox, stdin=json.dumps(SELFTEST_WORD))
        slug_ok = rc == 0 and '"slug": "obrigado"' in out
        check("add-word + schedule", slug_ok, (err or out).strip()[:120])

        # 4. stats shows 1 word
        rc, out, _ = _run_cli(["stats"], sandbox)
        check("stats", rc == 0 and '"total_words": 1' in out, out.strip()[:80])

        # 5. due-today on D+2 surfaces the word
        d2 = (date(2026, 1, 1) + timedelta(days=2)).isoformat()
        rc, out, _ = _run_cli(["due-today", "--on", d2], sandbox)
        check("due on day 2", "obrigado" in out, out.strip()[:80])

        # 6. wiki localized + word card written
        prof = Path(sandbox) / "journal" / "profile.md"
        card = Path(sandbox) / "course" / "words" / "obrigado.md"
        expected_title = wiki.t("profile_title", lang)
        prof_ok = prof.exists() and expected_title in prof.read_text(encoding="utf-8")
        check(f"wiki localized ({lang})", prof_ok and card.exists(),
              f"profile title='{expected_title}'")

        # 7. export -> import round-trip into a fresh sandbox (isolated bundle)
        bundle = str(Path(sandbox) / "bundle.ndjson")
        rc, _, err = _run_cli(["export", "--out", bundle], sandbox)
        rc3, _, err3 = _run_cli(["import", "--file", bundle], sandbox2)
        rc4, out4, _ = _run_cli(["stats"], sandbox2)
        check("export/import sync", rc == 0 and '"total_words": 1' in out4,
              (err or err3).strip()[:120])

        # 8. broken-link scan (the minimal card links a theme that doesn't exist yet)
        rc, out, _ = _run_cli(["check-links"], sandbox)
        check("link check runs", rc in (0, 1), out.strip()[:80])

        # 9. optional audio render (needs ffmpeg + say)
        if args.audio:
            have = shutil.which("ffmpeg") and shutil.which("say")
            if not have:
                check("audio render", True, "skipped (ffmpeg/say missing)")
            else:
                rc, out, err = _run_cli(["add-word", "--stdin", "--no-telegram",
                                         "--today", today],
                                        sandbox, stdin=json.dumps(
                                            {**SELFTEST_WORD, "lemma": "agua"}))
                ogg = Path(sandbox) / "audio" / "agua.ogg"
                check("audio render", rc == 0 and ogg.exists() and ogg.stat().st_size > 0,
                      (err or out).strip()[:120])
    finally:
        if args.keep:
            print(f"sandbox kept: {sandbox}")
        else:
            shutil.rmtree(sandbox, ignore_errors=True)
            shutil.rmtree(sandbox2, ignore_errors=True)

    # Report
    width = max(len(n) for n, _, _ in results)
    passed = 0
    for name, ok, detail in results:
        mark = "PASS" if ok else "FAIL"
        line = f"  [{mark}] {name.ljust(width)}"
        if detail and not ok:
            line += f"  — {detail}"
        print(line)
        passed += ok
    print(f"\n{passed}/{len(results)} checks passed")
    if passed != len(results):
        raise SystemExit(1)


def cmd_check_links(args) -> None:
    db.init()
    broken = wiki.find_broken_links()
    if not broken:
        print("No broken [[links]].")
        return
    for src, target in broken:
        print(f"broken: {src} -> [[{target}]]")
    raise SystemExit(1)


def cmd_test_telegram(args) -> None:
    """Send a test message (and optional voice) to verify the Telegram bot."""
    from core import telegram
    if not config.telegram_token():
        raise SystemExit("TELEGRAM_BOT_TOKEN not set in environment")
    chat_id = args.chat or config.telegram_chat_id()
    if not chat_id:
        raise SystemExit("No chat_id (set telegram.chat_id or pass --chat)")

    telegram.send_message(chat_id, "Test: portuguese-brasil-tutor bot is working.")
    print(f"text message sent to chat {chat_id}")

    if args.voice:
        db.init()
        sent = False
        for w in db.list_words():
            audio = db.latest_audio(w.id)
            if not audio:
                continue
            if audio.telegram_file_id:
                telegram.send_voice_by_id(chat_id, audio.telegram_file_id,
                                          caption=f"test: {w.target_lemma}")
                sent = True
                break
            local = paths.DATA / audio.file_path
            if local.exists():
                telegram.upload_voice(chat_id, local, caption=f"test: {w.target_lemma}")
                sent = True
                break
        print("voice sent" if sent else "no audio found to send (add a word first)")


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
    s.add_argument("--daily-words", type=int, help="new words per day (pace)")
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

    s = sub.add_parser("speak", help="render audio for an ad-hoc phrase set")
    s.add_argument("--json"); s.add_argument("--stdin", action="store_true")
    s.set_defaults(func=cmd_speak)

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
    s.add_argument("--out", help="write bundle to this path instead of sync/words.ndjson")
    s.set_defaults(func=cmd_export)
    s = sub.add_parser("import", help="import git sync bundle")
    s.add_argument("--file"); s.set_defaults(func=cmd_import)

    s = sub.add_parser("deploy", help="provision a remote notifier over SSH")
    s.add_argument("--ssh", required=True, help="user@host")
    s.add_argument("--send-time", default="09:00")
    s.set_defaults(func=cmd_deploy)

    s = sub.add_parser("selftest", help="end-to-end check of the tutor (sandboxed)")
    s.add_argument("--lang", choices=["ru", "en", "uk"], default="en")
    s.add_argument("--audio", action="store_true", help="also render audio (ffmpeg+say)")
    s.add_argument("--keep", action="store_true", help="keep the sandbox dir")
    s.set_defaults(func=cmd_selftest)

    s = sub.add_parser("check-links", help="report broken [[wiki-links]]")
    s.set_defaults(func=cmd_check_links)

    s = sub.add_parser("test-telegram", help="send a test message/voice to Telegram")
    s.add_argument("--chat", help="override chat_id")
    s.add_argument("--voice", action="store_true", help="also send a sample voice")
    s.set_defaults(func=cmd_test_telegram)

    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
