"""TOC-driven structure parsing + section-type classification.

Sections come from the table of contents, not the body: section divider
blocks float mid-page as decorative sidebars and appear after content starts,
so body scanning alone is unreliable. We use the embedded outline
(``doc.get_toc()``) when present, fall back to parsing the printed TOC text,
and finally to a font/caps body scan.

Subheaders are inline (they share and split pages), so each carries
offset boundaries ``(page, line)`` used to slice its body text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import fitz

from .spans import Document, Line, _is_caps, load_document

# Tier-3 (subheaders) are CAPS, tier-4 are Title Case -> flatten tier-4 into tier-3.
SECTION_RE = re.compile(r"^\s*SECTION\s+[IVXLC0-9]+\b", re.IGNORECASE)
# Per-section intro subheaders: "Section I Introduction" — not a top-level section.
_SECTION_INTRO_RE = re.compile(
    r"^\s*Section\s+[IVXLC0-9]+\s+Introduction\b",
    re.IGNORECASE,
)
# Section title with inline printed page (no dot leaders): "SECTION III: TITLE 37".
_SECTION_TRAILING_PAGE_RE = re.compile(
    r"^(SECTION\s+[IVXLC0-9]+\s*:\s*.+?)\s+(\d{1,3})\s*$",
    re.IGNORECASE,
)
# TOC line: "Title .... 12" or "Title<TAB>12" (page may be followed by stray leaders)
TOC_LINE_RE = re.compile(
    r"^(.*?)[\.\s\u2026\t]{2,}(\d{1,3})(?:\s*[\.\s\u2026\t].*)?$",
    re.DOTALL,
)
_TOC_COLUMN_GAP = 80.0
# Art/lit guides: "SELECTED WORK(S): <piece>, <location/date…>" names the subsection.
_SELECTED_WORK_LINE_RE = re.compile(
    r"^\s*selected\s+works?\s*:\s*(.+)$",
    re.IGNORECASE,
)
_SELECTED_WORK_TOC_RE = re.compile(r"^\s*selected\s+works?\s*:", re.IGNORECASE)
# Music guides: "Listening Companion 1: <song title>, …"
_LISTENING_COMPANION_LINE_RE = re.compile(
    r"^\s*listening\s+companion\s+(\d+)\s*:\s*(.+)$",
    re.IGNORECASE,
)
_LISTENING_COMPANION_TOC_RE = re.compile(
    r"^\s*listening\s+companion\s+\d+\s*:", re.IGNORECASE
)
_LISTENING_GUIDE_HEADING_RE = re.compile(
    r"^\s*listening\s+guide\b", re.IGNORECASE
)
_LISTENING_TIMESTAMP_RE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?\b")
# Composer / arranger attribution after song title (en dash, em dash, or hyphen).
_LC_ATTRIBUTION_DASH_RE = re.compile(r"\s+[–—-]\s+")
_LC_QUOTED_TITLE_RE = re.compile(
    r'^["\u201c](.+?)["\u201d]\s*(\(\d{4}\))?',
    re.DOTALL,
)

PIECE_SELECTED_WORK = "selected_work"
PIECE_LISTENING_COMPANION = "listening_companion"


@dataclass
class SubheaderBP:
    title: str
    start_page: int
    start_line: int
    end_page: int
    end_line: int
    body_text: str = ""
    caption_text: str = ""
    # Internal: ``selected_work`` | ``listening_companion``; not shown in UI.
    piece_type: str = ""


@dataclass
class ParseOptions:
    """Guide-specific parsing flags set at upload time."""

    is_iad: bool = False


@dataclass
class SectionBP:
    title: str
    section_type: str
    order: int
    subheaders: list[SubheaderBP] = field(default_factory=list)
    # Hoisted from a lone duplicate-titled subheader (e.g. INTRODUCTION / Introduction).
    body_text: str = ""
    caption_text: str = ""
    start_page: Optional[int] = None
    start_line: Optional[int] = None
    end_page: Optional[int] = None
    end_line: Optional[int] = None


def classify_section(title: str) -> str:
    t = title.strip().lower()
    if "glossary" in t:
        return "GLOSSARY"
    if "timeline" in t:
        return "TIMELINE"
    if "bibliograph" in t or "works cited" in t or t in {"references", "sources"}:
        return "BIBLIOGRAPHY"
    if t in {"notes", "endnotes", "footnotes"}:
        return "NOTES"
    if "summary" in t:
        return "SECTION_SUMMARY"
    if "introduction" in t:
        return "INTRODUCTION"
    if "conclusion" in t:
        return "CONCLUSION"
    return "BODY"


def _norm_title(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower().rstrip(":")


# ---------------------------------------------------------------------------
# TOC acquisition
# ---------------------------------------------------------------------------

@dataclass
class TocEntry:
    level: int
    title: str
    page_index: int  # resolved PDF page index (0-based)


def _toc_from_outline(fdoc: fitz.Document) -> list[TocEntry]:
    out: list[TocEntry] = []
    for level, title, page in fdoc.get_toc(simple=True):
        if title.strip():
            out.append(TocEntry(level=level, title=title.strip(), page_index=max(0, page - 1)))
    return out


@dataclass
class _RawToc:
    title: str
    printed: int
    x0: float
    is_caps: bool
    toc_page: int


def _looks_like_new_toc_entry(text: str) -> bool:
    stripped = text.strip()
    if SECTION_RE.match(stripped):
        return True
    if is_piece_toc_entry(stripped):
        return True
    if _norm_title(stripped).startswith("section "):
        return True
    return bool(TOC_LINE_RE.match(stripped))


def _clean_toc_piece_title(title: str) -> str:
    """Drop dot leaders and printed page numbers from a TOC title fragment."""
    title = re.sub(r"\s+", " ", title).strip()
    m = TOC_LINE_RE.match(title)
    if m:
        return m.group(1).strip()
    cleaned = re.sub(
        r"[\.\s\u2026\t]{2,}\d{1,3}(?:\s*[\.\s\u2026\t].*)?$",
        "",
        title,
    ).strip()
    return cleaned or title


def _printed_page_in_toc_title(title: str) -> Optional[int]:
    matches = list(
        re.finditer(r"[\.\s\u2026\t]{2,}(\d{1,3})\b", title)
    )
    if not matches:
        return None
    return int(matches[-1].group(1))


def _split_merged_piece_toc_titles(title: str) -> list[str]:
    """Split a stitched TOC line that contains multiple ``SELECTED WORK`` entries."""
    title = title.strip()
    if not title:
        return []
    starts = [
        m.start()
        for m in re.finditer(r"\bselected\s+works?\s*:", title, re.IGNORECASE)
    ]
    if len(starts) <= 1:
        return [title]
    parts: list[str] = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(title)
        part = title[start:end].strip()
        if part:
            parts.append(part)
    return parts or [title]


def _expand_piece_toc_entry(entry: TocEntry, doc: Document) -> list[TocEntry]:
    parts = _split_merged_piece_toc_titles(entry.title)
    if len(parts) == 1:
        return [entry]
    out: list[TocEntry] = []
    for part in parts:
        printed = _printed_page_in_toc_title(part)
        page_index = (
            _resolve_printed(doc, printed) if printed is not None else entry.page_index
        )
        out.append(
            TocEntry(
                level=entry.level,
                title=_clean_toc_piece_title(part),
                page_index=page_index,
            )
        )
    return out


def _flatten_toc(entries: list[TocEntry], doc: Document) -> list[TocEntry]:
    out: list[TocEntry] = []
    for entry in entries:
        out.extend(_expand_piece_toc_entry(entry, doc))
    return out


def _normalize_toc_line(text: str) -> str:
    """Collapse layout newlines inside a TOC leader line."""
    return re.sub(r"\s+", " ", text.strip())


def _try_flush_section_trailing_page(
    raws: list[_RawToc],
    text: str,
    x0: float,
    toc_page: int,
    min_printed: int | None,
) -> tuple[bool, int | None]:
    """Flush a section title that carries its printed page inline (no leaders)."""
    m = _SECTION_TRAILING_PAGE_RE.match(_normalize_toc_line(text))
    if not m:
        return False, min_printed
    printed = int(m.group(2))
    raws.append(
        _RawToc(
            title=m.group(1).strip(),
            printed=printed,
            x0=x0,
            is_caps=_is_caps(m.group(1)),
            toc_page=toc_page,
        )
    )
    new_min = printed if min_printed is None else min(min_printed, printed)
    return True, new_min


def _flush_pending_toc_line(
    raws: list[_RawToc],
    pending: str,
    pending_x0: float,
    toc_page: int,
    min_printed: int | None,
) -> int | None:
    """Commit a wrapped TOC fragment when it carries a printed page number."""
    if not pending:
        return min_printed
    m = TOC_LINE_RE.match(_normalize_toc_line(pending))
    if not m:
        return min_printed
    printed = int(m.group(2))
    raws.append(
        _RawToc(
            title=m.group(1).strip(),
            printed=printed,
            x0=pending_x0,
            is_caps=_is_caps(m.group(1)),
            toc_page=toc_page,
        )
    )
    return printed if min_printed is None else min(min_printed, printed)


def _toc_from_text(doc: Document) -> list[TocEntry]:
    """Parse the printed TOC by scanning early pages for leader lines.

    Handles wrapped multi-line entries (stitched within a page), both dot-leader
    and tab leaders, and uses left-indent (x0) to separate tier-3 subheaders
    from tier-4 entries (which are folded into their parent). Printed page
    numbers are mapped to PDF indices. Parsing is gated to the TOC region so
    title-page text doesn't bleed in.
    """
    raws: list[_RawToc] = []
    started = False
    min_printed: int | None = None

    for pg in doc.pages[:8]:
        pending = ""
        pending_x0 = 0.0
        for ln in pg.lines:
            text = _normalize_toc_line(ln.text)
            if not text:
                continue
            if not started:
                if _norm_title(text) == "table of contents":
                    started = True
                continue
            # Stop once the body has begun (printed page >= first TOC target).
            if min_printed is not None and pg.printed_number and pg.printed_number >= min_printed:
                return _level_raws(raws, doc)
            m = TOC_LINE_RE.match(text)
            if m:
                if pending:
                    flushed, min_printed = _try_flush_section_trailing_page(
                        raws, pending, pending_x0, pg.index, min_printed
                    )
                    if flushed:
                        pending = ""
                frag = m.group(1).strip()
                title = (pending + " " + frag).strip() if pending else frag
                x0 = pending_x0 if pending else ln.x0
                pending = ""
                printed = int(m.group(2))
                min_printed = printed if min_printed is None else min(min_printed, printed)
                raws.append(
                    _RawToc(
                        title=title, printed=printed, x0=x0,
                        is_caps=_is_caps(title), toc_page=pg.index,
                    )
                )
            else:
                # Wrapped fragment: remember it (including caps fragments).
                if pending and abs(ln.x0 - pending_x0) >= _TOC_COLUMN_GAP:
                    if _looks_like_new_toc_entry(text):
                        flushed, min_printed = _try_flush_section_trailing_page(
                            raws, pending, pending_x0, pg.index, min_printed
                        )
                        if not flushed:
                            min_printed = _flush_pending_toc_line(
                                raws, pending, pending_x0, pg.index, min_printed
                            )
                        pending = text.strip()
                        pending_x0 = ln.x0
                        continue
                flushed, min_printed = _try_flush_section_trailing_page(
                    raws, text, ln.x0, pg.index, min_printed
                )
                if flushed:
                    pending = ""
                    continue
                if not pending:
                    pending_x0 = ln.x0
                pending = (pending + " " + text).strip()
    if pending:
        _flush_pending_toc_line(raws, pending, pending_x0, pg.index, min_printed)
    return _level_raws(raws, doc)


def _is_section(r: _RawToc) -> bool:
    if _SECTION_INTRO_RE.match(r.title):
        return False
    return r.is_caps or bool(SECTION_RE.match(r.title))


def _cluster_columns(sorted_x: list[float], gap: float = 100.0) -> list[list[float]]:
    """Group x0 values into columns separated by a large horizontal gap."""
    cols: list[list[float]] = []
    for x in sorted_x:
        if cols and x - cols[-1][-1] <= gap:
            cols[-1].append(x)
        else:
            cols.append([x])
    return cols


def _column_min(columns: list[list[float]], x: float) -> float:
    for col in columns:
        if col[0] <= x <= col[-1]:
            return col[0]
    return min((c[0] for c in columns), default=x)


def _column_index(columns: list[list[float]], x: float) -> int:
    """Map a line's ``x0`` to a column cluster (0 = leftmost)."""
    for i, col in enumerate(columns):
        if col[0] - 8.0 <= x <= col[-1] + 8.0:
            return i
    return min(range(len(columns)), key=lambda i: abs(x - columns[i][0]))


