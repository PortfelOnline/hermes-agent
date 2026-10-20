"""Translate the reasoning block shown to the user into ``display.language``.

Providers such as Codex produce reasoning summaries with their own summarizer, so the system
prompt cannot force their language. The stored ``last_reasoning`` stays untouched; only the text
rendered into the reply is translated (task ``reasoning_translation`` under ``auxiliary:``).
"""
from __future__ import annotations

import logging

from agent.i18n import get_language
from agent.i18n_languages import BUNDLED_LANGUAGE_INFO

logger = logging.getLogger(__name__)

_LATIN_SHARE_THRESHOLD = 0.7
_MAX_CHARS = 6000
_PROMPT = (
    "Translate the text into {language} (language id: {lang}). Keep markdown markers such as ** and "
    "line breaks exactly as they are, keep code, identifiers, paths and commands unchanged. "
    "Reply with the translation only."
)


def needs_translation(text: str, lang: str) -> bool:
    """Only English-looking text is translated, and only for a non-English display language."""
    if not text or lang == "en":
        return False
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return False
    latin = sum(1 for ch in letters if ch.isascii())
    return latin / len(letters) >= _LATIN_SHARE_THRESHOLD


def translate_reasoning(text: str) -> str:
    """Blocking; returns *text* unchanged when no translation is needed or the call fails."""
    lang = get_language()
    if not needs_translation(text, lang):
        return text
    from agent.auxiliary_client import call_llm, extract_content_or_reasoning
    language = BUNDLED_LANGUAGE_INFO.get(lang, (lang, False))[0]
    try:
        response = call_llm(
            task="reasoning_translation",
            messages=[
                {"role": "system", "content": _PROMPT.format(language=language, lang=lang)},
                {"role": "user", "content": text[:_MAX_CHARS]},
            ],
            max_tokens=2000, timeout=25,
        )
        translated = (extract_content_or_reasoning(response) or "").strip()
    except Exception as exc:
        logger.warning("reasoning translation failed, showing original: %s", exc)
        return text
    return translated or text
