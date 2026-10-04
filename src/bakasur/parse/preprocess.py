"""Optional scan preprocessing before Docling conversion."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pypdfium2 as pdfium


def render_page_bgr(pdf_path: Path, page_index: int, dpi: int = 300) -> np.ndarray:
    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        page = doc[page_index]
        scale = dpi / 72.0
        bitmap = page.render(scale=scale)
        pil_image = bitmap.to_pil()
        arr = np.array(pil_image)
        if arr.ndim == 2:
            return cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
        if arr.shape[2] == 4:
            return cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    finally:
        doc.close()


def otsu_binarize(bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)


def build_preprocessed_pdf(
    pdf_path: Path,
    output_path: Path,
    *,
    dpi: int = 300,
    page_indices: list[int] | None = None,
) -> Path:
    """
    Render selected pages at higher DPI, binarize, and write a new PDF.
    Falls back to copying the source if img2pdf is unavailable.
    """
    try:
        import img2pdf
    except ImportError:
        import shutil

        shutil.copy2(pdf_path, output_path)
        return output_path

    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        indices = page_indices if page_indices is not None else list(range(len(doc)))
    finally:
        doc.close()

    temp_dir = output_path.parent / "_preprocess_tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    image_paths: list[Path] = []

    for idx in indices:
        bgr = render_page_bgr(pdf_path, idx, dpi=dpi)
        binary = otsu_binarize(bgr)
        img_path = temp_dir / f"page_{idx + 1:04d}.png"
        cv2.imwrite(str(img_path), binary)
        image_paths.append(img_path)

    with output_path.open("wb") as f:
        f.write(img2pdf.convert([str(p) for p in image_paths]))

    for p in image_paths:
        p.unlink(missing_ok=True)
    temp_dir.rmdir()

    return output_path