def _split_two_columns_by_midline(
    lines: list[Line], page_width: float
) -> Optional[tuple[list[Line], list[Line]]]:
    """Split a two-column page at the page midline (robust to gutter-spanning lines).

    Gap clustering on ``x0`` collapses when a single full-width banner, figure,
    or staggered indent bridges the gutter; a midline split does not. Returns
    ``(left, right)`` covering every line, or ``None`` when the page is not a
    genuine two-column spread (so the caller can fall back to top-to-bottom).
    """
    if page_width <= 0:
        return None
    mid = page_width / 2.0
    margin = max(20.0, page_width * 0.04)
    left = [ln for ln in lines if ln.x0 <= mid - margin]
    right = [ln for ln in lines if ln.x0 >= mid + margin]
    # Both columns must be substantially populated for this to be a real spread.
    if len(left) < 3 or len(right) < 3:
        return None
    # The columns must overlap vertically; otherwise this is a single column
    # with a corner title or a few right-aligned captions, not two columns.
    left_lo, left_hi = min(l.y0 for l in left), max(l.y0 for l in left)
    right_lo, right_hi = min(l.y0 for l in right), max(l.y0 for l in right)
    if min(left_hi, right_hi) - max(left_lo, right_lo) <= 0:
        return None
    # Lines starting inside the gutter band are ambiguous; assign by nearest side
    # so no line is dropped from the slice.
    for ln in lines:
        if mid - margin < ln.x0 < mid + margin:
            (left if ln.x0 < mid else right).append(ln)
    return left, right


