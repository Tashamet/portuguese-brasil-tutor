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
      "pronunciation": "então -> tão -> 'in-towng'",
      "card": "# ENTÃO\\n...comprehensive markdown card (superset of the audio)...",
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
    if args.name:
        cfg["student_name"] = args.name
    if args.study_time:
        cfg.setdefault("lessons", {})["time"] = args.study_time
    if args.study_days:
        cfg.setdefault("lessons", {})["days"] = args.study_days
    if args.cloud_engine:
        cfg.setdefault("tts", {}).setdefault("cloud", {})["engine"] = args.cloud_engine
    if args.cloud_voice:
        cfg.setdefault("tts", {}).setdefault("cloud", {})["voice_pt"] = args.cloud_voice
    if args.api_key:
        cfg.setdefault("tts", {}).setdefault("cloud", {})["api_key"] = args.api_key

    paths.CONFIG_PATH.write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    config.reload()

    db.init()
    if args.interface:
        db.set_setting("interface_language", args.interface)
    if args.name:
        db.set_setting("student_name", args.name)
    wiki.ensure_scaffold(db.get_setting("interface_language"))
    # Remember this profile as the default for future (non-prefixed) sessions.
    paths.set_active_profile(paths.active_profile())
    print(f"Profile: {paths.active_profile()}")
    print(f"Student data dir: {paths.DATA}")
    print(f"Config written to: {paths.CONFIG_PATH}")
    print("Telegram setup: get a bot token from @BotFather, set it as the env var")
    print("  TELEGRAM_BOT_TOKEN, and your chat_id via @userinfobot.")


def cmd_add_word(args) -> None:
    db.init()
    payload = _load_payload(args)
    today = _parse_date(args.today)
    lang = _interface_lang()

    slug = wiki.slugify(payload["lemma"])
    # 1. Write the wiki card. Always guarantee the card is a SUPERSET of the
    #    audio: every phrase that goes into the recording is recorded in the .md.
    card_md = payload.get("card") or _minimal_card(payload, slug)
    card_md = _ensure_phrases_in_card(card_md, payload, lang)
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


def cmd_notify(args) -> None:
    """One-shot delivery entry point used by cron, launchd, and scheduled agents.

    In git sync mode it first pulls + imports the latest words, then delivers
    today's due reviews to Telegram. This is what a remote notifier or a
    scheduled Claude agent runs daily.
    """
    db.init()
    if config.sync_mode() == "git" and not args.no_pull:
        # In git mode the STUDENT DATA dir is the synced repo (not the code).
        if (paths.DATA / ".git").exists():
            proc = subprocess.run(["git", "-C", str(paths.DATA), "pull", "--ff-only"],
                                  capture_output=True, text=True)
            if proc.returncode != 0:
                print(f"git pull failed: {proc.stderr.strip()}", file=sys.stderr)
        sync.import_bundle()
    # Lesson nudge on study days (separate from the due-word posts below).
    on = _parse_date(args.on)
    if (not args.no_lesson and config.lesson_reminders_enabled()
            and config.is_study_day(on)):
        try:
            cmd_lesson_reminder(args)
        except SystemExit as e:
            print(f"lesson reminder skipped: {e}", file=sys.stderr)
    cmd_send_due(args)


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
    name = config.student_name() or (db.get_setting("student_name") or "")
    nl = db.next_lesson()
    due = len(db.due_reviews())
    out += [
        f"# Tutor context (interface: {lang})",
        f"student_name: {name or '—'}",
        f"next_lesson: {nl['topic'] if nl else '—'}",
        f"due_reviews_today: {due}",
        "# Greeting: address the student by name. If due_reviews_today > 0, offer to"
        " review first; else if next_lesson is set, announce that topic; else just start.",
        "",
    ]
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


