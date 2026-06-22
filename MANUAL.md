# portuguese-brasil-tutor — Manual

A complete guide to how the skill works, how data flows, every command, and how
to deploy each profile.

---

## 1. Concept

A Claude **skill** teaches Brazilian Portuguese to a zero-level learner living
in Brazil. It explains in the learner's chosen **interface language** (English,
Ukrainian, or Russian) while the **target** is always Brazilian Portuguese.

The guiding principle:

> **Claude (in the skill session) authors the content. A tiny toolkit stores,
> renders and delivers it.**

So everything intelligent — word choice, the 10 contextual example sentences,
the cultural card, the audio script, finding real culture links — happens inside
Claude. The toolkit (`cli/tutor.py`) only persists to SQLite, writes Markdown,
renders audio with a TTS engine, and (optionally) pushes a reminder to Telegram.
The only thing that ever runs **outside** Claude is a small cron job that
delivers due reviews.

---

## 2. Architecture at a glance

```
┌─────────────────────────── Claude session (the skill) ───────────────────────────┐
│  SKILL.md  →  drives the lesson, calls the CLI via Bash                            │
│  references/  teaching-method.md · audio-script-format.md · interface/{en,uk,ru}   │
└───────────────────────────────────────────────────────────────────────────────────┘
                                   │ python3 cli/tutor.py ...
                                   ▼
┌─────────────────────────────── core/ (no LLM) ───────────────────────────────────┐
│  db.py        SQLite engine: words, variations, reviews, audio_assets, settings   │
│  scheduler.py Ebbinghaus intervals (day 2 / 7 / 30)                               │
│  wiki.py      Markdown course + journal, [[wiki-links]], index/progress           │
│  content.py   builds the 2-4 min audio script from a word + its variations        │
│  tts/         pluggable: system (macOS say) | local (Piper) | cloud (EL/OpenAI)   │
│  telegram.py  outbound Bot API: sendVoice, reuse by file_id                       │
│  sync.py      git-mode export/import (text bundle)                                │
└───────────────────────────────────────────────────────────────────────────────────┘
                                   │
            ┌──────────────────────┴───────────────────────┐
            ▼                                               ▼
  data/ (SQLite + Markdown)                       notifier/send_due.py
  the source of truth + the wiki                  (cron: pull → import → send)
```

---

## 3. Data model

### Where data lives — code vs student profiles

The skill folder is **code only**. Each student's data lives **outside** it, in a
**visible course folder you choose** (asked on first run, e.g.
`~/Documents/PortugueseTutor`), one isolated folder per student:

```
<course folder>/students/<profile>/
    config.yaml  tutor.db  audio/  course/  journal/  sync/
```

The course folder location resolves from `TUTOR_HOME` (env, wins) → a one-line
pointer at `~/.config/portuguese-brasil-tutor/home` (written by `set-home`) →
default `~/PortugueseTutor`. Choose/move it with
`tutor.py set-home "<path>" [--migrate]`. The active student comes from
`TUTOR_PROFILE` (or the `active_profile` pointer); `TUTOR_DATA_DIR` overrides
with an explicit path (sync checkouts, selftest). Manage with `tutor.py profiles`
(list) and `tutor.py use <name>` (set default). Paths below are relative to a
profile's data dir.

