"""Application services: persist blueprints, expose the tree, edit nodes."""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional

from .db.database import get_conn
from .generation.worker import (
    count_done_chunks,
    count_pending_chunks,
    count_scope_errors,
    list_chunk_failures,
    subtree_ids,
)
from .parsing.captions import attach_captions
from .parsing.navigation import strip_guide_navigation
from .parsing.deterministic import glossary_cards, timeline_cards
from .parsing.pages import pdf_page_to_printed
from .parsing.snippets import first_last_sentences
from .parsing.structure import build_blueprint, collapse_duplicate_singletons
from .validation.runner import rollup_section_validated

# Section types whose cards we never generate.
EXCLUDED_TYPES = {"NOTES", "BIBLIOGRAPHY", "SECTION_SUMMARY"}
DETERMINISTIC_TYPES = {"GLOSSARY", "TIMELINE"}
BUILTIN_TAG = "other"


def create_subject_from_pdf(
    name: str,
    filename: str,
    pdf_path: str,
    tags: list[dict[str, str]],
    *,
    is_iad: bool = False,
) -> int:
    from .parsing.structure import ParseOptions

    doc, sections = build_blueprint(pdf_path, ParseOptions(is_iad=is_iad))
    attach_captions(doc, sections)
    for sec in sections:
        if sec.body_text:
            sec.body_text = strip_guide_navigation(sec.body_text)
        for sub in sec.subheaders:
            if sub.body_text:
                sub.body_text = strip_guide_navigation(sub.body_text)
    collapse_duplicate_singletons(sections)

    page_map_json = json.dumps({str(k): v for k, v in doc.printed_to_index.items()})

    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO subjects (name, filename, pdf_path, page_count, status, is_iad, "
            "printed_page_map) VALUES (?, ?, ?, ?, 'uploaded', ?, ?)",
            (name, filename, pdf_path, doc.page_count, 1 if is_iad else 0, page_map_json),
        )
        subject_id = cur.lastrowid

        for t in tags:
            tname = (t.get("name") or "").strip()
            if tname and tname.lower() != BUILTIN_TAG:
                conn.execute(
                    "INSERT INTO tags (subject_id, name, definition, builtin) "
                    "VALUES (?, ?, ?, 0)",
                    (subject_id, tname, (t.get("definition") or "").strip()),
                )
        conn.execute(
            "INSERT INTO tags (subject_id, name, definition, builtin) "
            "VALUES (?, ?, ?, 1)",
            (subject_id, BUILTIN_TAG, "Does not fit any other tag."),
        )

        for sec in sections:
            excluded = 1 if sec.section_type in EXCLUDED_TYPES else 0
            sec_cur = conn.execute(
                "INSERT INTO nodes (subject_id, parent_id, tier, title, "
                "section_type, order_index, start_page, start_line, "
                "end_page, end_line, body_text, caption_text, excluded) "
                "VALUES (?, NULL, 'section', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    subject_id, sec.title, sec.section_type, sec.order,
                    sec.start_page, sec.start_line or 0,
                    sec.end_page, sec.end_line or 0,
                    sec.body_text, sec.caption_text, excluded,
                ),
            )
            section_id = sec_cur.lastrowid
            for idx, sub in enumerate(sec.subheaders):
                conn.execute(
                    "INSERT INTO nodes (subject_id, parent_id, tier, title, "
                    "section_type, order_index, start_page, start_line, "
                    "end_page, end_line, body_text, caption_text, "
                    "subheader_kind, excluded) "
                    "VALUES (?, ?, 'subheader', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        subject_id, section_id, sub.title, sec.section_type, idx,
                        sub.start_page, sub.start_line, sub.end_page, sub.end_line,
                        sub.body_text, sub.caption_text, sub.piece_type or "", excluded,
                    ),
                )
    return subject_id


def list_subjects() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, filename, page_count, status, created_at, is_iad "
            "FROM subjects ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def delete_subject(subject_id: int) -> None:
    """Remove a subject and all related data; delete the uploaded PDF from disk."""
    from pathlib import Path

    from .generation import worker

    worker.cancel_subject(subject_id)

    with get_conn() as conn:
        row = conn.execute(
            "SELECT pdf_path FROM subjects WHERE id = ?", (subject_id,)
        ).fetchone()
        if not row:
            raise KeyError("subject not found")
        pdf_path = row["pdf_path"]
        conn.execute("DELETE FROM subjects WHERE id = ?", (subject_id,))

    try:
        Path(pdf_path).unlink(missing_ok=True)
    except OSError:
        pass