def _page_lines_reading_order(lines: list[Line], page_width: float) -> list[Line]:
    """Return page lines in human reading order (column-major on two-column spreads).

    Single-column pages sort top-to-bottom. Multi-column pages read each column
    fully (top-to-bottom, left-to-right) instead of row-wise ``(y0, x0)`` bands,
    so the right column is never pulled in front of lower-but-later left content.
    """
    if not lines:
        return []
    xs = sorted({ln.x0 for ln in lines})
    columns = _cluster_columns(xs, gap=_TOC_COLUMN_GAP)
    if len(columns) >= 2:
        buckets: list[list[Line]] = [[] for _ in columns]
        for ln in lines:
            buckets[_column_index(columns, ln.x0)].append(ln)
        out: list[Line] = []
        for bucket in buckets:
            out.extend(sorted(bucket, key=lambda l: (l.y0, l.x0)))
        return out

    # Gap clustering can collapse to one column when a line bridges the gutter.
    # Recover the two-column layout via the page midline before giving up.
    grouped = _split_two_columns_by_midline(lines, page_width)
    if grouped is not None:
        left, right = grouped
        return sorted(left, key=lambda l: (l.y0, l.x0)) + sorted(
            right, key=lambda l: (l.y0, l.x0)
        )
    return sorted(lines, key=lambda l: (l.y0, l.x0))


def _level_raws(raws: list[_RawToc], doc: Document) -> list[TocEntry]:
    if len(raws) < 5:
        return []
    # The TOC is multi-column and margins drift between pages, so indent is
    # only meaningful within one column of one physical page. For each page we
    # split entries into columns by a large x-gap, then within each column the
    # least-indented entries are tier-3 (level 2) and deeper ones are tier-4
    # (level 3), which fold into their parent tier-3.
    by_page: dict[int, list[int]] = {}
    for i, r in enumerate(raws):
        by_page.setdefault(r.toc_page, []).append(i)

    levels = [1] * len(raws)
    for idxs in by_page.values():
        sub_idxs = [i for i in idxs if not _is_section(raws[i])]
        if not sub_idxs:
            continue
        columns = _cluster_columns(sorted({raws[i].x0 for i in sub_idxs}))
        for i in sub_idxs:
            col_min = _column_min(columns, raws[i].x0)
            levels[i] = 2 if raws[i].x0 <= col_min + 12.0 else 3

    out: list[TocEntry] = []
    for i, r in enumerate(raws):
        level = 1 if _is_section(r) else levels[i]
        out.append(TocEntry(level=level, title=r.title, page_index=_resolve_printed(doc, r.printed)))
    return out


def _resolve_printed(doc: Document, printed: int) -> int:
    if printed in doc.printed_to_index:
        return doc.printed_to_index[printed]
    # nearest known printed number
    best_idx = 0
    best_diff = 10**9
    for num, idx in doc.printed_to_index.items():
        diff = abs(num - printed)
        if diff < best_diff:
            best_diff, best_idx = diff, idx
    if doc.printed_to_index:
        # adjust by offset between nearest known and target
        near_num = min(doc.printed_to_index, key=lambda n: abs(n - printed))
        return max(0, doc.printed_to_index[near_num] + (printed - near_num))
    return min(printed, doc.page_count - 1)


def _toc_from_body(doc: Document) -> list[TocEntry]:
    """Last-resort heuristic: SECTION lines + bold/caps headings in the body."""
    entries: list[TocEntry] = []
    for pg in doc.pages:
        for ln in pg.lines:
            if SECTION_RE.match(ln.text):
                entries.append(TocEntry(1, ln.text.strip(), pg.index))
            elif ln.is_caps and ln.bold and 3 <= len(ln.text) <= 60:
                entries.append(TocEntry(2, ln.text.strip(), pg.index))
    return entries


def get_toc(doc: Document, pdf_path: str) -> list[TocEntry]:
    fdoc = fitz.open(pdf_path)
    try:
        entries = _toc_from_outline(fdoc)
    finally:
        fdoc.close()
    if len(entries) >= 5:
        return entries
    entries = _toc_from_text(doc)
    if len(entries) >= 5:
        return entries
    return _toc_from_body(doc)


# ---------------------------------------------------------------------------
# Building the 3-tier blueprint
# ---------------------------------------------------------------------------