Open a profile folder as an **[Obsidian](https://obsidian.md) vault** to browse
the course — the `[[wiki-links]]` render as a navigable graph.


### SQLite — `tutor.db` (the spaced-repetition engine)

Queryable, schedule-critical state. This is what the notifier reads.

| Table | Key columns | Purpose |
|---|---|---|
| `settings` | `key, value` | interface language, etc. |
| `words` | `slug, target_lemma, gloss, pos, topic, priority, status, card_path` | one row per learned word |
| `variations` | `word_id, idx, pt_sentence, gloss_sentence, context_label` | the 10 example sentences |
| `audio_assets` | `word_id, file_path, duration, telegram_file_id` | rendered audio + Telegram id |
| `reviews` | `word_id, due_date, interval_day, status` | the 2/7/30 schedule |

`status` on a word: `new → learning → known`.
`status` on a review: `pending → sent → done`.

### Markdown — the wiki you read

`data/course/` (the course, cross-linked with `[[wiki-links]]`):

```
index.md            hub: interface language, current stage, links to everything
plan.md             the agreed learning plan (stages → themes → priorities)
progress.md         where you are: stage, words known/learning, due today
words/{slug}.md     the word card (meanings, idioms, reductions, culture links)
grammar/{topic}.md  grammar nodes referenced by words
themes/{topic}.md   theme nodes (market, transport, doctor…)
```

`data/journal/` (Claude's working memory):

```
profile.md              diagnostics, region, pace, goals, panic zones
sessions/YYYY-MM-DD.md  session logs (link the words covered)
commands.md             your custom hotkeys (alias → action)
```

The whole wiki is written in the chosen interface language: section titles and
field labels (index, plan, progress, profile, session headers) are localized for
`en` / `ru` / `uk`, and Claude authors the word cards and session notes in that
language too.

**Why split SQLite + Markdown?** The Ebbinghaus engine needs indexed
"what's due today" queries and a stable schema (SQLite). The course and journal
are narrative, read by humans and by Claude, edited by hand — Markdown is native
there. MongoDB was rejected: it adds an always-on server that breaks the
"nothing runs" profile and complicates config distribution.

**Audio bytes** live in `data/audio/*.ogg` locally and, once uploaded, inside
Telegram's CDN (referenced by `telegram_file_id`). They are **not** committed to
git.

---

## 4. The learning loop

1. **First run (onboarding)** — the tutor walks you through it transparently:
   it asks your interface language, explains what the skill is and how it works,
   asks whether you want it **with or without the Telegram bot**, asks your work
   format (pace, focus, audio voice), runs a short survival diagnostic, agrees a
   plan with you, and only then configures and starts. Nothing is set up
   silently. See the ONBOARDING section in `SKILL.md`.
2. **Returning** — `tutor.py context` returns the saved profile, progress, recent
   sessions and word lists. Claude continues where you left off and surfaces
   what's due today.
3. **A new word** — Claude writes a rich card, 10 contextual variations (each in
   a different time/place), finds real culture links via web search, then calls
   `tutor.py add-word`. That single call:
   - writes `data/course/words/{slug}.md`,
   - inserts the word + variations into SQLite,
   - schedules reviews at **day 2, 7, 30**,
   - renders the **2-4 min audio lesson** (intro → word slow+natural → 10
     variations, each pt natural + pt slow + gloss → quick recap),
   - if Telegram is on, uploads the audio once and stores its `file_id`,
   - rebuilds `index.md` and `progress.md`.
4. **Reviews** — on day 2/7/30 the word is "due". Inside Claude you drill it
   with `/review`; with a notifier configured, a Telegram post arrives
   automatically (card text + voice).
5. **Session end** — `tutor.py log-session` appends what you covered.

### Lessons, plan, and reminders

Onboarding also captures the **student's name**, a **study schedule** (how often
and at what time), and a **full multi-lesson plan** (themes several lessons
ahead, stored with `set-plan`). From these:

- **Session greeting** — `context` returns `student_name`, the `next_lesson`
  topic, and `due_reviews_today`. The tutor greets by name and either reviews
  first (if anything is due), announces today's planned topic, or just starts.
- **Lesson reminders** — separate from the word-review posts. On a study day at
  the study time, the notifier (`notify`, or `lesson-reminder`) sends a Telegram
  nudge: *"Hi {name}! Today's planned lesson: {topic}. To review: N words."*
- Finishing a lesson's theme: `lesson-done` advances the plan to the next topic.

Two reminder kinds, both outbound Telegram: the **lesson nudge** (come study,
by schedule) and the **word-review posts** (the day 2/7/30 audio cards).

### Spaced repetition (Ebbinghaus)

When a word is learned on day **D**, three reviews are scheduled: **D+2**,
**D+7**, **D+30** (configurable via `review_intervals`). "Due" = a pending review
whose `due_date ≤ today`. A failed-review hook (`scheduler.next_interval_after_fail`)
can restart the chain; the default policy is the fixed 2/7/30 intervals.

---

## 5. Commands

### Slash commands (inside Claude)

| Command | What it does |
|---|---|
| `/word` | New word of the day → card + 10 variations + audio |
| `/review` | Show and drill today's due reviews |
| `/plan` | Open/update the learning plan |
| `/course` | Overview of the wiki (`index.md`) |
| `/progress` | Progress stats + `progress.md` |
| `/setup` | Configure Telegram / language / TTS / profile |
| `/commands` | Manage your custom hotkeys |
| `/situation [place]` | Role-play (shop, doctor, Uber, bank, neighbour) |
| `/pronounce [phrase]` | Pronunciation + spoken reductions |

You can rename or add aliases via `/commands`; they're stored in
`data/journal/commands.md` and applied on top of the defaults.

### CLI (`python3 cli/tutor.py <command>`)

| Command | Description |
|---|---|
| `setup [--interface ru\|en\|uk] [--tts local\|system\|cloud] [--name NAME] [--daily-words N] [--study-time HH:MM] [--study-days daily\|mon,wed,fri] [--profile ...] [--enable-telegram] [--telegram-chat ID]` | Write config, init DB + wiki scaffold |
| `set-plan --stdin` | Store the multi-lesson plan (+ render `plan.md`) |
| `lesson-done [--idx N]` | Mark a lesson complete so the plan advances |
| `lesson-reminder [--on DATE]` | Send the Telegram lesson nudge (greeting + topic) |
| `context` | Dump learner state for the skill (prints `first_run: true/false`) |
| `add-word --stdin` (or `--json FILE`) `[--today DATE] [--no-audio] [--no-telegram]` | Add a word: card, variations, schedule, audio |
| `speak --stdin` | Render audio for an ad-hoc phrase set (no DB entry) |
| `gen-audio SLUG [--no-telegram]` | Re-render audio for an existing word |
| `due-today [--on DATE] [--json-out]` | List reviews due (default today) |
| `send-due [--on DATE]` | Deliver due reviews to Telegram |
| `context` / `log-session --stdin\|--file\|--text` | Read / append session memory |
| `stats` | Progress JSON |
| `profiles` | List student profiles + data locations |
| `use NAME` | Set the default student profile |
| `set-home PATH [--migrate]` | Choose/move the course folder location |
| `commands [list\|add ALIAS TARGET\|remove ALIAS]` | Manage hotkeys |
| `export [--out PATH]` / `import [--file F]` | Git-sync text bundle |
| `deploy --ssh user@host [--send-time HH:MM]` | Provision a remote notifier |
| `selftest [--lang en\|ru\|uk] [--audio] [--keep]` | End-to-end self-check (sandboxed) |
| `check-links` | Report broken `[[wiki-links]]` |
| `test-telegram [--chat ID] [--voice]` | Send a test message/voice to Telegram |

### `add-word` payload (JSON)

```json
{
  "lemma": "então",
  "gloss": "well / then / so",
  "pos": "adverb", "topic": "small-talk", "priority": 2,
  "card": "# ENTÃO\n...full markdown card with [[themes/..]] and real culture URLs...",
  "variations": [
    {"pt": "Então, o que você acha?", "gloss": "Well, what do you think?", "context": "Morning at work"}
  ]
}
```

`pt` is always Brazilian Portuguese; `gloss`/`context` are in the interface
language. Provide **10** variations for a full 2-4 minute lesson.

---

## 6. Audio (TTS)

Claude writes the script; a TTS engine renders it. The provider is chosen in
`config.tts.provider`:

| Provider | Quality | Setup | Notes |
|---|---|---|---|
| `local` | good | installer (piper-tts) | **default** — Piper, offline, free, cross-platform; voices auto-download to `~/.local/share/piper-tts/voices` |
| `system` | good | none | macOS `say`; pt-BR voice **Luciana** (macOS only) |
| `cloud` | best | API key | ElevenLabs / OpenAI — see key options below |

The default **Piper** voices: `pt_BR-faber-medium`, `en_US-lessac-medium`,
`ru_RU-irina-medium`, `uk_UA-ukrainian_tts-medium` (override via
`tts.local.piper_voices`). They download once on first use; the installer
pre-fetches the pt-BR voice. On python.org macOS builds, `certifi` is used to
fix SSL when downloading voices.

**Cloud key** — resolved in order: env var (`ELEVENLABS_API_KEY` /
`OPENAI_API_KEY`, wins) → `tts.cloud.api_key` in config → engine-specific
`tts.cloud.elevenlabs_api_key` / `openai_api_key`. Easiest: paste it into the
config, or `setup --tts cloud --cloud-engine elevenlabs --cloud-voice <id>
--api-key <key>`. The key is only needed where audio is generated (your Claude
Code machine) — a notifier host never needs it.

Each lesson is built from `core/content.py`: intro (interface lang) → the word
slow then natural → for each variation: context label → pt natural → pt slow →
interface gloss → outro recap. Clips are assembled with **ffmpeg** into one
`OGG/Opus` voice file (`ffmpeg`/`ffprobe` must be on PATH).

For mixed-language lessons (pt sentence + interface gloss), `system`/`local`
render each segment with that language's voice; `cloud` uses one multilingual
voice. All providers go through the same assembly so pacing is identical.

---

## 7. Telegram reminders

Telegram is **outbound only** — there is no interactive bot. Its single job: on
a review day, deliver one post = the word card (text) + the voice audio. It does
**not** read incoming messages and is **not** an on-demand pronunciation
service: to hear a phrase, the tutor renders audio with `speak`/`add-word` and
delivers it in the chat — never by sending it to the bot.

How audio reaches the post without re-uploading: when a word is added, the
toolkit uploads its `.ogg` to Telegram **once** and stores the returned
`telegram_file_id`. Every later review just re-sends by `file_id`; the bytes
live in Telegram's CDN.

Setup:
1. Create a bot with **@BotFather**, copy the token.
2. Find your chat id via **@userinfobot**.
3. `export TELEGRAM_BOT_TOKEN=...`
4. `python3 cli/tutor.py setup --enable-telegram --telegram-chat <id> --profile local-notifier`

`TELEGRAM_BOT_TOKEN` and any git sync token are read **only** from the
environment — never written to config. The **cloud TTS API key** may optionally
be placed in the per-student config (`tts.cloud.api_key`) for convenience, since
that config lives in the student's local data dir; the env var still wins. Avoid
committing it if you push the data dir to a sync repo.

---

## 8. Deployment profiles

Switch with one field, `deployment_profile`. Presets live in `config/profiles/`.
The profile decides **where reminders are delivered from** — it is independent of
the voice engine (`tts.provider`). A reminder is sent by whatever runs at the due
time, and that sender needs only the bot token + the stored `file_id` + the
schedule (no TTS), because the audio was uploaded when the word was learned. So
choosing `cloud` TTS does not remove the need for a local or remote sender.

### A — `skill-only`
```
python3 cli/tutor.py setup --interface en --tts system --profile skill-only
```
Use the skill in Claude. See due reviews with `/review`. No Telegram, no cron.

### B — `local-notifier`
```
python3 cli/tutor.py setup --interface en --tts system --profile local-notifier \
    --enable-telegram --telegram-chat <CHAT_ID>
export TELEGRAM_BOT_TOKEN=...
```
Install the daily job:
- **macOS**: edit and load `deploy/launchd/com.tutor.notifier.plist`
  (`cp ... ~/Library/LaunchAgents/ && launchctl load ...`).
- **cron**: see `deploy/cron.example`.

Reminders arrive when the machine is on. Sync mode is `shared` — the cron job
reads the same profile data dir as Claude (set `TUTOR_PROFILE`), so nothing
transfers.

### C — `remote-notifier`
Code and data stay separate, like locally. First make the student's **data dir**
a private git repo and push it (`sync.mode: git`, set `sync.git.repo_url`); audio
rides Telegram `file_id`, so only text travels. Then locally:
```
python3 cli/tutor.py deploy --ssh user@host --send-time 09:00
```
This **rsyncs the code** to `~/ptb-tutor-code`, and the remote setup **clones your
private data repo** to `~/ptb-tutor-data`, installs a light venv (no Piper — the
host generates no audio), and a daily cron running
`TUTOR_DATA_DIR=~/ptb-tutor-data … tutor.py notify` (git pull → import → lesson
nudge + due reviews). On the host, put `TELEGRAM_BOT_TOKEN` in `~/.ptb_env` and
add a deploy key so it can pull the private repo. Pass `--data-repo <url>` if it's
not in the config.

### D — `scheduled-agent` (no personal server)
A Claude cloud **routine** runs the sender daily on a cron — always-on without a
VPS or leaving your machine on. It's the remote model with the "host" being an
ephemeral Claude agent environment.

1. Put your data in a **private** git repo: `sync.mode: git`, and commit
   `data/course`, `data/journal`, `sync/words.ndjson` (the binary DB and audio
   stay ignored; audio rides Telegram `file_id`). Run `tutor.py export` and push
   after each session (or let the skill do it).
2. Create a daily routine with the **`schedule`** skill that runs
   `deploy/agent-notify.sh` with two environment values:
   - `TUTOR_SYNC_REPO` — your private repo URL
   - `TELEGRAM_BOT_TOKEN` — a **dedicated** bot's token
   The script clones/pulls the repo, installs deps, and runs `tutor.py notify`
   (pull → import → send-due).

Caveat: the routine must hold the bot token in its environment. A bot token only
lets a sender post as that bot, but still use a dedicated bot and a private repo.

Every profile's sender is the same one-shot command — `tutor.py notify` (or
`notifier/send_due.py`) — differing only in *where* it runs.

