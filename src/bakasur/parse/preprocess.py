"""Optional scan preprocessing before Docling conversion."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pypdfium2 as pdfium
from PIL import Image


def render_page_gray(page: pdfium.PdfPage, dpi: int = 300) -> np.ndarray:
    return np.array(page.render(scale=dpi / 72.0).to_pil().convert("L"))


def otsu_binarize(gray: np.ndarray) -> np.ndarray:
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary


def build_preprocessed_pdf(
    pdf_path: Path,
    output_path: Path,
    *,
    dpi: int = 300,
    page_indices: list[int] | None = None,
) -> Path:
    """
    Write a copy of the PDF where the selected pages (zero-based; all if None) are
    re-rendered at higher DPI and binarized. Other pages are copied unchanged so
    digital pages keep their text layer, and every page keeps its original size
    so page numbers and coordinates still line up with the source.
    """
    src = pdfium.PdfDocument(str(pdf_path))
    out = pdfium.PdfDocument.new()
    try:
        selected = set(range(len(src)) if page_indices is None else page_indices)
        for idx in range(len(src)):
            if idx not in selected:
                out.import_pages(src, [idx])
                continue
            width, height = src[idx].get_size()
            binary = otsu_binarize(render_page_gray(src[idx], dpi=dpi))
            page = out.new_page(width, height)
            image = pdfium.PdfImage.new(out)
            image.set_bitmap(pdfium.PdfBitmap.from_pil(Image.fromarray(binary)))
            image.set_matrix(pdfium.PdfMatrix().scale(width, height))
            page.insert_obj(image)
            page.gen_content()
        out.save(str(output_path))
    finally:
        out.close()
        src.close()
    return output_path
