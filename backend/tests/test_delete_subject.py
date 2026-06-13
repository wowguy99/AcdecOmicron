"""Tests for subject deletion."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.database import get_conn, init_db
from app.service import delete_subject


def _seed_subject(pdf_path: str = "uploads/test.pdf") -> int:
    init_db()
    with get_conn() as conn:
        sid = conn.execute(
            "INSERT INTO subjects (name, filename, pdf_path, page_count, status) "
            "VALUES ('Test', 't.pdf', ?, 10, 'uploaded')",
            (pdf_path,),
        ).lastrowid
        sec_id = conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, order_index) "
            "VALUES (?, NULL, 'section', 'INTRODUCTION', 'INTRODUCTION', 0)",
            (sid,),
        ).lastrowid
        conn.execute(
            "INSERT INTO tags (subject_id, name, definition, builtin) "
            "VALUES (?, 'other', 'fallback', 1)",
            (sid,),
        )
        conn.execute(
            "INSERT INTO chunks (node_id, idx, track, text, status) "
            "VALUES (?, 0, 'A', 'sample', 'pending')",
            (sec_id,),
        )
    return sid


def test_delete_subject_removes_all_related_rows():
    sid = _seed_subject()
    delete_subject(sid)

    with get_conn() as conn:
        assert conn.execute("SELECT id FROM subjects WHERE id = ?", (sid,)).fetchone() is None
        assert conn.execute(
            "SELECT id FROM nodes WHERE subject_id = ?", (sid,)
        ).fetchall() == []
        assert conn.execute(
            "SELECT id FROM tags WHERE subject_id = ?", (sid,)
        ).fetchall() == []
        assert conn.execute(
            "SELECT id FROM jobs WHERE subject_id = ?", (sid,)
        ).fetchall() == []


def test_delete_subject_missing_raises():
    init_db()
    try:
        delete_subject(999999)
        assert False, "expected KeyError"
    except KeyError:
        pass