def is_selected_work_toc_entry(title: str) -> bool:
    return bool(_SELECTED_WORK_TOC_RE.match(title.strip()))


def is_listening_companion_toc_entry(title: str) -> bool:
    return bool(_LISTENING_COMPANION_TOC_RE.match(title.strip()))


def is_piece_toc_entry(title: str) -> bool:
    return is_selected_work_toc_entry(title) or is_listening_companion_toc_entry(title)


def piece_toc_type(title: str) -> str:
    if is_selected_work_toc_entry(title):
        return PIECE_SELECTED_WORK
    if is_listening_companion_toc_entry(title):
        return PIECE_LISTENING_COMPANION
    return ""


def _truncate_piece_label(rest: str) -> str:
    if not rest:
        return ""
    if "," in rest:
        rest = rest.split(",", 1)[0].strip()
    return rest


def extract_selected_work_label(text: str, *, is_iad: bool = False) -> Optional[str]:
    """Art/lit piece name from ``SELECTED WORK(S): …`` (before location comma)."""
    stripped = text.strip()
    m = _SELECTED_WORK_LINE_RE.match(stripped)
    if m:
        rest = m.group(1).strip()
    elif is_selected_work_toc_entry(stripped) and ":" in stripped:
        rest = stripped.split(":", 1)[1].strip()
    else:
        return None
    if is_iad:
        label = _append_piece_year_to_label(_iad_piece_title(rest), rest)
    else:
        label = _append_piece_year_to_label(_truncate_piece_label(rest), rest)
    return label or None


def _normalize_listening_companion_label(rest: str) -> str:
    """Song title only — drop composer, arranger, and surrounding quote marks."""
    source = rest.strip()
    if not source:
        return ""
    rest = source
    if ";" in rest:
        rest = rest.split(";", 1)[0].strip()
    dash = _LC_ATTRIBUTION_DASH_RE.search(rest)
    if dash:
        rest = rest[: dash.start()].strip()
    qm = _LC_QUOTED_TITLE_RE.match(rest)
    if qm:
        title = qm.group(1).strip()
        year = (qm.group(2) or "").strip()
        label = f"{title} {year}".strip() if year else title
        return _append_piece_year_to_label(label, source)
    if "," in rest:
        label = rest.split(",", 1)[0].strip()
        return _append_piece_year_to_label(label, source)
    label = rest.strip("\"'“”‘’")
    return _append_piece_year_to_label(label, source)


def extract_listening_companion_label(text: str) -> Optional[str]:
    """Song title from ``Listening Companion N: …`` (before composer/arranger)."""
    stripped = text.strip()
    m = _LISTENING_COMPANION_LINE_RE.match(stripped)
    if m:
        rest = m.group(2).strip()
    elif is_listening_companion_toc_entry(stripped) and ":" in stripped:
        rest = stripped.split(":", 1)[1].strip()
    else:
        return None
    label = _normalize_listening_companion_label(rest)
    return label or None


def extract_piece_label(text: str, *, is_iad: bool = False) -> Optional[str]:
    return extract_selected_work_label(text, is_iad=is_iad) or extract_listening_companion_label(text)


_PIECE_YEAR_BEFORE_RE = re.compile(r"\(\s*before\s+(\d{4})\s*\)", re.IGNORECASE)
_PIECE_YEAR_RANGE_RE = re.compile(
    r"\(\s*(\d{4})\s*([–—-])\s*(\d{2,4})\s*\)"
)
_PIECE_YEAR_PAREN_RE = re.compile(r"\(\s*(\d{4})\s*\)")
_PIECE_YEAR_TRAILING_RANGE_RE = re.compile(
    r",\s*(\d{4})\s*([–—-])\s*(\d{2,4})\s*\.?\s*$"
)
_PIECE_YEAR_TRAILING_SLASH_RE = re.compile(r",\s*(\d{4}/\d{2,4})\s*\.?\s*$")
_PIECE_YEAR_TRAILING_RE = re.compile(r",\s*(\d{4})\s*\.?\s*$")
_YEAR_FRAGMENT_RE = re.compile(
    r"^(\d{4}(?:/\d{2,4}|[–—-]\d{2,4})?)\s*\.?\s*$"
)


def extract_piece_year(text: str) -> Optional[str]:
    """Year or date range from a piece-entry line or display title, when present."""
    if not text or not text.strip():
        return None
    before = _PIECE_YEAR_BEFORE_RE.search(text)
    if before:
        return f"before {before.group(1)}"
    range_m = _PIECE_YEAR_RANGE_RE.search(text)
    if range_m:
        return f"{range_m.group(1)}{range_m.group(2)}{range_m.group(3)}"
    years = _PIECE_YEAR_PAREN_RE.findall(text)
    if years:
        return years[-1]
    stripped = text.strip()
    trailing_range = _PIECE_YEAR_TRAILING_RANGE_RE.search(stripped)
    if trailing_range:
        return (
            f"{trailing_range.group(1)}{trailing_range.group(2)}"
            f"{trailing_range.group(3)}"
        )
    trailing_slash = _PIECE_YEAR_TRAILING_SLASH_RE.search(stripped)
    if trailing_slash:
        return trailing_slash.group(1)
    trailing = _PIECE_YEAR_TRAILING_RE.search(stripped)
    if trailing:
        return trailing.group(1)
    return None


def _strip_trailing_piece_date(text: str) -> str:
    """Remove trailing year/date from a piece title segment."""
    if not text:
        return text
    stripped = text.strip()
    for pat in (
        _PIECE_YEAR_TRAILING_RANGE_RE,
        _PIECE_YEAR_TRAILING_SLASH_RE,
        _PIECE_YEAR_TRAILING_RE,
    ):
        m = pat.search(stripped)
        if m:
            return stripped[: m.start()].strip().rstrip(",")
    return stripped


def _iad_piece_title(rest: str) -> str:
    """IAD guides list ``author, title[, location…], year`` — use the title portion."""
    if "," not in rest:
        return rest.strip()
    title_part = rest.split(",", 1)[1].strip()
    if not title_part:
        return rest.split(",", 1)[0].strip()
    stripped = _strip_trailing_piece_date(title_part)
    return stripped or title_part