def _tags(conn: sqlite3.Connection, subject_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT name, definition, builtin FROM tags WHERE subject_id = ? ORDER BY builtin, id",
        (subject_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _card_counts(conn: sqlite3.Connection, subject_id: int) -> dict[int, dict[str, int]]:
    rows = conn.execute(
        "SELECT node_id, track, COUNT(*) n FROM cards "
        "WHERE deleted = 0 AND node_id IN (SELECT id FROM nodes WHERE subject_id = ?) "
        "GROUP BY node_id, track",
        (subject_id,),
    ).fetchall()
    counts: dict[int, dict[str, int]] = {}
    for r in rows:
        counts.setdefault(r["node_id"], {"A": 0, "B": 0})[r["track"]] = r["n"]
    return counts


def get_tree(subject_id: int) -> dict[str, Any]:
    with get_conn() as conn:
        subj = conn.execute(
            "SELECT * FROM subjects WHERE id = ?", (subject_id,)
        ).fetchone()
        if not subj:
            raise KeyError("subject not found")
        counts = _card_counts(conn, subject_id)
        tags = _tags(conn, subject_id)
        job = conn.execute(
            "SELECT status, message, total, completed FROM jobs "
            "WHERE subject_id = ? ORDER BY id DESC LIMIT 1",
            (subject_id,),
        ).fetchone()
        nodes = conn.execute(
            "SELECT * FROM nodes WHERE subject_id = ? ORDER BY order_index, id",
            (subject_id,),
        ).fetchall()

        node_chunk_stats: dict[int, dict[str, int]] = {}
        for n in nodes:
            if n["tier"] in ("section", "subheader"):
                ids = subtree_ids(conn, n["id"])
                node_chunk_stats[n["id"]] = {
                    "chunks_pending": count_pending_chunks(conn, ids),
                    "chunks_done": count_done_chunks(conn, ids),
                    "chunks_failed": count_scope_errors(conn, subject_id, ids),
                }
        chunk_errors = list_chunk_failures(conn, subject_id)

    sections = [n for n in nodes if n["parent_id"] is None]
    by_parent: dict[int, list[sqlite3.Row]] = {}
    for n in nodes:
        if n["parent_id"] is not None:
            by_parent.setdefault(n["parent_id"], []).append(n)

    def node_dict(n: sqlite3.Row) -> dict[str, Any]:
        children = [node_dict(c) for c in by_parent.get(n["id"], [])]
        own = counts.get(n["id"], {"A": 0, "B": 0})
        a = own["A"] + sum(c["cards_a"] for c in children)
        b = own["B"] + sum(c["cards_b"] for c in children)
        own_validated = bool(n["validated_at"]) if "validated_at" in n.keys() else False
        if n["tier"] == "section":
            validated = rollup_section_validated(
                validated_at=own_validated,
                direct_card_count=own["A"] + own["B"],
                subheaders=[
                    {
                        "excluded": c["excluded"],
                        "validated": c["validated"],
                        "card_count": c["cards_a"] + c["cards_b"],
                    }
                    for c in children
                ],
            )
        else:
            validated = own_validated
        out: dict[str, Any] = {
            "id": n["id"],
            "title": n["title"],
            "tier": n["tier"],
            "section_type": n["section_type"],
            "excluded": bool(n["excluded"]),
            "deterministic": n["section_type"] in DETERMINISTIC_TYPES,
            "validated": validated,
            "cards_a": a,
            "cards_b": b,
            "children": children,
        }
        if n["tier"] in ("section", "subheader"):
            stats = node_chunk_stats.get(n["id"], {})
            out["chunks_pending"] = stats.get("chunks_pending", 0)
            out["chunks_done"] = stats.get("chunks_done", 0)
            out["chunks_failed"] = stats.get("chunks_failed", 0)
        return out

    section_dicts = [node_dict(s) for s in sections]
    total_a = sum(s["cards_a"] for s in section_dicts)
    total_b = sum(s["cards_b"] for s in section_dicts)
    all_validated = all(
        s.get("validated", False) or (s["cards_a"] == 0 and s["cards_b"] == 0)
        for s in section_dicts
    )
    return {
        "subject": {
            "id": subj["id"],
            "name": subj["name"],
            "status": subj["status"],
            "page_count": subj["page_count"],
            "is_iad": bool(subj["is_iad"]) if "is_iad" in subj.keys() else False,
            "cards_a": total_a,
            "cards_b": total_b,
            "all_validated": all_validated,
        },
        "tags": tags,
        "job": dict(job) if job else None,
        "chunk_errors": chunk_errors,
        "sections": section_dicts,
    }


def _load_printed_page_map(raw: str | None) -> dict[int, int]:
    if not raw:
        return {}
    data = json.loads(raw)
    return {int(k): int(v) for k, v in data.items()}


def get_subsection_info(node_id: int) -> dict[str, Any]:
    """Return parse metadata and tag counts for a subheader node."""
    with get_conn() as conn:
        node = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if not node:
            raise KeyError("node not found")
        if node["tier"] != "subheader":
            raise ValueError("info is only available for subheader nodes")

        subj = conn.execute(
            "SELECT printed_page_map FROM subjects WHERE id = ?",
            (node["subject_id"],),
        ).fetchone()
        page_map = _load_printed_page_map(
            subj["printed_page_map"]
            if subj and "printed_page_map" in subj.keys()
            else None
        )

        body = node["body_text"] or ""
        caption = node["caption_text"] or ""
        first, last = first_last_sentences(body)

        start_page = node["start_page"]
        end_page = node["end_page"]
        pdf_start = int(start_page) + 1 if start_page is not None else None
        pdf_end = int(end_page) + 1 if end_page is not None else None
        printed_start = (
            pdf_page_to_printed(int(start_page), page_map)
            if start_page is not None and page_map
            else None
        )
        printed_end = (
            pdf_page_to_printed(int(end_page), page_map)
            if end_page is not None and page_map
            else None
        )

        tag_rows = conn.execute(
            "SELECT tag, COUNT(*) AS n FROM cards "
            "WHERE node_id = ? AND deleted = 0 GROUP BY tag",
            (node_id,),
        ).fetchall()
        counts_by_tag = {r["tag"]: int(r["n"]) for r in tag_rows}
        cards_total = sum(counts_by_tag.values())

        subject_tags = _tags(conn, node["subject_id"])
        tag_counts = [
            {
                "name": t["name"],
                "definition": t["definition"],
                "builtin": t["builtin"],
                "count": counts_by_tag.get(t["name"], 0),
            }
            for t in subject_tags
        ]
        known = {t["name"] for t in subject_tags}
        for tag, count in counts_by_tag.items():
            if tag not in known:
                tag_counts.append(
                    {"name": tag, "definition": "", "builtin": 0, "count": count}
                )

        subheader_kind = (
            node["subheader_kind"]
            if "subheader_kind" in node.keys()
            else ""
        ) or ""

        return {
            "node_id": node_id,
            "title": node["title"],
            "section_type": node["section_type"],
            "subheader_kind": subheader_kind,
            "first_sentence": first,
            "last_sentence": last,
            "pdf_start_page": pdf_start,
            "pdf_end_page": pdf_end,
            "printed_start_page": printed_start,
            "printed_end_page": printed_end,
            "body_char_count": len(body),
            "caption_char_count": len(caption),
            "cards_total": cards_total,
            "tag_counts": tag_counts,
        }


# --- node editing (editable approval gate) ---------------------------------

def rename_node(node_id: int, title: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE nodes SET title = ? WHERE id = ?", (title.strip(), node_id))


def delete_node(node_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))


def set_excluded(node_id: int, excluded: bool) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE nodes SET excluded = ? WHERE id = ?", (1 if excluded else 0, node_id)
        )


def reparent_node(node_id: int, new_parent_id: Optional[int]) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE nodes SET parent_id = ? WHERE id = ?", (new_parent_id, node_id)
        )


