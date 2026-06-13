"""Tests for hybrid flashcard validation (deterministic layer)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.validation.deterministic import (
    check_card,
    extract_back_numbers,
    extract_numbers,
    find_source_snippet,
    grounding_ratio,
    is_suspect_comparative,
)
from app.validation.ai_check import build_validation_prompt, parse_validation_response


SOURCE = (
    "Mental maps embody the highest degree of distortion and abstraction "
    "from literal representations typical of thematic maps. "
    "Absolute distance refers to a measurable span using standardized units "
    "of length, such as miles or kilometers."
)


def test_grounding_ratio_high_for_matching_back():
    ratio = grounding_ratio("Mental maps", SOURCE)
    assert ratio >= 0.5


def test_find_source_snippet_prefers_matching_sentence():
    snippet = find_source_snippet("Mental maps embody the highest degree", SOURCE)
    assert "Mental maps" in snippet


def test_suspect_comparative_detected():
    assert is_suspect_comparative(
        "What type of maps embody the highest distortion?",
        "Thematic maps",
        SOURCE,
    )


def test_extract_back_numbers_ignores_list_enumerators():
    back = "1. Environmental, 2. Cultural, 3. Population."
    assert extract_back_numbers(back) == set()
    assert extract_numbers(back) == {"1", "2", "3"}


def test_extract_back_numbers_keeps_substantive_values():
    back = "1. Environmental\n2. Invasion of 1947"
    assert "1947" in extract_back_numbers(back)
    assert "1" not in extract_back_numbers(back)
    assert "2" not in extract_back_numbers(back)


def test_extract_back_numbers_keeps_ratio_not_list_marker():
    back = "One map unit represents 3,000 real distance units; ratio 1:3,000."
    nums = extract_back_numbers(back)
    assert "3,000" in nums
    assert "1:3,000" in nums


def test_check_card_skips_number_mismatch_for_list_enumerators():
    card = {
        "front": "Name three types of patterns.",
        "back": "1. Environmental, 2. Cultural, 3. Population.",
        "source": "ai",
    }
    result = check_card(
        card,
        "Processes include environmental, cultural, and population patterns.",
    )
    codes = {f["code"] for f in result["flags"]}
    assert "number_mismatch" not in codes


def test_check_card_flags_number_mismatch():
    card = {
        "front": "What year?",
        "back": "1492",
        "source": "ai",
    }
    result = check_card(card, SOURCE)
    codes = {f["code"] for f in result["flags"]}
    assert "number_mismatch" in codes


def test_check_card_marks_comparative_as_suspect_ai():
    card = {
        "front": "What type of maps embody the highest distortion?",
        "back": "Thematic maps",
        "source": "ai",
    }
    result = check_card(card, SOURCE)
    assert result["suspect_ai"] is True


def test_check_card_skips_ai_grounding_for_glossary():
    card = {"front": "Define: foo", "back": "bar baz", "source": "glossary"}
    result = check_card(card, "")
    codes = {f["code"] for f in result["flags"]}
    assert "ungrounded" not in codes


def test_parse_validation_response():
    raw = '{"results":[{"id":3,"verdict":"error","message":"Wrong subject."}]}'
    parsed = parse_validation_response(raw)
    assert parsed[3]["verdict"] == "error"
    assert "Wrong" in parsed[3]["message"]


def test_build_validation_prompt_includes_cards():
    prompt = build_validation_prompt(SOURCE, [{"id": 1, "front": "Q", "back": "A"}])
    assert "SOURCE TEXT" in prompt
    assert '"id": 1' in prompt


def test_review_progress_skips_reviewed_flagged_cards():
    from app.db.database import get_conn, init_db
    from app.validation.runner import mark_card_reviewed, run_validation

    init_db()
    source = (
        "Mental maps embody the highest degree of distortion typical of thematic maps."
    )
    with get_conn() as conn:
        sid = conn.execute(
            "INSERT INTO subjects (name, filename, pdf_path, status) "
            "VALUES ('T', 't.pdf', 'x', 'approved')"
        ).lastrowid
        nid = conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, "
            "order_index, body_text) VALUES (?, NULL, 'section', 'S', 'BODY', 0, ?)",
            (sid, source),
        ).lastrowid
        chunk_id = conn.execute(
            "INSERT INTO chunks (node_id, idx, track, text, status) "
            "VALUES (?, 0, 'A', ?, 'done')",
            (nid, source),
        ).lastrowid
        c1 = conn.execute(
            "INSERT INTO cards (node_id, chunk_id, front, back, tag, track, card_hash, source) "
            "VALUES (?, ?, 'Q1', 'Thematic maps', 'other', 'A', 'h1', 'ai')",
            (nid, chunk_id),
        ).lastrowid
        conn.execute(
            "INSERT INTO cards (node_id, front, back, tag, track, card_hash, source) "
            "VALUES (?, 'Q2', 'A2', 'other', 'A', 'h2', 'glossary')",
            (nid,),
        ).lastrowid

    mark_card_reviewed(nid, c1, "A", "Q1 edited", "Mental maps", "other")

    report = run_validation(nid, "A")
    assert report["reviewed_count"] == 1
    assert report["items"] == []
    assert report["total_count"] == 2

    with get_conn() as conn:
        row = conn.execute(
            "SELECT front, back FROM cards WHERE id = ?", (c1,)
        ).fetchone()
        conn.execute("DELETE FROM subjects WHERE id = ?", (sid,))
    assert row["front"] == "Q1 edited"
    assert row["back"] == "Mental maps"


def test_run_validation_only_queues_flagged_cards():
    from app.db.database import get_conn, init_db
    from app.validation.runner import run_validation

    init_db()
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
        conn.execute(
            "INSERT INTO cards (node_id, front, back, tag, track, card_hash, source) "
            "VALUES (?, 'Q1', 'A1', 'other', 'A', 'h1', 'ai')",
            (nid,),
        )
        conn.execute(
            "INSERT INTO cards (node_id, front, back, tag, track, card_hash, source) "
            "VALUES (?, 'Q2', '1492', 'other', 'A', 'h2', 'ai')",
            (nid,),
        )

    report = run_validation(nid, "A")
    with get_conn() as conn:
        conn.execute("DELETE FROM subjects WHERE id = ?", (sid,))
    assert report["total_count"] == 2
    assert report["auto_passed_count"] >= 1
    assert len(report["items"]) <= report["flagged_count"]


def test_section_validated_when_all_subheaders_validated():
    from app.db.database import get_conn, init_db
    from app.service import get_tree
    from app.validation.runner import (
        is_effectively_validated,
        is_validated,
        require_validated,
        subject_download_ready,
    )

    init_db()
    with get_conn() as conn:
        sid = conn.execute(
            "INSERT INTO subjects (name, filename, pdf_path, status) "
            "VALUES ('T', 't.pdf', 'x', 'approved')"
        ).lastrowid
        section_id = conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, order_index) "
            "VALUES (?, NULL, 'section', 'Section I', 'BODY', 0)",
            (sid,),
        ).lastrowid
        sub1 = conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, order_index) "
            "VALUES (?, ?, 'subheader', 'Topic A', 'BODY', 0)",
            (sid, section_id),
        ).lastrowid
        sub2 = conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, order_index) "
            "VALUES (?, ?, 'subheader', 'Topic B', 'BODY', 1)",
            (sid, section_id),
        ).lastrowid
        conn.execute(
            "INSERT INTO cards (node_id, front, back, tag, track, card_hash, source) "
            "VALUES (?, 'Q1', 'A1', 'other', 'A', 'h1', 'ai')",
            (sub1,),
        )
        conn.execute(
            "INSERT INTO cards (node_id, front, back, tag, track, card_hash, source) "
            "VALUES (?, 'Q2', 'A2', 'other', 'A', 'h2', 'ai')",
            (sub2,),
        )
        conn.execute(
            "UPDATE nodes SET validated_at = datetime('now') WHERE id IN (?, ?)",
            (sub1, sub2),
        )

        assert not is_validated(conn, section_id)
        assert is_effectively_validated(conn, section_id)
        require_validated(conn, section_id)
        assert subject_download_ready(conn, sid)

    tree = get_tree(sid)
    section = tree["sections"][0]
    assert section["validated"] is True
    assert tree["subject"]["all_validated"] is True

    with get_conn() as conn:
        conn.execute("DELETE FROM subjects WHERE id = ?", (sid,))


def test_section_not_validated_until_every_subheader_with_cards_is_done():
    from app.db.database import get_conn, init_db
    from app.service import get_tree
    from app.validation.runner import is_effectively_validated, is_validated

    init_db()
    with get_conn() as conn:
        sid = conn.execute(
            "INSERT INTO subjects (name, filename, pdf_path, status) "
            "VALUES ('T', 't.pdf', 'x', 'approved')"
        ).lastrowid
        section_id = conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, order_index) "
            "VALUES (?, NULL, 'section', 'Section I', 'BODY', 0)",
            (sid,),
        ).lastrowid
        sub1 = conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, order_index) "
            "VALUES (?, ?, 'subheader', 'Topic A', 'BODY', 0)",
            (sid, section_id),
        ).lastrowid
        sub2 = conn.execute(
            "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, order_index) "
            "VALUES (?, ?, 'subheader', 'Topic B', 'BODY', 1)",
            (sid, section_id),
        ).lastrowid
        conn.execute(
            "INSERT INTO cards (node_id, front, back, tag, track, card_hash, source) "
            "VALUES (?, 'Q1', 'A1', 'other', 'A', 'h1', 'ai')",
            (sub1,),
        )
        conn.execute(
            "INSERT INTO cards (node_id, front, back, tag, track, card_hash, source) "
            "VALUES (?, 'Q2', 'A2', 'other', 'A', 'h2', 'ai')",
            (sub2,),
        )
        conn.execute(
            "UPDATE nodes SET validated_at = datetime('now') WHERE id = ?", (sub1,)
        )

        assert not is_validated(conn, section_id)
        assert not is_effectively_validated(conn, section_id)

    tree = get_tree(sid)
    assert tree["sections"][0]["validated"] is False

    with get_conn() as conn:
        conn.execute("DELETE FROM subjects WHERE id = ?", (sid,))
