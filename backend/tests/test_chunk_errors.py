"""Tests for chunk error reporting."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.database import get_conn, init_db
from app.generation.worker import _failure_summary, list_chunk_failures


def test_list_chunk_failures_includes_node_context():
    init_db()
    with get_conn() as conn:
        sid = conn.execute(
            "INSERT INTO subjects (name, filename, pdf_path, status) "
            "VALUES ('T', 't.pdf', 'x', 'approved')"
        ).lastrowid
        sec_id = conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, order_index) "
            "VALUES (?, NULL, 'section', 'Regional Analysis', 'BODY', 0)",
            (sid,),
        ).lastrowid
        sub_id = conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, order_index) "
            "VALUES (?, ?, 'subheader', 'Europe', 'BODY', 0)",
            (sid, sec_id),
        ).lastrowid
        conn.execute(
            "INSERT INTO chunks (node_id, idx, track, text, status, error, attempts) "
            "VALUES (?, 1, 'A', 'text', 'error', 'Gemini 429: quota exceeded', 2)",
            (sub_id,),
        )

        failures = list_chunk_failures(conn, sid)
        conn.execute("DELETE FROM subjects WHERE id = ?", (sid,))

    assert len(failures) == 1
    assert failures[0]["error"] == "Gemini 429: quota exceeded"
    assert failures[0]["section_title"] == "Regional Analysis"
    assert failures[0]["node_title"] == "Europe"
    assert failures[0]["attempts"] == 2


def test_failure_summary_includes_first_error():
    failures = [{"error": "Could not parse AI response as JSON: no parsable JSON object found"}]
    msg = _failure_summary("Regional Analysis", failures)
    assert "Regional Analysis" in msg
    assert "Could not parse AI response" in msg
    assert "↻" in msg
