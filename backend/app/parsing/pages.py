"""Map PDF page indices to printed guide page numbers."""
from __future__ import annotations


def pdf_page_to_printed(pdf_index: int, mapping: dict[int, int]) -> int | None:
    """Return the printed page number for a 0-based PDF page index."""
    if not mapping:
        return None
    index_to_printed = {idx: printed for printed, idx in mapping.items()}
    if pdf_index in index_to_printed:
        return index_to_printed[pdf_index]
    if not index_to_printed:
        return None
    nearest_idx = min(index_to_printed, key=lambda i: abs(i - pdf_index))
    nearest_printed = index_to_printed[nearest_idx]
    return nearest_printed + (pdf_index - nearest_idx)
