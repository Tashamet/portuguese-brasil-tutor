"""Build a 2-4 minute audio lesson script from a word and its variations.

One word, 10 contextual variations, in different times/places, slow + natural
repetition, glossed in the interface language. The intro/outro are templated
per interface language; the linguistic content (variations, gloss, card) is
authored by Claude in the skill session.
"""
from __future__ import annotations

from .models import Word
from .tts.base import Segment

INTRO = {
    "ru": "Слово дня: {lemma}. Это значит: {gloss}.",
    "en": "Word of the day: {lemma}. It means: {gloss}.",
    "uk": "Слово дня: {lemma}. Це означає: {gloss}.",
}
OUTRO = {
    "ru": "А теперь повторим быстро все примеры.",
    "en": "Now let's review all the examples quickly.",
    "uk": "А тепер повторимо швидко всі приклади.",
}


def build_segments(word: Word, interface_lang: str) -> list[Segment]:
    lang = interface_lang if interface_lang in INTRO else "ru"
    segs: list[Segment] = []

    # Intro in the interface language.
    segs.append(Segment(INTRO[lang].format(lemma=word.target_lemma, gloss=word.gloss),
                        lang, pause_after=0.7))
    # The word: slow, then natural.
    segs.append(Segment(word.target_lemma, "pt", slow=True, pause_after=0.4))
    segs.append(Segment(word.target_lemma, "pt", slow=False, pause_after=0.8))

    # 10 (or however many) contextual variations. Each: context label ->
    # natural pt -> slow pt (so the ear catches it) -> interface gloss.
    for v in word.variations:
        if v.context_label:
            segs.append(Segment(v.context_label, lang, pause_after=0.3))
        segs.append(Segment(v.pt_sentence, "pt", pause_after=0.4))
        segs.append(Segment(v.pt_sentence, "pt", slow=True, pause_after=0.5))
        segs.append(Segment(v.gloss_sentence, lang, pause_after=0.8))

    # Outro: quick recap of the pt sentences only.
    segs.append(Segment(OUTRO[lang], lang, pause_after=0.5))
    for v in word.variations:
        segs.append(Segment(v.pt_sentence, "pt", pause_after=0.3))

    return segs


def build_phrase_segments(phrases: list[dict], interface_lang: str) -> list[Segment]:
    """Audio for an ad-hoc set of phrases (e.g. a survival set), not a saved word.

    Each phrase: ``{"pt": ..., "gloss": ..., "context": ...}``. Rendered as
    context -> pt natural -> pt slow -> gloss, so the learner can just listen.
    """
    lang = interface_lang if interface_lang in INTRO else "ru"
    segs: list[Segment] = []
    for p in phrases:
        if p.get("context"):
            segs.append(Segment(p["context"], lang, pause_after=0.3))
        segs.append(Segment(p["pt"], "pt", pause_after=0.4))
        segs.append(Segment(p["pt"], "pt", slow=True, pause_after=0.5))
        if p.get("gloss"):
            segs.append(Segment(p["gloss"], lang, pause_after=0.7))
    return segs
