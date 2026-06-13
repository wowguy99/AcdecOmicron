"""Prompt construction and tolerant JSON parsing for card extraction."""
from __future__ import annotations

import json
import re
from typing import Any

SYSTEM_PROMPT = (
    "You are an expert Academic Decathlon study-aid creator. You convert "
    "curriculum text into ATOMIC flashcards. Academic Decathlon tests obscure "
    "details, so you must be EXHAUSTIVE and lossless: every testable statistic, "
    "date, name, definition, cause, effect, list item, illustrative example, "
    "comparative claim, and source attribution becomes its own card.\n"
    "Rules:\n"
    "1. Each card tests exactly ONE fact. Fronts are short, direct questions; "
    "backs are the bare answer only (a word, phrase, or one short clause). "
    "Do NOT add explanations, purpose clauses (\"used to...\", \"in order to\"), "
    "or restate the question. If a definition has multiple testable parts, split "
    "into multiple cards — never cram them into one long back.\n"
    "2. For list facts, the front asks to name the N items and the back is a "
    "numbered list (list cards are exempt from the short-back rule).\n"
    "3. Illustrative examples and scenarios in the text ARE testable. Turn each "
    "into an application card (e.g. front: \"Give an example of relative location "
    "from the text.\" back: the example only). Include narrative illustrations "
    "(e.g. a geographer tracing migration at local, regional, and global scales).\n"
    "4. Comparative, superlative, and relational statements are their own cards. "
    "Capture claims with most, highest, greatest, least, differs from, unlike, "
    "compared to, more/less than, versus, or contrasts between types (e.g. "
    "world-map scale vs. local-map scale; which map type is most abstract).\n"
    "5. Source attributions are testable. When the text attributes a fact, "
    "claim, definition, figure, or position to a NAMED source (a person, "
    "organization, agency, study, report, or law — e.g. \"According to the "
    "IUGS...\", \"the IPCC reports...\", \"Smith argues...\"), create an "
    "ADDITIONAL card asking who the source is, SEPARATE from the card testing "
    "the underlying fact. Front names the fact and asks for the source; back is "
    "the source only (e.g. front: \"According to whom did the Holocene begin "
    "about 11,700 years ago?\" back: \"the International Union of Geological "
    "Sciences (IUGS)\"). Skip vague attributions like \"scientists say\" or "
    "\"some historians\" with no named source.\n"
    "6. Do NOT summarize, editorialize, or invent facts not in the text.\n"
    "7. Assign each card EXACTLY ONE tag from the provided tag list. If a card "
    "could fit two tags, choose the more specific one. If it fits none, use "
    "\"other\".\n"
    "8. Do NOT create cards for guide navigation or roadmap sentences — text that "
    "only says what a section of this resource guide will cover later (e.g. "
    "\"Section II of this guide will describe…\", \"we will examine the sources "
    "in this section\"). Those are not testable curriculum facts.\n"
    "9. Return cards in the same order facts appear in the source text "
    "(top to bottom).\n"
    "10. Return ONLY valid JSON, no markdown fences, in this schema: "
    '{"cards":[{"front":"...","back":"...","tag":"..."}]}'
)


def build_user_prompt(
    subject: str,
    section: str,
    subheader: str,
    tags: list[tuple[str, str]],
    track: str,
    text: str,
) -> str:
    tag_lines = "\n".join(f'- "{name}": {definition or "(no description)"}' for name, definition in tags)
    source = (
        "image/figure caption text" if track == "B" else "main body text"
    )
    return (
        f"Subject: {subject}\nSection: {section}\nSubheader: {subheader}\n"
        f"Source type: {source}\n\n"
        f"Allowed tags (assign exactly one per card):\n{tag_lines}\n- \"other\"\n\n"
        "Extract every atomic, testable fact from the text below into cards. "
        "Include illustrative examples, narrative scenarios, comparative or "
        "superlative claims, and source attributions (who a named person, "
        "organization, study, or law is credited with) — each as its own card "
        "with a short back. Skip guide roadmap sentences that only preview what "
        "another section will discuss.\n\n"
        f"TEXT:\n{text}"
    )


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _card_field(card: dict, *keys: str) -> str:
    for key in keys:
        for name in (key, key.lower(), key.capitalize(), key.upper()):
            if name not in card or card[name] is None:
                continue
            value = card[name]
            if isinstance(value, str):
                return value.strip()
            return str(value).strip()
    return ""


def _extract_cards_raw(obj: Any) -> list:
    if isinstance(obj, list):
        return obj
    if not isinstance(obj, dict):
        return []
    for key in ("cards", "flashcards", "flash_cards", "items", "data", "results"):
        val = obj.get(key)
        if isinstance(val, list):
            return val
        if isinstance(val, dict):
            nested = _extract_cards_raw(val)
            if nested:
                return nested
    return []


def _normalize_card_entry(entry: Any) -> dict[str, str] | None:
    if not isinstance(entry, dict):
        return None
    card = entry.get("card") if isinstance(entry.get("card"), dict) else entry
    if not isinstance(card, dict):
        return None
    front = _card_field(
        card, "front", "question", "prompt", "q", "term", "clue", "query"
    )
    back = _card_field(
        card, "back", "answer", "response", "a", "definition", "value", "reply"
    )
    tag = _card_field(card, "tag", "category", "label", "type") or "other"
    if front and back:
        return {"front": front, "back": back, "tag": tag}
    return None


_LISTENING_TIMESTAMP_RE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?\b")


def chunk_low_yield(text: str) -> bool:
    """True when chunk text is unlikely to produce study cards (e.g. listening timestamps)."""
    text = text.strip()
    if not text:
        return True
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return True
    timestamp_lines = sum(
        1 for ln in lines if _LISTENING_TIMESTAMP_RE.match(ln)
    )
    if timestamp_lines >= max(2, len(lines) // 2):
        return True
    if len(text) < 120 and timestamp_lines >= 1:
        return True
    return False


def parse_cards(raw: str) -> list[dict[str, str]]:
    """Tolerant parse: strip fences, find the JSON object, validate cards.

    Raises ValueError if nothing usable is found so the worker can retry.
    """
    text = raw.strip()
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    obj = _load_json_object(text)
    cards_raw = _extract_cards_raw(obj)
    out: list[dict[str, str]] = []
    for entry in cards_raw:
        normalized = _normalize_card_entry(entry)
        if normalized:
            out.append(normalized)
    return out


def _load_json_object(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Repair: take from first '{' to last '}' and retry.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        snippet = text[start : end + 1]
        try:
            return json.loads(snippet)
        except json.JSONDecodeError:
            # Last resort: drop a trailing truncated card and close the array.
            salvaged = _salvage_truncated(snippet)
            if salvaged is not None:
                return salvaged
    raise ValueError("no parsable JSON object found")


def _salvage_truncated(snippet: str) -> Any | None:
    """Close a truncated ``{"cards":[ ... ]}`` at the last complete object."""
    last = snippet.rfind("}")
    if last == -1:
        return None
    candidate = snippet[: last + 1] + "]}"
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None
