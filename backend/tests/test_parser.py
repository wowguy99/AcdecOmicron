"""Golden-file tests for the parser (the riskiest component).

Asserted against the bundled sample guide. These pin the structure, section
typing, offset slicing, superscript handling, furniture stripping, and
deterministic card extraction so regressions are caught immediately.
"""
import re

import pytest


def _body_sections(sections):
    return [s for s in sections if s.section_type == "BODY"]


def test_section_structure(blueprint):
    _, sections = blueprint
    body = _body_sections(sections)
    titles = [s.title for s in body]
    assert any("SECTION I" in t for t in titles)
    assert any("SECTION V" in t for t in titles)
    # Subheader counts (golden values for this guide).
    counts = {s.title.split(":")[0]: len(s.subheaders) for s in body}
    assert counts["SECTION I"] == 7
    assert counts["SECTION II"] == 6
    assert counts["SECTION III"] == 9
    assert counts["SECTION IV"] == 10


def test_section_types_present(blueprint):
    _, sections = blueprint
    types = {s.section_type for s in sections}
    for expected in {
        "GLOSSARY", "TIMELINE", "NOTES", "BIBLIOGRAPHY", "CONCLUSION",
        "INTRODUCTION", "SECTION_SUMMARY", "BODY",
    }:
        assert expected in types, expected


def test_subheader_offsets_ordered(blueprint):
    _, sections = blueprint
    for sec in _body_sections(sections):
        for sub in sec.subheaders:
            assert (sub.start_page, sub.start_line) <= (sub.end_page, sub.end_line)
            assert sub.body_text  # non-empty slice


def test_footnote_superscripts_stripped(blueprint):
    """Body text should not contain 'word.<digit>' footnote artifacts, but must
    keep real numbers like years."""
    _, sections = blueprint
    sec1 = _body_sections(sections)[0]
    text = "\n".join(s.body_text for s in sec1.subheaders)
    # No 'sentence.<1-3 digits>' glued footnotes.
    assert not re.search(r"[a-z]\.\d{1,3}\b", text)


def test_inline_photo_caption_detection():
    from app.parsing.captions import is_inline_photo_caption

    assert is_inline_photo_caption(
        "Two programmers working with the IBM 704 computer."
    )
    assert is_inline_photo_caption(
        "This vintage photograph illustrates the penny-farthing's design."
    )
    assert not is_inline_photo_caption(
        "programmers at Bell Laboratories in Murray Hill, New Jersey, "
        "used an IBM 704 computer to synthesize the song for a demonstration."
    )
    assert not is_inline_photo_caption("LISTENING GUIDE 1: Example Song")
    assert not is_inline_photo_caption("photograph was added to the sheet music.")
    assert is_inline_photo_caption("Photo by Subhashish Panigrahi")
    assert is_inline_photo_caption(
        "This rib-bone fragment contains a carved image of a horse's head."
    )


def test_music_daisy_bell_photo_caption_moves_to_master_source():
    from pathlib import Path

    from app.parsing.captions import attach_captions
    from app.parsing.structure import build_blueprint, collapse_duplicate_singletons

    guide = (
        Path(__file__).resolve().parent.parent.parent
        / "Guides"
        / "MusicRG_Transportation.pdf"
    )
    if not guide.exists():
        import pytest

        pytest.skip(f"music guide not found at {guide}")

    _, sections = build_blueprint(str(guide))
    attach_captions(_, sections)
    collapse_duplicate_singletons(sections)
    sub = next(
        s
        for sec in sections
        for s in sec.subheaders
        if "Daisy Bell" in s.title
    )
    assert "Two programmers working with the IBM 704" not in (sub.body_text or "")
    assert "IBM 704" in (sub.caption_text or "")
    assert "computer-generated" in (sub.body_text or "").lower()
    assert "photograph was added to the sheet music" in (sub.body_text or "").lower()
    assert "photograph was added to the sheet music" not in (sub.caption_text or "").lower()


