"""Deterministic card extraction for GLOSSARY and TIMELINE sections.

These sections are pre-structured (term -> definition; date -> event), so we
parse them directly into cards with zero AI calls and zero hallucination.
"""
from __future__ import annotations

import re

_GLOSSARY_SEP = re.compile(r"^(.{1,60}?)\s[\u2013\u2014]\s(.+)$")
_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|"
    "November|December"
)
_YEAR = re.compile(r"^\d{3,4}\s*[\u2013\-]?\s*\d{0,4}$")
_MONTH_LINE = re.compile(rf"^({_MONTHS})\b[\s\d,]*$", re.IGNORECASE)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _looks_like_term(left: str) -> bool:
    words = left.split()
    return 1 <= len(words) <= 6


def parse_glossary(text: str) -> list[tuple[str, str]]:
    """Return (term, definition) pairs."""
    entries: list[tuple[str, str]] = []
    term: str | None = None
    buf: list[str] = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line or _norm(line) == "glossary":
            continue
        m = _GLOSSARY_SEP.match(line)
        if m and _looks_like_term(m.group(1)):
            if term:
                entries.append((term, " ".join(buf).strip()))
            term = m.group(1).strip()
            buf = [m.group(2).strip()]
        elif term:
            buf.append(line)
    if term and buf:
        entries.append((term, " ".join(buf).strip()))
    return [(t, d) for t, d in entries if d]


def _is_date_line(line: str) -> bool:
    if _YEAR.match(line):
        return True
    if _MONTH_LINE.match(line) and len(line) <= 25:
        return True
    return False


def parse_timeline(text: str) -> list[tuple[str, str]]:
    """Return (date, event) pairs."""
    entries: list[tuple[str, str]] = []
    date_parts: list[str] = []
    event_parts: list[str] = []

    def flush() -> None:
        if date_parts and event_parts:
            date = " ".join(date_parts).strip().rstrip(",")
            event = " ".join(event_parts).strip()
            if event:
                entries.append((date, event))

    for raw in text.split("\n"):
        line = raw.strip()
        if not line or _norm(line) == "timeline":
            continue
        if _is_date_line(line):
            # A date after we've collected an event starts a new entry.
            if event_parts:
                flush()
                date_parts, event_parts = [], []
            date_parts.append(line)
        else:
            event_parts.append(line)
    flush()
    return entries


def glossary_cards(text: str) -> list[tuple[str, str]]:
    """(front, back) cards from a glossary section."""
    return [(f"Define: {term}", definition) for term, definition in parse_glossary(text)]


def timeline_cards(text: str) -> list[tuple[str, str]]:
    """(front, back) cards from a timeline section."""
    return [
        (f"What happened in {date}?", event) for date, event in parse_timeline(text)
    ]


_YEAR_SUFFIX_RE = re.compile(
    r"\s*\(\s*(?:before\s+\d{4}|\d{4}(?:\s*[–—-]\s*\d{2,4})?)\s*\)\s*$",
    re.IGNORECASE,
)


def _piece_name_for_year_card(title: str) -> str:
    return _YEAR_SUFFIX_RE.sub("", title.strip()).strip()


def piece_year_cards(
    title: str, year: str, piece_type: str
) -> list[tuple[str, str]]:
    """One card asking the work/song year when a year is known."""
    name = _piece_name_for_year_card(title)
    if not name or not year:
        return []
    if piece_type == "listening_companion":
        front = f'What year is "{name}" from?'
    else:
        front = f"When was {name} made?"
    return [(front, year)]
