"""Tests for CSV export filename construction."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.database import get_conn, init_db
from app.generation.compile import (
    WINDOWS_MAX_FILENAME,
    build_csv_filename,
    cards_to_csv,
    resolve_node_filename_parts,
)


def test_cards_to_csv_has_no_header_row():
    text = cards_to_csv([{"front": "Q?", "back": "A", "tag": "other"}])
    lines = text.strip().split("\n")
    assert len(lines) == 1
    assert lines[0] == '"Q?","A","other"'
    assert "Front" not in text


def test_build_csv_filename_section_only():
    name = build_csv_filename("Social Science", "INTRODUCTION", track="A")
    assert name == "Social_Science_INTRODUCTION_TextOnly.csv"


def test_build_csv_filename_with_topic():
    name = build_csv_filename(
        "Social Science",
        "SECTION I: OVERVIEW",
        "TRANSPORTATION MODES",
        track="master",
    )
    assert name == "Social_Science_SECTION_I_OVERVIEW_TRANSPORTATION_MODES_Master.csv"


def test_build_csv_filename_subject_only():
    name = build_csv_filename("Social Science", track="A")
    assert name == "Social_Science_TextOnly.csv"


def test_build_csv_filename_truncates_for_windows():
    long = "A" * 300
    name = build_csv_filename(long, "SECTION", "TOPIC", track="A")
    assert len(name) <= WINDOWS_MAX_FILENAME
    assert name.endswith("_TextOnly.csv")


def test_resolve_node_filename_parts_subheader():
    init_db()
    with get_conn() as conn:
        sid = conn.execute(
            "INSERT INTO subjects (name, filename, pdf_path, page_count, status) "
            "VALUES ('Social Science', 't.pdf', 'x', 1, 'uploaded')"
        ).lastrowid
        sec_id = conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, order_index) "
            "VALUES (?, NULL, 'section', 'SECTION I', 'BODY', 0)",
            (sid,),
        ).lastrowid
        sub_id = conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, order_index) "
            "VALUES (?, ?, 'subheader', 'Railroads', 'BODY', 0)",
            (sid, sec_id),
        ).lastrowid
        parts = resolve_node_filename_parts(conn, sub_id)
        conn.execute("DELETE FROM subjects WHERE id = ?", (sid,))

    assert parts == ("Social Science", "SECTION I", "Railroads")


def test_resolve_node_filename_parts_section():
    init_db()
    with get_conn() as conn:
        sid = conn.execute(
            "INSERT INTO subjects (name, filename, pdf_path, page_count, status) "
            "VALUES ('Social Science', 't.pdf', 'x', 1, 'uploaded')"
        ).lastrowid
        sec_id = conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, order_index) "
            "VALUES (?, NULL, 'section', 'INTRODUCTION', 'INTRODUCTION', 0)",
            (sid,),
        ).lastrowid
        parts = resolve_node_filename_parts(conn, sec_id)
        conn.execute("DELETE FROM subjects WHERE id = ?", (sid,))

    assert parts == ("Social Science", "INTRODUCTION", None)
