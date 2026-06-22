# Audio lesson format — 2-4 minutes, one word x 10 variations

Each new word becomes a single ~2-4 minute audio lesson. You author the
content; `cli/tutor.py add-word` renders it (intro → word → 10 variations →
outro) via the configured TTS provider and produces a Telegram-ready `.ogg`.

## What the audio contains (built by `core/content.py`)

1. **Intro** (interface language): "Word of the day: ___ — it means ___."
2. **The word** in pt-BR: once slow, once at natural speed.
3. **10 variations** — the word in 10 different contexts/times of day. Each:
   optional short context label (interface language) → pt sentence → pause →
   interface-language gloss.
4. **Outro**: a quick recap of the 10 pt sentences at natural speed.

To hit 2-4 minutes, provide **10** variations (fewer = shorter audio). Aim for
genuinely different situations: morning at the bakery, paying an Uber, replying
to a neighbour, at the pharmacy, texting on WhatsApp, etc.

## add-word JSON payload

```json
{
  "lemma": "então",
  "gloss": "ну / тогда / значит",
  "pos": "adverb",
  "topic": "small-talk",
  "priority": 2,
  "card": "# ENTÃO\n...full markdown card with [[themes/..]] links and real culture URLs...",
  "variations": [
    {"pt": "Então, o que você acha?", "gloss": "Ну, что ты думаешь?", "context": "Утром на работе"},
    {"pt": "Então tá bom!",           "gloss": "Ну ладно!",          "context": "В конце разговора"}
  ]
}
```

Pass it via stdin:

```
python3 cli/tutor.py add-word --stdin <<'JSON'
{ ... }
JSON
```

Notes:
- `gloss`/`context` are in the **interface language** (en/uk/ru). `pt` is always
  Brazilian Portuguese.
- The `card` is the body of the Telegram review post; write it for a human to
  read, with real cultural links (found via WebSearch — never invented).
- `add-word` schedules reviews at day 2/7/30, renders audio to
  `data/audio/<slug>.ogg`, and (if Telegram is enabled) uploads once and stores
  the reusable `file_id`.
- Use `--no-audio` only for quick text-only tests; `--no-telegram` to skip the
  upload while still rendering local audio.
