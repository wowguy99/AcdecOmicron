"""Export and import full subject archives (.acdec-subject.zip)."""
from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import UPLOAD_DIR, ensure_dirs
from .db.database import get_conn
from .generation.compile import CARD_ORDER_BY, CARD_ORDER_FROM, sanitize_filename_part

FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"
PDF_NAME = "guide.pdf"
ZIP_SUFFIX = ".acdec-subject.zip"


class TransferError(Exception):
    pass


def _unique_subject_name(conn, base_name: str) -> str:
    if not conn.execute("SELECT 1 FROM subjects WHERE name = ?", (base_name,)).fetchone():
        return base_name
    for n in range(2, 1000):
        suffix = " (imported)" if n == 2 else f" (imported {n - 1})"
        candidate = f"{base_name}{suffix}"
        if not conn.execute("SELECT 1 FROM subjects WHERE name = ?", (candidate,)).fetchone():
            return candidate
    raise TransferError("Too many imported subjects with the same name.")


def export_archive_filename(subject_name: str) -> str:
    safe = sanitize_filename_part(subject_name) or "subject"
    return f"{safe}{ZIP_SUFFIX}"


def export_subject(subject_id: int) -> tuple[bytes, str]:
    with get_conn() as conn:
        subj = conn.execute("SELECT * FROM subjects WHERE id = ?", (subject_id,)).fetchone()
        if not subj:
            raise KeyError("subject not found")

        pdf_path = Path(subj["pdf_path"])
        if not pdf_path.is_file():
            raise TransferError(f"PDF not found for subject: {pdf_path}")

        node_rows = conn.execute(
            "SELECT * FROM nodes WHERE subject_id = ? ORDER BY order_index, id",
            (subject_id,),
        ).fetchall()
        node_ids = [n["id"] for n in node_rows]
        if not node_ids:
            ph = "?"
        else:
            ph = ",".join("?" for _ in node_ids)

        tags = [
            {
                "name": r["name"],
                "definition": r["definition"],
                "builtin": bool(r["builtin"]),
            }
            for r in conn.execute(
                "SELECT name, definition, builtin FROM tags WHERE subject_id = ? ORDER BY id",
                (subject_id,),
            ).fetchall()
        ]

        nodes = []
        for n in node_rows:
            nodes.append(
                {
                    "ref": str(n["id"]),
                    "parent_ref": str(n["parent_id"]) if n["parent_id"] is not None else None,
                    "tier": n["tier"],
                    "title": n["title"],
                    "section_type": n["section_type"],
                    "order_index": n["order_index"],
                    "start_page": n["start_page"],
                    "start_line": n["start_line"],
                    "start_char": n["start_char"] if "start_char" in n.keys() else None,
                    "end_page": n["end_page"],
                    "end_line": n["end_line"],
                    "end_char": n["end_char"] if "end_char" in n.keys() else None,
                    "body_text": n["body_text"],
                    "caption_text": n["caption_text"],
                    "subheader_kind": n["subheader_kind"]
                    if "subheader_kind" in n.keys()
                    else "",
                    "excluded": bool(n["excluded"]),
                    "validated_at": n["validated_at"]
                    if "validated_at" in n.keys()
                    else None,
                }
            )

        chunks = []
        cards = []
        validation_progress = []
        if node_ids:
            chunks = [
                {
                    "ref": str(c["id"]),
                    "node_ref": str(c["node_id"]),
                    "idx": c["idx"],
                    "track": c["track"],
                    "text": c["text"],
                    "status": c["status"],
                    "error": c["error"],
                    "attempts": c["attempts"],
                }
                for c in conn.execute(
                    f"SELECT * FROM chunks WHERE node_id IN ({ph}) ORDER BY id",
                    node_ids,
                ).fetchall()
            ]
            cards = [
                {
                    "ref": str(c["id"]),
                    "node_ref": str(c["node_id"]),
                    "chunk_ref": str(c["chunk_id"]) if c["chunk_id"] is not None else None,
                    "card_index": c["card_index"],
                    "front": c["front"],
                    "back": c["back"],
                    "tag": c["tag"],
                    "track": c["track"],
                    "card_hash": c["card_hash"],
                    "source": c["source"],
                    "edited": bool(c["edited"]),
                    "deleted": bool(c["deleted"]),
                }
                for c in conn.execute(
                    f"SELECT c.* {CARD_ORDER_FROM} "
                    f"WHERE c.node_id IN ({ph}) {CARD_ORDER_BY}",
                    node_ids,
                ).fetchall()
            ]
            validation_progress = [
                {
                    "validation_node_ref": str(vp["validation_node_id"]),
                    "card_ref": str(vp["card_id"]),
                    "track": vp["track"],
                    "reviewed_at": vp["reviewed_at"],
                }
                for vp in conn.execute(
                    f"""
                    SELECT vp.validation_node_id, vp.card_id, vp.track, vp.reviewed_at
                    FROM validation_progress vp
                    JOIN nodes n ON n.id = vp.validation_node_id
                    WHERE n.subject_id = ?
                    ORDER BY vp.validation_node_id, vp.card_id, vp.track
                    """,
                    (subject_id,),
                ).fetchall()
            ]

        job_row = conn.execute(
            "SELECT status, message, total, completed FROM jobs "
            "WHERE subject_id = ? ORDER BY id DESC LIMIT 1",
            (subject_id,),
        ).fetchone()
        job = dict(job_row) if job_row else None

    manifest = {
        "format_version": FORMAT_VERSION,
        "exported_at": datetime.now(tz=timezone.utc).isoformat(),
        "subject": {
            "name": subj["name"],
            "filename": subj["filename"],
            "page_count": subj["page_count"],
            "status": subj["status"],
            "created_at": subj["created_at"],
            "is_iad": bool(subj["is_iad"]) if "is_iad" in subj.keys() else False,
        },
        "tags": tags,
        "nodes": nodes,
        "chunks": chunks,
        "cards": cards,
        "job": job,
        "validation_progress": validation_progress,
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
        zf.write(pdf_path, PDF_NAME)
    return buf.getvalue(), export_archive_filename(subj["name"])


def import_subject(zip_bytes: bytes) -> tuple[int, str]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise TransferError("Invalid zip file.") from exc

    names = set(zf.namelist())
    if MANIFEST_NAME not in names or PDF_NAME not in names:
        raise TransferError(
            f"Archive must contain {MANIFEST_NAME} and {PDF_NAME}."
        )

    try:
        manifest = json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise TransferError("Invalid manifest.json.") from exc

    if manifest.get("format_version") != FORMAT_VERSION:
        raise TransferError(
            f"Unsupported archive format version: {manifest.get('format_version')!r}"
        )

    subject_meta = manifest.get("subject") or {}
    name = (subject_meta.get("name") or "").strip()
    filename = (subject_meta.get("filename") or "guide.pdf").strip() or "guide.pdf"
    if not name:
        raise TransferError("Manifest is missing subject name.")

    pdf_bytes = zf.read(PDF_NAME)
    ensure_dirs()
    dest = UPLOAD_DIR / f"{uuid.uuid4().hex}_{filename}"
    dest.write_bytes(pdf_bytes)

    node_ref_map: dict[str, int] = {}
    chunk_ref_map: dict[str, int] = {}
    card_ref_map: dict[str, int] = {}

    with get_conn() as conn:
        unique_name = _unique_subject_name(conn, name)
        cur = conn.execute(
            "INSERT INTO subjects (name, filename, pdf_path, page_count, status, is_iad, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                unique_name,
                filename,
                str(dest),
                int(subject_meta.get("page_count") or 0),
                subject_meta.get("status") or "uploaded",
                1 if subject_meta.get("is_iad") else 0,
                subject_meta.get("created_at")
                or datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        subject_id = cur.lastrowid

        for tag in manifest.get("tags") or []:
            conn.execute(
                "INSERT INTO tags (subject_id, name, definition, builtin) "
                "VALUES (?, ?, ?, ?)",
                (
                    subject_id,
                    tag.get("name") or "",
                    tag.get("definition") or "",
                    1 if tag.get("builtin") else 0,
                ),
            )

        nodes = manifest.get("nodes") or []
        pending = list(nodes)
        while pending:
            progress = False
            next_pending = []
            for node in pending:
                parent_ref = node.get("parent_ref")
                if parent_ref is not None and parent_ref not in node_ref_map:
                    next_pending.append(node)
                    continue
                parent_id = node_ref_map.get(parent_ref) if parent_ref else None
                cur = conn.execute(
                    "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, "
                    "order_index, start_page, start_line, start_char, end_page, end_line, "
                    "end_char, body_text, caption_text, subheader_kind, excluded, validated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        subject_id,
                        parent_id,
                        node.get("tier") or "section",
                        node.get("title") or "",
                        node.get("section_type") or "BODY",
                        int(node.get("order_index") or 0),
                        node.get("start_page"),
                        node.get("start_line"),
                        node.get("start_char"),
                        node.get("end_page"),
                        node.get("end_line"),
                        node.get("end_char"),
                        node.get("body_text") or "",
                        node.get("caption_text") or "",
                        node.get("subheader_kind") or "",
                        1 if node.get("excluded") else 0,
                        node.get("validated_at"),
                    ),
                )
                node_ref_map[str(node["ref"])] = cur.lastrowid
                progress = True
            if not progress and next_pending:
                raise TransferError("Could not resolve node parent references in archive.")
            pending = next_pending

        for chunk in manifest.get("chunks") or []:
            node_ref = str(chunk.get("node_ref") or "")
            if node_ref not in node_ref_map:
                raise TransferError(f"Unknown node_ref in chunk: {node_ref!r}")
            cur = conn.execute(
                "INSERT INTO chunks (node_id, idx, track, text, status, error, attempts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    node_ref_map[node_ref],
                    int(chunk.get("idx") or 0),
                    chunk.get("track") or "A",
                    chunk.get("text") or "",
                    chunk.get("status") or "pending",
                    chunk.get("error") or "",
                    int(chunk.get("attempts") or 0),
                ),
            )
            chunk_ref_map[str(chunk["ref"])] = cur.lastrowid

        for card in manifest.get("cards") or []:
            node_ref = str(card.get("node_ref") or "")
            if node_ref not in node_ref_map:
                raise TransferError(f"Unknown node_ref in card: {node_ref!r}")
            chunk_ref = card.get("chunk_ref")
            chunk_id = (
                chunk_ref_map.get(str(chunk_ref)) if chunk_ref is not None else None
            )
            cur = conn.execute(
                "INSERT INTO cards (node_id, chunk_id, card_index, front, back, tag, track, "
                "card_hash, source, edited, deleted) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    node_ref_map[node_ref],
                    chunk_id,
                    int(card.get("card_index") or 0),
                    card.get("front") or "",
                    card.get("back") or "",
                    card.get("tag") or "other",
                    card.get("track") or "A",
                    card.get("card_hash") or "",
                    card.get("source") or "ai",
                    1 if card.get("edited") else 0,
                    1 if card.get("deleted") else 0,
                ),
            )
            card_ref_map[str(card["ref"])] = cur.lastrowid

        job = manifest.get("job")
        if job:
            conn.execute(
                "INSERT INTO jobs (subject_id, status, message, total, completed) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    subject_id,
                    job.get("status") or "idle",
                    job.get("message") or "",
                    int(job.get("total") or 0),
                    int(job.get("completed") or 0),
                ),
            )

        for vp in manifest.get("validation_progress") or []:
            node_ref = str(vp.get("validation_node_ref") or "")
            card_ref = str(vp.get("card_ref") or "")
            if node_ref not in node_ref_map or card_ref not in card_ref_map:
                continue
            conn.execute(
                "INSERT INTO validation_progress "
                "(validation_node_id, card_id, track, reviewed_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    node_ref_map[node_ref],
                    card_ref_map[card_ref],
                    vp.get("track") or "master",
                    vp.get("reviewed_at")
                    or datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )

    return subject_id, unique_name
