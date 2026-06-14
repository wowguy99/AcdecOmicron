"""Resumable, rate-limited generation worker.

All state lives in SQLite (chunk status), so an interrupted run resumes by
re-reading pending chunks. A single background thread per subject processes
the queue sequentially, throttled to the provider's free-tier RPM/RPD (counted
locally, since free tiers don't report remaining quota reliably).

When ``scope_node_ids`` is set, only pending chunks under that subtree are
processed — used for per-section generation.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

from ..config import load_config
from ..db.database import get_conn
from .compile import card_hash, reorder_node_cards_in_db
from .prompt import SYSTEM_PROMPT, build_user_prompt, chunk_low_yield, parse_cards
from .yes_no import enhance_yes_no_cards
from ..parsing.navigation import filter_navigation_cards
from .providers import ProviderError, RateLimited, get_provider

DETERMINISTIC_TYPES = {"GLOSSARY", "TIMELINE"}
NON_GENERATABLE = {"NOTES", "BIBLIOGRAPHY", "SECTION_SUMMARY"}
GENERATABLE_TYPES = {"BODY", "INTRODUCTION", "CONCLUSION"}
CHUNK_CHARS = 6000
CHUNK_OVERLAP = 200
MAX_JSON_RETRIES = 2

_active: set[int] = set()
_cancelled: set[int] = set()
_lock = threading.Lock()


def reset_ai_work(conn, node_ids: list[int]) -> None:
    """Delete AI chunks and cards for a subtree so they rebuild from node text."""
    if not node_ids:
        return
    ph = ",".join("?" for _ in node_ids)
    conn.execute(
        f"DELETE FROM cards WHERE node_id IN ({ph}) AND chunk_id IS NOT NULL",
        node_ids,
    )
    conn.execute(f"DELETE FROM chunks WHERE node_id IN ({ph})", node_ids)


def retry_failed_chunks(conn, node_ids: list[int]) -> int:
    """Reset errored chunks in a subtree so generation can retry them."""
    if not node_ids:
        return 0
    ph = ",".join("?" for _ in node_ids)
    cur = conn.execute(
        f"UPDATE chunks SET status = 'pending' WHERE status = 'error' "
        f"AND node_id IN ({ph})",
        node_ids,
    )
    return cur.rowcount


def count_pending_chunks(conn, node_ids: list[int]) -> int:
    if not node_ids:
        return 0
    ph = ",".join("?" for _ in node_ids)
    return conn.execute(
        f"SELECT COUNT(*) c FROM chunks WHERE status = 'pending' AND node_id IN ({ph})",
        node_ids,
    ).fetchone()["c"]


def count_done_chunks(conn, node_ids: list[int]) -> int:
    if not node_ids:
        return 0
    ph = ",".join("?" for _ in node_ids)
    return conn.execute(
        f"SELECT COUNT(*) c FROM chunks WHERE status = 'done' AND node_id IN ({ph})",
        node_ids,
    ).fetchone()["c"]


def count_scope_errors(
    conn, subject_id: int, scope_node_ids: list[int] | None
) -> int:
    extra, params = _scope_clause(scope_node_ids)
    return conn.execute(
        f"SELECT COUNT(*) c FROM chunks WHERE status = 'error' AND node_id IN "
        f"(SELECT id FROM nodes WHERE subject_id = ?){extra}",
        [subject_id, *params],
    ).fetchone()["c"]


def list_chunk_failures(
    conn, subject_id: int, scope_node_ids: list[int] | None = None
) -> list[dict]:
    """Return errored chunks with node context for UI display."""
    extra, params = _scope_clause(scope_node_ids)
    rows = conn.execute(
        f"""
        SELECT c.id, c.idx, c.track, c.error, c.attempts, n.title AS node_title,
               n.tier,
               (SELECT title FROM nodes WHERE id = n.parent_id) AS section_title
        FROM chunks c
        JOIN nodes n ON n.id = c.node_id
        WHERE n.subject_id = ? AND c.status = 'error'{extra}
        ORDER BY c.id
        """,
        [subject_id, *params],
    ).fetchall()
    out = []
    for r in rows:
        err = (r["error"] or "").strip() or "Generation failed (no detail recorded)"
        out.append(
            {
                "id": r["id"],
                "idx": r["idx"],
                "track": r["track"],
                "error": err,
                "attempts": r["attempts"],
                "node_title": r["node_title"],
                "section_title": r["section_title"],
                "tier": r["tier"],
            }
        )
    return out


def _failure_summary(label: str, failures: list[dict]) -> str:
    n = len(failures)
    if n == 0:
        return f"{label}: generation failed. Use ↻ to retry."
    first = failures[0]["error"]
    if n == 1:
        return f"{label}: {first} Use ↻ to retry."
    return f"{label}: {n} chunk(s) failed — {first} (+{n - 1} more). Use ↻ to retry."


def subtree_ids(conn, node_id: int) -> list[int]:
    ids = [node_id]
    frontier = [node_id]
    while frontier:
        nid = frontier.pop()
        for r in conn.execute("SELECT id FROM nodes WHERE parent_id = ?", (nid,)).fetchall():
            ids.append(r["id"])
            frontier.append(r["id"])
    return ids


def _chunk_text(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= CHUNK_CHARS:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + CHUNK_CHARS)
        nl = text.rfind("\n", start, end)
        if nl > start + CHUNK_CHARS // 2:
            end = nl
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - CHUNK_OVERLAP, end)
    return [c for c in chunks if c]


def _match_tag(tag_names: list[str], *keywords: str) -> str:
    for name in tag_names:
        low = name.lower()
        if any(k in low for k in keywords):
            return name
    return "other"


def _insert_piece_year_card(conn, sub, tag_names) -> None:
    from ..parsing.deterministic import piece_year_cards
    from ..parsing.structure import PIECE_LISTENING_COMPANION, PIECE_SELECTED_WORK
    from ..parsing.structure import piece_year_from_subheader

    piece_type = (sub["subheader_kind"] or "").strip()
    if piece_type not in (PIECE_SELECTED_WORK, PIECE_LISTENING_COMPANION):
        return
    existing = conn.execute(
        "SELECT 1 FROM cards WHERE node_id = ? AND source = 'piece_year'",
        (sub["id"],),
    ).fetchone()
    if existing:
        return
    year = piece_year_from_subheader(
        sub["title"], sub["body_text"] or "", piece_type
    )
    if not year:
        return
    tag = _match_tag(tag_names, "date", "year", "time", "event")
    for card_idx, (front, back) in enumerate(
        piece_year_cards(sub["title"], year, piece_type)
    ):
        conn.execute(
            "INSERT INTO cards (node_id, chunk_id, card_index, front, back, tag, track, "
            "card_hash, source) VALUES (?, NULL, ?, ?, ?, ?, 'A', ?, 'piece_year')",
            (sub["id"], card_idx, front, back, tag, card_hash(front, back)),
        )


def _insert_deterministic(conn, sub, tag_names, glossary_cards, timeline_cards) -> None:
    existing = conn.execute(
        "SELECT COUNT(*) c FROM cards WHERE node_id = ?", (sub["id"],)
    ).fetchone()["c"]
    if existing:
        return
    if sub["section_type"] == "GLOSSARY":
        pairs = glossary_cards(sub["body_text"])
        tag = _match_tag(tag_names, "defin", "term", "vocab", "concept")
        source = "glossary"
    else:
        pairs = timeline_cards(sub["body_text"])
        tag = _match_tag(tag_names, "date", "event", "time")
        source = "timeline"
    for card_idx, (front, back) in enumerate(pairs):
        conn.execute(
            "INSERT INTO cards (node_id, chunk_id, card_index, front, back, tag, track, "
            "card_hash, source) VALUES (?, NULL, ?, ?, ?, ?, 'A', ?, ?)",
            (sub["id"], card_idx, front, back, tag, card_hash(front, back), source),
        )


def _enqueue_nodes(conn, nodes, tag_names, glossary_cards, timeline_cards) -> int:
    """Create chunks + deterministic cards for the given node rows. Returns new pending count."""
    pending = 0
    for sub in nodes:
        stype = sub["section_type"]
        if stype in DETERMINISTIC_TYPES:
            _insert_deterministic(conn, sub, tag_names, glossary_cards, timeline_cards)
            continue
        _insert_piece_year_card(conn, sub, tag_names)
        for track, source in (("A", sub["body_text"]), ("B", sub["caption_text"])):
            chunk_idx = 0
            for chunk in _chunk_text(source or ""):
                if chunk_low_yield(chunk):
                    continue
                exists = conn.execute(
                    "SELECT 1 FROM chunks WHERE node_id = ? AND track = ? AND idx = ?",
                    (sub["id"], track, chunk_idx),
                ).fetchone()
                if exists:
                    chunk_idx += 1
                    continue
                conn.execute(
                    "INSERT INTO chunks (node_id, idx, track, text, status) "
                    "VALUES (?, ?, ?, ?, 'pending')",
                    (sub["id"], chunk_idx, track, chunk),
                )
                chunk_idx += 1
                pending += 1
    return pending


def _scope_clause(scope_node_ids: list[int] | None) -> tuple[str, list]:
    if not scope_node_ids:
        return "", []
    ph = ",".join("?" for _ in scope_node_ids)
    return f" AND node_id IN ({ph})", list(scope_node_ids)


def _count_chunks(conn, subject_id: int, scope_node_ids: list[int] | None, done_only: bool) -> int:
    extra, params = _scope_clause(scope_node_ids)
    status = "status = 'done'" if done_only else "status != 'done'"
    row = conn.execute(
        f"SELECT COUNT(*) c FROM chunks WHERE {status} AND node_id IN "
        f"(SELECT id FROM nodes WHERE subject_id = ?){extra}",
        [subject_id, *params],
    ).fetchone()
    return row["c"]


def _count_scoped_progress(
    conn, subject_id: int, scope_node_ids: list[int] | None
) -> tuple[int, int]:
    extra, params = _scope_clause(scope_node_ids)
    done = conn.execute(
        f"SELECT COUNT(*) c FROM chunks WHERE status IN ('done','error') "
        f"AND node_id IN (SELECT id FROM nodes WHERE subject_id = ?){extra}",
        [subject_id, *params],
    ).fetchone()["c"]
    total = conn.execute(
        f"SELECT COUNT(*) c FROM chunks WHERE node_id IN "
        f"(SELECT id FROM nodes WHERE subject_id = ?){extra}",
        [subject_id, *params],
    ).fetchone()["c"]
    return done, total


def enqueue_subject(subject_id: int) -> int:
    """Create all chunks and deterministic cards for a subject."""
    from ..parsing.deterministic import glossary_cards, timeline_cards

    with get_conn() as conn:
        tag_rows = conn.execute(
            "SELECT name FROM tags WHERE subject_id = ?", (subject_id,)
        ).fetchall()
        tag_names = [r["name"] for r in tag_rows]
        nodes = conn.execute(
            "SELECT * FROM nodes WHERE subject_id = ? AND excluded = 0 "
            "AND (trim(body_text) != '' OR trim(caption_text) != '') "
            "ORDER BY id",
            (subject_id,),
        ).fetchall()
        pending = _enqueue_nodes(conn, nodes, tag_names, glossary_cards, timeline_cards)
        total = conn.execute(
            "SELECT COUNT(*) c FROM chunks WHERE status != 'done' AND node_id IN "
            "(SELECT id FROM nodes WHERE subject_id = ?)",
            (subject_id,),
        ).fetchone()["c"]
        done = conn.execute(
            "SELECT COUNT(*) c FROM chunks WHERE status = 'done' AND node_id IN "
            "(SELECT id FROM nodes WHERE subject_id = ?)",
            (subject_id,),
        ).fetchone()["c"]
        conn.execute(
            "INSERT INTO jobs (subject_id, status, total, completed, message) "
            "VALUES (?, 'idle', ?, ?, '')",
            (subject_id, total + done, done),
        )
        conn.execute(
            "UPDATE subjects SET status = 'approved' WHERE id = ?", (subject_id,)
        )
    return pending


def enqueue_section(node_id: int) -> tuple[int, list[int], str]:
    """Ensure chunks/cards exist for one section subtree. Returns pending AI chunks."""
    from ..parsing.deterministic import glossary_cards, timeline_cards

    with get_conn() as conn:
        root = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if not root:
            return 0, [], ""
        ids = subtree_ids(conn, node_id)
        ph = ",".join("?" for _ in ids)
        tag_rows = conn.execute(
            "SELECT name FROM tags WHERE subject_id = ?", (root["subject_id"],)
        ).fetchall()
        tag_names = [r["name"] for r in tag_rows]
        nodes = conn.execute(
            f"SELECT * FROM nodes WHERE id IN ({ph}) AND excluded = 0 "
            "AND (trim(body_text) != '' OR trim(caption_text) != '') "
            "ORDER BY id",
            ids,
        ).fetchall()
        _enqueue_nodes(conn, nodes, tag_names, glossary_cards, timeline_cards)
        pending = conn.execute(
            f"SELECT COUNT(*) c FROM chunks WHERE status = 'pending' AND node_id IN ({ph})",
            ids,
        ).fetchone()["c"]
    return pending, ids, root["title"]


def _today_request_count(conn) -> int:
    return conn.execute(
        "SELECT COUNT(*) c FROM request_log WHERE date(ts) = date('now')"
    ).fetchone()["c"]


def _is_cancelled(subject_id: int) -> bool:
    with _lock:
        return subject_id in _cancelled


def _subject_status_after_stop(conn, subject_id: int) -> str:
    remaining = conn.execute(
        "SELECT COUNT(*) c FROM chunks WHERE status = 'pending' AND node_id IN "
        "(SELECT id FROM nodes WHERE subject_id = ?)",
        (subject_id,),
    ).fetchone()["c"]
    return "done" if remaining == 0 else "approved"


def stop_job(subject_id: int) -> bool:
    """Stop generation, reset in-flight chunks, and update job/subject status."""
    with _lock:
        _cancelled.add(subject_id)
        was_running = subject_id in _active

    with get_conn() as conn:
        conn.execute(
            "UPDATE chunks SET status = 'pending' WHERE status = 'in_progress' "
            "AND node_id IN (SELECT id FROM nodes WHERE subject_id = ?)",
            (subject_id,),
        )
        job = conn.execute(
            "SELECT status FROM jobs WHERE subject_id = ? ORDER BY id DESC LIMIT 1",
            (subject_id,),
        ).fetchone()
        if job and job["status"] == "running":
            completed, total = _count_scoped_progress(conn, subject_id, None)
            conn.execute(
                "UPDATE jobs SET status = 'cancelled', message = ?, "
                "completed = ?, total = ?, updated_at = datetime('now') "
                "WHERE id = (SELECT id FROM jobs WHERE subject_id = ? ORDER BY id DESC LIMIT 1)",
                ("Stopped by user.", completed, total, subject_id),
            )
            was_running = True
        subj = conn.execute(
            "SELECT status FROM subjects WHERE id = ?", (subject_id,)
        ).fetchone()
        if subj and subj["status"] == "generating":
            conn.execute(
                "UPDATE subjects SET status = ? WHERE id = ?",
                (_subject_status_after_stop(conn, subject_id), subject_id),
            )

    return was_running


def cancel_subject(subject_id: int) -> None:
    """Stop an in-flight generation job for this subject (e.g. before delete)."""
    stop_job(subject_id)


def start_job(
    subject_id: int,
    scope_node_ids: list[int] | None = None,
    section_title: str = "",
) -> bool:
    with _lock:
        if subject_id in _active:
            return False
        _active.add(subject_id)

    label = section_title or "subject"
    with get_conn() as conn:
        done, total = _count_scoped_progress(conn, subject_id, scope_node_ids)
        conn.execute(
            "INSERT INTO jobs (subject_id, status, total, completed, message) "
            "VALUES (?, 'running', ?, ?, ?)",
            (subject_id, total, done, f"Generating: {label}..."),
        )
        conn.execute(
            "UPDATE subjects SET status = 'generating' WHERE id = ?", (subject_id,)
        )

    t = threading.Thread(
        target=_run,
        args=(subject_id, scope_node_ids, section_title),
        daemon=True,
    )
    t.start()
    return True


def _set_job(subject_id: int, **fields) -> None:
    cols = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [subject_id]
    with get_conn() as conn:
        conn.execute(
            f"UPDATE jobs SET {cols}, updated_at = datetime('now') "
            "WHERE id = (SELECT id FROM jobs WHERE subject_id = ? ORDER BY id DESC LIMIT 1)",
            vals,
        )


def _run(
    subject_id: int,
    scope_node_ids: list[int] | None = None,
    section_title: str = "",
) -> None:
    scoped = bool(scope_node_ids)
    try:
        cfg = load_config()
        if not cfg.api_key:
            _set_job(subject_id, status="error", message="No API key configured.")
            return
        provider = get_provider(cfg)
        interval = 60.0 / max(1, cfg.rpm)

        with get_conn() as conn:
            subj = conn.execute(
                "SELECT name FROM subjects WHERE id = ?", (subject_id,)
            ).fetchone()
            subject_name = subj["name"] if subj else ""
            tag_rows = conn.execute(
                "SELECT name, definition FROM tags WHERE subject_id = ?", (subject_id,)
            ).fetchall()
            tags = [(r["name"], r["definition"]) for r in tag_rows]

        label = section_title or "subject"

        while True:
            if _is_cancelled(subject_id):
                return
            with get_conn() as conn:
                extra, params = _scope_clause(scope_node_ids)
                chunk = conn.execute(
                    "SELECT c.*, n.title sub_title, n.parent_id, "
                    "(SELECT title FROM nodes WHERE id = n.parent_id) sec_title "
                    "FROM chunks c JOIN nodes n ON n.id = c.node_id "
                    f"WHERE n.subject_id = ? AND c.status = 'pending'{extra} "
                    "ORDER BY c.id LIMIT 1",
                    [subject_id, *params],
                ).fetchone()
                if chunk is None:
                    break
                if _today_request_count(conn) >= cfg.rpd:
                    _set_job(
                        subject_id, status="paused",
                        message="Daily free-tier quota reached. Resume tomorrow.",
                    )
                    return
                conn.execute(
                    "UPDATE chunks SET status = 'in_progress', attempts = attempts + 1 "
                    "WHERE id = ?",
                    (chunk["id"],),
                )

            if _is_cancelled(subject_id):
                with get_conn() as conn:
                    conn.execute(
                        "UPDATE chunks SET status = 'pending' WHERE id = ?",
                        (chunk["id"],),
                    )
                return

            ok, err_msg = _process_chunk(provider, subject_name, chunk, tags)

            if _is_cancelled(subject_id):
                with get_conn() as conn:
                    conn.execute("DELETE FROM cards WHERE chunk_id = ?", (chunk["id"],))
                    conn.execute(
                        "UPDATE chunks SET status = 'pending', error = '' WHERE id = ?",
                        (chunk["id"],),
                    )
                return

            with get_conn() as conn:
                conn.execute("INSERT INTO request_log DEFAULT VALUES")
                if ok:
                    conn.execute(
                        "UPDATE chunks SET status = 'done', error = '' WHERE id = ?",
                        (chunk["id"],),
                    )
                else:
                    conn.execute(
                        "UPDATE chunks SET status = 'error', error = ? WHERE id = ?",
                        (err_msg[:500], chunk["id"]),
                    )
                completed, total = _count_scoped_progress(conn, subject_id, scope_node_ids)
            progress = f"Generating: {label} ({completed}/{total})"
            _set_job(subject_id, completed=completed, total=total, message=progress)
            time.sleep(interval)

        if _is_cancelled(subject_id):
            return

        done_msg = f"Section complete: {label}" if scoped else "Generation complete."
        with get_conn() as conn:
            failures = list_chunk_failures(conn, subject_id, scope_node_ids)
            if failures:
                _set_job(
                    subject_id,
                    status="error",
                    message=_failure_summary(label, failures),
                )
            else:
                _set_job(subject_id, status="done", message=done_msg)
            # Only mark subject done if no pending chunks remain anywhere.
            remaining = conn.execute(
                "SELECT COUNT(*) c FROM chunks WHERE status = 'pending' AND node_id IN "
                "(SELECT id FROM nodes WHERE subject_id = ?)",
                (subject_id,),
            ).fetchone()["c"]
            new_status = "done" if remaining == 0 else "approved"
            conn.execute(
                "UPDATE subjects SET status = ? WHERE id = ?", (new_status, subject_id)
            )
    except Exception as exc:  # noqa: BLE001
        _set_job(subject_id, status="error", message=str(exc)[:300])
    finally:
        with _lock:
            _active.discard(subject_id)
            _cancelled.discard(subject_id)


def _process_chunk(provider, subject_name, chunk, tags) -> tuple[bool, str]:
    user = build_user_prompt(
        subject=subject_name,
        section=chunk["sec_title"] or "",
        subheader=chunk["sub_title"] or "",
        tags=tags,
        track=chunk["track"],
        text=chunk["text"],
    )
    valid_tags = {t[0] for t in tags} | {"other"}
    last_err = "Generation failed after retries"
    for attempt in range(MAX_JSON_RETRIES + 1):
        try:
            raw = provider.generate(SYSTEM_PROMPT, user)
        except RateLimited as rl:
            last_err = f"Rate limited by API (retry after {rl.retry_after:.0f}s)"
            time.sleep(min(rl.retry_after, 30))
            continue
        except ProviderError as exc:
            return False, str(exc)
        try:
            cards = parse_cards(raw)
        except ValueError as exc:
            last_err = f"Could not parse AI response as JSON: {exc}"
            if attempt < MAX_JSON_RETRIES:
                continue
            return False, last_err
        cards = filter_navigation_cards(cards)
        cards = enhance_yes_no_cards(cards)
        if not cards:
            if chunk_low_yield(chunk["text"]):
                _save_cards(chunk, [], valid_tags)
                return True, ""
            last_err = "AI returned JSON but no valid flashcards (missing front/back fields)"
            if attempt < MAX_JSON_RETRIES:
                user = (
                    user
                    + "\n\nIMPORTANT: Return JSON with a non-empty \"cards\" array. "
                    'Each card MUST use exactly these keys: "front", "back", "tag".'
                )
                continue
            return False, last_err
        _save_cards(chunk, cards, valid_tags)
        return True, ""
    return False, last_err


def _save_cards(chunk, cards: list[dict[str, str]], valid_tags: set[str]) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM cards WHERE chunk_id = ?", (chunk["id"],))
        for c in cards:
            tag = c["tag"] if c["tag"] in valid_tags else "other"
            h = card_hash(c["front"], c["back"])
            conn.execute(
                "INSERT INTO cards (node_id, chunk_id, card_index, front, back, tag, "
                "track, card_hash, source) VALUES (?, ?, 0, ?, ?, ?, ?, ?, 'ai')",
                (
                    chunk["node_id"],
                    chunk["id"],
                    c["front"],
                    c["back"],
                    tag,
                    chunk["track"],
                    h,
                ),
            )
        reorder_node_cards_in_db(conn, chunk["node_id"], chunk["track"])