def test_real_numbers_preserved_in_captions(blueprint):
    _, sections = blueprint
    captions = " ".join(
        s.caption_text for sec in sections for s in sec.subheaders
    )
    assert "1482" in captions  # medieval map caption year


def test_figure_caption_text_removed_from_body(blueprint):
    _, sections = blueprint
    for sec in sections:
        for sub in sec.subheaders:
            if not sub.caption_text:
                continue
            body_lines = {
                line.strip()
                for line in (sub.body_text or "").split("\n")
                if line.strip()
            }
            for line in body_lines:
                if line.startswith("FIGURE "):
                    pytest.fail(
                        f"FIGURE label still in body for {sub.title!r}: {line!r}"
                    )
            for caption in sub.caption_text.split("\n"):
                caption = caption.strip()
                if caption and caption in body_lines:
                    pytest.fail(
                        f"Caption line still in body for {sub.title!r}: {caption[:60]!r}"
                    )


def test_furniture_removed(blueprint):
    doc, _ = blueprint
    # The running header appears on nearly every page in the raw PDF; after
    # frequency-based furniture detection it must be gone from body lines.
    header_hits = sum(
        1
        for pg in doc.pages
        for ln in pg.lines
        if "Social Science Resource Guide" in ln.text
    )
    assert header_hits == 0


def test_collapse_duplicate_singletons(blueprint):
    """Sections with one same-titled subheader are hoisted (e.g. INTRODUCTION)."""
    _, sections = blueprint
    for stype in ("INTRODUCTION", "CONCLUSION", "GLOSSARY", "TIMELINE"):
        sec = next(s for s in sections if s.section_type == stype)
        assert len(sec.subheaders) == 0
        assert sec.body_text


def test_glossary_cards(blueprint):
    _, sections = blueprint
    from app.parsing.deterministic import glossary_cards

    glo = [s for s in sections if s.section_type == "GLOSSARY"][0]
    cards = glossary_cards(glo.body_text)
    assert len(cards) > 250
    fronts = [f for f, _ in cards]
    assert "Define: absolute distance" in fronts


def test_timeline_cards(blueprint):
    _, sections = blueprint
    from app.parsing.deterministic import timeline_cards

    tl = [s for s in sections if s.section_type == "TIMELINE"][0]
    cards = timeline_cards(tl.body_text)
    assert len(cards) > 30
    assert any("1492" in front for front, _ in cards)


def test_selected_works_subheader_uses_title_after_colon():
    from app.parsing.spans import Document, Line, Page
    from app.parsing.structure import resolve_subheader_title

    doc = Document(
        pages=[
            Page(
                index=0,
                width=600,
                height=800,
                lines=[
                    Line(
                        page=0,
                        index=0,
                        text="SELECTED WORKS: The Great Gatsby",
                        size=12,
                        bold=True,
                        is_caps=True,
                        y0=100,
                    ),
                    Line(
                        page=0,
                        index=1,
                        text="Some body text about the novel.",
                        size=10,
                        bold=False,
                        is_caps=False,
                        y0=120,
                    ),
                ],
            )
        ],
        body_size=10,
    )
    title = resolve_subheader_title(
        doc, (0, 0), "Selected Works: The Great Gatsby"
    )
    assert title == "The Great Gatsby"


def test_selected_works_fallback_splits_toc_title():
    from app.parsing.spans import Document, Page
    from app.parsing.structure import resolve_subheader_title

    doc = Document(pages=[Page(index=0, width=600, height=800, lines=[])], body_size=10)
    title = resolve_subheader_title(
        doc, (0, 0), "Selected Works: Pride and Prejudice"
    )
    assert title == "Pride and Prejudice"


