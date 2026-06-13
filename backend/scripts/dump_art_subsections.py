"""Print subsection boundaries for art guides (debug helper)."""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.parsing.structure import build_blueprint, collapse_duplicate_singletons


def first_last(text: str) -> tuple[str, str]:
    words = [w for w in text.replace("\n", " ").split() if w]
    if not words:
        return "(empty)", "(empty)"
    return words[0], words[-1]


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    pdf = BACKEND.parent / "Guides" / "ArtRG_Transportation.pdf"
    if not pdf.exists():
        print(f"guide not found: {pdf}")
        return

    _, sections = build_blueprint(str(pdf))
    collapse_duplicate_singletons(sections)

    for sec in sections:
        if sec.section_type != "BODY" or not sec.subheaders:
            continue
        if not any(s.piece_type for s in sec.subheaders):
            continue
        print(f"=== {sec.title} ===")
        for sub in sec.subheaders:
            fw, lw = first_last(sub.body_text or "")
            span = (
                f"p{sub.start_page}:{sub.start_line}-"
                f"p{sub.end_page}:{sub.end_line}"
            )
            print(f"{sub.title}")
            print(f"  span: {span}")
            print(f"  first word: {fw!r}")
            print(f"  last word:  {lw!r}")
        print()


if __name__ == "__main__":
    main()
