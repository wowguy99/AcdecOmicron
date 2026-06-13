"""Stable card identity, deduplication, and bottom-up CSV compilation."""
from __future__ import annotations

import csv
import hashlib
import io
import re
import sqlite3
from typing import Any

# Track A = body cards only. Master (Track B) = body + caption cards.

# Windows filename limit (path component, including extension).
WINDOWS_MAX_FILENAME = 255
_TRACK_SUFFIX = {"A": "_TextOnly", "master": "_Master"}
_FILENAME_PART_RE = re.compile(r"[^\w\s-]", re.UNICODE)


def sanitize_filename_part(text: str) -> str:
    """Make one filename segment safe; collapse whitespace to underscores."""
    s = (text or "").strip()
    s = _FILENAME_PART_RE.sub("_", s)
    s = re.sub(r"[\s_]+", "_", s).strip("_")
    return s or "untitled"


def build_csv_filename(
    subject: str,
    section: str | None = None,
    topic: str | None = None,
    track: str = "A",
) -> str:
    """Build ``Subject_Section_Topic_TextOnly.csv`` (omit empty section/topic).

    Truncates the joined base name so the full filename fits Windows limits.
    """
    suffix = _TRACK_SUFFIX.get(track, "_TextOnly")
    ext = ".csv"
    budget = WINDOWS_MAX_FILENAME - len(suffix) - len(ext)

    parts = [sanitize_filename_part(subject)]
    if section:
        parts.append(sanitize_filename_part(section))
    if topic:
        parts.append(sanitize_filename_part(topic))

    joined = "_".join(parts)
    if len(joined) > budget:
        if len(parts) == 1:
            joined = joined[:budget].rstrip("_")
        else:
            sep_budget = budget - (len(parts) - 1)
            per_part = max(1, sep_budget // len(parts))
            trimmed = [p[:per_part].rstrip("_") or "x" for p in parts]
            joined = "_".join(trimmed)
            if len(joined) > budget:
                joined = joined[:budget].rstrip("_")

    return f"{joined}{suffix}{ext}"


def resolve_node_filename_parts(
    conn: sqlite3.Connection, node_id: int
) -> tuple[str, str | None, str | None]:
    """Map a tree node to subject / section / topic labels for export filenames."""
    node = conn.execute(
        "SELECT n.title, n.tier, n.parent_id, s.name AS subject_name "
        "FROM nodes n JOIN subjects s ON s.id = n.subject_id WHERE n.id = ?",
        (node_id,),
    ).fetchone()
    if not node:
        return "deck", None, None

    subject = node["subject_name"]
    if node["tier"] == "section":
        return subject, node["title"], None

    if node["tier"] == "subheader" and node["parent_id"]:
        parent = conn.execute(
            "SELECT title FROM nodes WHERE id = ?", (node["parent_id"],)
        ).fetchone()
        return subject, parent["title"] if parent else None, node["title"]

    return subject, node["title"], None


def card_hash(front: str, back: str) -> str:
    norm = lambda s: re.sub(r"\s+", " ", s).strip().lower()
    return hashlib.sha1(f"{norm(front)}||{norm(back)}".encode("utf-8")).hexdigest()


def _normalize_for_search(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


_WORD_RE = re.compile(r"[a-z0-9]+", re.I)


def _text_tokens(text: str) -> set[str]:
    return set(_WORD_RE.findall(_normalize_for_search(text)))


def _all_literal_positions(norm_source: str, fragment: str) -> list[int]:
    """Every start offset of *fragment* (or a long prefix) in normalized source."""
    norm_frag = _normalize_for_search(fragment)
    if not norm_frag or len(norm_frag) < 3:
        return []
    found: set[int] = set()
    start = 0
    while True:
        idx = norm_source.find(norm_frag, start)
        if idx < 0:
            break
        found.add(idx)
        start = idx + 1
    words = norm_frag.split()
    for length in range(len(words), 2, -1):
        prefix = " ".join(words[:length])
        if len(prefix) < 4:
            continue
        start = 0
        while True:
            idx = norm_source.find(prefix, start)
            if idx < 0:
                break
            found.add(idx)
            start = idx + 1
    return sorted(found)


def _best_sentence_position(
    card: dict[str, str], source_text: str, norm_source: str
) -> int:
    """Token-overlap anchor for non-literal backs (attribution, list cards)."""
    bt = _text_tokens(card.get("back", "")) | _text_tokens(card.get("front", ""))
    if not bt:
        return -1
    best_pos = -1
    best_score = 0
    cursor = 0
    for sent in re.split(r"(?<=[.!?])\s+", source_text):
        if not sent.strip():
            continue
        st = _text_tokens(sent)
        if not st:
            continue
        score = len(bt & st)
        if score > best_score:
            ns = _normalize_for_search(sent)
            idx = norm_source.find(ns[: min(len(ns), 48)], cursor)
            if idx < 0 and ns.split():
                idx = norm_source.find(ns.split()[0], cursor)
            if idx >= 0:
                best_score = score
                best_pos = idx
        cursor += len(sent) + 1
    return best_pos if best_score >= 2 else -1


def source_position_for_card(
    card: dict[str, str], source_text: str, *, norm_source: str | None = None
) -> int:
    """Best-effort character offset in normalized source for PDF-order checks."""
    if not source_text.strip():
        return -1
    norm = norm_source if norm_source is not None else _normalize_for_search(source_text)
    back = card.get("back", "")
    front = card.get("front", "")

    for fragment in (back, front):
        positions = _all_literal_positions(norm, fragment)
        if positions:
            return positions[0]

    sent_pos = _best_sentence_position(card, source_text, norm)
    if sent_pos >= 0:
        return sent_pos
    return -1


def order_cards_by_source_text(
    cards: list[dict[str, str]], source_text: str
) -> list[dict[str, str]]:
    """Reorder cards to match top-to-bottom fact order in *source_text*."""
    if not cards or not source_text.strip():
        return cards
    norm = _normalize_for_search(source_text)
    tail = len(norm)
    scored: list[tuple[int, int, dict[str, str]]] = []
    for orig_i, card in enumerate(cards):
        pos = source_position_for_card(card, source_text, norm_source=norm)
        sort_key = pos if pos >= 0 else tail + orig_i
        scored.append((sort_key, orig_i, card))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [card for _, _, card in scored]


def detect_order_inversions(
    cards: list[dict[str, Any]], source_text: str, *, min_gap: int = 15
) -> dict[int, dict[str, str]]:
    """Return ``out_of_order`` flags for cards that invert PDF position vs prior card."""
    if len(cards) < 2 or not source_text.strip():
        return {}
    norm = _normalize_for_search(source_text)
    flags: dict[int, dict[str, str]] = {}
    prev_pos = -1
    for card in cards:
        cid = card.get("id")
        if cid is None:
            continue
        pos = source_position_for_card(card, source_text, norm_source=norm)
        if pos >= 0 and prev_pos >= 0 and pos + min_gap < prev_pos:
            flags[cid] = {
                "code": "out_of_order",
                "severity": "warn",
                "message": (
                    "This card's fact appears earlier in the source text than "
                    "the previous card — PDF reading order may be wrong."
                ),
            }
        if pos >= 0:
            prev_pos = max(prev_pos, pos)
    return flags


def reorder_node_cards_in_db(
    conn: sqlite3.Connection, node_id: int, track: str
) -> None:
    """Assign node-level ``card_index`` for all cards on *node_id* + *track*."""
    node = conn.execute(
        "SELECT body_text, caption_text FROM nodes WHERE id = ?", (node_id,)
    ).fetchone()
    if not node:
        return
    source = (node["body_text"] or "") if track == "A" else (node["caption_text"] or "")
    if not source.strip():
        return
    rows = conn.execute(
        """
        SELECT c.id, c.front, c.back, c.tag
        FROM cards c
        WHERE c.node_id = ? AND c.track = ? AND c.deleted = 0
        ORDER BY COALESCE(
            (SELECT ch.idx FROM chunks ch WHERE ch.id = c.chunk_id), 999
        ), c.id
        """,
        (node_id, track),
    ).fetchall()
    if not rows:
        return
    cards = [
        {"id": r["id"], "front": r["front"], "back": r["back"], "tag": r["tag"]}
        for r in rows
    ]
    ordered = order_cards_by_source_text(cards, source)
    for idx, card in enumerate(ordered):
        conn.execute(
            "UPDATE cards SET card_index = ? WHERE id = ?", (idx, card["id"])
        )


def reorder_chunk_cards_in_db(conn: sqlite3.Connection, chunk_id: int, source_text: str) -> None:
    """Legacy chunk reorder — delegates to node-level when chunk is known."""
    row = conn.execute(
        "SELECT node_id, track FROM chunks WHERE id = ?", (chunk_id,)
    ).fetchone()
    if row:
        reorder_node_cards_in_db(conn, row["node_id"], row["track"])
        return
    rows = conn.execute(
        "SELECT id, front, back, tag FROM cards "
        "WHERE chunk_id = ? AND deleted = 0 ORDER BY id",
        (chunk_id,),
    ).fetchall()
    if not rows:
        return
    cards = [{"id": r["id"], "front": r["front"], "back": r["back"], "tag": r["tag"]} for r in rows]
    ordered = order_cards_by_source_text(cards, source_text)
    for idx, card in enumerate(ordered):
        conn.execute(
            "UPDATE cards SET card_index = ? WHERE id = ?", (idx, card["id"])
        )


# PDF reading order: section → subheader → body before captions → chunk → card.
CARD_ORDER_FROM = """
FROM cards c
JOIN nodes n ON n.id = c.node_id
LEFT JOIN nodes parent ON parent.id = n.parent_id
LEFT JOIN chunks ch ON ch.id = c.chunk_id
"""

CARD_ORDER_BY = """
ORDER BY
  COALESCE(parent.order_index, n.order_index),
  CASE WHEN n.parent_id IS NOT NULL THEN n.order_index ELSE -1 END,
  COALESCE(n.start_page, 0),
  COALESCE(n.start_line, 0),
  CASE c.track WHEN 'A' THEN 0 ELSE 1 END,
  c.card_index,
  COALESCE(ch.idx, -1),
  c.id
"""


def track_filter_sql(track: str) -> str:
    return "" if track == "master" else "AND c.track = 'A'"


def _dedupe_export_rows(rows) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for r in rows:
        h = r["card_hash"]
        if h in seen:
            continue
        seen.add(h)
        out.append({"front": r["front"], "back": r["back"], "tag": r["tag"]})
    return out


def _descendant_node_ids(conn: sqlite3.Connection, node_id: int) -> list[int]:
    ids = [node_id]
    frontier = [node_id]
    while frontier:
        nid = frontier.pop()
        rows = conn.execute(
            "SELECT id FROM nodes WHERE parent_id = ?", (nid,)
        ).fetchall()
        for r in rows:
            ids.append(r["id"])
            frontier.append(r["id"])
    return ids


def collect_cards(
    conn: sqlite3.Connection, node_id: int, track: str
) -> list[dict[str, str]]:
    """Return deduped cards for a node + track in PDF reading order.

    ``track`` == 'A' -> only Track A cards. 'master' -> Track A + Track B.
    """
    node_ids = _descendant_node_ids(conn, node_id)
    placeholders = ",".join("?" for _ in node_ids)
    rows = conn.execute(
        f"""
        SELECT c.front, c.back, c.tag, c.card_hash
        {CARD_ORDER_FROM}
        WHERE c.node_id IN ({placeholders}) AND c.deleted = 0 {track_filter_sql(track)}
        {CARD_ORDER_BY}
        """,
        node_ids,
    ).fetchall()
    return _dedupe_export_rows(rows)


def collect_subject_cards(
    conn: sqlite3.Connection, subject_id: int, track: str
) -> list[dict[str, str]]:
    """Return deduped cards for an entire subject in PDF reading order."""
    rows = conn.execute(
        f"""
        SELECT c.front, c.back, c.tag, c.card_hash
        {CARD_ORDER_FROM}
        WHERE c.deleted = 0 {track_filter_sql(track)}
          AND c.node_id IN (SELECT id FROM nodes WHERE subject_id = ?)
        {CARD_ORDER_BY}
        """,
        (subject_id,),
    ).fetchall()
    return _dedupe_export_rows(rows)


def cards_to_csv(cards: list[dict[str, str]]) -> str:
    """Plain 3-column Front,Back,Tag CSV. Fully quoted so commas/newlines/HTML
    in fields survive Anki import (comma separator, enable 'Allow HTML')."""
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writerow(["Front", "Back", "Tag"])
    for c in cards:
        writer.writerow([c["front"], c["back"], c["tag"]])
    return buf.getvalue()
