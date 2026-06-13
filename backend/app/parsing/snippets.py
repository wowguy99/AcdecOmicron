"""Extract readable snippets from parsed subsection body text."""
from __future__ import annotations

import re

_EMPTY = "(empty)"
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _split_sentences(text: str) -> list[str]:
    normalized = text.replace("\n", " ").strip()
    if not normalized:
        return []
    parts = _SENTENCE_SPLIT.split(normalized)
    return [p.strip() for p in parts if p.strip()]


def first_last_sentences(text: str, *, max_len: int = 200) -> tuple[str, str]:
    """Return the first and last sentence from *text*, truncated if needed."""
    sentences = _split_sentences(text or "")
    if not sentences:
        return _EMPTY, _EMPTY
    first = _truncate(sentences[0], max_len)
    last = _truncate(sentences[-1], max_len)
    return first, last
