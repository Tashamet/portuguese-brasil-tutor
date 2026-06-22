"""Piper adapter — offline, free, cross-platform, higher quality than ``say``.

Needs the ``piper`` binary and per-language ``.onnx`` voice models. Configure
``config.tts.local.piper_bin`` and ``config.tts.local.piper_voices`` (a map of
language -> path to the .onnx model). Mixed-language lessons are handled the
same way as elsewhere: one clip per segment using that language's voice.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from .. import config
from .audio import AudioError, run
from .base import Segment, TTSAdapter


class LocalTTS(TTSAdapter):
    name = "local"

    def __init__(self) -> None:
        self.bin = config.get("tts.local.piper_bin", "piper") or "piper"
        if not shutil.which(self.bin) and not Path(self.bin).exists():
            raise AudioError(
                f"Piper binary '{self.bin}' not found — install piper or set "
                "tts.local.piper_bin"
            )
        self.voices = config.get("tts.local.piper_voices", {}) or {}
        if not self.voices:
            raise AudioError("tts.local.piper_voices is empty — map lang -> .onnx model")

    def render_clip(self, segment: Segment, dst: Path) -> Path:
        model = self.voices.get(segment.lang) or self.voices.get("pt")
        if not model:
            raise AudioError(f"No Piper voice configured for '{segment.lang}'")
        wav = dst.with_suffix(".wav")
        # Piper reads text on stdin and writes a wav to --output_file.
        length_scale = "1.3" if segment.slow else "1.0"
        cmd = [self.bin, "--model", str(model), "--length_scale", length_scale,
               "--output_file", str(wav)]
        proc = __import__("subprocess").run(cmd, input=segment.text, text=True,
                                            capture_output=True)
        if proc.returncode != 0:
            raise AudioError(f"piper failed: {proc.stderr.strip()}")
        return wav
