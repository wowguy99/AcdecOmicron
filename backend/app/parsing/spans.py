"""Span-level, font-aware PDF extraction.

This is the foundation for everything else. We never use plain ``get_text()``
because we need font size, flags (bold), and baseline to:

* drop footnote-superscript digits without corrupting real numbers,
* detect repeated header/footer furniture by frequency (not literal strings),
* map printed page numbers to PDF page indices.

The public artifact is a :class:`Document` of :class:`Line` objects carrying
offset coordinates (page, line index, char offset) used downstream to slice
inline subheaders that share or split a page.
"""
from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

import fitz  # PyMuPDF

# PyMuPDF span flag bits.
FLAG_SUPERSCRIPT = 1
FLAG_BOLD = 16

_DIGITS_ONLY = re.compile(r"^\d{1,3}$")
_TRAILING_FOOTNOTE = re.compile(r"(?<=[.,;:%)\u201d\"])\d{1,3}$")


@dataclass
class Line:
    page: int          # PDF page index (0-based)
    index: int         # line index within page (after furniture removal)
    text: str          # cleaned text (footnote digits dropped)
    size: float        # dominant font size on the line
    bold: bool
    is_caps: bool      # text is (mostly) uppercase letters
    y0: float          # top y of the line bbox
    x0: float = 0.0    # left x of the line bbox (indent, used for TOC levels)
    raw_text: str = "" # text before footnote stripping (debugging/tests)


@dataclass
class Page:
    index: int
    width: float
    height: float
    printed_number: Optional[int] = None
    lines: list[Line] = field(default_factory=list)


@dataclass
class Document:
    pages: list[Page]
    body_size: float
    # printed page number -> PDF page index (first occurrence)
    printed_to_index: dict[int, int] = field(default_factory=dict)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def full_text(self) -> str:
        return "\n".join(
            ln.text for pg in self.pages for ln in pg.lines if ln.text.strip()
        )


def _is_caps(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 2:
        return False
    upper = sum(1 for c in letters if c.isupper())
    return upper / len(letters) >= 0.85


def _span_is_footnote(span: dict, body_size: float) -> bool:
    """A superscript citation marker: flagged superscript or a small digit run."""
    text = span.get("text", "").strip()
    if not text:
        return False
    size = float(span.get("size", body_size))
    flags = int(span.get("flags", 0))
    small = size <= body_size - 1.0
    if (flags & FLAG_SUPERSCRIPT) and _DIGITS_ONLY.match(text):
        return True
    if small and _DIGITS_ONLY.match(text):
        return True
    return False


def _clean_glued_footnote(text: str, next_small_digits: bool) -> str:
    """Best-effort: if the extractor glued a trailing citation digit onto a
    word ending in punctuation (e.g. ``locations.2``), strip it. We only do
    this when the following span was a small digit run, to avoid eating real
    numbers like ``1482`` or ``60,000``.
    """
    if next_small_digits:
        return _TRAILING_FOOTNOTE.sub("", text)
    return text


def _compute_body_size(doc: fitz.Document) -> float:
    sizes: Counter[int] = Counter()
    for page in doc:
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    t = span.get("text", "")
                    if t.strip():
                        sizes[round(float(span["size"]))] += len(t.strip())
    if not sizes:
        return 10.0
    return float(sizes.most_common(1)[0][0])


def _detect_furniture(raw_pages: list[list[str]], page_total: int) -> set[str]:
    """Lines repeated across many pages are running headers/footers."""
    counter: Counter[str] = Counter()
    for lines in raw_pages:
        for t in set(_norm(x) for x in lines if x.strip()):
            counter[t] += 1
    threshold = max(3, int(page_total * 0.25))
    return {t for t, c in counter.items() if t and c >= threshold and len(t) < 80}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def load_document(pdf_path: str) -> Document:
    doc = fitz.open(pdf_path)
    body_size = _compute_body_size(doc)

    # First pass: gather raw per-page line text for furniture detection.
    raw_pages: list[list[str]] = []
    page_dicts = []
    for page in doc:
        d = page.get_text("dict")
        page_dicts.append((page, d))
        raw_lines: list[str] = []
        for block in d["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block["lines"]:
                txt = "".join(s.get("text", "") for s in line["spans"]).strip()
                if txt:
                    raw_lines.append(txt)
        raw_pages.append(raw_lines)

    furniture = _detect_furniture(raw_pages, len(page_dicts))

    pages: list[Page] = []
    printed_to_index: dict[int, int] = {}

    for pidx, (page, d) in enumerate(page_dicts):
        pg = Page(index=pidx, width=d["width"], height=d["height"])
        line_idx = 0
        # Collect (y, line) for ordering and to find margin page numbers.
        for block in d["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block["lines"]:
                spans = line["spans"]
                # Build cleaned text, dropping footnote spans.
                parts: list[str] = []
                sizes: list[float] = []
                bold_votes = 0
                total_votes = 0
                n = len(spans)
                for i, span in enumerate(spans):
                    stext = span.get("text", "")
                    if _span_is_footnote(span, body_size):
                        continue
                    next_small = (
                        i + 1 < n and _span_is_footnote(spans[i + 1], body_size)
                    )
                    stext = _clean_glued_footnote(stext, next_small)
                    parts.append(stext)
                    if stext.strip():
                        sizes.append(float(span["size"]))
                        total_votes += 1
                        if int(span.get("flags", 0)) & FLAG_BOLD:
                            bold_votes += 1
                raw_text = "".join(s.get("text", "") for s in spans).strip()
                text = "".join(parts).strip()
                # Catch footnote digits glued onto a sentence end in a single
                # span (not split out as a superscript). Requires a lowercase
                # letter before the period so real values like "0.5", "3.2",
                # or "U.S." abbreviations are left untouched.
                text = re.sub(r"(?<=[a-z])\.\d{1,3}\b", ".", text)
                if not text:
                    continue

                norm = _norm(text)
                y0 = line["bbox"][1]
                x0 = line["bbox"][0]
                # Standalone page number near top/bottom margin.
                if _DIGITS_ONLY.match(text) and (
                    y0 < d["height"] * 0.12 or y0 > d["height"] * 0.88
                ):
                    num = int(text)
                    if num not in printed_to_index:
                        printed_to_index[num] = pidx
                    pg.printed_number = pg.printed_number or num
                    continue
                if norm in furniture:
                    continue

                size = statistics.median(sizes) if sizes else body_size
                pg.lines.append(
                    Line(
                        page=pidx,
                        index=line_idx,
                        text=text,
                        size=round(size, 1),
                        bold=(total_votes > 0 and bold_votes / total_votes >= 0.6),
                        is_caps=_is_caps(text),
                        y0=y0,
                        x0=x0,
                        raw_text=raw_text,
                    )
                )
                line_idx += 1
        pages.append(pg)

    doc.close()
    return Document(
        pages=pages, body_size=body_size, printed_to_index=printed_to_index
    )
