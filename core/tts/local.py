"""Piper adapter — offline, free, cross-platform. The default voice engine.

Uses the ``piper-tts`` Python package (``python3 -m piper``). Voices are
downloaded on first use into a shared cache and reused. Works on macOS and
Linux alike, which is why it's the default (unlike macOS-only ``say``).

Config (all optional):
    tts.local.voices_dir   where to cache .onnx voices (default ~/.local/share/piper-tts/voices)
    tts.local.piper_voices map of lang -> voice name (overrides the defaults below)
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .. import config
from .audio import AudioError
from .base import Segment, TTSAdapter

# Confirmed voice names from the piper voices catalogue.
DEFAULT_VOICES = {
    "pt": "pt_BR-faber-medium",
    "en": "en_US-lessac-medium",
    "ru": "ru_RU-irina-medium",
    "uk": "uk_UA-ukrainian_tts-medium",
}


def _ssl_env() -> dict:
    """Env with SSL_CERT_FILE set — fixes python.org macOS cert failures."""
    env = dict(os.environ)
    if "SSL_CERT_FILE" not in env:
        try:
            import certifi
            env["SSL_CERT_FILE"] = certifi.where()
        except Exception:
            pass
    return env


class LocalTTS(TTSAdapter):
    name = "local"

    def __init__(self) -> None:
        # Confirm the piper package is importable for this interpreter.
        probe = subprocess.run([sys.executable, "-c", "import piper"],
                               capture_output=True, text=True)
        if probe.returncode != 0:
            raise AudioError(
                "piper-tts is not installed for this Python. Install it with "
                "`pip install piper-tts`, or run the project's install.sh."
            )
        vdir = config.get("tts.local.voices_dir") or "~/.local/share/piper-tts/voices"
        self.voices_dir = Path(vdir).expanduser()
        self.voices_dir.mkdir(parents=True, exist_ok=True)
        self.voices = {**DEFAULT_VOICES, **(config.get("tts.local.piper_voices", {}) or {})}

    def _ensure_voice(self, voice: str) -> None:
        if (self.voices_dir / f"{voice}.onnx").exists():
            return
        proc = subprocess.run(
            [sys.executable, "-m", "piper.download_voices", voice,
             "--download-dir", str(self.voices_dir)],
            capture_output=True, text=True, env=_ssl_env(),
        )
        if proc.returncode != 0 or not (self.voices_dir / f"{voice}.onnx").exists():
            raise AudioError(f"Could not download Piper voice '{voice}': "
                             f"{proc.stderr.strip()[:200]}")

    def render_clip(self, segment: Segment, dst: Path) -> Path:
        voice = self.voices.get(segment.lang) or self.voices["pt"]
        self._ensure_voice(voice)
        wav = dst.with_suffix(".wav")
        cmd = [sys.executable, "-m", "piper", "-m", voice,
               "--data-dir", str(self.voices_dir), "-f", str(wav),
               "--length-scale", "1.3" if segment.slow else "1.0"]
        proc = subprocess.run(cmd, input=segment.text, text=True,
                              capture_output=True, env=_ssl_env())
        if proc.returncode != 0 or not wav.exists():
            raise AudioError(f"piper synthesis failed: {proc.stderr.strip()[:200]}")
        return wav
