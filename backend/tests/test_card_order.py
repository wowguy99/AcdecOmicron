"""Cards export in PDF reading order (section → subheader → chunk → card)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.database import get_conn, init_db
from app.generation.compile import (
    card_hash,
    collect_cards,
    collect_subject_cards,
    order_cards_by_source_text,
)


def _seed_subject(conn):
    sid = conn.execute(
        "INSERT INTO subjects (name, filename, pdf_path, page_count, status) "
        "VALUES ('Test', 't.pdf', 'x', 1, 'uploaded')"
    ).lastrowid
    sec_a = conn.execute(
        "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, "
        "order_index, start_page, start_line) "
        "VALUES (?, NULL, 'section', 'SECTION A', 'BODY', 0, 1, 0)",
        (sid,),
    ).lastrowid
    sec_b = conn.execute(
        "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, "
        "order_index, start_page, start_line) "
        "VALUES (?, NULL, 'section', 'SECTION B', 'BODY', 1, 5, 0)",
        (sid,),
    ).lastrowid
    sub_a1 = conn.execute(
        "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, "
        "order_index, start_page, start_line) "
        "VALUES (?, ?, 'subheader', 'Topic 1', 'BODY', 0, 1, 10)",
        (sid, sec_a),
    ).lastrowid
    sub_a2 = conn.execute(
        "INSERT INTO nodes (subject_id, parent_id, tier, title, section_type, "
        "order_index, start_page, start_line) "
        "VALUES (?, ?, 'subheader', 'Topic 2', 'BODY', 1, 2, 0)",
        (sid, sec_a),
    ).lastrowid
    return sid, sec_a, sec_b, sub_a1, sub_a2


def _insert_card(
    conn, node_id, front, *, track="A", chunk_id=None, chunk_idx=None, card_index=0
):
    if chunk_id is None and chunk_idx is not None:
        chunk_id = conn.execute(
            "INSERT INTO chunks (node_id, idx, track, text, status) "
            "VALUES (?, ?, ?, 'text', 'done')",
            (node_id, chunk_idx, track),
        ).lastrowid
    conn.execute(
        "INSERT INTO cards (node_id, chunk_id, card_index, front, back, tag, track, "
        "card_hash, source) "
        "VALUES (?, ?, ?, ?, 'back', 'other', ?, ?, 'ai')",
        (node_id, chunk_id, card_index, front, track, card_hash(front, "back")),
    )


def test_collect_cards_section_subheader_chunk_order():
    init_db()
    with get_conn() as conn:
        sid, sec_a, sec_b, sub_a1, sub_a2 = _seed_subject(conn)

        # Insert in reverse PDF order; export should still follow the guide.
        _insert_card(conn, sub_a2, "later subheader")
        _insert_card(conn, sub_a1, "chunk 1 second", chunk_idx=1)
        _insert_card(conn, sub_a1, "chunk 0 first", chunk_idx=0)
        _insert_card(conn, sec_a, "section intro")
        _insert_card(conn, sec_b, "other section")

        ordered = [c["front"] for c in collect_cards(conn, sec_a, "A")]
        conn.execute("DELETE FROM subjects WHERE id = ?", (sid,))

    assert ordered == [
        "section intro",
        "chunk 0 first",
        "chunk 1 second",
        "later subheader",
    ]


def test_collect_subject_cards_orders_sections():
    init_db()
    with get_conn() as conn:
        sid, sec_a, sec_b, sub_a1, _sub_a2 = _seed_subject(conn)
        _insert_card(conn, sec_b, "section B card")
        _insert_card(conn, sub_a1, "section A card")

        ordered = [c["front"] for c in collect_subject_cards(conn, sid, "A")]
        conn.execute("DELETE FROM subjects WHERE id = ?", (sid,))

    assert ordered == ["section A card", "section B card"]


def test_master_track_body_before_caption():
    init_db()
    with get_conn() as conn:
        sid, _sec_a, _sec_b, sub_a1, _sub_a2 = _seed_subject(conn)
        _insert_card(conn, sub_a1, "caption card", track="B", chunk_idx=0)
        _insert_card(conn, sub_a1, "body card", track="A", chunk_idx=0)

        ordered = [c["front"] for c in collect_cards(conn, sub_a1, "master")]
        conn.execute("DELETE FROM subjects WHERE id = ?", (sid,))

    assert ordered == ["body card", "caption card"]


def test_dedupe_keeps_first_in_pdf_order():
    init_db()
    with get_conn() as conn:
        sid, _sec_a, sec_b, sub_a1, _sub_a2 = _seed_subject(conn)
        dup = card_hash("dup", "back")
        conn.execute(
            "INSERT INTO cards (node_id, front, back, tag, track, card_hash, source) "
            "VALUES (?, 'dup', 'back', 'other', 'A', ?, 'ai')",
            (sub_a1, dup),
        )
        conn.execute(
            "INSERT INTO cards (node_id, front, back, tag, track, card_hash, source) "
            "VALUES (?, 'dup', 'back', 'other', 'A', ?, 'ai')",
            (sec_b, dup),
        )

        ordered = [c["front"] for c in collect_subject_cards(conn, sid, "A")]
        conn.execute("DELETE FROM subjects WHERE id = ?", (sid,))

    assert ordered == ["dup"]


def test_order_cards_by_source_text_reorders_ai_response():
    source = (
        "The first civilization arose in Mesopotamia around 3500 BCE. "
        "Writing developed on clay tablets. "
        "The Code of Hammurabi appeared in 1754 BCE."
    )
    shuffled = [
        {"front": "When was Hammurabi's code?", "back": "1754 BCE", "tag": "other"},
        {"front": "Where did civilization begin?", "back": "Mesopotamia", "tag": "other"},
        {"front": "What medium carried early writing?", "back": "clay tablets", "tag": "other"},
    ]
    ordered = order_cards_by_source_text(shuffled, source)
    assert [c["back"] for c in ordered] == [
        "Mesopotamia",
        "clay tablets",
        "1754 BCE",
    ]


def test_order_cards_uses_sentence_overlap_for_attribution():
    source = (
        "According to the International Union of Geological Sciences (IUGS), "
        "the Holocene began about 11,700 years ago."
    )
    shuffled = [
        {
            "front": "When did the Holocene begin?",
            "back": "about 11,700 years ago",
            "tag": "date",
        },
        {
            "front": "According to whom did the Holocene begin about 11,700 years ago?",
            "back": "the International Union of Geological Sciences (IUGS)",
            "tag": "other",
        },
    ]
    ordered = order_cards_by_source_text(shuffled, source)
    assert "IUGS" in ordered[0]["back"]


def test_detect_order_inversions_flags_later_card():
    from app.generation.compile import detect_order_inversions

    source = "Alpha fact here. Beta fact follows. Gamma fact last."
    cards = [
        {"id": 1, "front": "Q gamma", "back": "Gamma fact last", "tag": "other"},
        {"id": 2, "front": "Q alpha", "back": "Alpha fact here", "tag": "other"},
    ]
    flags = detect_order_inversions(cards, source)
    assert 2 in flags
    assert flags[2]["code"] == "out_of_order"


def test_reorder_node_cards_in_db_uses_full_body():
    init_db()
    with get_conn() as conn:
        sid, _sec, _sec_b, sub, _ = _seed_subject(conn)
        body = "First fact alpha. Second fact beta. Third fact gamma."
        conn.execute("UPDATE nodes SET body_text = ? WHERE id = ?", (body, sub))
        chunk_a = conn.execute(
            "INSERT INTO chunks (node_id, idx, track, text, status) "
            "VALUES (?, 0, 'A', ?, 'done')",
            (sub, "First fact alpha. Second fact beta."),
        ).lastrowid
        chunk_b = conn.execute(
            "INSERT INTO chunks (node_id, idx, track, text, status) "
            "VALUES (?, 1, 'A', ?, 'done')",
            (sub, "Third fact gamma."),
        ).lastrowid
        conn.execute(
            "INSERT INTO cards (node_id, chunk_id, card_index, front, back, tag, track, "
            "card_hash, source) VALUES (?, ?, 0, 'Q3', 'Third fact gamma', 'other', 'A', ?, 'ai')",
            (sub, chunk_b, card_hash("Q3", "Third fact gamma")),
        )
        conn.execute(
            "INSERT INTO cards (node_id, chunk_id, card_index, front, back, tag, track, "
            "card_hash, source) VALUES (?, ?, 0, 'Q1', 'First fact alpha', 'other', 'A', ?, 'ai')",
            (sub, chunk_a, card_hash("Q1", "First fact alpha")),
        )
        conn.execute(
            "INSERT INTO cards (node_id, chunk_id, card_index, front, back, tag, track, "
            "card_hash, source) VALUES (?, ?, 1, 'Q2', 'Second fact beta', 'other', 'A', ?, 'ai')",
            (sub, chunk_a, card_hash("Q2", "Second fact beta")),
        )
        from app.generation.compile import reorder_node_cards_in_db

        reorder_node_cards_in_db(conn, sub, "A")
        rows = conn.execute(
            "SELECT front FROM cards WHERE node_id = ? AND track = 'A' "
            "ORDER BY card_index",
            (sub,),
        ).fetchall()
        conn.execute("DELETE FROM subjects WHERE id = ?", (sid,))

    assert [r["front"] for r in rows] == ["Q1", "Q2", "Q3"]


def test_within_chunk_card_index_controls_export_order():
    init_db()
    with get_conn() as conn:
        sid, _sec_a, _sec_b, sub_a1, _sub_a2 = _seed_subject(conn)
        chunk_id = conn.execute(
            "INSERT INTO chunks (node_id, idx, track, text, status) "
            "VALUES (?, 0, 'A', 'alpha fact. beta fact.', 'done')",
            (sub_a1,),
        ).lastrowid
        _insert_card(conn, sub_a1, "second", chunk_id=chunk_id, card_index=1)
        _insert_card(conn, sub_a1, "first", chunk_id=chunk_id, card_index=0)

        ordered = [c["front"] for c in collect_cards(conn, sub_a1, "A")]
        conn.execute("DELETE FROM subjects WHERE id = ?", (sid,))

    assert ordered == ["first", "second"]