def _join_text(existing: str, addition: str) -> str:
    a = (existing or "").strip()
    b = (addition or "").strip()
    if a and b:
        return a + "\n" + b
    return a or b


def reparse_subject(subject_id: int) -> dict[str, Any]:
    """Re-run the PDF parser and refresh stored body/caption text on existing nodes."""
    from pathlib import Path

    from .parsing.structure import ParseOptions, build_blueprint, collapse_duplicate_singletons

    with get_conn() as conn:
        subj = conn.execute(
            "SELECT * FROM subjects WHERE id = ?", (subject_id,)
        ).fetchone()
        if not subj:
            raise KeyError("subject not found")
        if subj["status"] == "uploaded":
            raise ValueError("Approve the tree before re-parsing the PDF.")
        pdf_path = Path(subj["pdf_path"])
        if not pdf_path.is_file():
            raise ValueError(
                f"PDF file not found ({subj['filename']}). "
                "Re-upload the guide or restore the file on disk."
            )

    doc, sections = build_blueprint(
        str(pdf_path), ParseOptions(is_iad=bool(subj["is_iad"]))
    )
    attach_captions(doc, sections)
    for sec in sections:
        if sec.body_text:
            sec.body_text = strip_guide_navigation(sec.body_text)
        for sub in sec.subheaders:
            if sub.body_text:
                sub.body_text = strip_guide_navigation(sub.body_text)
    collapse_duplicate_singletons(sections)

    updated = 0
    warnings: list[str] = []
    with get_conn() as conn:
        db_secs = conn.execute(
            "SELECT * FROM nodes WHERE subject_id = ? AND parent_id IS NULL "
            "ORDER BY order_index, id",
            (subject_id,),
        ).fetchall()
        if len(db_secs) != len(sections):
            warnings.append(
                f"Section count changed ({len(db_secs)} in DB, {len(sections)} in PDF). "
                "Matched by order where possible."
            )
        for bp_sec, db_sec in zip(sections, db_secs):
            conn.execute(
                "UPDATE nodes SET body_text = ?, caption_text = ?, "
                "start_page = ?, start_line = ?, end_page = ?, end_line = ? "
                "WHERE id = ?",
                (
                    bp_sec.body_text,
                    bp_sec.caption_text,
                    bp_sec.start_page,
                    bp_sec.start_line or 0,
                    bp_sec.end_page,
                    bp_sec.end_line or 0,
                    db_sec["id"],
                ),
            )
            updated += 1
            db_subs = conn.execute(
                "SELECT * FROM nodes WHERE parent_id = ? ORDER BY order_index, id",
                (db_sec["id"],),
            ).fetchall()
            if len(db_subs) != len(bp_sec.subheaders):
                warnings.append(
                    f"Subheader count differs under “{db_sec['title']}” "
                    f"({len(db_subs)} in DB, {len(bp_sec.subheaders)} in PDF)."
                )
            for bp_sub, db_sub in zip(bp_sec.subheaders, db_subs):
                conn.execute(
                    "UPDATE nodes SET body_text = ?, caption_text = ?, "
                    "start_page = ?, start_line = ?, end_page = ?, end_line = ?, "
                    "subheader_kind = ? WHERE id = ?",
                    (
                        bp_sub.body_text,
                        bp_sub.caption_text,
                        bp_sub.start_page,
                        bp_sub.start_line,
                        bp_sub.end_page,
                        bp_sub.end_line,
                        bp_sub.piece_type or "",
                        db_sub["id"],
                    ),
                )
                updated += 1
    return {"ok": True, "nodes_updated": updated, "warnings": warnings}


