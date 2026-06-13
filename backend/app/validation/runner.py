"""Hybrid validation: deterministic checks first, AI only for suspect cards."""
from __future__ import annotations

from typing import Any

from ..config import load_config
from ..db.database import get_conn
from ..generation.compile import (
    CARD_ORDER_BY,
    CARD_ORDER_FROM,
    detect_order_inversions,
    reorder_node_cards_in_db,
    track_filter_sql,
)
from ..generation.providers import ProviderError, RateLimited, get_provider
from ..generation.worker import subtree_ids
from .ai_check import VALIDATION_SYSTEM, build_validation_prompt, parse_validation_response
from .deterministic import check_card


def _resolve_source(
    card: dict[str, Any],
    chunk_texts: dict[int, str],
    node_sources: dict[int, str],
) -> str:
    chunk_id = card.get("chunk_id")
    if chunk_id and chunk_id in chunk_texts:
        return chunk_texts[chunk_id]
    node_id = card.get("node_id")
    if node_id and node_id in node_sources:
        return node_sources[node_id]
    return ""


def _collect_cards(
    conn, node_id: int, track: str, *, include_reviewed: bool = False
) -> list[dict[str, Any]]:
    node_ids = subtree_ids(conn, node_id)
    ph = ",".join("?" for _ in node_ids)
    reviewed_filter = ""
    params: list[Any] = list(node_ids)
    if not include_reviewed:
        reviewed_filter = """
            AND NOT EXISTS (
                SELECT 1 FROM validation_progress vp
                WHERE vp.validation_node_id = ?
                  AND vp.card_id = c.id
                  AND vp.track = ?
            )
        """
        params.extend([node_id, track])
    rows = conn.execute(
        f"""
        SELECT c.id, c.node_id, c.chunk_id, c.front, c.back, c.tag, c.track, c.source
        {CARD_ORDER_FROM}
        WHERE c.node_id IN ({ph}) AND c.deleted = 0 {track_filter_sql(track)}
        {reviewed_filter}
        {CARD_ORDER_BY}
        """,
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def _count_reviewed(conn, node_id: int, track: str) -> int:
    return conn.execute(
        """
        SELECT COUNT(*) c FROM validation_progress vp
        JOIN cards c ON c.id = vp.card_id AND c.deleted = 0
        WHERE vp.validation_node_id = ? AND vp.track = ?
        """,
        (node_id, track),
    ).fetchone()["c"]


def _reviewed_card_ids(conn, node_id: int, track: str) -> set[int]:
    rows = conn.execute(
        """
        SELECT vp.card_id FROM validation_progress vp
        JOIN cards c ON c.id = vp.card_id AND c.deleted = 0
        WHERE vp.validation_node_id = ? AND vp.track = ?
        """,
        (node_id, track),
    ).fetchall()
    return {row["card_id"] for row in rows}


def _needs_manual_review(item: dict[str, Any], was_suspect: bool) -> bool:
    """True when a card should appear in the human walkthrough."""
    has_error = any(f["severity"] == "error" for f in item["flags"])
    has_warn = any(f["severity"] == "warn" for f in item["flags"])
    if item.get("ai_verdict") == "error":
        return True
    if has_error or has_warn:
        return True
    # Comparative / ambiguous cards sent to AI but not verified (e.g. no API key).
    if was_suspect and item.get("ai_verdict") is None:
        return True
    return False


def _load_sources(
    conn, cards: list[dict[str, Any]]
) -> tuple[dict[int, str], dict[int, str]]:
    chunk_ids = {c["chunk_id"] for c in cards if c.get("chunk_id")}
    node_ids = {c["node_id"] for c in cards}

    chunk_texts: dict[int, str] = {}
    if chunk_ids:
        ph = ",".join("?" for _ in chunk_ids)
        for row in conn.execute(
            f"SELECT id, text FROM chunks WHERE id IN ({ph})", list(chunk_ids)
        ).fetchall():
            chunk_texts[row["id"]] = row["text"]

    node_sources: dict[int, str] = {}
    if node_ids:
        ph = ",".join("?" for _ in node_ids)
        for row in conn.execute(
            f"SELECT id, body_text, caption_text FROM nodes WHERE id IN ({ph})",
            list(node_ids),
        ).fetchall():
            body = (row["body_text"] or "").strip()
            caps = (row["caption_text"] or "").strip()
            node_sources[row["id"]] = "\n".join(p for p in (body, caps) if p)

    return chunk_texts, node_sources


def _run_ai_checks(
    suspects_by_chunk: dict[int, list[dict[str, Any]]],
    chunk_texts: dict[int, str],
) -> tuple[dict[int, dict[str, str]], int, str | None]:
    cfg = load_config()
    if not cfg.api_key:
        return {}, 0, "No API key — skipped AI checks for suspect cards."

    if not suspects_by_chunk:
        return {}, 0, None

    provider = get_provider(cfg)
    merged: dict[int, dict[str, str]] = {}
    calls = 0
    warning: str | None = None

    with get_conn() as conn:
        today = conn.execute(
            "SELECT COUNT(*) c FROM request_log WHERE date(ts) = date('now')"
        ).fetchone()["c"]
        if today + len(suspects_by_chunk) > cfg.rpd:
            return (
                {},
                0,
                "Daily API quota too low for AI validation — deterministic checks only.",
            )

    for chunk_id, chunk_cards in suspects_by_chunk.items():
        source = chunk_texts.get(chunk_id, "")
        if not source:
            continue
        user = build_validation_prompt(source, chunk_cards)
        try:
            raw = provider.generate(VALIDATION_SYSTEM, user)
            merged.update(parse_validation_response(raw))
            calls += 1
            with get_conn() as conn:
                conn.execute("INSERT INTO request_log DEFAULT VALUES")
        except RateLimited:
            warning = "Rate limited during AI validation — partial AI results."
            break
        except (ProviderError, ValueError) as exc:
            warning = f"AI validation failed: {exc}"
            break

    return merged, calls, warning


def run_validation(node_id: int, track: str = "master") -> dict[str, Any]:
    """Validate all cards under ``node_id`` for the given export track."""
    if track not in ("A", "master"):
        raise ValueError("track must be 'A' or 'master'")

    with get_conn() as conn:
        root = conn.execute("SELECT id, title FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if not root:
            raise KeyError("node not found")

        reviewed_count = _count_reviewed(conn, node_id, track)
        reviewed_ids = _reviewed_card_ids(conn, node_id, track)
        cards = _collect_cards(conn, node_id, track, include_reviewed=True)
        total_count = len(cards)
        if not cards:
            return {
                "node_id": node_id,
                "title": root["title"],
                "track": track,
                "items": [],
                "issue_count": 0,
                "reviewed_count": reviewed_count,
                "total_count": 0,
                "auto_passed_count": 0,
                "flagged_count": 0,
                "ai_calls": 0,
                "warning": None,
            }

        chunk_texts, node_sources = _load_sources(conn, cards)
        node_bodies = conn.execute(
            f"""
            SELECT id, body_text, caption_text FROM nodes
            WHERE id IN ({",".join("?" for _ in {c["node_id"] for c in cards})})
            """,
            list({c["node_id"] for c in cards}),
        ).fetchall() if cards else []
        body_by_node = {r["id"]: (r["body_text"] or "") for r in node_bodies}
        caption_by_node = {r["id"]: (r["caption_text"] or "") for r in node_bodies}

        for nid in {c["node_id"] for c in cards}:
            for trk in {c["track"] for c in cards if c["node_id"] == nid}:
                reorder_node_cards_in_db(conn, nid, trk)
        cards = _collect_cards(conn, node_id, track, include_reviewed=True)

    order_flags: dict[int, dict[str, str]] = {}
    by_node_track: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for card in cards:
        by_node_track.setdefault((card["node_id"], card["track"]), []).append(card)
    for (nid, trk), group in by_node_track.items():
        if len(group) < 2:
            continue
        source = body_by_node.get(nid, "") if trk == "A" else caption_by_node.get(nid, "")
        if not source.strip():
            source = node_sources.get(nid, "")
        order_flags.update(detect_order_inversions(group, source))

    items: list[dict[str, Any]] = []
    suspects_by_chunk: dict[int, list[dict[str, Any]]] = {}
    suspect_ids: set[int] = set()

    for card in cards:
        source = _resolve_source(card, chunk_texts, node_sources)
        checked = check_card(card, source)
        if card["id"] in order_flags:
            checked["flags"].append(order_flags[card["id"]])
        item = {
            "card_id": card["id"],
            "front": card["front"],
            "back": card["back"],
            "tag": card["tag"],
            "track": card["track"],
            "source": card["source"],
            "flags": checked["flags"],
            "source_snippet": checked["source_snippet"],
            "grounding_ratio": checked["grounding_ratio"],
            "ai_verdict": None,
            "ai_message": "",
        }
        items.append(item)
        if checked["suspect_ai"] and card.get("chunk_id"):
            suspect_ids.add(card["id"])
            suspects_by_chunk.setdefault(card["chunk_id"], []).append(card)

    ai_results, ai_calls, warning = _run_ai_checks(suspects_by_chunk, chunk_texts)

    flagged: list[dict[str, Any]] = []
    for item in items:
        cid = item["card_id"]
        was_suspect = cid in suspect_ids
        if cid in ai_results:
            item["ai_verdict"] = ai_results[cid]["verdict"]
            item["ai_message"] = ai_results[cid]["message"]
        item["needs_attention"] = _needs_manual_review(item, was_suspect)
        if item["needs_attention"]:
            flagged.append(item)

    review_queue = [i for i in flagged if i["card_id"] not in reviewed_ids]
    flagged_count = len(flagged)
    auto_passed_count = total_count - flagged_count

    return {
        "node_id": node_id,
        "title": root["title"],
        "track": track,
        "items": review_queue,
        "issue_count": len(review_queue),
        "reviewed_count": reviewed_count,
        "total_count": total_count,
        "auto_passed_count": auto_passed_count,
        "flagged_count": flagged_count,
        "ai_calls": ai_calls,
        "warning": warning,
    }


def mark_card_reviewed(
    validation_node_id: int,
    card_id: int,
    track: str,
    front: str,
    back: str,
    tag: str,
) -> None:
    """Save card edits and record that this card was reviewed in the walkthrough."""
    from ..generation.compile import card_hash

    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM cards WHERE id = ? AND deleted = 0", (card_id,)
        ).fetchone()
        if not row:
            raise KeyError("card not found")
        conn.execute(
            "UPDATE cards SET front = ?, back = ?, tag = ?, card_hash = ?, edited = 1 "
            "WHERE id = ?",
            (front, back, tag, card_hash(front, back), card_id),
        )
        conn.execute(
            """
            INSERT INTO validation_progress (validation_node_id, card_id, track)
            VALUES (?, ?, ?)
            ON CONFLICT(validation_node_id, card_id, track) DO UPDATE SET
                reviewed_at = datetime('now')
            """,
            (validation_node_id, card_id, track),
        )


def mark_validated(node_id: int, track: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE nodes SET validated_at = datetime('now') WHERE id = ?",
            (node_id,),
        )
        clear_review_progress(conn, [node_id], track)


def clear_review_progress(conn, node_ids: list[int], track: str | None = None) -> None:
    if not node_ids:
        return
    ph = ",".join("?" for _ in node_ids)
    if track:
        conn.execute(
            f"DELETE FROM validation_progress WHERE validation_node_id IN ({ph}) "
            f"AND track = ?",
            [*node_ids, track],
        )
    else:
        conn.execute(
            f"DELETE FROM validation_progress WHERE validation_node_id IN ({ph})",
            node_ids,
        )


def clear_validation(node_ids: list[int], conn=None) -> None:
    if not node_ids:
        return

    def _run(c) -> None:
        ph = ",".join("?" for _ in node_ids)
        c.execute(
            f"UPDATE nodes SET validated_at = NULL WHERE id IN ({ph})", node_ids
        )
        clear_review_progress(c, node_ids, track=None)

    if conn is not None:
        _run(conn)
    else:
        with get_conn() as c:
            _run(c)


def invalidate_card_ancestors(node_id: int, conn=None) -> None:
    """Clear validation on a card's node and every ancestor (download scope)."""
    def _run(c) -> None:
        current: int | None = node_id
        while current is not None:
            c.execute(
                "UPDATE nodes SET validated_at = NULL WHERE id = ?", (current,)
            )
            row = c.execute(
                "SELECT parent_id FROM nodes WHERE id = ?", (current,)
            ).fetchone()
            current = row["parent_id"] if row else None

    if conn is not None:
        _run(conn)
    else:
        with get_conn() as c:
            _run(c)


def _node_card_count(conn, node_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM cards WHERE node_id = ? AND deleted = 0",
        (node_id,),
    ).fetchone()
    return int(row["n"]) if row else 0


def rollup_section_validated(
    *,
    validated_at: bool,
    direct_card_count: int,
    subheaders: list[dict],
) -> bool:
    """Section is validated when marked directly or every card-bearing subheader is."""
    if validated_at:
        return True
    card_bearing = [
        s
        for s in subheaders
        if not s.get("excluded") and int(s.get("card_count") or 0) > 0
    ]
    if card_bearing:
        return all(s.get("validated") for s in card_bearing) and direct_card_count == 0
    return direct_card_count == 0


def is_validated(conn, node_id: int) -> bool:
    row = conn.execute(
        "SELECT validated_at FROM nodes WHERE id = ?", (node_id,)
    ).fetchone()
    return bool(row and row["validated_at"])


def is_effectively_validated(conn, node_id: int) -> bool:
    """True when a node is validated directly or (for sections) all card-bearing subheaders are."""
    row = conn.execute(
        "SELECT tier, validated_at FROM nodes WHERE id = ?", (node_id,)
    ).fetchone()
    if not row:
        return False
    if row["tier"] != "section":
        return bool(row["validated_at"])

    children = conn.execute(
        """
        SELECT id, validated_at, excluded FROM nodes
        WHERE parent_id = ? AND tier = 'subheader'
        """,
        (node_id,),
    ).fetchall()
    subheaders = [
        {
            "excluded": bool(c["excluded"]),
            "validated": bool(c["validated_at"]),
            "card_count": _node_card_count(conn, c["id"]),
        }
        for c in children
    ]
    return rollup_section_validated(
        validated_at=bool(row["validated_at"]),
        direct_card_count=_node_card_count(conn, node_id),
        subheaders=subheaders,
    )


def require_validated(conn, node_id: int) -> None:
    if not is_effectively_validated(conn, node_id):
        raise PermissionError("Validate cards before downloading.")


def subject_download_ready(conn, subject_id: int) -> bool:
    """True when every section with cards has been validated."""
    rows = conn.execute(
        """
        SELECT n.id,
               (SELECT COUNT(*) FROM cards c
                WHERE c.deleted = 0 AND c.node_id IN (
                    SELECT id FROM nodes WHERE id = n.id
                    UNION SELECT id FROM nodes WHERE parent_id = n.id
                )) AS card_count
        FROM nodes n
        WHERE n.subject_id = ? AND n.tier = 'section' AND n.excluded = 0
        """,
        (subject_id,),
    ).fetchall()
    for row in rows:
        if row["card_count"] > 0 and not is_effectively_validated(conn, row["id"]):
            return False
    return True
