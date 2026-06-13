"""Batched AI verification for suspect flashcards (one call per source chunk)."""
from __future__ import annotations

import json
import re
from typing import Any

VALIDATION_SYSTEM = (
    "You are a flashcard fact-checker for Academic Decathlon study guides. "
    "Given source text and flashcards, verify each card's BACK is factually "
    "supported by the source.\n"
    "Pay special attention to comparative and superlative claims — verify "
    "which noun is the true subject of the claim (e.g. 'mental maps embody the "
    "highest distortion, typical of thematic maps' means mental maps are most "
    "distorted, not thematic maps).\n"
    "Return ONLY valid JSON, no markdown fences: "
    '{"results":[{"id":<card_id>,"verdict":"ok"|"error","message":"..."}]}'
)


def build_validation_prompt(source: str, cards: list[dict[str, Any]]) -> str:
    payload = [
        {"id": c["id"], "front": c["front"], "back": c["back"]} for c in cards
    ]
    return (
        "Verify each card below against the SOURCE TEXT only. "
        "Mark verdict 'error' if the back misattributes a claim, inverts "
        "subject/comparison, contradicts the source, or adds facts not present.\n\n"
        f"SOURCE TEXT:\n{source}\n\n"
        f"CARDS:\n{json.dumps(payload, indent=2)}"
    )


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_validation_response(raw: str) -> dict[int, dict[str, str]]:
    text = raw.strip()
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    obj = json.loads(text)
    results = obj.get("results", []) if isinstance(obj, dict) else []
    out: dict[int, dict[str, str]] = {}
    for row in results:
        if not isinstance(row, dict):
            continue
        cid = row.get("id")
        verdict = str(row.get("verdict", "")).strip().lower()
        if cid is None or verdict not in ("ok", "error"):
            continue
        out[int(cid)] = {
            "verdict": verdict,
            "message": str(row.get("message", "")).strip(),
        }
    return out