def merge_into_previous(node_id: int) -> dict[str, Any]:
    """Merge a subheader's body/caption text into the previous sibling.

    If there is no previous sibling (e.g. a lone INTRODUCTION subheader under
    the INTRODUCTION section), merge into the parent section instead.
    """
    with get_conn() as conn:
        node = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if not node or node["parent_id"] is None:
            return {"ok": False, "error": "Cannot merge a top-level section."}

        target = conn.execute(
            "SELECT * FROM nodes WHERE parent_id = ? AND order_index < ? "
            "ORDER BY order_index DESC LIMIT 1",
            (node["parent_id"], node["order_index"]),
        ).fetchone()
        if target is None:
            target = conn.execute(
                "SELECT * FROM nodes WHERE id = ?", (node["parent_id"],)
            ).fetchone()

        if not target or target["id"] == node_id:
            return {"ok": False, "error": "Nothing to merge into."}

        body = _join_text(target["body_text"], node["body_text"])
        captions = _join_text(target["caption_text"], node["caption_text"])
        conn.execute(
            "UPDATE nodes SET body_text = ?, caption_text = ?, "
            "start_page = COALESCE(start_page, ?), start_line = COALESCE(start_line, ?), "
            "end_page = COALESCE(?, end_page), end_line = COALESCE(?, end_line) "
            "WHERE id = ?",
            (
                body,
                captions,
                node["start_page"],
                node["start_line"],
                node["end_page"],
                node["end_line"],
                target["id"],
            ),
        )
        conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
        return {"ok": True, "target_id": target["id"]}
