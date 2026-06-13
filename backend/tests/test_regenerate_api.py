"""Tests for regenerate and reparse API endpoints."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.database import get_conn, init_db
from app.generation import worker
from app.main import app


@pytest.fixture()
def client():
    init_db()
    return TestClient(app)


def _seed_subheader_with_cards():
    with get_conn() as conn:
        sid = conn.execute(
            "INSERT INTO subjects (name, filename, pdf_path, status) "
            "VALUES ('T', 't.pdf', 'x', 'approved')"
        ).lastrowid
        sec = conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, order_index) "
            "VALUES (?, NULL, 'section', 'SECTION I', 'BODY', 0)",
            (sid,),
        ).lastrowid
        sub = conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, "
            "order_index, body_text) VALUES (?, ?, 'subheader', 'Sub A', 'BODY', 0, ?)",
            (sid, sec, "chunk text " * 800),
        ).lastrowid
    worker.enqueue_section(sub)
    with get_conn() as conn:
        chunk = conn.execute(
            "SELECT id FROM chunks WHERE node_id = ?", (sub,)
        ).fetchone()
        assert chunk is not None
        conn.execute(
            "INSERT INTO cards (node_id, chunk_id, front, back, tag, track, card_hash, source) "
            "VALUES (?, ?, 'Q', 'A', 'other', 'A', 'hash1', 'ai')",
            (sub, chunk["id"]),
        )
        conn.execute(
            "INSERT INTO validation_progress (validation_node_id, card_id, track) "
            "SELECT ?, id, 'A' FROM cards WHERE node_id = ?",
            (sub, sub),
        )
    return sid, sec, sub


def test_regenerate_without_api_key_returns_400_not_500(client):
    _, _, sub = _seed_subheader_with_cards()
    fake_cfg = type("Cfg", (), {"api_key": "", "rpm": 60, "rpd": 1000})()
    with patch("app.main.load_config", return_value=fake_cfg):
        res = client.post(f"/api/nodes/{sub}/regenerate")
    assert res.status_code == 400
    assert "API key" in res.json()["detail"]


def test_regenerate_rebuilds_chunks_and_starts_job(client):
    sid, _, sub = _seed_subheader_with_cards()
    fake_cfg = type("Cfg", (), {"api_key": "test-key", "rpm": 60, "rpd": 1000})()
    with patch("app.main.load_config", return_value=fake_cfg), patch.object(
        worker, "start_job", return_value=True
    ) as mock_start:
        res = client.post(f"/api/nodes/{sub}/regenerate")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["started"] is True
    assert body["pending_chunks"] >= 1
    mock_start.assert_called_once()
    with get_conn() as conn:
        cards = conn.execute(
            "SELECT COUNT(*) c FROM cards WHERE node_id = ? AND chunk_id IS NOT NULL",
            (sub,),
        ).fetchone()["c"]
        pending = conn.execute(
            "SELECT COUNT(*) c FROM chunks WHERE node_id = ? AND status = 'pending'",
            (sub,),
        ).fetchone()["c"]
        conn.execute("DELETE FROM subjects WHERE id = ?", (sid,))
    assert cards == 0
    assert pending >= 1


def test_regenerate_unapproved_returns_400(client):
    with get_conn() as conn:
        sid = conn.execute(
            "INSERT INTO subjects (name, filename, pdf_path, status) "
            "VALUES ('T', 't.pdf', 'x', 'uploaded')"
        ).lastrowid
        nid = conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, order_index) "
            "VALUES (?, NULL, 'section', 'S', 'BODY', 0)",
            (sid,),
        ).lastrowid
    res = client.post(f"/api/nodes/{nid}/regenerate")
    assert res.status_code == 400
    with get_conn() as conn:
        conn.execute("DELETE FROM subjects WHERE id = ?", (sid,))


def test_reparse_missing_pdf_returns_400_with_message(client):
    sid, _, _ = _seed_subheader_with_cards()
    res = client.post(f"/api/subjects/{sid}/reparse")
    assert res.status_code == 400
    assert "PDF file not found" in res.json()["detail"]
    with get_conn() as conn:
        conn.execute("DELETE FROM subjects WHERE id = ?", (sid,))
