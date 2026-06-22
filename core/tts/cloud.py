"""Cloud TTS adapter — ElevenLabs (default) or OpenAI. Best voice quality.

The API key is resolved in this order:
  1. env var  ``ELEVENLABS_API_KEY`` / ``OPENAI_API_KEY``  (wins)
  2. config   ``tts.cloud.api_key``                        (easiest — paste it)
  3. config   ``tts.cloud.elevenlabs_api_key`` / ``tts.cloud.openai_api_key``
ElevenLabs' multilingual model handles mixed pt + interface text in one voice;
we still render per segment so pacing/pauses are identical across providers.
"""
from __future__ import annotations

import os
from pathlib import Path

import requests

from .. import config
from .audio import AudioError
from .base import Segment, TTSAdapter


def _resolve_key(env_var: str, engine: str) -> str | None:
    return (os.environ.get(env_var)
            or config.get("tts.cloud.api_key")
            or config.get(f"tts.cloud.{engine}_api_key"))


class CloudTTS(TTSAdapter):
    name = "cloud"

    def __init__(self) -> None:
        self.engine = (config.get("tts.cloud.engine", "elevenlabs") or "elevenlabs").lower()
        if self.engine == "elevenlabs":
            self.key = _resolve_key("ELEVENLABS_API_KEY", "elevenlabs")
            self.voice = config.get("tts.cloud.voice_pt", "")
            if not self.key:
                raise AudioError("No ElevenLabs key — set tts.cloud.api_key in config "
                                 "or the ELEVENLABS_API_KEY env var")
            if not self.voice:
                raise AudioError("tts.cloud.voice_pt (ElevenLabs voice id) not set")
        elif self.engine == "openai":
            self.key = _resolve_key("OPENAI_API_KEY", "openai")
            self.voice = config.get("tts.cloud.voice_pt", "alloy") or "alloy"
            if not self.key:
                raise AudioError("No OpenAI key — set tts.cloud.api_key in config "
                                 "or the OPENAI_API_KEY env var")
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