def cmd_profiles(args) -> None:
    """List student profiles and where their data lives."""
    print(json.dumps({
        "home": str(paths.TUTOR_HOME),
        "active": paths.active_profile(),
        "active_dir": str(paths.DATA),
        "profiles": paths.list_profiles(),
    }, ensure_ascii=False, indent=2))


def cmd_use(args) -> None:
    """Set the default student profile for future sessions."""
    prof = paths.set_active_profile(args.name)
    print(f"active profile: {prof} -> {paths.STUDENTS_DIR / prof}")
    print("Tip: prefix a command with TUTOR_PROFILE=<name> to target a profile "
          "for one call without changing the default.")


def cmd_set_home(args) -> None:
    """Choose where the course folder lives; optionally move existing data there."""
    new = Path(args.path).expanduser().resolve()
    old = paths.TUTOR_HOME.resolve()
    new.mkdir(parents=True, exist_ok=True)
    if args.migrate and old != new and old.exists() and any(old.iterdir()):
        for item in old.iterdir():
            target = new / item.name
            if target.exists():
                print(f"skip (exists): {target}")
                continue
            shutil.move(str(item), str(target))
        print(f"moved existing data: {old} -> {new}")
        # Leave a breadcrumb so a stale hidden folder isn't confusing.
        try:
            if not any(old.iterdir()):
                old.rmdir()
        except OSError:
            pass
    paths.set_tutor_home(new)
    print(f"Course folder is now: {new}")
    print("Open it in Finder or as an Obsidian vault to browse your course.")


def cmd_set_plan(args) -> None:
    """Store the multi-lesson plan and render course/plan.md.

    Input JSON: a list of lessons, or {"lessons": [...]}. Each lesson:
    {"topic": ..., "notes": ...}. Pass the FULL plan (several lessons ahead).
    """
    db.init()
    payload = _load_payload(args)
    lessons = payload if isinstance(payload, list) else payload.get("lessons", [])
    if not lessons:
        raise SystemExit("no lessons (provide a list of {topic, notes})")
    db.set_lessons(lessons)
    lang = _interface_lang()
    paths.ensure_dirs()
    lines = [f"# {wiki.t('learning_plan', lang)}", ""]
    for i, le in enumerate(lessons, 1):
        slug = wiki.slugify(le["topic"])
        notes = f" — {le['notes']}" if le.get("notes") else ""
        lines.append(f"{i}. [[themes/{slug}|{le['topic']}]]{notes}")
        # Front-load a theme stub so the wiki shows the whole arc, linked, from
        # day one. Don't clobber a theme the tutor already filled in.
        theme = paths.THEMES_DIR / f"{slug}.md"
        if not theme.exists():
            theme.write_text(
                f"# {le['topic']}\n\n_{wiki.t('learning_plan', lang)} · #{i}_\n\n"
                f"{le.get('notes', '')}\n\n## {wiki.t('words', lang)}\n\n_—_\n\n"
                f"{wiki.t('related', lang)}: [[plan]], [[index]]\n",
                encoding="utf-8")
    lines += ["", f"{wiki.t('related', lang)}: [[index]], [[progress]]"]
    paths.COURSE_PLAN.write_text("\n".join(lines) + "\n", encoding="utf-8")
    wiki.rebuild_index(lang)
    print(f"stored {len(lessons)} lessons; themes scaffolded → {paths.COURSE_PLAN}")


def cmd_lesson_done(args) -> None:
    """Mark a lesson complete so the plan advances (default: the next one)."""
    db.init()
    idx = args.idx
    if idx is None:
        nl = db.next_lesson()
        if not nl:
            print("no planned lesson to complete")
            return
        idx = nl["idx"]
    db.mark_lesson_done(int(idx))
    nxt = db.next_lesson()
    print(f"lesson {idx} done; next: {nxt['topic'] if nxt else '— (plan finished)'}")


