"""Tests for editable-tree merge behavior."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.database import get_conn, init_db
from app.service import merge_into_previous


def _seed_intro_tree():
    init_db()
    with get_conn() as conn:
        sid = conn.execute(
            "INSERT INTO subjects (name, filename, pdf_path, status) "
            "VALUES ('T', 't.pdf', 'x', 'uploaded')"
        ).lastrowid
        sec_id = conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, order_index) "
            "VALUES (?, NULL, 'section', 'INTRODUCTION', 'INTRODUCTION', 0)",
            (sid,),
        ).lastrowid
        sub_id = conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, "
            "order_index, body_text, caption_text) "
            "VALUES (?, ?, 'subheader', 'INTRODUCTION', 'INTRODUCTION', 0, 'intro body', 'cap')",
            (sid, sec_id),
        ).lastrowid
    return sid, sec_id, sub_id


def test_merge_lone_subheader_into_parent_section():
    sid, sec_id, sub_id = _seed_intro_tree()
    result = merge_into_previous(sub_id)
    assert result["ok"] is True
    assert result["target_id"] == sec_id

    with get_conn() as conn:
        section = conn.execute("SELECT * FROM nodes WHERE id = ?", (sec_id,)).fetchone()
        gone = conn.execute("SELECT id FROM nodes WHERE id = ?", (sub_id,)).fetchone()
        conn.execute("DELETE FROM subjects WHERE id = ?", (sid,))

    assert gone is None
    assert section["body_text"] == "intro body"
    assert section["caption_text"] == "cap"
