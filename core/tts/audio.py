"""ffmpeg/ffprobe helpers shared by every TTS adapter.

All adapters render per-segment clips, then this module normalises, inserts
silence gaps and concatenates everything into a single Telegram-ready
``.ogg`` (Opus) voice file.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

SAMPLE_RATE = 24000


class AudioError(RuntimeError):
    pass


def _require(binary: str) -> str:
    found = shutil.which(binary)
    if not found:
        raise AudioError(f"'{binary}' not found in PATH — install ffmpeg")
    return found


def run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AudioError(f"command failed: {' '.join(cmd)}\n{proc.stderr.strip()}")


def normalize(src: Path, dst: Path) -> Path:
    """Re-encode any input to mono 24 kHz WAV so clips concatenate cleanly."""
    _require("ffmpeg")
    run(["ffmpeg", "-y", "-i", str(src), "-ac", "1", "-ar", str(SAMPLE_RATE),
         "-f", "wav", str(dst)])
    return dst


def silence(seconds: float, dst: Path) -> Path:
    _require("ffmpeg")
    run(["ffmpeg", "-y", "-f", "lavfi", "-i",
         f"anullsrc=channel_layout=mono:sample_rate={SAMPLE_RATE}",
         "-t", f"{max(seconds, 0.05):.3f}", "-f", "wav", str(dst)])
    return dst


def concat(wavs: list[Path], dst: Path) -> Path:
    _require("ffmpeg")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as listing:
        for w in wavs:
            listing.write(f"file '{w.as_posix()}'\n")
        list_path = listing.name
    try:
        run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
             "-c", "copy", str(dst)])
    finally:
        Path(list_path).unlink(missing_ok=True)
    return dst


def to_ogg(src: Path, dst: Path) -> Path:
    """Convert a WAV to OGG/Opus — the format Telegram needs for voice."""
    _require("ffmpeg")
    run(["ffmpeg", "-y", "-i", str(src), "-c:a", "libopus", "-b:a", "48k", str(dst)])
    return dst


def duration(path: Path) -> float:
    _require("ffprobe")
    proc = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(json.loads(proc.stdout)["format"]["duration"])
    except Exception:
        return 0.0


def assemble(segment_wavs: list[tuple[Path, float]], out_ogg: Path) -> float:
    """Normalise + interleave silence + concat + encode to ogg.

    ``segment_wavs`` is a list of ``(wav_path, pause_after_seconds)``.
    Returns the final duration in seconds.
    """
    work = Path(tempfile.mkdtemp(prefix="tutor_tts_"))
    pieces: list[Path] = []
    try:
        for i, (wav, pause) in enumerate(segment_wavs):
            norm = normalize(wav, work / f"seg_{i:03d}.wav")
            pieces.append(norm)
            if pause > 0:
                pieces.append(silence(pause, work / f"gap_{i:03d}.wav"))
        combined = concat(pieces, work / "combined.wav")
        to_ogg(combined, out_ogg)
        return duration(out_ogg)
    finally:
        shutil.rmtree(work, ignore_errors=True)
