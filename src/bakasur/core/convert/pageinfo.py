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


def image_pages(pdf_path: Path, min_cover: float = 0.8) -> dict[int, bool]:
    """
    Return page_no (1-based) -> whether one image covers at least ``min_cover`` of the page.
    Catches scans that carry an embedded OCR text layer (the GCZMA minutes do, and a poor
    one), which ``classify_pages`` counts as digital because they have plenty of text.
    """
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        result: dict[int, bool] = {}
        for i in range(len(doc)):
            page = doc[i]
            width, height = page.get_size()
            cover = 0.0
            for obj in page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_IMAGE], max_depth=3):
                left, bottom, right, top = obj.get_bounds()
                w = max(0.0, min(right, width) - max(left, 0.0))
                h = max(0.0, min(top, height) - max(bottom, 0.0))
                cover = max(cover, w * h / (width * height))
            result[i + 1] = cover >= min_cover
        return result
    finally:
        doc.close()
