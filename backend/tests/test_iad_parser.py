"""Tests for IAD guide parsing and two-column TOC recovery."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
ART_IAD = ROOT / "Guides" / "ART_IAD.pdf"
SS_IAD = ROOT / "guides" / "SocialScience_IAD.pdf"
if not SS_IAD.exists():
    SS_IAD = ROOT / "Guides" / "SocialScience_IAD.pdf"


@pytest.fixture(scope="module")
def iad_blueprint():
    if not ART_IAD.exists():
        pytest.skip(f"IAD art guide not found at {ART_IAD}")
    from app.parsing.captions import attach_captions
    from app.parsing.structure import ParseOptions, build_blueprint, collapse_duplicate_singletons

    doc, sections = build_blueprint(str(ART_IAD), ParseOptions(is_iad=True))
    attach_captions(doc, sections)
    collapse_duplicate_singletons(sections)
    return doc, sections


def test_iad_section_iv_includes_mark_dion(iad_blueprint):
    _, sections = iad_blueprint
    sec = next(
        s for s in sections if "ECOLOGICAL SYSTEMS OF KNOWLEDGE" in s.title.upper()
    )
    titles = [sub.title for sub in sec.subheaders]
    assert any("meter of jungle" in t.lower() for t in titles), titles
    assert any("sun tunnel" in t.lower() or "sun tunnels" in t.lower() for t in titles), titles


def test_iad_selected_work_uses_title_not_author():
    from app.parsing.structure import extract_selected_work_label

    toc = "SELECTED WORK: Mark Dion, A Meter of Jungle, 1992"
    assert extract_selected_work_label(toc, is_iad=True) == "A Meter of Jungle (1992)"
    assert extract_selected_work_label(toc, is_iad=False) == "Mark Dion (1992)"


def test_iad_selected_work_multi_part_title():
    from app.parsing.structure import extract_selected_work_label

    toc = (
        "SELECTED WORK: Helen and Newton Harrison, "
        "Shrimp Farm, Survival Piece #2, 1971"
    )
    assert (
        extract_selected_work_label(toc, is_iad=True)
        == "Shrimp Farm, Survival Piece #2 (1971)"
    )


def test_split_merged_selected_work_toc_titles():
    from app.parsing.structure import _split_merged_piece_toc_titles

    merged = (
        "SELECTED WORK: Nancy Holt, Sun Tunnels, 1973–76 . . . 78 "
        "SELECTED WORK: Mark Dion, A Meter of Jungle, 1992"
    )
    parts = _split_merged_piece_toc_titles(merged)
    assert len(parts) == 2
    assert "Nancy Holt" in parts[0]
    assert "Mark Dion" in parts[1]


def test_toc_line_allows_trailing_leader_garbage():
    from app.parsing.structure import TOC_LINE_RE

    line = (
        "Tunnels, 1973–76 . . . . . . . . . . . . . . . . . . 78 "
        ".............. ............."
    )
    m = TOC_LINE_RE.match(line)
    assert m is not None
    assert m.group(2) == "78"


def test_section_intro_not_top_level_section():
    from app.parsing.structure import _RawToc, _is_section

    intro = _RawToc("Section I Introduction", 5, 36.0, False, 1)
    summary = _RawToc("Section I Summary", 20, 36.0, False, 1)
    section = _RawToc("SECTION I: CONCEPTUALIZING CLIMATE", 5, 36.0, True, 1)

    assert not _is_section(intro)
    assert _is_section(summary)
    assert _is_section(section)


def test_section_trailing_page_regex_splits_title():
    from app.parsing.structure import _SECTION_TRAILING_PAGE_RE

    m = _SECTION_TRAILING_PAGE_RE.match("SECTION III: THE ANTHROPOCENE 37")
    assert m is not None
    assert m.group(1) == "SECTION III: THE ANTHROPOCENE"
    assert m.group(2) == "37"


@pytest.fixture(scope="module")
def ss_iad_blueprint():
    if not SS_IAD.exists():
        pytest.skip(f"Social Science IAD guide not found at {SS_IAD}")
    from app.parsing.captions import attach_captions
    from app.parsing.navigation import strip_guide_navigation
    from app.parsing.structure import build_blueprint, collapse_duplicate_singletons

    doc, sections = build_blueprint(str(SS_IAD))
    attach_captions(doc, sections)
    for sec in sections:
        if sec.body_text:
            sec.body_text = strip_guide_navigation(sec.body_text)
        for sub in sec.subheaders:
            if sub.body_text:
                sub.body_text = strip_guide_navigation(sub.body_text)
    collapse_duplicate_singletons(sections)
    return doc, sections


def test_ss_iad_section_intro_is_first_subheader(ss_iad_blueprint):
    _, sections = ss_iad_blueprint
    sec1 = next(
        s for s in sections
        if s.title.startswith("SECTION I:") and s.section_type == "BODY"
    )
    assert len(sec1.subheaders) >= 1
    assert sec1.subheaders[0].title == "Section I Introduction"
    assert sec1.subheaders[0].body_text
    assert "climate change" in sec1.subheaders[0].body_text.lower()


def test_ss_iad_no_standalone_section_introduction_section(ss_iad_blueprint):
    _, sections = ss_iad_blueprint
    standalone = [
        s for s in sections
        if s.section_type == "INTRODUCTION" and "section" in s.title.lower()
    ]
    assert standalone == []


def test_ss_iad_section_iii_title_not_merged_with_intro(ss_iad_blueprint):
    _, sections = ss_iad_blueprint
    sec3 = next(
        s for s in sections
        if s.title.startswith("SECTION III:") and s.section_type == "BODY"
    )
    assert "Section III Introduction" not in sec3.title
    assert sec3.subheaders[0].title == "Section III Introduction"


def test_ss_iad_section_summary_stays_top_level(ss_iad_blueprint):
    _, sections = ss_iad_blueprint
    summary = next(s for s in sections if s.title == "Section I Summary")
    assert summary.section_type == "SECTION_SUMMARY"
    assert summary.subheaders == []


def test_image_source_credit_detection():
    from app.parsing.captions import is_image_source_credit

    assert is_image_source_credit(
        "Source: California State University Northridge, Earth Systems Interactions"
    )
    assert is_image_source_credit("Source: WorldAtlas")
    assert not is_image_source_credit(
        "The source of this debate is scholarly disagreement."
    )
    assert not is_image_source_credit("")


def test_page_lines_reading_order_is_column_major():
    from app.parsing.spans import Line
    from app.parsing.structure import _page_lines_reading_order

    lines = [
        Line(0, 0, "right top", 10.0, False, False, 100.0, 320.0),
        Line(0, 1, "left top", 10.0, False, False, 100.0, 55.0),
        Line(0, 2, "left second", 10.0, False, False, 120.0, 55.0),
        Line(0, 3, "right second", 10.0, False, False, 120.0, 320.0),
    ]
    ordered = [ln.text for ln in _page_lines_reading_order(lines, 612.0)]
    assert ordered == ["left top", "left second", "right top", "right second"]


def test_ss_iad_section_ii_intro_two_column_reading_order(ss_iad_blueprint):
    """Body text must read left column fully before right column (not row-wise)."""
    _, sections = ss_iad_blueprint
    intro = next(
        s
        for sec in sections
        for s in sec.subheaders
        if s.title == "Section II Introduction"
    )
    body = intro.body_text or ""
    iugs = body.find("According to the International Union of Geological")
    homo = body.find("record of Homo sapiens around 300,000 years ago")
    assert iugs >= 0 and homo >= 0
    assert iugs < homo, (
        "IUGS/Holocene paragraph (left column) must precede the Homo sapiens "
        f"timeline (right column); got iugs@{iugs} homo@{homo}"
    )
    holocene_date = body.find("known as the Holocene began about 11,700 years ago")
    assert holocene_date >= 0 and holocene_date < homo


def test_ss_iad_ess_sources_boundary_no_bleed(ss_iad_blueprint):
    """ESS body must not include Sources prose from the right column on page 9."""
    _, sections = ss_iad_blueprint
    sec1 = next(
        s for s in sections
        if s.title.startswith("SECTION I:") and s.section_type == "BODY"
    )
    ess = next(s for s in sec1.subheaders if "Essential Concepts" in s.title)
    sources = next(
        s for s in sec1.subheaders if s.title.startswith("Sources for Reconstructing")
    )
    ess_body = (ess.body_text or "").lower()
    src_body = (sources.body_text or "").lower()
    assert "archives of nature" not in ess_body
    assert "called a proxy" not in ess_body and " is called a proxy" not in ess_body
    assert "archives of nature" in src_body
    assert "ice core" in src_body


def test_ss_iad_intro_strips_guide_roadmap(ss_iad_blueprint):
    _, sections = ss_iad_blueprint
    intro = next(
        s
        for sec in sections
        for s in sec.subheaders
        if s.title == "Section I Introduction"
    )
    body = intro.body_text or ""
    assert "In Section I of this resource guide, we will establish" not in body
    assert "Sections II and III of this guide will cover" not in body
    assert "climate change" in body.lower()


def test_ss_iad_source_lines_move_to_master_source(ss_iad_blueprint):
    _, sections = ss_iad_blueprint
    intro = next(
        s
        for sec in sections
        for s in sec.subheaders
        if s.title == "Section I Introduction"
    )
    assert "Source: California State University Northridge" not in (
        intro.body_text or ""
    )
    assert "California State University Northridge" in (intro.caption_text or "")
    assert "csun.edu" not in (intro.body_text or "").lower()
    assert "csun.edu" in (intro.caption_text or "").lower()

    body_sources = [
        line.strip()
        for sec in sections
        for sub in sec.subheaders
        for line in (sub.body_text or "").split("\n")
        if line.strip().startswith("Source:")
    ]
    assert body_sources == []

    caption_sources = [
        line.strip()
        for sec in sections
        for sub in sec.subheaders
        for line in (sub.caption_text or "").split("\n")
        if line.strip().startswith("Source:")
    ]
    assert len(caption_sources) >= 50


def test_ss_iad_figure_labels_not_in_body_text(ss_iad_blueprint):
    """Chart labels and image descriptions must not feed Text-Only generation."""
    _, sections = ss_iad_blueprint
    earth = next(
        s
        for sec in sections
        for s in sec.subheaders
        if s.title.startswith("Essential Concepts from Earth")
    )
    body = earth.body_text or ""
    assert "Earth's atmospheric layers." not in body
    assert "Earth\u2019s atmospheric layers." not in body
    assert "The greenhouse effect." not in body
    assert "Lake-effect snow over the Great Lakes." not in body
    cap = earth.caption_text or ""
    assert "greenhouse effect" in cap.lower() or "atmospheric layers" in cap.lower()


def test_caption_line_classifiers():
    from app.parsing.captions import (
        is_caption_line,
        is_figure_label_line,
        is_source_continuation_line,
        is_standalone_image_credit,
    )

    assert is_source_continuation_line("(csun.edu).")
    assert is_source_continuation_line("| GLISA (umich.edu)")
    assert is_standalone_image_credit(
        "European Geosciences Union. Cryospheric Sciences | Image of the Week — "
        "Last Glacial Maximum in Europe (egu.eu)"
    )
    assert is_figure_label_line("Lake-effect snow over the Great Lakes.")
    assert is_figure_label_line("Ice core sample.")
    assert not is_caption_line(
        "Christian Pfister led the creation of the field of climate history."
    )
    assert not is_caption_line("System Science.")
