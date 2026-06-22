"""Telegram Bot API — outbound only (no aiogram, no polling).

The bot does exactly one thing: deliver a review post = the word card (text) +
the voice audio. Audio is uploaded once; the returned ``file_id`` is reused for
every later review so bytes never travel again.
"""
from __future__ import annotations

from pathlib import Path

import requests

from . import config

API = "https://api.telegram.org/bot{token}/{method}"


class TelegramError(RuntimeError):
    pass


def _token() -> str:
    token = config.telegram_token()
    if not token:
        raise TelegramError("TELEGRAM_BOT_TOKEN not set in environment")
    return token


def _call(method: str, data: dict, files: dict | None = None) -> dict:
    url = API.format(token=_token(), method=method)
    resp = requests.post(url, data=data, files=files, timeout=60)
    payload = resp.json()
    if not payload.get("ok"):
        raise TelegramError(f"{method} failed: {payload.get('description')}")
    return payload["result"]


def send_message(chat_id: str, text: str) -> dict:
    # Plain text: card markdown contains [[links]] and chars that break parse modes.
    return _call("sendMessage", {"chat_id": chat_id, "text": text[:4096],
                                 "disable_web_page_preview": True})


def upload_voice(chat_id: str, ogg_path: Path, caption: str = "") -> str:
    """Send a voice file and return its reusable ``file_id``."""
    with open(ogg_path, "rb") as fh:
        result = _call("sendVoice", {"chat_id": chat_id, "caption": caption[:1024]},
                       files={"voice": fh})
    return result["voice"]["file_id"]


def send_voice_by_id(chat_id: str, file_id: str, caption: str = "") -> dict:
    return _call("sendVoice", {"chat_id": chat_id, "voice": file_id,
                               "caption": caption[:1024]})


def send_card_post(chat_id: str, card_text: str, *, ogg_path: Path | None = None,
                   file_id: str | None = None) -> str | None:
    """Deliver one review post: card text message + voice.

    Prefers ``file_id`` (no re-upload). If only ``ogg_path`` is given, uploads
    it and returns the new ``file_id`` so the caller can persist it.
    """
    if card_text:
        send_message(chat_id, card_text)
    if file_id:
        send_voice_by_id(chat_id, file_id)
        return file_id
    if ogg_path:
        return upload_voice(chat_id, ogg_path)
    return None
