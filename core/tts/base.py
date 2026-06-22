"""TTS adapter interface and the segment model.

A lesson is a list of :class:`Segment`s — each a short bit of text in one
language, optionally slow, with a pause after it. Adapters render each segment
to a clip; :func:`core.tts.audio.assemble` stitches them into one ogg. This
keeps multilingual lessons (pt sentence -> pause -> interface gloss) and
pacing uniform across system/local/cloud backends.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import audio


@dataclass
class Segment:
    text: str
    lang: str  # 'pt' | 'ru' | 'en' | 'uk'
    slow: bool = False
    pause_after: float = 0.4


class TTSAdapter:
    """Base class. Subclasses implement :meth:`render_clip`."""

    name = "base"

    def render_clip(self, segment: Segment, dst: Path) -> Path:
        """Render a single segment to an audio file at ``dst`` (any format
        ffmpeg can read). Must be overridden."""
        raise NotImplementedError

    def synthesize(self, segments: list[Segment], out_ogg: Path) -> float:
        """Render every segment and assemble into ``out_ogg``. Returns duration."""
        out_ogg.parent.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix=f"tutor_{self.name}_"))
        rendered: list[tuple[Path, float]] = []
        try:
            for i, seg in enumerate(segments):
                clip = self.render_clip(seg, work / f"clip_{i:03d}")
                rendered.append((clip, seg.pause_after))
            return audio.assemble(rendered, out_ogg)
        finally:
            import shutil
            shutil.rmtree(work, ignore_errors=True)
