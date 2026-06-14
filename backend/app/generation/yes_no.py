"""Rewrite yes/no flashcards into substantive-answer cards when appropriate."""
from __future__ import annotations

import re

_CLASSIFICATION_RE = re.compile(
    r"^(?:was|were|is|are)\s+.+\s+(?:a|an)\s+",
    re.IGNORECASE,
)

_OCCURRENCE_RE = re.compile(
    r"\b(?:occur(?:red|s)?|happened|happen|take place|took place|exists|exist)\b",
    re.IGNORECASE,
)

_BINARY_TYPE_RE = re.compile(
    r"\b(?:a|an)\s+(?:\w+\s+,?\s*)*(?:single|unified|one|distinct|separate|same|different|true|false)\b",
    re.IGNORECASE,
)

_AUX_RE = re.compile(r"^(Did|Was|Were|Does|Do|Is|Are)\s+", re.IGNORECASE)

ADVERB_ANTONYMS: dict[str, str] = {
    "evenly": "unevenly",
    "uniformly": "variably",
    "entirely": "partially",
    "completely": "partially",
    "fully": "partially",
    "wholly": "partially",
    "always": "sometimes",
    "never": "sometimes",
    "solely": "also",
    "exclusively": "also",
    "equally": "unequally",
    "symmetrically": "asymmetrically",
    "consistently": "inconsistently",
}

_OPEN_AUX: dict[str, str] = {
    "did": "How did",
    "was": "How was",
    "were": "How were",
    "does": "How does",
    "do": "How do",
    "is": "How is",
    "are": "How are",
}


def _normalize_yes_no(back: str) -> str | None:
    cleaned = back.strip().lower().rstrip(".!")
    if cleaned in ("yes", "no"):
        return cleaned
    return None


def _should_keep_yes_no(front: str) -> bool:
    text = front.strip()
    if _CLASSIFICATION_RE.match(text):
        return True
    if _OCCURRENCE_RE.search(text):
        return True
    if _BINARY_TYPE_RE.search(text):
        return True
    return False


def _find_manner_adverb(front: str) -> str | None:
    lower = front.lower()
    for adv in sorted(ADVERB_ANTONYMS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(adv)}\b", lower):
            return adv
    return None


def _open_front(front: str, adverb: str) -> str:
    text = front.strip().rstrip("?").strip()
    text = re.sub(rf"\b{re.escape(adverb)}\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip().rstrip(",").strip()

    match = _AUX_RE.match(text)
    if match:
        aux = match.group(1).lower()
        rest = text[match.end() :].strip()
        opener = _OPEN_AUX.get(aux, "How did")
        return f"{opener} {rest}?"

    return f"{text}?"


def _substantive_back(adverb: str, *, is_yes: bool) -> str | None:
    key = adverb.lower()
    if key not in ADVERB_ANTONYMS:
        return None
    if is_yes:
        return adverb.capitalize()
    return ADVERB_ANTONYMS[key].capitalize()


def _rewrite_card(front: str, back: str) -> tuple[str, str] | None:
    yn = _normalize_yes_no(back)
    if yn is None or _should_keep_yes_no(front):
        return None
    adverb = _find_manner_adverb(front)
    if not adverb:
        return None
    new_back = _substantive_back(adverb, is_yes=(yn == "yes"))
    if not new_back:
        return None
    return _open_front(front, adverb), new_back


def enhance_yes_no_cards(cards: list[dict[str, str]]) -> list[dict[str, str]]:
    """Return cards with high-confidence yes/no rewrites applied."""
    out: list[dict[str, str]] = []
    for card in cards:
        rewritten = _rewrite_card(card.get("front", ""), card.get("back", ""))
        if rewritten:
            new_front, new_back = rewritten
            out.append({**card, "front": new_front, "back": new_back})
        else:
            out.append(dict(card))
    return out