---

## 9. Sync (how the remote notifier learns what to send)

The local Claude session is the **only writer**. Two modes (`sync.mode`):

- **`shared`** — notifier and Claude on the same disk. No sync; the cron job
  queries `reviews WHERE due_date ≤ today` directly.
- **`git`** — `tutor.py export` writes a text bundle (`sync/words.ndjson`:
  words + variations + schedule + `file_id`) and you commit it together with the
  `data/course` cards. The host does `git pull → tutor.py import`. Hard rules:
  - In the repo, **text only**. `data/tutor.db` and `data/audio/` are
    git-ignored (audio rides Telegram `file_id`, not git).
  - **One-directional**: the host pulls read-only and keeps its own
    `sent`/`done` delivery status locally; it never pushes back. `import` never
    downgrades a review the host already marked done.

---

## 10. Configuration reference

`config/config.example.yaml` (copy to `config.yaml`, or run `setup`):

```yaml
deployment_profile: skill-only   # skill-only | local-notifier | remote-notifier
interface_language: ""           # ru | en | uk — asked on first run, then fixed
review_intervals: [2, 7, 30]     # Ebbinghaus days
daily_new_words: 1

tts:
  provider: system               # system | local | cloud
  system: { voice_pt: Luciana }
  local:  { piper_bin: piper, piper_voices: { pt: ..., ru: ..., en: ..., uk: ... } }
  cloud:  { engine: elevenlabs, voice_pt: "" }   # key in env

telegram:
  enabled: false
  chat_id: ""
  send_time: "09:00"             # cron/launchd time

sync:
  mode: shared                   # shared | git
  git: { repo_url: "" }

deploy:
  ssh_host: ""
```