def cmd_lesson_reminder(args) -> None:
    """Send the Telegram lesson nudge (greeting + today's topic + review count)."""
    db.init()
    from core import content, telegram
    chat_id = config.telegram_chat_id()
    if not config.telegram_enabled() or not chat_id:
        raise SystemExit("Telegram is disabled or chat_id missing (see /setup)")
    lang = _interface_lang()
    name = config.student_name() or (db.get_setting("student_name") or "")
    nl = db.next_lesson()
    topic = nl["topic"] if nl else ""
    due = len(db.due_reviews(_parse_date(args.on)))
    telegram.send_message(chat_id, content.lesson_reminder_text(name, topic, due, lang))
    print("lesson reminder sent")


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
    data_repo = args.data_repo or config.get("sync.git.repo_url", "")
    remote.deploy_ssh(args.ssh, send_time=args.send_time, data_repo=data_repo)


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


def _phrases_section(payload: dict, lang: str) -> str:
    """A complete, numbered list of every phrase that goes into the audio."""
    lines = [f"## {wiki.t('audio_phrases', lang)}", ""]
    for i, v in enumerate(payload.get("variations", []), 1):
        ctx = f"  _{v['context']}_" if v.get("context") else ""
        gloss = f" — {v['gloss']}" if v.get("gloss") else ""
        lines.append(f"{i}. **{v['pt']}**{gloss}{ctx}")
    return "\n".join(lines)


def _ensure_phrases_in_card(card_md: str, payload: dict, lang: str) -> str:
    """Append the complete phrase list unless the card already contains them all.

    Guarantees the .md is a superset of the audio — no phrase the learner hears
    is missing from the written card.
    """
    variations = payload.get("variations", [])
    if not variations:
        return card_md
    if all(v.get("pt") and v["pt"] in card_md for v in variations):
        return card_md  # the card already lists every phrase
    out = card_md.rstrip() + "\n\n" + _phrases_section(payload, lang) + "\n"
    if payload.get("topic") and "[[themes/" not in card_md:
        related = wiki.t("related", lang)
        out += f"\n{related}: [[themes/{wiki.slugify(payload['topic'])}]], [[index]]\n"
    return out


def _minimal_card(payload: dict, slug: str) -> str:
    lang = _interface_lang()
    lines = [f"# {payload['lemma'].upper()}", ""]
    if payload.get("gloss"):
        lines += [f"**{wiki.t('meaning', lang)}:** {payload['gloss']}", ""]
    if payload.get("pronunciation"):
        lines += [f"_{payload['pronunciation']}_", ""]
    if payload.get("topic"):
        related = wiki.t("related", lang)
        lines += [f"{related}: [[themes/{wiki.slugify(payload['topic'])}]], [[index]]"]
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