def test_selected_work_singular_truncates_art_name_at_comma():
    from app.parsing.spans import Document, Line, Page
    from app.parsing.structure import extract_selected_work_label, resolve_subheader_title

    toc = (
        "SELECTED WORK: Example Artwork, Some Country, "
        "Some Region, Nineteenth Century (before 1892)"
    )
    assert extract_selected_work_label(toc) == "Example Artwork (before 1892)"

    doc = Document(
        pages=[
            Page(
                index=0,
                width=600,
                height=800,
                lines=[
                    Line(
                        page=0,
                        index=0,
                        text=toc,
                        size=12,
                        bold=True,
                        is_caps=True,
                        y0=100,
                    ),
                ],
            )
        ],
        body_size=10,
    )
    title = resolve_subheader_title(doc, (0, 0), toc)
    assert title == "Example Artwork (before 1892)"


def test_selected_work_tier4_toc_entry_becomes_subheader():
    from app.parsing.structure import TocEntry, _toc_entry_is_subheader

    assert _toc_entry_is_subheader(TocEntry(2, "Topic Overview", 47))
    assert _toc_entry_is_subheader(
        TocEntry(3, "SELECTED WORK: Example Piece, Some Place", 48)
    )
    assert not _toc_entry_is_subheader(TocEntry(3, "A Closer Look", 50))


def test_dedupe_selected_work_outline_level2_and_level3():
    from app.parsing.structure import _dedupe_selected_work_toc_entries

    sw = "SELECTED WORK: Example Piece, Some Place"
    subs = [
        ("Topic Overview", 47, 2),
        (sw, 48, 2),
        (sw, 48, 3),
    ]
    deduped = _dedupe_selected_work_toc_entries(subs)
    assert deduped == [("Topic Overview", 47, 2), (sw, 48, 3)]


def test_dedupe_keeps_flat_level2_selected_work_when_only_entry():
    from app.parsing.structure import _dedupe_selected_work_toc_entries

    subs = [
        ("Maps Overview", 10, 2),
        ("SELECTED WORK: Star Chart, Pacific Ocean", 11, 2),
    ]
    assert _dedupe_selected_work_toc_entries(subs) == subs


def test_prepare_subheader_units_merges_topic_with_first_selected_work():
    from app.parsing.structure import PIECE_SELECTED_WORK, _prepare_subheader_units

    sw = "SELECTED WORK: Example Piece, Some Place"
    other = "SELECTED WORK: Other Piece, Other Place"
    subs = [
        ("Topic Overview", 47, 2),
        (sw, 48, 3),
        ("Another Topic", 51, 2),
        (other, 53, 3),
        ("Standalone Topic", 57, 2),
    ]
    prepared = _prepare_subheader_units(subs)
    assert prepared == [
        (sw, "Topic Overview", 47, PIECE_SELECTED_WORK),
        (other, "Another Topic", 51, PIECE_SELECTED_WORK),
        ("Standalone Topic", "Standalone Topic", 57, ""),
    ]


def test_prepare_subheader_units_merges_topic_with_first_listening_companion():
    from app.parsing.structure import (
        PIECE_LISTENING_COMPANION,
        _prepare_subheader_units,
    )

    lc1 = "Listening Companion 1: Bohemian Rhapsody, Queen"
    lc2 = "Listening Companion 2: Stairway to Heaven, Led Zeppelin"
    subs = [
        ("Rock Overview", 10, 2),
        (lc1, 11, 3),
        (lc2, 14, 3),
    ]
    prepared = _prepare_subheader_units(subs)
    assert prepared == [
        (lc1, "Rock Overview", 10, PIECE_LISTENING_COMPANION),
        (lc2, lc2, 14, PIECE_LISTENING_COMPANION),
    ]


def test_listening_companion_label_extraction():
    from app.parsing.structure import extract_listening_companion_label

    assert (
        extract_listening_companion_label(
            "Listening Companion 2: Bohemian Rhapsody, Queen"
        )
        == "Bohemian Rhapsody"
    )
    assert (
        extract_listening_companion_label(
            'LISTENING COMPANION 1: “Daisy Bell (Bicycle Built for Two)” '
            "(1892) – Harry Dacre; Arranged by Hiroshi Tamawari"
        )
        == "Daisy Bell (Bicycle Built for Two) (1892)"
    )
    assert (
        extract_listening_companion_label(
            "Listening Companion 5: Long Song Title Here, Composer Name (1975)"
        )
        == "Long Song Title Here (1975)"
    )


