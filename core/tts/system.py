"""macOS ``say`` adapter — zero install, free, the default on a Mac.

Uses the built-in voices (pt-BR Luciana by default). Other interface
languages map to bundled macOS voices; override in
``config.tts.system.voices``.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from .. import config
from .audio import AudioError, run
from .base import Segment, TTSAdapter

# Sensible macOS voice defaults per language.
DEFAULT_VOICES = {
    "pt": "Luciana",   # pt-BR
    "ru": "Milena",    # ru-RU
    "en": "Samantha",  # en-US
    "uk": "Lesya",     # uk-UA
}


class SystemTTS(TTSAdapter):
    name = "system"

    def __init__(self) -> None:
        if not shutil.which("say"):
            raise AudioError("'say' not found — system TTS only works on macOS")
        cfg_voices = config.get("tts.system.voices", {}) or {}
        pt_override = config.get("tts.system.voice_pt")
        self.voices = {**DEFAULT_VOICES, **cfg_voices}
        if pt_override:
            self.voices["pt"] = pt_override

    def render_clip(self, segment: Segment, dst: Path) -> Path:
        aiff = dst.with_suffix(".aiff")
        voice = self.voices.get(segment.lang, DEFAULT_VOICES["pt"])
        cmd = ["say", "-v", voice, "-o", str(aiff)]
        if segment.slow:
            cmd += ["-r", "120"]  # words per minute; default ~175
        cmd.append(segment.text)
        run(cmd)
        return aiff
