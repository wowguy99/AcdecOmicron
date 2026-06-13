"""Tests for stopping an in-flight generation job."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.database import get_conn, init_db
from app.generation import worker


def _seed_running_job():
    init_db()
    with get_conn() as conn:
        sid = conn.execute(
            "INSERT INTO subjects (name, filename, pdf_path, status) "
            "VALUES ('T', 't.pdf', 'x', 'generating')"
        ).lastrowid
        nid = conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, order_index) "
            "VALUES (?, NULL, 'section', 'SECTION I', 'BODY', 0)",
            (sid,),
        ).lastrowid
        chunk_id = conn.execute(
            "INSERT INTO chunks (node_id, idx, track, text, status) "
            "VALUES (?, 0, 'A', 'body', 'in_progress')",
            (nid,),
        ).lastrowid
        conn.execute(
            "INSERT INTO jobs (subject_id, status, total, completed, message) "
            "VALUES (?, 'running', 3, 1, 'Generating...')",
            (sid,),
        )
    return sid, chunk_id


def test_stop_job_resets_in_progress_chunk_and_marks_cancelled():
    sid, chunk_id = _seed_running_job()
    assert worker.stop_job(sid) is True
    with get_conn() as conn:
        chunk = conn.execute(
            "SELECT status FROM chunks WHERE id = ?", (chunk_id,)
        ).fetchone()
        job = conn.execute(
            "SELECT status, message FROM jobs WHERE subject_id = ? ORDER BY id DESC LIMIT 1",
            (sid,),
        ).fetchone()
        subj = conn.execute(
            "SELECT status FROM subjects WHERE id = ?", (sid,)
        ).fetchone()
        conn.execute("DELETE FROM subjects WHERE id = ?", (sid,))
    assert chunk["status"] == "pending"
    assert job["status"] == "cancelled"
    assert job["message"] == "Stopped by user."
    assert subj["status"] == "approved"


def test_stop_job_when_idle_returns_false():
    init_db()
    with get_conn() as conn:
        sid = conn.execute(
            "INSERT INTO subjects (name, filename, pdf_path, status) "
            "VALUES ('T', 't.pdf', 'x', 'approved')"
        ).lastrowid
    assert worker.stop_job(sid) is False
