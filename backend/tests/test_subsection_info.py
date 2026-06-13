"""Tests for subsection info API."""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.database import get_conn, init_db
from app.main import app
from app.parsing.snippets import first_last_sentences
from app.service import get_subsection_info


@pytest.fixture()
def client():
    init_db()
    return TestClient(app)


def test_first_last_sentences():
    text = "First sentence here. Middle content ignored. Last sentence ends!"
    first, last = first_last_sentences(text)
    assert first == "First sentence here."
    assert last == "Last sentence ends!"


def test_first_last_sentences_empty():
    assert first_last_sentences("") == ("(empty)", "(empty)")


def _seed_subheader(*, body_text: str, page_map: str | None = None, cards: list[tuple[str, str]] | None = None):
    with get_conn() as conn:
        sid = conn.execute(
            "INSERT INTO subjects (name, filename, pdf_path, page_count, status, printed_page_map) "
            "VALUES ('T', 't.pdf', 'x', 20, 'approved', ?)",
            (page_map,),
        ).lastrowid
        conn.execute(
            "INSERT INTO tags (subject_id, name, definition, builtin) "
            "VALUES (?, 'statistic', 'A number', 0)",
            (sid,),
        )
        conn.execute(
            "INSERT INTO tags (subject_id, name, definition, builtin) "
            "VALUES (?, 'other', 'Fallback', 1)",
            (sid,),
        )
        section_id = conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, order_index) "
            "VALUES (?, NULL, 'section', 'Section I', 'BODY', 0)",
            (sid,),
        ).lastrowid
        sub_id = conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, order_index, "
            "start_page, start_line, end_page, end_line, body_text, caption_text, subheader_kind) "
            "VALUES (?, ?, 'subheader', 'Topic A', 'BODY', 0, 5, 2, 7, 0, ?, 'Caption line.', 'selected_work')",
            (sid, section_id, body_text),
        ).lastrowid
        for tag, track in cards or []:
            conn.execute(
                "INSERT INTO cards (node_id, front, back, tag, track, card_hash, source) "
                "VALUES (?, 'Q', 'A', ?, ?, 'h', 'ai')",
                (sub_id, tag, track),
            )
    return sid, sub_id


def test_get_subsection_info_sentences_and_pages(client):
    body = "Alpha opens the topic. Beta closes it."
    page_map = json.dumps({"12": 5, "14": 7})
    _, sub_id = _seed_subheader(body_text=body, page_map=page_map)

    info = get_subsection_info(sub_id)
    assert info["first_sentence"] == "Alpha opens the topic."
    assert info["last_sentence"] == "Beta closes it."
    assert info["pdf_start_page"] == 6
    assert info["pdf_end_page"] == 8
    assert info["printed_start_page"] == 12
    assert info["printed_end_page"] == 14
    assert info["subheader_kind"] == "selected_work"
    assert info["body_char_count"] == len(body)
    assert info["caption_char_count"] == len("Caption line.")

    res = client.get(f"/api/nodes/{sub_id}/info")
    assert res.status_code == 200
    assert res.json()["title"] == "Topic A"


def test_get_subsection_info_tag_counts(client):
    _, sub_id = _seed_subheader(
        body_text="One. Two.",
        cards=[("statistic", "A"), ("other", "A"), ("other", "master")],
    )

    info = get_subsection_info(sub_id)
    assert info["cards_total"] == 3
    by_name = {t["name"]: t["count"] for t in info["tag_counts"]}
    assert by_name["statistic"] == 1
    assert by_name["other"] == 2


def test_get_subsection_info_without_page_map():
    _, sub_id = _seed_subheader(body_text="Only sentence.")
    info = get_subsection_info(sub_id)
    assert info["printed_start_page"] is None
    assert info["printed_end_page"] is None
    assert info["pdf_start_page"] == 6


def test_subsection_info_rejects_section_node(client):
    with get_conn() as conn:
        sid = conn.execute(
            "INSERT INTO subjects (name, filename, pdf_path, status) "
            "VALUES ('T', 't.pdf', 'x', 'approved')"
        ).lastrowid
        section_id = conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, order_index) "
            "VALUES (?, NULL, 'section', 'S', 'BODY', 0)",
            (sid,),
        ).lastrowid

    res = client.get(f"/api/nodes/{section_id}/info")
    assert res.status_code == 400

    with get_conn() as conn:
        conn.execute("DELETE FROM subjects WHERE id = ?", (sid,))


def test_subsection_info_missing_node(client):
    res = client.get("/api/nodes/999999/info")
    assert res.status_code == 404