Environment variables (never in the file): `TELEGRAM_BOT_TOKEN`,
`ELEVENLABS_API_KEY`, `OPENAI_API_KEY`, `COACH_SYNC_TOKEN`, and
`TUTOR_DATA_DIR` (override the data directory location).

---

## 11. Requirements & install

One line (clones into `~/.claude/skills/`, installs deps, checks ffmpeg):

```
curl -fsSL https://raw.githubusercontent.com/Tashamet/portuguese-brasil-tutor/main/install.sh | bash
```

Manual:

```
pip install -r requirements.txt     # PyYAML, requests
```
Plus on PATH: `ffmpeg` + `ffprobe` (audio assembly). `system` TTS needs macOS;
`local` needs the `piper` binary + voice models; `cloud` needs an API key.

---

## 12. Testing & diagnostics

Two commands let you confirm the tutor and the bot work without going through a
full Claude session.

### `selftest` — verify the tutor

Runs the whole pipeline in a throwaway sandbox (a temp data dir; nothing real is
touched): scheduler math, `setup`, `add-word` with a 10-variation word, schedule
on day 2, stats, a localized wiki scaffold, an export/import round-trip, and the
link checker. Add `--audio` to also render a real audio lesson.

```
python3 cli/tutor.py selftest                 # English, no audio
python3 cli/tutor.py selftest --lang ru        # check the Russian wiki labels
python3 cli/tutor.py selftest --lang uk --audio  # also render audio (needs ffmpeg+say)
python3 cli/tutor.py selftest --keep           # keep the sandbox dir to inspect
```

