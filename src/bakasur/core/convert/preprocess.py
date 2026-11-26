"""Scan preprocessing before Docling conversion: binarization and orientation fixes."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import pypdfium2 as pdfium
from PIL import Image

from bakasur.core.convert.orientation import Orientation, OrientationDetector, detect_orientations


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
    binarize: bool | Collection[int] = True,
    rotations: dict[int, int] | None = None,
) -> Path:
    """
    Write a copy of the PDF where the selected pages (zero-based; all if None) are
    re-rendered at higher DPI, binarized if ``binarize`` is True or lists the page, and
    turned counter-clockwise by ``rotations[idx]`` degrees where given. Other pages are copied unchanged so digital
    pages keep their text layer. Every page keeps its original size, with width and height
    swapped on pages turned a quarter, so page numbers still line up with the source.
    """
    rotations = rotations or {}
    src = pdfium.PdfDocument(str(pdf_path))
    out = pdfium.PdfDocument.new()
    try:
        selected = set(range(len(src)) if page_indices is None else page_indices)
        for idx in range(len(src)):
            if idx not in selected:
                out.import_pages(src, [idx])
                continue
            width, height = src[idx].get_size()
            pixels = render_page_gray(src[idx], dpi=dpi)
            if binarize is True or (binarize is not False and idx in binarize):
                pixels = otsu_binarize(pixels)
            image = Image.fromarray(pixels)
            turn = rotations.get(idx, 0) % 360
            if turn:
                image = image.rotate(turn, expand=True)
                if turn in (90, 270):
                    width, height = height, width
            page = out.new_page(width, height)
            pdf_image = pdfium.PdfImage.new(out)
            pdf_image.set_bitmap(pdfium.PdfBitmap.from_pil(image))
            pdf_image.set_matrix(pdfium.PdfMatrix().scale(width, height))
            page.insert_obj(pdf_image)
            page.gen_content()
        out.save(str(output_path))
    finally:
        out.close()
        src.close()
    return output_path


@dataclass
class PreparedPdf:
    """The PDF to hand Docling, and what the orientation check found on each scanned page."""

    path: Path
    orientations: list[Orientation] = field(default_factory=list)

    @property
    def uncertain(self) -> list[Orientation]:
        return [o for o in self.orientations if not o.confident]

    @property
    def rotated(self) -> list[Orientation]:
        return [o for o in self.orientations if o.rotation]


def prepare_pdf(
    pdf_path: Path,
    out_path: Path,
    *,
    binarize_indices: list[int] = (),
    orient_indices: list[int] = (),
    detector: OrientationDetector | None = None,
) -> PreparedPdf:
    """
    Binarize ``binarize_indices`` and turn upright any of ``orient_indices`` found sideways
    or upside down (zero-based pages). A corrected copy is written to ``out_path`` only when
    some page actually changes; otherwise the source is used as is. A turned page is
    re-rendered as an image, which also drops any embedded text layer: on a sideways scan
    that layer was read from the sideways image and is garbage anyway.
    """
    orientations: list[Orientation] = []
    if orient_indices:
        orientations = detect_orientations(pdf_path, list(orient_indices), detector or OrientationDetector())
    rotations = {o.page_no - 1: o.rotation for o in orientations if o.rotation}
    pages = sorted(set(binarize_indices) | set(rotations))
    if not pages:
        return PreparedPdf(pdf_path, orientations)
    build_preprocessed_pdf(
        pdf_path, out_path, page_indices=pages, binarize=set(binarize_indices), rotations=rotations
    )
    return PreparedPdf(out_path, orientations)