def _append_piece_year_to_label(label: str, source: str) -> str:
    """Keep short piece/song name but add trailing year from the full entry line."""
    if not label:
        return label
    if extract_piece_year(label):
        return label
    year = extract_piece_year(source)
    if year:
        return f"{label} ({year})"
    return label


def piece_year_from_subheader(
    title: str, body_text: str, piece_type: str
) -> Optional[str]:
    """Resolve year from display title, else the piece-entry line in body."""
    if piece_type not in (PIECE_SELECTED_WORK, PIECE_LISTENING_COMPANION):
        return None
    year = extract_piece_year(title)
    if year:
        return year
    label = piece_label_from_body(body_text, piece_type)
    if label:
        return extract_piece_year(label)
    return None


def _join_selected_work_rest(
    lines: list[str], start_idx: int, max_continuation: int = 3
) -> Optional[str]:
    """Join a wrapped ``SELECTED WORK:`` entry through the line that carries the year."""
    if start_idx >= len(lines):
        return None
    m = _SELECTED_WORK_LINE_RE.match(lines[start_idx].strip())
    if not m:
        return None
    rest = m.group(1).strip()
    if extract_piece_year(rest) or "," not in rest:
        return rest
    for j in range(start_idx + 1, min(start_idx + 1 + max_continuation, len(lines))):
        chunk = lines[j].strip()
        if not chunk:
            break
        if _SELECTED_WORK_LINE_RE.match(chunk) or _LISTENING_COMPANION_LINE_RE.match(
            chunk
        ):
            break
        if _YEAR_FRAGMENT_RE.match(chunk):
            rest = f"{rest} {chunk}"
            break
        if _is_major_heading_line(chunk) and chunk[0].isupper():
            break
        rest = f"{rest} {chunk}"
        if extract_piece_year(rest):
            break
    return rest


def piece_label_from_body(body_text: str, piece_type: str, *, is_iad: bool = False) -> Optional[str]:
    """First piece/song label (with year when present) from subsection body text."""
    lines = (body_text or "").split("\n")
    for i, line in enumerate(lines):
        if piece_type == PIECE_SELECTED_WORK:
            rest = _join_selected_work_rest(lines, i)
            if rest:
                if is_iad:
                    label = _append_piece_year_to_label(_iad_piece_title(rest), rest)
                else:
                    label = _append_piece_year_to_label(_truncate_piece_label(rest), rest)
                return label
        elif piece_type == PIECE_LISTENING_COMPANION:
            m = _LISTENING_COMPANION_LINE_RE.match(line.strip())
            if m:
                label = _normalize_listening_companion_label(m.group(2))
                if label:
                    return label
    return None


def enrich_piece_display_title(
    title: str,
    body_text: str,
    toc_title: str,
    piece_type: str,
    *,
    is_iad: bool = False,
) -> str:
    """Add year to piece titles using the full entry line when the short label omits it."""
    if not piece_type or extract_piece_year(title):
        return title
    from_body = piece_label_from_body(body_text, piece_type, is_iad=is_iad)
    if from_body:
        return from_body
    from_toc = extract_piece_label(toc_title, is_iad=is_iad)
    if from_toc and extract_piece_year(from_toc):
        return from_toc
    year = piece_year_from_subheader(title, body_text, piece_type)
    if year:
        base = _truncate_piece_label(title) if "," in title else title.split("(")[0].strip()
        return _append_piece_year_to_label(base, f"({year})")
    return title


def _selected_work_rest_multiline(
    doc: Document, page_idx: int, start_line: int, max_continuation: int = 3
) -> Optional[str]:
    """Join a wrapped ``SELECTED WORK:`` entry through the line that carries the year."""
    if page_idx >= doc.page_count:
        return None
    line_texts = [ln.text for ln in doc.pages[page_idx].lines]
    line_indices = [ln.index for ln in doc.pages[page_idx].lines]
    try:
        start_idx = line_indices.index(start_line)
    except ValueError:
        return None
    return _join_selected_work_rest(line_texts, start_idx, max_continuation)


def _piece_label_near(
    doc: Document, pos: tuple[int, int], max_lines: int = 4, *, is_iad: bool = False
) -> Optional[str]:
    """Return piece/song name from a piece-entry line at anchor."""
    pidx, lidx = pos
    if pidx >= doc.page_count:
        return None
    for ln in doc.pages[pidx].lines:
        if ln.index < lidx:
            continue
        if ln.index > lidx + max_lines:
            break
        if _SELECTED_WORK_LINE_RE.match(ln.text.strip()):
            rest = _selected_work_rest_multiline(doc, pidx, ln.index)
            if rest:
                if is_iad:
                    label = _append_piece_year_to_label(_iad_piece_title(rest), rest)
                else:
                    label = _append_piece_year_to_label(_truncate_piece_label(rest), rest)
                if label:
                    return label
        label = extract_piece_label(ln.text, is_iad=is_iad)
        if label:
            return label
    return None


def resolve_subheader_title(
    doc: Document, pos: tuple[int, int], toc_title: str, *, is_iad: bool = False
) -> str:
    """Use piece/song name for ``SELECTED WORK`` / ``Listening Companion`` entries."""
    if not is_piece_toc_entry(toc_title):
        return toc_title
    from_body = _piece_label_near(doc, pos, is_iad=is_iad)
    if from_body:
        return from_body
    from_toc = extract_piece_label(toc_title, is_iad=is_iad)
    if from_toc:
        return from_toc
    return toc_title


def _toc_entry_is_subheader(entry: TocEntry) -> bool:
    """Tier-3 subheaders; tier-4 piece entries get their own node."""
    if entry.level == 2:
        return True
    return entry.level == 3 and is_piece_toc_entry(entry.title)


def _piece_dedupe_key(title: str) -> str:
    label = extract_piece_label(title)
    return _norm_title(label) if label else _norm_title(title)


