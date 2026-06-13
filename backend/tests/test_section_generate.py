"""Tests for per-section generation."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.database import get_conn, init_db
from app.generation import worker


def _seed_two_sections():
    init_db()
    with get_conn() as conn:
        sid = conn.execute(
            "INSERT INTO subjects (name, filename, pdf_path, status) "
            "VALUES ('T', 't.pdf', 'x', 'uploaded')"
        ).lastrowid
        sec1 = conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, order_index) "
            "VALUES (?, NULL, 'section', 'SECTION I', 'BODY', 0)",
            (sid,),
        ).lastrowid
        sec2 = conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, order_index) "
            "VALUES (?, NULL, 'section', 'SECTION II', 'BODY', 1)",
            (sid,),
        ).lastrowid
        conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, "
            "order_index, body_text) VALUES (?, ?, 'subheader', 'Sub A', 'BODY', 0, ?)",
            (sid, sec1, "A" * 7000),
        )
        conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, "
            "order_index, body_text) VALUES (?, ?, 'subheader', 'Sub B', 'BODY', 0, ?)",
            (sid, sec2, "B" * 7000),
        )
    return sid, sec1, sec2


def test_enqueue_section_only_creates_chunks_for_subtree():
    sid, sec1, sec2 = _seed_two_sections()
    pending, ids, title = worker.enqueue_section(sec1)
    assert title == "SECTION I"
    assert pending >= 1
    with get_conn() as conn:
        sec1_chunks = conn.execute(
            "SELECT COUNT(*) c FROM chunks WHERE node_id IN "
            "(SELECT id FROM nodes WHERE parent_id = ? OR id = ?)",
            (sec1, sec1),
        ).fetchone()["c"]
        sec2_chunks = conn.execute(
            "SELECT COUNT(*) c FROM chunks WHERE node_id IN "
            "(SELECT id FROM nodes WHERE parent_id = ? OR id = ?)",
            (sec2, sec2),
        ).fetchone()["c"]
        conn.execute("DELETE FROM subjects WHERE id = ?", (sid,))
    assert sec1_chunks >= 1
    assert sec2_chunks == 0


def test_approve_enqueue_does_not_start_job():
    sid, sec1, _ = _seed_two_sections()
    with patch.object(worker, "start_job") as mock_start:
        pending = worker.enqueue_subject(sid)
        mock_start.assert_not_called()
    assert pending >= 1
    with get_conn() as conn:
        subj = conn.execute("SELECT status FROM subjects WHERE id = ?", (sid,)).fetchone()
        conn.execute("DELETE FROM subjects WHERE id = ?", (sid,))
    assert subj["status"] == "approved"


def test_enqueue_subheader_only_scopes_to_subtree():
    init_db()
    with get_conn() as conn:
        sid = conn.execute(
            "INSERT INTO subjects (name, filename, pdf_path, status) "
            "VALUES ('T', 't.pdf', 'x', 'approved')"
        ).lastrowid
        sec_id = conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, order_index) "
            "VALUES (?, NULL, 'section', 'SECTION I', 'BODY', 0)",
            (sid,),
        ).lastrowid
        sub_a = conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, "
            "order_index, body_text) VALUES (?, ?, 'subheader', 'Sub A', 'BODY', 0, ?)",
            (sid, sec_id, "A" * 7000),
        ).lastrowid
        sub_b = conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, "
            "order_index, body_text) VALUES (?, ?, 'subheader', 'Sub B', 'BODY', 1, ?)",
            (sid, sec_id, "B" * 7000),
        ).lastrowid

    pending, ids, title = worker.enqueue_section(sub_a)
    assert title == "Sub A"
    assert pending >= 1
    assert sub_a in ids
    assert sub_b not in ids

    with get_conn() as conn:
        conn.execute("DELETE FROM subjects WHERE id = ?", (sid,))


def test_retry_failed_chunks_requeues_errors():
    sid, sec1, _ = _seed_two_sections()
    worker.enqueue_subject(sid)
    with get_conn() as conn:
        ids = worker.subtree_ids(conn, sec1)
        conn.execute(
            "UPDATE chunks SET status = 'error' WHERE node_id IN "
            "(SELECT id FROM nodes WHERE parent_id = ? OR id = ?)",
            (sec1, sec1),
        )
        assert worker.count_pending_chunks(conn, ids) == 0
        n = worker.retry_failed_chunks(conn, ids)
        assert n >= 1
        assert worker.count_pending_chunks(conn, ids) == n
        conn.execute("DELETE FROM subjects WHERE id = ?", (sid,))


def test_tree_reports_chunks_done_for_section():
    sid, sec1, _ = _seed_two_sections()
    worker.enqueue_subject(sid)
    with get_conn() as conn:
        ids = worker.subtree_ids(conn, sec1)
        chunk_id = conn.execute(
            "SELECT id FROM chunks WHERE node_id IN "
            "(SELECT id FROM nodes WHERE parent_id = ? OR id = ?) LIMIT 1",
            (sec1, sec1),
        ).fetchone()["id"]
        conn.execute("UPDATE chunks SET status = 'done' WHERE id = ?", (chunk_id,))
        assert worker.count_done_chunks(conn, ids) == 1
        conn.execute("DELETE FROM subjects WHERE id = ?", (sid,))


def test_enqueue_inserts_piece_year_card_for_selected_work():
    init_db()
    with get_conn() as conn:
        sid = conn.execute(
            "INSERT INTO subjects (name, filename, pdf_path, status) "
            "VALUES ('Art', 'art.pdf', 'x', 'approved')"
        ).lastrowid
        sec_id = conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, order_index) "
            "VALUES (?, NULL, 'section', 'SECTION I', 'BODY', 0)",
            (sid,),
        ).lastrowid
        sub_id = conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, "
            "subheader_kind, order_index, body_text) "
            "VALUES (?, ?, 'subheader', ?, 'BODY', 'selected_work', 0, ?)",
            (
                sid,
                sec_id,
                "Rebbelib Navigation Chart, Marshall Islands",
                "SELECTED WORK: Rebbelib Navigation Chart (before 1892)\nBody.",
            ),
        ).lastrowid

    worker.enqueue_subject(sid)

    with get_conn() as conn:
        card = conn.execute(
            "SELECT front, back, source FROM cards WHERE node_id = ?",
            (sub_id,),
        ).fetchone()
        conn.execute("DELETE FROM subjects WHERE id = ?", (sid,))

    assert card is not None
    assert card["source"] == "piece_year"
    assert "Rebbelib Navigation Chart" in card["front"]
    assert card["back"] == "before 1892"


def test_scoped_pending_query():
    sid, sec1, sec2 = _seed_two_sections()
    worker.enqueue_subject(sid)
    with get_conn() as conn:
        ids = worker.subtree_ids(conn, sec1)
        ph = ",".join("?" for _ in ids)
        scoped = conn.execute(
            f"SELECT COUNT(*) c FROM chunks WHERE status = 'pending' AND node_id IN ({ph})",
            ids,
        ).fetchone()["c"]
        all_pending = conn.execute(
            "SELECT COUNT(*) c FROM chunks WHERE status = 'pending' AND node_id IN "
            "(SELECT id FROM nodes WHERE subject_id = ?)",
            (sid,),
        ).fetchone()["c"]
        conn.execute("DELETE FROM subjects WHERE id = ?", (sid,))
    assert scoped >= 1
    assert all_pending > scoped


def test_reset_ai_work_rebuilds_chunks_from_updated_body():
    init_db()
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
            (sid, sec, "old text " * 800),
        ).lastrowid
    worker.enqueue_section(sub)
    with get_conn() as conn:
        old_chunk = conn.execute(
            "SELECT text FROM chunks WHERE node_id = ?", (sub,)
        ).fetchone()["text"]
        assert "old text" in old_chunk
        conn.execute(
            "UPDATE nodes SET body_text = ? WHERE id = ?", ("new text " * 800, sub)
        )
        ids = worker.subtree_ids(conn, sub)
        worker.reset_ai_work(conn, ids)
    pending, _, _ = worker.enqueue_section(sub)
    assert pending >= 1
    with get_conn() as conn:
        new_chunk = conn.execute(
            "SELECT text FROM chunks WHERE node_id = ?", (sub,)
        ).fetchone()["text"]
        assert "new text" in new_chunk
        assert "old text" not in new_chunk
        conn.execute("DELETE FROM subjects WHERE id = ?", (sid,))
