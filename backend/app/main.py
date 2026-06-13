"""FastAPI app: upload, blueprint tree, editing, generation, downloads."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import service
from .config import (
    UPLOAD_DIR,
    ProviderConfig,
    ensure_dirs,
    load_config,
    public_config,
    save_config,
)
from .db.database import get_conn, init_db, purge_accidental_test_subjects
from .generation import worker
from .licensing import LicenseResult, machine_fingerprint, verify_key
from .paths import frontend_dist_dir
from .transfer import TransferError, export_subject, import_subject
from .generation.compile import (
    CARD_ORDER_BY,
    CARD_ORDER_FROM,
    cards_to_csv,
    collect_cards,
    collect_subject_cards,
    build_csv_filename,
    resolve_node_filename_parts,
    track_filter_sql,
)
from .validation import (
    clear_validation,
    invalidate_card_ancestors,
    mark_card_reviewed,
    mark_validated,
    require_validated,
    run_validation,
    subject_download_ready,
)

app = FastAPI(title="AcDec Atomic Flashcard Generator")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    ensure_dirs()
    init_db()
    purge_accidental_test_subjects()


# --- config -----------------------------------------------------------------

@app.get("/api/config")
def get_config() -> dict:
    return public_config(load_config())


class ConfigIn(BaseModel):
    provider: str
    model: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    rpm: int = 15
    rpd: int = 1000
    temperature: float = 0.1


@app.post("/api/config")
def post_config(body: ConfigIn) -> dict:
    current = load_config()
    cfg = ProviderConfig(
        provider=body.provider,
        model=body.model,
        # keep existing key if the UI sends blank (key is masked on read)
        api_key=body.api_key if body.api_key else current.api_key,
        base_url=body.base_url,
        rpm=body.rpm,
        rpd=body.rpd,
        temperature=body.temperature,
        license_key=current.license_key,
    )
    save_config(cfg)
    return public_config(cfg)


# --- license ----------------------------------------------------------------

def _license_status(stored_key: str) -> LicenseResult:
    if not stored_key:
        return LicenseResult(status="missing")
    return verify_key(stored_key)


def _license_payload(stored_key: str) -> dict:
    result = _license_status(stored_key)
    return {
        "machine_id": machine_fingerprint(),
        "status": result.status,
        "expires_at": result.expires_at,
        "expires_iso": result.expires_iso,
        "has_key": bool(stored_key),
    }


@app.get("/api/license")
def get_license() -> dict:
    cfg = load_config()
    return _license_payload(cfg.license_key)


class LicenseIn(BaseModel):
    key: str


@app.post("/api/license")
def post_license(body: LicenseIn) -> dict:
    submitted = body.key.strip()
    result = verify_key(submitted)
    cfg = load_config()
    if result.status == "valid":
        cfg.license_key = submitted
        save_config(cfg)
        return _license_payload(cfg.license_key)
    return {
        "machine_id": machine_fingerprint(),
        "status": result.status,
        "expires_at": result.expires_at,
        "expires_iso": result.expires_iso,
        "has_key": bool(cfg.license_key),
    }


# --- subjects / upload ------------------------------------------------------

@app.post("/api/subjects")
async def create_subject(
    file: UploadFile = File(...),
    name: str = Form(...),
    tags: str = Form("[]"),
    is_iad: str = Form("false"),
) -> dict:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Please upload a PDF file.")
    try:
        tag_list = json.loads(tags)
    except json.JSONDecodeError:
        raise HTTPException(400, "tags must be a JSON array.")

    ensure_dirs()
    dest = UPLOAD_DIR / f"{uuid.uuid4().hex}_{file.filename}"
    dest.write_bytes(await file.read())
    try:
        subject_id = service.create_subject_from_pdf(
            name=name,
            filename=file.filename,
            pdf_path=str(dest),
            tags=tag_list,
            is_iad=is_iad.strip().lower() in {"1", "true", "yes", "on"},
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Failed to parse PDF: {exc}")
    return {"subject_id": subject_id}


@app.get("/api/subjects")
def get_subjects() -> list:
    return service.list_subjects()


@app.delete("/api/subjects/{subject_id}")
def delete_subject(subject_id: int) -> dict:
    try:
        service.delete_subject(subject_id)
    except KeyError:
        raise HTTPException(404, "Subject not found.")
    return {"ok": True}


@app.get("/api/subjects/{subject_id}/export")
def export_subject_archive(subject_id: int) -> Response:
    try:
        data, filename = export_subject(subject_id)
    except KeyError:
        raise HTTPException(404, "Subject not found.")
    except TransferError as exc:
        raise HTTPException(400, str(exc))
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/subjects/import")
async def import_subject_archive(file: UploadFile = File(...)) -> dict:
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(400, "Please upload a .acdec-subject.zip export file.")
    try:
        subject_id, name = import_subject(await file.read())
    except TransferError as exc:
        raise HTTPException(400, str(exc))
    return {"subject_id": subject_id, "name": name}


@app.get("/api/subjects/{subject_id}/tree")
def get_tree(subject_id: int) -> dict:
    try:
        return service.get_tree(subject_id)
    except KeyError:
        raise HTTPException(404, "Subject not found.")


# --- editable approval gate -------------------------------------------------

class RenameIn(BaseModel):
    title: str


class ExcludeIn(BaseModel):
    excluded: bool


class ReparentIn(BaseModel):
    parent_id: Optional[int] = None


@app.post("/api/nodes/{node_id}/rename")
def rename_node(node_id: int, body: RenameIn) -> dict:
    service.rename_node(node_id, body.title)
    return {"ok": True}


@app.delete("/api/nodes/{node_id}")
def delete_node(node_id: int) -> dict:
    service.delete_node(node_id)
    return {"ok": True}


@app.post("/api/nodes/{node_id}/exclude")
def exclude_node(node_id: int, body: ExcludeIn) -> dict:
    service.set_excluded(node_id, body.excluded)
    return {"ok": True}


@app.post("/api/nodes/{node_id}/reparent")
def reparent_node(node_id: int, body: ReparentIn) -> dict:
    service.reparent_node(node_id, body.parent_id)
    return {"ok": True}


@app.post("/api/nodes/{node_id}/merge")
def merge_node(node_id: int) -> dict:
    result = service.merge_into_previous(node_id)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "Merge failed."))
    return result


# --- generation -------------------------------------------------------------

@app.post("/api/subjects/{subject_id}/approve")
def approve(subject_id: int) -> dict:
    worker.enqueue_subject(subject_id)
    cfg = load_config()
    return {
        "approved": True,
        "has_key": bool(cfg.api_key),
        "message": "Structure approved. Generate sections individually.",
    }


@app.post("/api/subjects/{subject_id}/reparse")
def reparse_subject(subject_id: int) -> dict:
    try:
        return service.reparse_subject(subject_id)
    except KeyError:
        raise HTTPException(404, "Subject not found.")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Failed to re-parse PDF: {exc}")


@app.post("/api/subjects/{subject_id}/resume")
def resume(subject_id: int) -> dict:
    started = worker.start_job(subject_id)
    return {"started": started}


@app.post("/api/subjects/{subject_id}/stop")
def stop_generation(subject_id: int) -> dict:
    with get_conn() as conn:
        subj = conn.execute(
            "SELECT id FROM subjects WHERE id = ?", (subject_id,)
        ).fetchone()
        if not subj:
            raise HTTPException(404, "Subject not found.")
    stopped = worker.stop_job(subject_id)
    return {"ok": True, "stopped": stopped}


@app.post("/api/nodes/{node_id}/generate")
def generate_section(node_id: int) -> dict:
    with get_conn() as conn:
        node = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if not node:
            raise HTTPException(404, "Node not found.")
        if node["tier"] not in ("section", "subheader"):
            raise HTTPException(
                400, "Generate is only available on section or subheader nodes."
            )
        subj = conn.execute(
            "SELECT status FROM subjects WHERE id = ?", (node["subject_id"],)
        ).fetchone()
        if not subj or subj["status"] == "uploaded":
            raise HTTPException(400, "Approve the tree structure before generating.")
        if node["excluded"]:
            raise HTTPException(400, "This section is excluded.")
        stype = node["section_type"]
        if stype in worker.NON_GENERATABLE:
            raise HTTPException(400, f"Section type {stype} is not generatable.")
        if stype in worker.DETERMINISTIC_TYPES:
            pending, _, title = worker.enqueue_section(node_id)
            return {
                "started": False,
                "deterministic": True,
                "pending_chunks": pending,
                "section_title": title,
            }

    cfg = load_config()
    if not cfg.api_key:
        raise HTTPException(
            400, "Configure an AI provider API key in Settings before generating."
        )

    pending, scope_ids, title = worker.enqueue_section(node_id)
    with get_conn() as conn:
        worker.retry_failed_chunks(conn, scope_ids)
        pending = worker.count_pending_chunks(conn, scope_ids)
    if pending == 0:
        return {
            "started": False,
            "pending_chunks": 0,
            "section_title": title,
            "message": "Already generated. Use ↻ to regenerate.",
        }
    started = worker.start_job(node["subject_id"], scope_ids, title)
    if not started:
        raise HTTPException(
            409,
            "Generation is already running for this subject. Wait for it to finish.",
        )
    return {
        "started": True,
        "pending_chunks": pending,
        "section_title": title,
    }


@app.post("/api/nodes/{node_id}/regenerate")
def regenerate(node_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Node not found.")
        if row["tier"] not in ("section", "subheader"):
            raise HTTPException(
                400, "Regenerate is only available on section or subheader nodes."
            )
        subj = conn.execute(
            "SELECT status FROM subjects WHERE id = ?", (row["subject_id"],)
        ).fetchone()
        if not subj or subj["status"] == "uploaded":
            raise HTTPException(400, "Approve the tree structure before regenerating.")
        subject_id = row["subject_id"]
        node_ids = worker.subtree_ids(conn, node_id)
        worker.reset_ai_work(conn, node_ids)
        clear_validation(node_ids, conn)

    cfg = load_config()
    if not cfg.api_key and row["section_type"] not in worker.DETERMINISTIC_TYPES:
        raise HTTPException(400, "Configure an AI provider API key in Settings.")

    pending, scope_ids, title = worker.enqueue_section(node_id)
    with get_conn() as conn:
        worker.retry_failed_chunks(conn, scope_ids)
        pending = worker.count_pending_chunks(conn, scope_ids)
    started = False
    message = ""
    if pending == 0:
        message = "Nothing to regenerate — no text chunks for this section."
    elif not cfg.api_key:
        message = "Chunks reset. Configure an API key in Settings, then click Generate."
    elif not worker.start_job(subject_id, scope_ids, title):
        raise HTTPException(
            409,
            "Generation is already running for this subject. Wait for it to finish.",
        )
    else:
        started = True
        message = f"Regenerating {pending} chunk(s)…"
    return {
        "ok": True,
        "started": started,
        "pending_chunks": pending,
        "section_title": title,
        "message": message,
    }


# --- subsection info --------------------------------------------------------

@app.get("/api/nodes/{node_id}/info")
def subsection_info(node_id: int) -> dict:
    try:
        return service.get_subsection_info(node_id)
    except KeyError:
        raise HTTPException(404, "Node not found.")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


# --- card review ------------------------------------------------------------

@app.get("/api/nodes/{node_id}/cards")
def list_cards(node_id: int, track: str = "master") -> list:
    with get_conn() as conn:
        node_ids = worker.subtree_ids(conn, node_id)
        ph = ",".join("?" for _ in node_ids)
        rows = conn.execute(
            f"SELECT c.id, c.front, c.back, c.tag, c.track, c.source "
            f"{CARD_ORDER_FROM} "
            f"WHERE c.node_id IN ({ph}) AND c.deleted = 0 {track_filter_sql(track)} "
            f"{CARD_ORDER_BY}",
            node_ids,
        ).fetchall()
        return [dict(r) for r in rows]


class CardIn(BaseModel):
    front: str
    back: str
    tag: str


@app.put("/api/cards/{card_id}")
def update_card(card_id: int, body: CardIn) -> dict:
    from .generation.compile import card_hash

    with get_conn() as conn:
        row = conn.execute(
            "SELECT node_id FROM cards WHERE id = ?", (card_id,)
        ).fetchone()
        conn.execute(
            "UPDATE cards SET front = ?, back = ?, tag = ?, card_hash = ?, edited = 1 "
            "WHERE id = ?",
            (body.front, body.back, body.tag, card_hash(body.front, body.back), card_id),
        )
        if row:
            invalidate_card_ancestors(row["node_id"], conn)
    return {"ok": True}


@app.delete("/api/cards/{card_id}")
def delete_card(card_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, node_id FROM cards WHERE id = ? AND deleted = 0",
            (card_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Card not found.")
        conn.execute("UPDATE cards SET deleted = 1 WHERE id = ?", (card_id,))
        invalidate_card_ancestors(row["node_id"], conn)
    return {"ok": True}


# --- validation -------------------------------------------------------------

class ValidateIn(BaseModel):
    track: str = "master"


@app.post("/api/nodes/{node_id}/validate")
def validate_node(node_id: int, body: ValidateIn) -> dict:
    if body.track not in ("A", "master"):
        raise HTTPException(400, "track must be 'A' or 'master'.")
    with get_conn() as conn:
        node = conn.execute("SELECT id FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if not node:
            raise HTTPException(404, "Node not found.")
    try:
        return run_validation(node_id, body.track)
    except KeyError:
        raise HTTPException(404, "Node not found.")


class ReviewCardIn(BaseModel):
    card_id: int
    track: str = "master"
    front: str
    back: str
    tag: str


@app.post("/api/nodes/{node_id}/validate/review")
def review_card(node_id: int, body: ReviewCardIn) -> dict:
    if body.track not in ("A", "master"):
        raise HTTPException(400, "track must be 'A' or 'master'.")
    with get_conn() as conn:
        node = conn.execute("SELECT id FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if not node:
            raise HTTPException(404, "Node not found.")
    try:
        mark_card_reviewed(
            node_id, body.card_id, body.track, body.front, body.back, body.tag
        )
    except KeyError:
        raise HTTPException(404, "Card not found.")
    return {"ok": True}


@app.post("/api/nodes/{node_id}/validate/complete")
def complete_validation(node_id: int, body: ValidateIn) -> dict:
    if body.track not in ("A", "master"):
        raise HTTPException(400, "track must be 'A' or 'master'.")
    with get_conn() as conn:
        node = conn.execute("SELECT id FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if not node:
            raise HTTPException(404, "Node not found.")
    mark_validated(node_id, body.track)
    return {"ok": True, "validated": True}


# --- downloads --------------------------------------------------------------

@app.get("/api/subjects/{subject_id}/download")
def download_subject(subject_id: int, track: str = "A") -> Response:
    if track not in ("A", "master"):
        raise HTTPException(400, "track must be 'A' or 'master'.")
    with get_conn() as conn:
        subj = conn.execute(
            "SELECT name FROM subjects WHERE id = ?", (subject_id,)
        ).fetchone()
        if not subj:
            raise HTTPException(404, "Subject not found.")
        if not subject_download_ready(conn, subject_id):
            raise HTTPException(
                403,
                "Validate every section with cards before downloading the full subject.",
            )
        cards = collect_subject_cards(conn, subject_id, track)
    csv_text = cards_to_csv(cards)
    filename = build_csv_filename(subj["name"], track=track)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/download")
def download(node_id: int, track: str = "A") -> Response:
    if track not in ("A", "master"):
        raise HTTPException(400, "track must be 'A' or 'master'.")
    with get_conn() as conn:
        subject, section, topic = resolve_node_filename_parts(conn, node_id)
        if subject == "deck":
            raise HTTPException(404, "Node not found.")
        try:
            require_validated(conn, node_id)
        except PermissionError as exc:
            raise HTTPException(403, str(exc))
        cards = collect_cards(conn, node_id, track)
    csv_text = cards_to_csv(cards)
    filename = build_csv_filename(subject, section, topic, track)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- static frontend (built) ------------------------------------------------

_FRONTEND_DIST = frontend_dist_dir()
if _FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="static")