def _prepare_subheader_units(
    subs: list[tuple[str, int, int]],
) -> list[tuple[str, str, int, str]]:
    """Build generation units from TOC subheader entries.

    When an L2 topic is followed by a piece entry (``SELECTED WORK`` or
    ``Listening Companion``), merge topic intro + first piece into one unit.
    Additional pieces in the same topic remain separate.

    Returns ``(toc_title, anchor_title, start_page, piece_type)``.
    """
    subs = _dedupe_piece_toc_entries(subs)
    out: list[tuple[str, str, int, str]] = []
    i = 0
    while i < len(subs):
        title, page, level = subs[i]
        if level == 2 and is_piece_toc_entry(title):
            out.append((title, title, page, piece_toc_type(title)))
        elif level == 2 and i + 1 < len(subs):
            nxt_title, _, nxt_level = subs[i + 1]
            if nxt_level == 3 and is_piece_toc_entry(nxt_title):
                out.append((nxt_title, title, page, piece_toc_type(nxt_title)))
                i += 2
                continue
            out.append((title, title, page, ""))
        elif level == 3 and is_piece_toc_entry(title):
            out.append((title, title, page, piece_toc_type(title)))
        elif level == 2:
            out.append((title, title, page, ""))
        i += 1
    return out


def _dedupe_piece_toc_entries(
    subs: list[tuple[str, int, int]],
) -> list[tuple[str, int, int]]:
    """Drop duplicate piece TOC lines (outline often lists both L2 and L3)."""
    groups: dict[str, list[tuple[int, str, int, int]]] = {}
    for idx, (title, page, level) in enumerate(subs):
        if not is_piece_toc_entry(title):
            continue
        groups.setdefault(_piece_dedupe_key(title), []).append(
            (idx, title, page, level)
        )

    skip: set[int] = set()
    for group in groups.values():
        if len(group) <= 1:
            continue
        keep = max(group, key=lambda g: (g[3], g[2]))
        for idx, _, _, _ in group:
            if idx != keep[0]:
                skip.add(idx)

    return [entry for i, entry in enumerate(subs) if i not in skip]


def _dedupe_selected_work_toc_entries(
    subs: list[tuple[str, int, int]],
) -> list[tuple[str, int, int]]:
    return _dedupe_piece_toc_entries(subs)


def _resolve_unit_start(
    doc: Document,
    toc_title: str,
    anchor_title: str,
    start_page: int,
    piece_type: str,
    *,
    is_iad: bool = False,
) -> tuple[int, int]:
    if anchor_title != toc_title:
        topic_pos = _find_anchor(doc, anchor_title, start_page) or (start_page, 0)
        piece_pos = _find_piece_anchor(doc, toc_title, start_page, is_iad=is_iad)
        if piece_pos and piece_pos < topic_pos:
            return piece_pos
        return topic_pos
    if piece_type or is_piece_toc_entry(toc_title):
        return _find_piece_anchor(doc, toc_title, start_page, is_iad=is_iad) or (
            start_page,
            0,
        )
    pos = _find_anchor(doc, anchor_title, start_page)
    return pos if pos else (start_page, 0)


def _display_title_for_unit(
    doc: Document,
    pos: tuple[int, int],
    toc_title: str,
    anchor_title: str,
    piece_type: str,
    *,
    is_iad: bool = False,
) -> str:
    if piece_type or is_piece_toc_entry(toc_title):
        return resolve_subheader_title(doc, pos, toc_title, is_iad=is_iad)
    return anchor_title


def _dedupe_built_subheaders(subheaders: list[SubheaderBP]) -> list[SubheaderBP]:
    """Drop subheaders that resolved to the same title and anchor."""
    seen: set[tuple[str, int, int]] = set()
    out: list[SubheaderBP] = []
    for sub in subheaders:
        key = (_norm_title(sub.title), sub.start_page, sub.start_line)
        if key in seen:
            continue
        seen.add(key)
        out.append(sub)
    return out


def _find_piece_anchor_by_label(
    doc: Document,
    from_page: int,
    label: Optional[str],
    line_matcher,
) -> Optional[tuple[int, int]]:
    if not label:
        return None
    target = _norm_title(label)
    for pidx in range(max(0, from_page - 1), min(doc.page_count, from_page + 4)):
        for ln in doc.pages[pidx].lines:
            piece = line_matcher(ln.text)
            if not piece:
                continue
            norm = _norm_title(piece)
            if norm == target or norm.startswith(target) or target.startswith(norm):
                return (pidx, ln.index)
    return None


def _find_selected_work_anchor(
    doc: Document, toc_title: str, from_page: int, *, is_iad: bool = False
) -> Optional[tuple[int, int]]:
    matcher = lambda text: extract_selected_work_label(text, is_iad=is_iad)
    return _find_piece_anchor_by_label(
        doc, from_page, matcher(toc_title), matcher
    )


def _find_listening_companion_anchor(
    doc: Document, toc_title: str, from_page: int
) -> Optional[tuple[int, int]]:
    return _find_piece_anchor_by_label(
        doc,
        from_page,
        extract_listening_companion_label(toc_title),
        extract_listening_companion_label,
    )


def _find_piece_anchor(
    doc: Document, toc_title: str, from_page: int, *, is_iad: bool = False
) -> tuple[int, int]:
    if is_selected_work_toc_entry(toc_title):
        pos = _find_selected_work_anchor(doc, toc_title, from_page, is_iad=is_iad)
        if pos:
            return pos
    if is_listening_companion_toc_entry(toc_title):
        pos = _find_listening_companion_anchor(doc, toc_title, from_page)
        if pos:
            return pos
    pos = _find_anchor(doc, toc_title, from_page)
    return pos if pos else (from_page, 0)


def _find_subheader_anchor(
    doc: Document, title: str, from_page: int
) -> tuple[int, int]:
    if is_piece_toc_entry(title):
        return _find_piece_anchor(doc, title, from_page)
    pos = _find_anchor(doc, title, from_page)
    return pos if pos else (from_page, 0)