def test_listening_companion_tier4_becomes_subheader():
    from app.parsing.structure import TocEntry, _toc_entry_is_subheader

    assert _toc_entry_is_subheader(
        TocEntry(3, "Listening Companion 1: Example Song, Artist", 48)
    )


def test_strip_listening_guide_removes_block_until_next_heading():
    from app.parsing.structure import strip_listening_guide

    body = "\n".join(
        [
            "SONG OVERVIEW",
            "Context about the song.",
            "LISTENING GUIDE",
            "0:00 Intro",
            "1:30 Verse",
            "NEXT TOPIC HEADING",
            "More content to keep.",
        ]
    )
    stripped = strip_listening_guide(body)
    assert "0:00 Intro" not in stripped
    assert "1:30 Verse" not in stripped
    assert "Context about the song." in stripped
    assert "NEXT TOPIC HEADING" in stripped
    assert "More content to keep." in stripped


def test_strip_listening_guide_removes_heading_with_suffix():
    from app.parsing.structure import strip_listening_guide

    body = "\n".join(
        [
            "SONG OVERVIEW",
            "Context about the song.",
            "LISTENING GUIDE FOR DAISY BELL",
            "0:00 Intro",
            "1:30 Verse",
        ]
    )
    stripped = strip_listening_guide(body)
    assert "0:00 Intro" not in stripped
    assert "Context about the song." in stripped


def test_strip_listening_guide_removes_trailing_timestamps_without_heading():
    from app.parsing.structure import strip_listening_guide

    body = "\n".join(
        [
            "SONG OVERVIEW",
            "Context about the song.",
            "0:00 Intro",
            "1:30 Verse",
        ]
    )
    stripped = strip_listening_guide(body)
    assert "0:00 Intro" not in stripped
    assert "Context about the song." in stripped


def test_strip_listening_guide_noop_for_selected_work_body():
    from app.parsing.structure import strip_listening_guide

    body = "SELECTED WORK: Art Piece\nDescription text."
    assert strip_listening_guide(body) == body


def test_parent_topic_not_renamed_by_child_selected_work():
    from app.parsing.spans import Document, Line, Page
    from app.parsing.structure import resolve_subheader_title

    doc = Document(
        pages=[
            Page(
                index=0,
                width=600,
                height=800,
                lines=[
                    Line(
                        page=0,
                        index=0,
                        text="TOPIC OVERVIEW",
                        size=12,
                        bold=True,
                        is_caps=True,
                        y0=100,
                    ),
                    Line(
                        page=0,
                        index=1,
                        text="Intro body text.",
                        size=10,
                        bold=False,
                        is_caps=False,
                        y0=120,
                    ),
                ],
            ),
            Page(
                index=1,
                width=600,
                height=800,
                lines=[
                    Line(
                        page=1,
                        index=0,
                        text="SELECTED WORK: Example Piece, Some Place",
                        size=12,
                        bold=True,
                        is_caps=True,
                        y0=100,
                    ),
                ],
            ),
        ],
        body_size=10,
    )
    title = resolve_subheader_title(doc, (0, 0), "Topic Overview")
    assert title == "Topic Overview"


def test_non_selected_works_subheader_keeps_toc_title():
    from app.parsing.spans import Document, Line, Page
    from app.parsing.structure import resolve_subheader_title

    doc = Document(
        pages=[
            Page(
                index=0,
                width=600,
                height=800,
                lines=[
                    Line(
                        page=0,
                        index=0,
                        text="RAILROADS",
                        size=12,
                        bold=True,
                        is_caps=True,
                        y0=100,
                    ),
                ],
            )
        ],
        body_size=10,
    )
    title = resolve_subheader_title(doc, (0, 0), "Railroads")
    assert title == "Railroads"


