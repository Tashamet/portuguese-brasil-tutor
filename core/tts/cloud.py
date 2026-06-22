"""Cloud TTS adapter — ElevenLabs (default) or OpenAI. Best voice quality.

Needs an API key from the environment (never the config file):
``ELEVENLABS_API_KEY`` or ``OPENAI_API_KEY``. ElevenLabs' multilingual model
handles mixed pt + interface text in one voice; we still render per segment so
pacing/pauses are identical across providers.
"""
from __future__ import annotations

import os
from pathlib import Path

import requests

from .. import config
from .audio import AudioError
from .base import Segment, TTSAdapter


class CloudTTS(TTSAdapter):
    name = "cloud"

    def __init__(self) -> None:
        self.engine = (config.get("tts.cloud.engine", "elevenlabs") or "elevenlabs").lower()
        if self.engine == "elevenlabs":
            self.key = os.environ.get("ELEVENLABS_API_KEY")
            self.voice = config.get("tts.cloud.voice_pt", "")
            if not self.key:
                raise AudioError("ELEVENLABS_API_KEY not set")
            if not self.voice:
                raise AudioError("tts.cloud.voice_pt (ElevenLabs voice id) not set")
        elif self.engine == "openai":
            self.key = os.environ.get("OPENAI_API_KEY")
            self.voice = config.get("tts.cloud.voice_pt", "alloy") or "alloy"
            if not self.key:
                raise AudioError("OPENAI_API_KEY not set")
        else:
            raise AudioError(f"Unknown cloud engine '{self.engine}'")

    def render_clip(self, segment: Segment, dst: Path) -> Path:
        mp3 = dst.with_suffix(".mp3")
        if self.engine == "elevenlabs":
            audio_bytes = self._elevenlabs(segment.text)
        else:
            audio_bytes = self._openai(segment.text)
        mp3.write_bytes(audio_bytes)
        return mp3

    def _elevenlabs(self, text: str) -> bytes:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice}"
        resp = requests.post(
            url,
            headers={"xi-api-key": self.key, "accept": "audio/mpeg"},
            json={"text": text, "model_id": "eleven_multilingual_v2"},
            timeout=60,
        )
        if resp.status_code != 200:
            raise AudioError(f"ElevenLabs error {resp.status_code}: {resp.text[:200]}")
        return resp.content

    def _openai(self, text: str) -> bytes:
        resp = requests.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {self.key}"},
            json={"model": "tts-1", "voice": self.voice, "input": text,
                  "response_format": "mp3"},
            timeout=60,
        )
        if resp.status_code != 200:
            raise AudioError(f"OpenAI error {resp.status_code}: {resp.text[:200]}")
        return resp.content