Each step prints `[PASS]`/`[FAIL]` and the command exits non-zero if anything
fails — suitable for CI.

```
python3 tests/test_scheduler.py                # unit tests for the scheduler
python3 cli/tutor.py check-links               # broken [[wiki-links]] in your course
```

### `test-telegram` — verify the bot

Sends a real message to your configured chat (and a sample voice with
`--voice`). Requires `TELEGRAM_BOT_TOKEN` in the environment and a `chat_id`.

```
export TELEGRAM_BOT_TOKEN=...
python3 cli/tutor.py test-telegram                       # text only
python3 cli/tutor.py test-telegram --voice               # text + a sample lesson
python3 cli/tutor.py test-telegram --chat 123456 --voice # override chat id
```

To rehearse a reminder exactly as it will arrive, add a word, then:
`python3 cli/tutor.py send-due --on <a due date>`.

---

## 13. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `'ffmpeg' not found` | Install ffmpeg; ensure `ffmpeg`/`ffprobe` on PATH |
| `piper-tts is not installed` | `pip install piper-tts certifi`, or rerun install.sh |
| Piper voice download SSL error | python.org macOS cert issue — `pip install certifi` (the adapter sets `SSL_CERT_FILE`) |
| `'say' not found` | `system` TTS is macOS-only; switch to `local`/`cloud` |
| `TELEGRAM_BOT_TOKEN not set` | Export the token in the environment |
| `Telegram is disabled or chat_id missing` | Run `/setup` / `setup --enable-telegram --telegram-chat ID` |
| Audio shorter than 2 min | Provide 10 variations; `system` voice is fast — `cloud` runs longer |
| Broken `[[links]]` | Create the missing `themes/` or `grammar/` file the card links to |
| Remote gets nothing | Check `git pull`/`import` on the host; confirm `file_id` is set in the bundle |
