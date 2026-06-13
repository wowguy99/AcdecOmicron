"""FIGURE caption extraction (Track B source).

Captions are the ``FIGURE N`` label plus the descriptive line(s) that follow.
Each caption is associated to a subheader by OFFSET position (page, line),
not page range, because a figure can sit right at a subheader boundary.

Note: only caption TEXT is captured. The figure images themselves are not in
the text stream, so the Master (Track B) deck contains no images.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .spans import Document
from .structure import SectionBP

FIGURE_RE = re.compile(r"^\s*FIGURE\s+\d+\b", re.IGNORECASE)
_SOURCE_CREDIT_RE = re.compile(r"^\s*Source:\s*.+", re.IGNORECASE)
_DOMAIN_IN_PARENS_RE = re.compile(
    r"\([^)]*\.\s*(?:edu|gov|org|eu|com)\)", re.IGNORECASE
)
_URL_DOMAIN_RE = re.compile(r"\b\w+\.(?:edu|gov|org|eu)\b", re.IGNORECASE)
_BIBLIOGRAPHIC_CAPTION_RE = re.compile(
    r'^\s*[A-Z][^.]{2,50},\s+[""\u201c].+[""\u201d]\s*,\s*\d+\.?\s*$'
)
_PROSE_VERB_RE = re.compile(
    r"\b(?:led|occurred|evolved|became|consider|shows that|have become|"
    r"has been|because|although|which means|we will|scholars consider)\b",
    re.IGNORECASE,
)
_FIGURE_LABEL_RE = re.compile(
    r"(?:"
    r"\bshowing the\b|"
    r"\bfrom around \d{3,4}\b|"
    r"\bartifact from\b|"
    r"\bMap of\b|"
    r"\bMosaic depicting\b|"
    r"\bRing from\b|"
    r"\bFigure from\b|"
    r"\bdepicting an?\b|"
    r"\bIce core sample\b|"
    r"\btree ring sample\b|"
    r"\bthermometer from\b|"
    r"\blandscape with\b|"
    r"\bWinter Landscape\b|"
    r"\bbronze (?:axe|head)\b|"
    r"\bOlmec Figure\b|"
    r"\batmospheric layers\b|"
    r"\bgreenhouse effect\b|"
    r"\bLake-effect snow\b|"
    r"\bVolcanic gases in the atmosphere\b|"
    r"\bLast Glacial Maximum\b|"
    r"\bspread of agriculture\b|"
    r"\bDynasties of Imperial\b|"
    r"\bbell from the\b|"
    r"\bPortuguese map of\b|"
    r"\bThe Sahel region\b|"
    r"\bLocation of .+ sample\b|"
    r"\bTemperature reconstruction\b|"
    r"\bGrindelwald\b|"
    r"\bHendrick Avercamp\b|"
    r",\s*c\.\s*[\d–—-]+"
    r")",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"[.!?][\"\u201d)]?\s*$")
_WORKING_WITH_THE_RE = re.compile(r"\bworking with the\b", re.IGNORECASE)
_PHOTO_BYLINE_RE = re.compile(r"^\s*photo(?:graph)?\s+by\b", re.IGNORECASE)
_THIS_PHOTO_CAPTION_RE = re.compile(
    r"^\s*this\b.{0,80}\b(photograph|photo|image)\b", re.IGNORECASE
)
_THIS_DEPICTS_RE = re.compile(
    r"^\s*this\b.{0,100}\b(illustrates|shows|depicts|contains)\b", re.IGNORECASE
)
_LEADING_PHOTO_CAPTION_RE = re.compile(
    r"^\s*(?:photograph|photo|image)\b", re.IGNORECASE
)
_BODY_FRAGMENT_RE = re.compile(
    r"\b(?:was added|photograph was|had learned|used an|at bell laboratories)\b",
    re.IGNORECASE,
)
_MAX_INLINE_PHOTO_CAPTION_LEN = 140


@dataclass
class Caption:
    page: int
    line: int
    text: str


def extract_captions(doc: Document, max_caption_lines: int = 4) -> list[Caption]:
    captions: list[Caption] = []
    for pg in doc.pages:
        lines = pg.lines
        for i, ln in enumerate(lines):
            if not FIGURE_RE.match(ln.text):
                continue
            parts: list[str] = []
            j = i + 1
            while j < len(lines) and len(parts) < max_caption_lines:
                nxt = lines[j].text.strip()
                if not nxt or FIGURE_RE.match(nxt) or nxt.isupper():
                    break
                parts.append(nxt)
                if _SENTENCE_END.search(nxt):
                    j += 1
                    break
                j += 1
            text = " ".join(parts).strip()
            if text:
                captions.append(Caption(page=pg.index, line=ln.index, text=text))
    return captions


def _pos_in_range(
    pos: tuple[int, int], start: tuple[int, int], end: tuple[int, int]
) -> bool:
    return start <= pos < end


def _is_mid_sentence_photo_mention(text: str) -> bool:
    """Prose that mentions a photo but is not a standalone image caption."""
    low = text.lower().strip()
    if _BODY_FRAGMENT_RE.search(low):
        return True
    if low.startswith(("the ", "a ", "an ", "and ", "but ", "when ", "as ")):
        return True
    if text.strip() and text.strip()[0].islower():
        return True
    return False


def is_inline_photo_caption(text: str) -> bool:
    """Short unlabeled lines under guide photos (no ``FIGURE N`` prefix)."""
    stripped = text.strip()
    if not stripped or len(stripped) > _MAX_INLINE_PHOTO_CAPTION_LEN:
        return False
    if FIGURE_RE.match(stripped):
        return False
    if stripped.isupper() and len(stripped) > 24:
        return False
    low = stripped.lower()
    if "listening companion" in low or low.startswith("listening guide"):
        return False
    if _is_mid_sentence_photo_mention(stripped):
        return False
    if _WORKING_WITH_THE_RE.search(stripped):
        return True
    if _PHOTO_BYLINE_RE.match(stripped):
        return True
    if _THIS_PHOTO_CAPTION_RE.match(stripped):
        return True
    if _THIS_DEPICTS_RE.match(stripped):
        return True
    if _LEADING_PHOTO_CAPTION_RE.match(stripped) and len(stripped) < 90:
        return True
    return False


def is_image_source_credit(text: str) -> bool:
    """Standalone ``Source: …`` lines under guide images (IAD social science style)."""
    stripped = text.strip()
    return bool(stripped and _SOURCE_CREDIT_RE.match(stripped))


def is_source_continuation_line(text: str) -> bool:
    """URL tails, pipe segments, and citation fragments that follow a ``Source:`` line."""
    stripped = text.strip()
    if not stripped:
        return False
    if re.match(r"^\([^)]+\.(?:edu|gov|org|eu|com)\)\.?$", stripped, re.IGNORECASE):
        return True
    if re.match(r"^\|\s*.+", stripped):
        return True
    if re.match(r"^\d{1,4}\.$", stripped):
        return True
    if "|" in stripped and _URL_DOMAIN_RE.search(stripped) and len(stripped) < 160:
        return True
    if _DOMAIN_IN_PARENS_RE.search(stripped) and len(stripped) < 160:
        return True
    return False


def is_standalone_image_credit(text: str) -> bool:
    """Image credits without a ``Source:`` prefix (IAD pipe/institution lines)."""
    stripped = text.strip()
    if not stripped or is_image_source_credit(stripped):
        return False
    if is_source_continuation_line(stripped):
        return True
    low = stripped.lower()
    if "|" in stripped and (
        "image of the week" in low or _URL_DOMAIN_RE.search(stripped)
    ):
        return True
    return False


def is_bibliographic_caption_line(text: str) -> bool:
    """Short citation lines printed under guide figures."""
    stripped = text.strip()
    if not stripped:
        return False
    if _BIBLIOGRAPHIC_CAPTION_RE.match(stripped):
        return True
    if stripped.endswith("Springer, Dordrecht.") and len(stripped) < 90:
        return True
    return False


def is_figure_label_line(text: str) -> bool:
    """Short figure/chart labels under images (not main article prose)."""
    stripped = text.strip()
    if not stripped or len(stripped) > 120:
        return False
    if not stripped.endswith("."):
        return False
    if FIGURE_RE.match(stripped):
        return False
    if is_image_source_credit(stripped) or is_standalone_image_credit(stripped):
        return False
    if is_inline_photo_caption(stripped):
        return False
    if _PROSE_VERB_RE.search(stripped):
        return False
    if _FIGURE_LABEL_RE.search(stripped):
        return True
    words = [w for w in re.split(r"\s+", stripped.rstrip(".")) if w]
    if len(words) <= 4 and stripped[0].isupper():
        if any(
            w.lower() in {"sample", "map", "figure", "artifact", "photograph", "image"}
            for w in words
        ):
            return True
    return False


def is_caption_line(text: str) -> bool:
    """True when a line belongs in Master (Track B), not Text-Only body source."""
    stripped = text.strip()
    if not stripped:
        return False
    return (
        is_image_source_credit(stripped)
        or is_standalone_image_credit(stripped)
        or is_figure_label_line(stripped)
        or is_bibliographic_caption_line(stripped)
        or is_inline_photo_caption(stripped)
    )


def strip_source_credits(body_text: str) -> tuple[str, list[str]]:
    """Move image credits and caption lines from body to Master (Track B) source."""
    if not body_text:
        return "", []
    kept: list[str] = []
    moved: list[str] = []
    lines = body_text.split("\n")
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped and is_caption_line(stripped):
            moved.append(stripped)
            i += 1
            while i < len(lines):
                nxt = lines[i].strip()
                if nxt and is_source_continuation_line(nxt):
                    moved.append(nxt)
                    i += 1
                else:
                    break
            continue
        kept.append(lines[i])
        i += 1
    return "\n".join(kept).strip(), moved


def strip_figure_blocks(body_text: str) -> tuple[str, list[str]]:
    """Remove ``FIGURE N`` labels and their full caption blocks from body prose."""
    if not body_text:
        return "", []
    lines = body_text.split("\n")
    kept: list[str] = []
    moved: list[str] = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if FIGURE_RE.match(stripped):
            parts: list[str] = []
            j = i + 1
            while j < len(lines):
                nxt = lines[j].strip()
                if not nxt or FIGURE_RE.match(nxt):
                    break
                if nxt.isupper() and len(nxt) > 24:
                    break
                parts.append(nxt)
                j += 1
            text = " ".join(parts).strip()
            if text:
                moved.append(text)
            i = j
            continue
        kept.append(lines[i])
        i += 1
    return "\n".join(kept).strip(), moved


def strip_inline_photo_captions(body_text: str) -> tuple[str, list[str]]:
    """Move inline photo captions from body prose to the Master (Track B) source."""
    if not body_text:
        return "", []
    kept: list[str] = []
    moved: list[str] = []
    for line in body_text.split("\n"):
        stripped = line.strip()
        if stripped and is_inline_photo_caption(stripped):
            moved.append(stripped)
        else:
            kept.append(line)
    return "\n".join(kept).strip(), moved


def strip_captions_from_body(body_text: str) -> tuple[str, list[str]]:
    """Remove all caption material from body text; return cleaned body + moved lines."""
    body, figure = strip_figure_blocks(body_text)
    body, credits = strip_source_credits(body)
    return body, [*figure, *credits]


def strip_known_caption_lines(body_text: str, known: list[str]) -> str:
    """Drop lines that duplicate captions already assigned to Track B."""
    if not body_text or not known:
        return body_text
    drop: set[str] = set()
    for item in known:
        text = item.strip()
        if not text:
            continue
        drop.add(text)
        for part in text.split("\n"):
            part = part.strip()
            if part:
                drop.add(part)
    kept = [line for line in body_text.split("\n") if line.strip() not in drop]
    return "\n".join(kept).strip()


def _merge_caption_parts(*groups: list[str]) -> str:
    seen: set[str] = set()
    out: list[str] = []
    for group in groups:
        for item in group:
            key = item.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(key)
    return "\n".join(out)


def attach_captions(doc: Document, sections: list[SectionBP]) -> None:
    """Populate ``SubheaderBP.caption_text`` and strip caption lines from body."""
    captions = extract_captions(doc)
    for sec in sections:
        for sub in sec.subheaders:
            start = (sub.start_page, sub.start_line)
            end = (sub.end_page, sub.end_line)
            hits = [
                c.text
                for c in captions
                if _pos_in_range((c.page, c.line), start, end)
            ]
            body, moved = strip_captions_from_body(sub.body_text)
            body = strip_known_caption_lines(body, hits)
            sub.body_text = body
            sub.caption_text = _merge_caption_parts(moved, hits)
        if sec.body_text:
            body, moved = strip_captions_from_body(sec.body_text)
            sec_hits = [
                c.text
                for c in captions
                if _pos_in_range(
                    (c.page, c.line),
                    (sec.start_page, sec.start_line),
                    (sec.end_page, sec.end_line),
                )
            ]
            body = strip_known_caption_lines(body, sec_hits)
            sec.body_text = body
            if moved or sec_hits:
                sec.caption_text = _merge_caption_parts(
                    moved, sec_hits, [sec.caption_text] if sec.caption_text else []
                )