def test_art_guide_merges_intro_and_first_selected_work_per_topic():
    from pathlib import Path

    guide = Path(__file__).resolve().parent.parent.parent / "Guides" / "ArtRG_Transportation.pdf"
    if not guide.exists():
        import pytest

        pytest.skip(f"art guide not found at {guide}")

    from app.parsing.structure import build_blueprint, collapse_duplicate_singletons

    _, sections = build_blueprint(str(guide))
    collapse_duplicate_singletons(sections)
    sec2 = next(
        s for s in sections if s.title.startswith("SECTION II:") and s.section_type == "BODY"
    )
    assert len(sec2.subheaders) == 4
    rebbelib = next(
        s for s in sec2.subheaders if s.title == "Rebbelib Navigation Chart (before 1892)"
    )
    body = rebbelib.body_text
    words = body.replace("\n", " ").split()
    assert words[0].upper().startswith("WAYFINDING")
    assert words[-1].rstrip(".") == "years"
    assert "Marshallese sailors across thousands of years" in body
    assert "SELECTED WORK" in body.upper()
    assert "AFRICAN AMERICAN" not in body.upper()
    assert "Division" not in body.split()[-3:]


def test_art_guide_multi_work_topic_has_separate_sw_units():
    from pathlib import Path

    guide = Path(__file__).resolve().parent.parent.parent / "Guides" / "ArtRG_Transportation.pdf"
    if not guide.exists():
        import pytest

        pytest.skip(f"art guide not found at {guide}")

    from app.parsing.structure import build_blueprint, collapse_duplicate_singletons

    _, sections = build_blueprint(str(guide))
    collapse_duplicate_singletons(sections)
    sec3 = next(
        s for s in sections if s.title.startswith("SECTION III:") and s.section_type == "BODY"
    )
    assert len(sec3.subheaders) == 5
    millais = next(s for s in sec3.subheaders if "Millais" in s.title)
    reihana = next(s for s in sec3.subheaders if "Reihana" in s.title)

    assert "EXPLORATION" in millais.body_text.split("\n")[0].upper()
    assert "SELECTED WORK" in millais.body_text.upper()
    assert "SELECTED WORK" in reihana.body_text.split("\n")[0].upper()
    assert "ARTISTS IN TRANSIT" not in reihana.body_text.upper()


def test_collapse_only_when_single_matching_subheader():
    from app.parsing.structure import SectionBP, SubheaderBP, collapse_duplicate_singletons

    intro = SectionBP(
        "INTRODUCTION",
        "INTRODUCTION",
        0,
        subheaders=[
            SubheaderBP("Introduction", 1, 0, 2, 0, body_text="text", caption_text="fig")
        ],
    )
    body = SectionBP(
        "SECTION I",
        "BODY",
        1,
        subheaders=[
            SubheaderBP("A", 3, 0, 4, 0, body_text="a"),
            SubheaderBP("B", 5, 0, 6, 0, body_text="b"),
        ],
    )
    mismatch = SectionBP(
        "GLOSSARY",
        "GLOSSARY",
        2,
        subheaders=[SubheaderBP("Terms", 7, 0, 8, 0, body_text="terms")],
    )
    collapse_duplicate_singletons([intro, body, mismatch])

    assert intro.body_text == "text"
    assert intro.caption_text == "fig"
    assert intro.subheaders == []
    assert len(body.subheaders) == 2
    assert mismatch.subheaders[0].body_text == "terms"


def test_selected_work_label_appends_trailing_comma_year():
    from app.parsing.structure import extract_selected_work_label

    assert (
        extract_selected_work_label(
            "SELECTED WORK: Lisa Reihana, in Pursuit of Venus [infected], 2015"
        )
        == "Lisa Reihana (2015)"
    )


