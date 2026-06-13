"""Strip guide roadmap sentences that preview other sections (not testable facts)."""
from __future__ import annotations

import re

# Sentences that describe what the guide/another section will cover — not curriculum facts.
_GUIDE_NAV_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\bin\s+section\s+[IVXLC0-9]+\s+of\s+this\s+(?:resource\s+)?guide\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bsections?\s+[IVXLC0-9]+(?:\s+and\s+[IVXLC0-9]+)?\s+of\s+this\s+"
        r"(?:resource\s+)?guide\s+will\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bsection\s+[IVXLC0-9]+\s+will\s+"
        r"(?:explore|examine|cover|discuss|describe|address|establish)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bwill\s+be\s+the\s+subject\s+of\s+section\s+[IVXLC0-9]+\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bthe\s+final\s+section\s+of\s+(?:the\s+)?(?:resource\s+)?guide\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bthis\s+(?:resource\s+)?guide\s+will\s+"
        r"(?:explore|examine|cover|discuss|describe)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bnext\s+(?:part|section)\s+of\s+(?:our\s+)?(?:discussion|the\s+guide)\s+will\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bwe\s+will\s+(?:establish|examine|explore|discuss|describe|turn\s+to)\s+"
        r"(?:some\s+)?(?:key\s+)?(?:concepts|sources|themes|topics)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bwhat\s+(?:will|does)\s+section\s+[IVXLC0-9]+\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bsection\s+[IVXLC0-9]+\s+of\s+this\s+(?:resource\s+)?guide\s+will\b",
        re.IGNORECASE,
    ),
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def is_guide_navigation_sentence(text: str) -> bool:
    """True when *text* is roadmap prose about guide structure, not a curriculum fact."""
    stripped = re.sub(r"\s+", " ", (text or "").strip())
    if not stripped or len(stripped) < 20:
        return False
    return any(p.search(stripped) for p in _GUIDE_NAV_PATTERNS)


def is_guide_navigation_card(front: str, back: str) -> bool:
    """True when a flashcard only restates guide/section preview prose."""
    combined = f"{front} {back}"
    if is_guide_navigation_sentence(combined):
        return True
    low = combined.lower()
    if "resource guide" in low and re.search(
        r"\bwill\s+(?:describe|examine|cover|explore|discuss|establish)\b", low
    ):
        return True
    if re.search(
        r"\bsection\s+[IVXLC0-9]+\s+(?:of\s+this\s+guide\s+)?will\s+"
        r"(?:describe|examine|cover|explore)",
        low,
    ):
        return True
    return False


def strip_guide_navigation(body_text: str) -> str:
    """Remove guide roadmap sentences from subsection body source text."""
    if not body_text or not body_text.strip():
        return body_text or ""
    flat = re.sub(r"\s+", " ", body_text.replace("\n", " "))
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(flat) if s.strip()]
    if not sentences:
        return body_text.strip()
    kept = [s for s in sentences if not is_guide_navigation_sentence(s)]
    if len(kept) == len(sentences):
        return body_text.strip()
    return " ".join(kept).strip()


def filter_navigation_cards(
    cards: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Drop AI cards that only encode guide structure previews."""
    return [
        c
        for c in cards
        if not is_guide_navigation_card(c.get("front", ""), c.get("back", ""))
    ]