def _is_major_heading_line(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if is_piece_toc_entry(stripped) or extract_piece_label(stripped):
        return True
    if _LISTENING_GUIDE_HEADING_RE.match(stripped):
        return False
    norm = _norm_title(stripped)
    if stripped.isupper() and len(norm) >= 12:
        return True
    return False


def _strip_trailing_timestamp_block(lines: list[str]) -> list[str]:
    """Drop a trailing run of listening-guide timestamp lines (no flashcard value)."""
    end = len(lines)
    while end > 0:
        stripped = lines[end - 1].strip()
        if not stripped:
            end -= 1
            continue
        if _LISTENING_TIMESTAMP_RE.match(stripped):
            end -= 1
            continue
        break
    return lines[:end]


def _is_listening_guide_content_line(text: str) -> bool:
    """Lines that belong to a listening guide block (not surrounding article prose)."""
    stripped = text.strip()
    if not stripped:
        return True
    if _LISTENING_TIMESTAMP_RE.match(stripped):
        return True
    if stripped in {"Timeline", "Form", "Chorus", "Verse", "Text"}:
        return True
    if stripped.startswith("[") and stripped.endswith("]"):
        return True
    if len(stripped) < 28 and stripped.isupper():
        return True
    if len(stripped) < 80 and stripped.count("!") >= 1:
        return True
    if len(stripped) < 72 and stripped.startswith(
        ("I ", "It ", "Planted", "Whether", "Yet ", "But ", "Of ", "There ")
    ):
        return True
    return False


def strip_listening_guide(body_text: str) -> str:
    """Remove ``Listening Guide`` blocks from listening-companion subsection text."""
    if not body_text:
        return body_text
    lines = body_text.split("\n")
    out: list[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if _LISTENING_GUIDE_HEADING_RE.match(stripped) or _norm_title(stripped).startswith(
            "listening guide"
        ):
            skipping = True
            continue
        if skipping:
            if _is_major_heading_line(stripped):
                skipping = False
                out.append(line)
                continue
            # Column-major body places article prose after the guide block.
            if stripped and stripped[0].islower():
                skipping = False
                out.append(line)
                continue
            if not _is_listening_guide_content_line(stripped):
                skipping = False
                out.append(line)
                continue
            continue
        out.append(line)
    out = _strip_trailing_timestamp_block(out)
    return "\n".join(out).strip()


def _find_anchor(doc: Document, title: str, from_page: int) -> Optional[tuple[int, int]]:
    """Locate a subheader's first body occurrence at/after ``from_page``.

    Cross-validates against the title text rather than caps-only (caps also
    appears in NOTE TO STUDENTS:, FIGURE 1, etc.). Handles wrapped headings
    where the first body line is only a prefix of the TOC title.
    """
    target = _norm_title(title)
    page_lo = max(0, from_page - 1)
    page_hi = min(doc.page_count, from_page + 4)
    for pidx in range(page_lo, page_hi):
        for ln in doc.pages[pidx].lines:
            norm = _norm_title(ln.text)
            if norm == target:
                return (pidx, ln.index)
    for pidx in range(page_lo, page_hi):
        for ln in doc.pages[pidx].lines:
            norm = _norm_title(ln.text)
            if norm.startswith(target) and len(target) > 4:
                return (pidx, ln.index)
            # Wrapped heading: "PERCEPTION AND THE ART OF" + continuation line.
            if len(norm) >= 12 and target.startswith(norm):
                return (pidx, ln.index)
    return None


def _next_unit_boundary(
    units: list[tuple[str, str, int, str, tuple[int, int]]],
    index: int,
    fallback: tuple[int, int],
) -> tuple[int, int]:
    """Earliest anchor strictly after this unit's start (handles out-of-order PDF layout)."""
    pos = units[index][4]
    best: Optional[tuple[int, int]] = None
    for j, unit in enumerate(units):
        if j == index:
            continue
        npos = unit[4]
        if npos > pos and (best is None or npos < best):
            best = npos
    return best if best is not None else fallback


def _slice_text(doc: Document, start: tuple[int, int], end: tuple[int, int]) -> str:
    (sp, sl), (ep, el) = start, end
    out: list[str] = []
    for pidx in range(sp, ep + 1):
        page = doc.pages[pidx]
        for ln in _page_lines_reading_order(page.lines, page.width):
            if pidx == sp and ln.index < sl:
                continue
            if pidx == ep and ln.index >= el:
                continue
            out.append(ln.text)
    return "\n".join(out).strip()


_CREDIT_MARKERS = (
    "metropolitan museum of art",
    "library of congress",
    "geography and map division",
    "bequest of",
    "memorial collection",
    "crosby brown collection",
    "collection of musical instruments",
)
_EXAMPLE_OF_RE = re.compile(r"^\s*example of (a|an)\b", re.IGNORECASE)
_OBJECT_CAPTION_RE = re.compile(
    r"^[A-Z][^.]{5,80},\s+[A-Z][a-z].*,\s+(nineteenth|twentieth|twenty)",
    re.IGNORECASE,
)


def _line_y0(doc: Document, pos: tuple[int, int]) -> float:
    pidx, lidx = pos
    if pidx >= doc.page_count:
        return 0.0
    page = doc.pages[pidx]
    if lidx >= len(page.lines):
        return 0.0
    return page.lines[lidx].y0


def _is_sidebar_credit_line(text: str) -> bool:
    low = text.strip().lower()
    if not low:
        return True
    if any(marker in low for marker in _CREDIT_MARKERS):
        return True
    if _EXAMPLE_OF_RE.match(low):
        return True
    if _OBJECT_CAPTION_RE.match(text.strip()):
        return True
    return False


def _is_decorative_margin_line(ln: Line) -> bool:
    """Floating section divider / sidebar title (not inline subheader body)."""
    text = ln.text.strip()
    if not text:
        return True
    if SECTION_RE.match(text):
        return True
    if ln.y0 < 120 and 140 < ln.x0 < 280:
        return True
    return False


def _anchor_index_in_reading_order(
    ordered: list[Line], line_index: int
) -> Optional[int]:
    for i, ln in enumerate(ordered):
        if ln.index == line_index:
            return i
    return None


def _slice_page_lines(
    ordered: list[Line],
    *,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
    start_y: Optional[float] = None,
    end_y: Optional[float] = None,
) -> list[Line]:
    """Trim a page's reading-ordered lines to a subheader span.

    Prefer anchor line indices (column-major safe). Fall back to ``y0`` only
    when the anchor line is missing from the ordered set.
    """
    start_idx = 0
    end_idx = len(ordered)
    if start_line is not None:
        idx = _anchor_index_in_reading_order(ordered, start_line)
        if idx is not None:
            start_idx = idx
        elif start_y is not None:
            for i, ln in enumerate(ordered):
                if ln.y0 >= start_y - 0.5:
                    start_idx = i
                    break
    if end_line is not None:
        idx = _anchor_index_in_reading_order(ordered, end_line)
        if idx is not None:
            end_idx = idx
        elif end_y is not None:
            for i, ln in enumerate(ordered):
                if ln.y0 >= end_y - 0.5:
                    end_idx = i
                    break
    return ordered[start_idx:end_idx]


def _slice_subheader_body(
    doc: Document, start: tuple[int, int], end_anchor: tuple[int, int]
) -> str:
    """Slice subheader prose in column-major reading order.

    On boundary pages, cut at the next subheader anchor by reading-order index
    (not ``y0`` alone), so the right column of a spread is not pulled into the
    previous subsection when its lines sit higher on the page.
    """
    sp, sl = start
    ep, el = end_anchor
    start_y = _line_y0(doc, start)
    end_y: Optional[float] = None
    if ep < doc.page_count and el < len(doc.pages[ep].lines):
        end_y = doc.pages[ep].lines[el].y0

    out: list[str] = []
    for pidx in range(sp, min(ep, doc.page_count - 1) + 1):
        page = doc.pages[pidx]
        ordered = _page_lines_reading_order(page.lines, page.width)
        slice_lines = _slice_page_lines(
            ordered,
            start_line=sl if pidx == sp else None,
            end_line=el if pidx == ep else None,
            start_y=start_y if pidx == sp else None,
            end_y=end_y if pidx == ep else None,
        )
        for ln in slice_lines:
            if _is_sidebar_credit_line(ln.text) or _is_decorative_margin_line(ln):
                continue
            out.append(ln.text)
    return "\n".join(out).strip()


def build_blueprint(
    pdf_path: str, parse_options: Optional[ParseOptions] = None
) -> tuple[Document, list[SectionBP]]:
    opts = parse_options or ParseOptions()
    doc = load_document(pdf_path)
    toc = _flatten_toc(get_toc(doc, pdf_path), doc)

    # Group into sections (level 1) with their descendant subheaders.
    sections: list[SectionBP] = []
    current: Optional[SectionBP] = None
    # Track raw (title, page, level) subheader anchors per section for boundary calc.
    raw_subs: list[list[tuple[str, int, int]]] = []

    order = 0
    for entry in toc:
        if entry.level <= 1:
            current = SectionBP(
                title=entry.title,
                section_type=classify_section(entry.title),
                order=order,
            )
            sections.append(current)
            raw_subs.append([])
            order += 1
        elif _toc_entry_is_subheader(entry):
            if current is None:
                current = SectionBP(title="(root)", section_type="BODY", order=order)
                sections.append(current)
                raw_subs.append([])
                order += 1
            # Tier-4 entries normally fold into their parent, except piece
            # entries (``SELECTED WORK``, ``Listening Companion``).
            raw_subs[-1].append((entry.title, entry.page_index, entry.level))

    # Resolve subheader boundaries within each section.
    doc_end = (doc.page_count - 1, len(doc.pages[-1].lines) if doc.pages else 0)
    for si, sec in enumerate(sections):
        units_spec = _prepare_subheader_units(raw_subs[si])
        if not units_spec:
            # Section with no subheaders (e.g. INTRODUCTION): make one unit
            # spanning to the next section's first page.
            start_page = _section_start_page(toc, sec.title)
            next_page = _next_section_page(toc, sec.title, doc.page_count)
            start = (start_page, 0)
            end = (min(next_page, doc.page_count - 1), 0)
            body = _slice_text(doc, start, (end[0], 0)) if end[0] > start[0] else \
                _slice_text(doc, start, doc_end)
            sec.subheaders.append(
                SubheaderBP(sec.title, start[0], 0, end[0], 0, body_text=body)
            )
            continue

        units: list[tuple[str, str, int, str, tuple[int, int]]] = []
        for toc_title, anchor_title, start_page, piece_type in units_spec:
            pos = _resolve_unit_start(
                doc,
                toc_title,
                anchor_title,
                start_page,
                piece_type,
                is_iad=opts.is_iad,
            )
            units.append((toc_title, anchor_title, start_page, piece_type, pos))

        built: list[SubheaderBP] = []
        for i, (toc_title, anchor_title, _start_page, piece_type, pos) in enumerate(
            units
        ):
            fallback = _section_boundary_end(toc, sec, doc, doc_end)
            end = _next_unit_boundary(units, i, fallback)
            body = _slice_subheader_body(doc, pos, end)
            if piece_type == PIECE_LISTENING_COMPANION:
                body = strip_listening_guide(body)
            display_title = _display_title_for_unit(
                doc,
                pos,
                toc_title,
                anchor_title,
                piece_type,
                is_iad=opts.is_iad,
            )
            display_title = enrich_piece_display_title(
                display_title,
                body,
                toc_title,
                piece_type,
                is_iad=opts.is_iad,
            )
            built.append(
                SubheaderBP(
                    display_title,
                    pos[0],
                    pos[1],
                    end[0],
                    end[1],
                    body_text=body,
                    piece_type=piece_type,
                )
            )
        sec.subheaders = _dedupe_built_subheaders(built)

    return doc, sections


def collapse_duplicate_singletons(sections: list[SectionBP]) -> None:
    """When a section has exactly one subheader with the same title, hoist its
    content onto the section and drop the redundant child (e.g. INTRODUCTION).
    """
    for sec in sections:
        if len(sec.subheaders) != 1:
            continue
        sub = sec.subheaders[0]
        if _norm_title(sec.title) != _norm_title(sub.title):
            continue
        sec.body_text = sub.body_text
        sec.caption_text = sub.caption_text
        sec.start_page = sub.start_page
        sec.start_line = sub.start_line
        sec.end_page = sub.end_page
        sec.end_line = sub.end_line
        sec.subheaders = []


def _section_start_page(toc: list[TocEntry], title: str) -> int:
    for e in toc:
        if e.title == title:
            return e.page_index
    return 0


def _next_section_page(toc: list[TocEntry], title: str, page_count: int) -> int:
    seen = False
    for e in toc:
        if seen and e.level <= 1:
            return e.page_index
        if e.title == title and e.level <= 1:
            seen = True
    return page_count - 1


def _section_boundary_end(
    toc: list[TocEntry], sec: SectionBP, doc: Document, doc_end: tuple[int, int]
) -> tuple[int, int]:
    nxt = _next_section_page(toc, sec.title, doc.page_count)
    if nxt >= doc.page_count - 1:
        return doc_end
    return (nxt, 0)