def _engine_available(provider: str) -> bool:
    if provider == "system":
        return bool(shutil.which("say"))
    if provider == "local":
        return subprocess.run([sys.executable, "-c", "import piper"],
                              capture_output=True).returncode == 0
    if provider == "cloud":
        return bool(os.environ.get("ELEVENLABS_API_KEY")
                    or os.environ.get("OPENAI_API_KEY"))
    return False


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
        # 2. setup (use the requested voice engine; default Piper)
        rc, out, err = _run_cli(["setup", "--interface", lang, "--tts", args.tts,
                                 "--name", "Tester", "--study-days", "mon,wed,fri",
                                 "--study-time", "19:00", "--profile", "skill-only"],
                                sandbox)
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

        # 9. multi-lesson plan + greeting context (name + next lesson)
        plan = json.dumps({"lessons": [{"topic": "Café"}, {"topic": "Transport"}]})
        rc, _, err = _run_cli(["set-plan", "--stdin"], sandbox, stdin=plan)
        rc2, ctx, _ = _run_cli(["context"], sandbox)
        check("plan + greeting context",
              rc == 0 and "student_name: Tester" in ctx and "next_lesson: Café" in ctx,
              (err or ctx).strip()[:120])

        # 10. optional audio render with the configured engine
        if args.audio:
            engine_ok = bool(shutil.which("ffmpeg")) and _engine_available(args.tts)
            if not engine_ok:
                check(f"audio render ({args.tts})", True,
                      "skipped (ffmpeg or voice engine unavailable)")
            else:
                rc, out, err = _run_cli(["add-word", "--stdin", "--no-telegram",
                                         "--today", today],
                                        sandbox, stdin=json.dumps(
                                            {**SELFTEST_WORD, "lemma": "agua"}))
                ogg = Path(sandbox) / "audio" / "agua.ogg"
                check(f"audio render ({args.tts})",
                      rc == 0 and ogg.exists() and ogg.stat().st_size > 0,
                      (err or out).strip()[:160])
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
    s.add_argument("--profile", choices=["skill-only", "local-notifier",
                                         "remote-notifier", "scheduled-agent"])
    s.add_argument("--telegram-chat")
    s.add_argument("--enable-telegram", action="store_true")
    s.add_argument("--daily-words", type=int, help="new words per day (pace)")
    s.add_argument("--name", help="student's name (for greetings)")
    s.add_argument("--study-time", help="lesson reminder time HH:MM")
    s.add_argument("--study-days", help="study days: daily or e.g. mon,wed,fri")
    s.add_argument("--cloud-engine", choices=["elevenlabs", "openai"],
                   help="cloud TTS engine (with --tts cloud)")
    s.add_argument("--cloud-voice", help="ElevenLabs voice id / OpenAI voice name")
    s.add_argument("--api-key", help="ElevenLabs/OpenAI key to store in config")
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

    s = sub.add_parser("notify", help="pull+import (git mode), lesson nudge, send due reviews")
    s.add_argument("--on"); s.add_argument("--no-pull", action="store_true")
    s.add_argument("--no-lesson", action="store_true", help="skip the lesson reminder")
    s.set_defaults(func=cmd_notify)

    s = sub.add_parser("set-plan", help="store the multi-lesson plan (+ render plan.md)")
    s.add_argument("--json"); s.add_argument("--stdin", action="store_true")
    s.set_defaults(func=cmd_set_plan)

    s = sub.add_parser("lesson-done", help="mark a lesson complete (plan advances)")
    s.add_argument("--idx", type=int, help="lesson index (default: next planned)")
    s.set_defaults(func=cmd_lesson_done)

    s = sub.add_parser("lesson-reminder", help="send the Telegram lesson nudge")
    s.add_argument("--on"); s.set_defaults(func=cmd_lesson_reminder)

    s = sub.add_parser("context", help="dump learner context for the skill")
    s.set_defaults(func=cmd_context)

    s = sub.add_parser("log-session", help="append to today's session log")
    s.add_argument("--stdin", action="store_true"); s.add_argument("--file")
    s.add_argument("--text"); s.set_defaults(func=cmd_log_session)

    s = sub.add_parser("stats", help="progress stats (json)")
    s.set_defaults(func=cmd_stats)

    s = sub.add_parser("profiles", help="list student profiles and data locations")
    s.set_defaults(func=cmd_profiles)

    s = sub.add_parser("use", help="set the default student profile")
    s.add_argument("name"); s.set_defaults(func=cmd_use)

    s = sub.add_parser("set-home", help="choose where the course folder lives")
    s.add_argument("path", help="e.g. ~/Documents/PortugueseTutor")
    s.add_argument("--migrate", action="store_true", help="move existing data there")
    s.set_defaults(func=cmd_set_home)

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
    s.add_argument("--data-repo", help="private data-repo URL (else sync.git.repo_url)")
    s.set_defaults(func=cmd_deploy)

    s = sub.add_parser("selftest", help="end-to-end check of the tutor (sandboxed)")
    s.add_argument("--lang", choices=["ru", "en", "uk"], default="en")
    s.add_argument("--tts", choices=["local", "system", "cloud"], default="local")
    s.add_argument("--audio", action="store_true", help="also render audio")
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
