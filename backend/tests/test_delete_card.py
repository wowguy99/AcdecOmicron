"""Tests for card deletion API."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.database import get_conn, init_db
from app.main import app


@pytest.fixture()
def client():
    init_db()
    return TestClient(app)


def _seed_card():
    with get_conn() as conn:
        sid = conn.execute(
            "INSERT INTO subjects (name, filename, pdf_path, status) "
            "VALUES ('T', 't.pdf', 'x', 'approved')"
        ).lastrowid
        nid = conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, order_index) "
            "VALUES (?, NULL, 'section', 'S', 'BODY', 0)",
            (sid,),
        ).lastrowid
        cid = conn.execute(
            "INSERT INTO cards (node_id, front, back, tag, track, card_hash, source) "
            "VALUES (?, 'Q', 'A', 'other', 'A', 'hash1', 'ai')",
            (nid,),
        ).lastrowid
        conn.execute(
            "UPDATE nodes SET validated_at = datetime('now') WHERE id = ?", (nid,)
        )
    return cid, nid


def test_delete_card_soft_deletes_and_clears_validation(client):
    card_id, node_id = _seed_card()
    res = client.delete(f"/api/cards/{card_id}")
    assert res.status_code == 200
    assert res.json()["ok"] is True

    with get_conn() as conn:
        row = conn.execute(
            "SELECT deleted FROM cards WHERE id = ?", (card_id,)
        ).fetchone()
        node = conn.execute(
            "SELECT validated_at FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()
        conn.execute("DELETE FROM subjects WHERE id = (SELECT subject_id FROM nodes WHERE id = ?)", (node_id,))
    assert row["deleted"] == 1
    assert node["validated_at"] is None


def test_delete_card_missing_returns_404(client):
    res = client.delete("/api/cards/999999")
    assert res.status_code == 404
