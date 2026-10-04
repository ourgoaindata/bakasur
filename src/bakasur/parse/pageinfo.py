"""Per-page digital vs scanned classification."""

from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium


def count_page_chars(pdf_path: Path, page_index: int) -> int:
    """Return extractable character count for a zero-based page index."""
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        page = doc[page_index]
        textpage = page.get_textpage()
        text = textpage.get_text_bounded()
        return len(text.strip())
    finally:
        doc.close()


def classify_pages(pdf_path: Path, threshold: int = 50) -> dict[int, bool]:
    """
    Return page_no (1-based) -> is_scanned mapping.
    Pages below the character threshold are treated as scanned.
    """
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        result: dict[int, bool] = {}
        for i in range(len(doc)):
            page = doc[i]
            textpage = page.get_textpage()
            text = textpage.get_text_bounded()
            result[i + 1] = len(text.strip()) < threshold
        return result
    finally:
        doc.close()


def page_count(pdf_path: Path) -> int:
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        return len(doc)
    finally:
        doc.close()
