"""Offline flashcard checks against source text (no AI provider calls)."""
from __future__ import annotations

import re
from typing import Any

_WORD_RE = re.compile(r"[a-z0-9]+", re.I)
_NUM_RE = re.compile(r"\b\d[\d,.:/%-]*\b")
# Flashcard list backs: "1. Foo, 2. Bar" or newline-separated "1. Foo\n2. Bar"
_LIST_ENUMERATOR_RE = re.compile(r"(?:^|[\n,;])\s*\d+\.\s+", re.MULTILINE)
_COMPARATIVE_RE = re.compile(
    r"\b(most|least|highest|lowest|greatest|more|less|greater|smaller|larger|"
    r"differs?|unlike|versus|vs\.|compared to|compared with|typical of|"
    r"rather than|instead of|in contrast|whereas)\b",
    re.I,
)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def tokens(text: str) -> set[str]:
    return set(_WORD_RE.findall(normalize(text)))


def extract_numbers(text: str) -> set[str]:
    return {m.group(0) for m in _NUM_RE.finditer(text or "")}


def _strip_list_enumerators(text: str) -> str:
    """Remove ordered-list markers (``1. ``, ``2. ``, …) from flashcard backs."""
    return _LIST_ENUMERATOR_RE.sub(" ", text or "")


def extract_back_numbers(back: str) -> set[str]:
    """Extract substantive numbers from a card back, ignoring list enumerators."""
    return extract_numbers(_strip_list_enumerators(back))


def grounding_ratio(back: str, source: str) -> float:
    bt = tokens(back)
    if not bt:
        return 0.0
    st = tokens(source)
    return len(bt & st) / len(bt)


def back_restates_front(front: str, back: str) -> bool:
    ft, bt = tokens(front), tokens(back)
    if not bt or not ft:
        return False
    return len(bt & ft) / len(bt) > 0.85


def is_suspect_comparative(front: str, back: str, source: str) -> bool:
    return bool(_COMPARATIVE_RE.search(f"{front} {back} {source}"))


def find_source_snippet(back: str, source: str, window: int = 220) -> str:
    """Return the source sentence/region that best matches the card back."""
    if not source:
        return ""
    if not back.strip():
        return source[:window].strip()

    sentences = re.split(r"(?<=[.!?])\s+", source)
    bt = tokens(back)
    best = ""
    best_score = 0
    for sent in sentences:
        st = tokens(sent)
        if not st:
            continue
        score = len(bt & st)
        if score > best_score:
            best_score = score
            best = sent.strip()
    if best_score >= 2:
        return best[:500]

    words = normalize(back).split()
    norm_source = normalize(source)
    for length in range(min(len(words), 8), 2, -1):
        for i in range(len(words) - length + 1):
            phrase = " ".join(words[i : i + length])
            idx = norm_source.find(phrase)
            if idx >= 0:
                start = max(0, idx - 60)
                return source[start : start + window].strip()
    return source[:window].strip()


def check_card(card: dict[str, Any], source: str) -> dict[str, Any]:
    """Run deterministic checks for one card against its source text."""
    front = card.get("front", "")
    back = card.get("back", "")
    source_text = source or ""
    flags: list[dict[str, str]] = []

    if not front.strip():
        flags.append(
            {"code": "empty_front", "severity": "error", "message": "Front is empty."}
        )
    if not back.strip():
        flags.append(
            {"code": "empty_back", "severity": "error", "message": "Back is empty."}
        )
    if back_restates_front(front, back):
        flags.append(
            {
                "code": "restates_front",
                "severity": "warn",
                "message": "Back largely restates the front.",
            }
        )

    ratio: float | None = None
    if source_text:
        ratio = grounding_ratio(back, source_text)
        if card.get("source") == "ai":
            if ratio < 0.35:
                flags.append(
                    {
                        "code": "ungrounded",
                        "severity": "warn",
                        "message": (
                            f"Only {int(ratio * 100)}% of answer tokens appear in "
                            "source text."
                        ),
                    }
                )
            elif ratio < 0.55:
                flags.append(
                    {
                        "code": "weak_grounding",
                        "severity": "info",
                        "message": (
                            f"Moderate grounding ({int(ratio * 100)}% token overlap)."
                        ),
                    }
                )

            back_nums = extract_back_numbers(back)
            source_nums = extract_numbers(source_text)
            missing = back_nums - source_nums
            if missing:
                flags.append(
                    {
                        "code": "number_mismatch",
                        "severity": "error",
                        "message": (
                            "Numbers not found in source: "
                            + ", ".join(sorted(missing))
                        ),
                    }
                )

    snippet = find_source_snippet(back, source_text)
    suspect_ai = card.get("source") == "ai" and (
        is_suspect_comparative(front, back, snippet or source_text)
        or any(f["code"] in ("ungrounded", "weak_grounding") for f in flags)
    )

    return {
        "flags": flags,
        "source_snippet": snippet,
        "grounding_ratio": ratio,
        "suspect_ai": suspect_ai,
    }
