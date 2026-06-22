"""Select the TTS adapter named by ``config.tts.provider``."""
from __future__ import annotations

from .. import config
from .base import TTSAdapter


def get_adapter(provider: str | None = None) -> TTSAdapter:
    provider = (provider or config.tts_provider()).lower()
    if provider == "system":
        from .system import SystemTTS
        return SystemTTS()
    if provider == "local":
        from .local import LocalTTS
        return LocalTTS()
    if provider == "cloud":
        from .cloud import CloudTTS
        return CloudTTS()
    raise ValueError(f"Unknown TTS provider '{provider}' (system|local|cloud)")
