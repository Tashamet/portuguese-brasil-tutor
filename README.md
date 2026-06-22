# portuguese-brasil-tutor

A Claude skill + toolkit for learning **Brazilian Portuguese** from zero while
living in Brazil. Explains in **English / Ukrainian / Russian** (your choice),
builds a **Markdown wiki-course** you can browse yourself, generates **2-4 min
audio lessons** (one word × 10 contextual variations), schedules **Ebbinghaus
spaced repetition** (day 2 / 7 / 30) and can push review reminders to
**Telegram**.

📖 **Full documentation:** [MANUAL.md](MANUAL.md) · skill entry point:
[SKILL.md](SKILL.md)

## Quick start

```bash
pip install -r requirements.txt          # PyYAML, requests (+ ffmpeg on PATH)
python3 cli/tutor.py setup --interface en --tts system --profile skill-only
```

Then open the skill in Claude and say e.g. *"teach me Brazilian Portuguese"*.
On first run the tutor asks your interface language, runs a short diagnostic,
agrees a learning plan, and starts. All slash commands are in English (see
below); all CLI subcommands are in English too.

## How it works

- All teaching happens **inside Claude** (the skill). Claude authors each word:
  a cultural card, 10 contextual variations, real culture links (via web
  search), and the audio script.
- The toolkit (`cli/tutor.py`) stores words in **SQLite** (the spaced-repetition
  engine), writes the human-readable course as **Markdown** (`data/course/`),
  renders audio, and — if enabled — uploads it to Telegram once (reused by
  `file_id`).
- The only thing that runs **outside Claude** is a tiny cron notifier that
  delivers due reviews. No interactive bot, no always-on server.

## Requirements

- Python 3.11+, `pip install -r requirements.txt`
- `ffmpeg` + `ffprobe` on PATH (audio assembly)
- TTS: **system** (macOS `say`, default, zero-install) / **local** (Piper) /
  **cloud** (ElevenLabs or OpenAI; API key in env)

## Three deployment profiles

### A — skill + database (nothing runs)
```
python3 cli/tutor.py setup --interface ru --tts system --profile skill-only
```
Use the skill in Claude. See due reviews with `/review`. No Telegram.

### B — skill + local notifier (this Mac)
```
python3 cli/tutor.py setup --interface ru --tts system --profile local-notifier \
    --enable-telegram --telegram-chat <YOUR_CHAT_ID>
export TELEGRAM_BOT_TOKEN=...        # from @BotFather
```
Install the daily reminder via `deploy/launchd/com.tutor.notifier.plist`
(edit the paths) or `deploy/cron.example`. Reminders arrive when the Mac is on.

### C — skill + remote notifier (24/7, SSH host)
Author locally; words travel to the host via a private git repo (text bundle),
audio via Telegram `file_id`. On the host, set `TELEGRAM_BOT_TOKEN`, then:
```
python3 cli/tutor.py deploy --ssh user@host --send-time 09:00
```
This copies the package, installs a venv + deps, and a daily cron that runs
`git pull → tutor.py import → send-due`. The `remote-notifier.yaml` profile is
safe to share (no secrets).

## Commands

**In Claude (slash commands — always English):**

| Command | What |
|---|---|
| `/word` | New word of the day → card + 10 variations + audio |
| `/review` | Show and drill today's due reviews |
| `/plan` · `/course` · `/progress` | Plan, wiki overview, progress |
| `/setup` | Configure Telegram / language / TTS / profile |
| `/commands` | Manage custom hotkeys |
| `/situation [place]` · `/pronounce [phrase]` | Role-play · pronunciation |

**CLI (`python3 cli/tutor.py <command>`):**

| Command | What |
|---|---|
| `setup` | write config, init db + wiki |
| `context` | dump learner state for the skill |
| `add-word --stdin` | add word (+10 variations, audio, schedule) |
| `due-today [--on DATE]` | list reviews due |
| `send-due` | deliver due reviews to Telegram |
| `export` / `import` | git sync bundle (`sync/words.ndjson`) |
| `stats` | progress |

See [MANUAL.md](MANUAL.md) for every command, the data model, audio, sync and
troubleshooting.

## Data layout

```
data/tutor.db          SQLite engine (gitignored)
data/audio/*.ogg       generated lessons (gitignored; Telegram holds the bytes)
data/course/           the wiki you read: index, plan, progress, words/, grammar/, themes/
data/journal/          Claude's working memory: profile, sessions, commands
sync/words.ndjson      text bundle for git-mode sync
```

Secrets live only in environment variables, never in config files.