def test_enrich_piece_display_title_from_body_selected_work():
    from app.parsing.structure import PIECE_SELECTED_WORK, enrich_piece_display_title

    body = "\n".join(
        [
            "TOPIC INTRO",
            "More intro text.",
            "SELECTED WORK: Eero Saarinen, TWA Flight Center, John F. Kennedy",
            "International Airport, New York, New York, 1959–62",
            "Body about the terminal.",
        ]
    )
    title = enrich_piece_display_title(
        "Eero Saarinen",
        body,
        "SELECTED WORK: Eero Saarinen, TWA Flight Center",
        PIECE_SELECTED_WORK,
    )
    assert title == "Eero Saarinen (1959–62)"


def test_enrich_piece_display_title_joins_slash_year_fragment():
    from app.parsing.structure import PIECE_SELECTED_WORK, enrich_piece_display_title

    body = "\n".join(
        [
            "INTRO",
            "SELECTED WORK: Canaletto, The Square of Saint Mark's, Venice,",
            "1742/44",
            "Description.",
        ]
    )
    title = enrich_piece_display_title(
        "Canaletto",
        body,
        "SELECTED WORK: Canaletto, The Square of Saint Mark's, Venice",
        PIECE_SELECTED_WORK,
    )
    assert title == "Canaletto (1742/44)"


def test_selected_work_label_joins_wrapped_year_line():
    from app.parsing.spans import Document, Line, Page
    from app.parsing.structure import resolve_subheader_title

    toc = "SELECTED WORK: Frida Kahlo, Self-Portrait on the Borderline"
    doc = Document(
        pages=[
            Page(
                index=0,
                width=600,
                height=800,
                lines=[
                    Line(
                        page=0,
                        index=0,
                        text=toc,
                        size=12,
                        bold=True,
                        is_caps=True,
                        y0=100,
                    ),
                    Line(
                        page=0,
                        index=1,
                        text="between Mexico and the United States, 1932",
                        size=12,
                        bold=False,
                        is_caps=False,
                        y0=120,
                    ),
                ],
            )
        ],
        body_size=10,
    )
    title = resolve_subheader_title(doc, (0, 0), toc)
    assert title == "Frida Kahlo (1932)"


def test_extract_piece_year_from_title_and_body():
    from app.parsing.structure import (
        PIECE_LISTENING_COMPANION,
        PIECE_SELECTED_WORK,
        extract_piece_year,
        piece_year_from_subheader,
    )

    assert extract_piece_year("Daisy Bell (Bicycle Built for Two) (1892)") == "1892"
    assert (
        extract_piece_year(
            "Rebbelib Navigation Chart, Marshall Islands (before 1892)"
        )
        == "before 1892"
    )
    assert extract_piece_year("Symphony No. 5 (1959–62)") == "1959–62"
    assert extract_piece_year("Topic Without Year") is None

    body = (
        "SELECTED WORK: Rebbelib Navigation Chart, Marshall Islands, "
        "Micronesia, Nineteenth Century (before 1892)\nDescription."
    )
    assert (
        piece_year_from_subheader(
            "Rebbelib Navigation Chart, Marshall Islands",
            body,
            PIECE_SELECTED_WORK,
        )
        == "before 1892"
    )
    assert (
        piece_year_from_subheader(
            "Daisy Bell (Bicycle Built for Two) (1892)",
            "SONG OVERVIEW\nContext.",
            PIECE_LISTENING_COMPANION,
        )
        == "1892"
    )


def test_piece_year_cards():
    from app.parsing.deterministic import piece_year_cards

    assert piece_year_cards(
        "Daisy Bell (Bicycle Built for Two) (1892)",
        "1892",
        "listening_companion",
    ) == [
        ('What year is "Daisy Bell (Bicycle Built for Two)" from?', "1892")
    ]
    assert piece_year_cards(
        "Rebbelib Navigation Chart, Marshall Islands (before 1892)",
        "before 1892",
        "selected_work",
    ) == [
        ("When was Rebbelib Navigation Chart, Marshall Islands made?", "before 1892")
    ]
