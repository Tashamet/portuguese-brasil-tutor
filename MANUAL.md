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

### SQLite — `data/tutor.db` (the spaced-repetition engine)

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

1. **Session start** — `tutor.py context` tells the skill whether this is a
   first run (no profile/words) or returns the saved profile, progress, recent
   sessions and word lists. Claude continues where you left off and surfaces
   what's due today.
2. **A new word** — Claude writes a rich card, 10 contextual variations (each in
   a different time/place), finds real culture links via web search, then calls
   `tutor.py add-word`. That single call:
   - writes `data/course/words/{slug}.md`,
   - inserts the word + variations into SQLite,
   - schedules reviews at **day 2, 7, 30**,
   - renders the **2-4 min audio lesson** (intro → word slow+natural → 10
     variations, each pt natural + pt slow + gloss → quick recap),
   - if Telegram is on, uploads the audio once and stores its `file_id`,
   - rebuilds `index.md` and `progress.md`.
3. **Reviews** — on day 2/7/30 the word is "due". Inside Claude you drill it
   with `/review`; with a notifier configured, a Telegram post arrives
   automatically (card text + voice).
4. **Session end** — `tutor.py log-session` appends what you covered.

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
| `setup [--interface ru\|en\|uk] [--tts system\|local\|cloud] [--profile ...] [--enable-telegram] [--telegram-chat ID]` | Write config, init DB + wiki scaffold |
| `context` | Dump learner state for the skill (prints `first_run: true/false`) |
| `add-word --stdin` (or `--json FILE`) `[--today DATE] [--no-audio] [--no-telegram]` | Add a word: card, variations, schedule, audio |
| `gen-audio SLUG [--no-telegram]` | Re-render audio for an existing word |
| `due-today [--on DATE] [--json-out]` | List reviews due (default today) |
| `send-due [--on DATE]` | Deliver due reviews to Telegram |
| `context` / `log-session --stdin\|--file\|--text` | Read / append session memory |
| `stats` | Progress JSON |
| `commands [list\|add ALIAS TARGET\|remove ALIAS]` | Manage hotkeys |
| `export` / `import [--file F]` | Git-sync text bundle |
| `deploy --ssh user@host [--send-time HH:MM]` | Provision a remote notifier |

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
| `system` | good | none | macOS `say`; pt-BR voice **Luciana** (default) |
| `local` | better | install Piper + `.onnx` voices | offline, free, cross-platform |
| `cloud` | best | API key in env | ElevenLabs (`ELEVENLABS_API_KEY`) or OpenAI (`OPENAI_API_KEY`) |

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
a review day, deliver one post = the word card (text) + the voice audio.

How audio reaches the post without re-uploading: when a word is added, the
toolkit uploads its `.ogg` to Telegram **once** and stores the returned
`telegram_file_id`. Every later review just re-sends by `file_id`; the bytes
live in Telegram's CDN.

Setup:
1. Create a bot with **@BotFather**, copy the token.
2. Find your chat id via **@userinfobot**.
3. `export TELEGRAM_BOT_TOKEN=...`
4. `python3 cli/tutor.py setup --enable-telegram --telegram-chat <id> --profile local-notifier`

Secrets (`TELEGRAM_BOT_TOKEN`, API keys, sync token) are only ever read from the
environment — never written to config files.

---

## 8. Deployment profiles

Switch with one field, `deployment_profile`. Presets live in `config/profiles/`.

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
reads the same `data/` as Claude, so nothing transfers.

### C — `remote-notifier`
Author locally; words travel to the host via a private git repo (text bundle),
audio via Telegram `file_id`. On the host set `TELEGRAM_BOT_TOKEN`, then locally:
```
python3 cli/tutor.py deploy --ssh user@host --send-time 09:00
```
This copies the package, creates a venv, installs deps, and installs a daily
cron that runs `git pull → tutor.py import → send-due`. The
`remote-notifier.yaml` profile is safe to share (no secrets).

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

```
pip install -r requirements.txt     # PyYAML, requests
```
Plus on PATH: `ffmpeg` + `ffprobe` (audio assembly). `system` TTS needs macOS;
`local` needs the `piper` binary + voice models; `cloud` needs an API key.

Run the tests:
```
python3 tests/test_scheduler.py
```

---

## 12. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `'ffmpeg' not found` | Install ffmpeg; ensure `ffmpeg`/`ffprobe` on PATH |
| `'say' not found` | `system` TTS is macOS-only; switch to `local`/`cloud` |
| `TELEGRAM_BOT_TOKEN not set` | Export the token in the environment |
| `Telegram is disabled or chat_id missing` | Run `/setup` / `setup --enable-telegram --telegram-chat ID` |
| Audio shorter than 2 min | Provide 10 variations; `system` voice is fast — `cloud` runs longer |
| Broken `[[links]]` | Create the missing `themes/` or `grammar/` file the card links to |
| Remote gets nothing | Check `git pull`/`import` on the host; confirm `file_id` is set in the bundle |
