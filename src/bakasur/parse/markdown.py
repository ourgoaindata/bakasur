"""Convert any Docling-supported file to Markdown, OCRing with RapidOCR."""

from __future__ import annotations

import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions,
    RapidOcrOptions,
    TableFormerMode,
    TableStructureOptions,
)
from docling.document_converter import DocumentConverter, ImageFormatOption, PdfFormatOption
from docling_core.types.doc import DoclingDocument

from bakasur.config import Settings
from bakasur.parse.artifacts import TRAVERSE_PICTURES
from bakasur.parse.orientation import Orientation, OrientationDetector
from bakasur.parse.pageinfo import classify_pages, image_pages
from bakasur.parse.preprocess import PreparedPdf, prepare_pdf

# The Markdown converter runs RapidOCR on torch (see build_markdown_converter).
OCR_BACKEND = "torch"


def build_markdown_converter(cfg: Settings, *, force_ocr: bool = False) -> DocumentConverter:
    """
    Converter for arbitrary inputs. PDFs and images go through layout, TableFormer and
    RapidOCR; other formats (docx, pptx, html, xlsx, ...) use Docling's native backends.
    """
    ocr_options = RapidOcrOptions(
        lang=["en"],
        # torch ships with docling; RapidOCR's default onnxruntime is not installed.
        backend=OCR_BACKEND,
        scale=cfg.ocr_scale,
        force_full_page_ocr=force_ocr,
        # The 180° line classifier flips some wide, letter-spaced lines in layout crops and
        # garbles them ("MANAGEMENT AUTHORITY (GCZMA) HELD ON ..." -> "M  O Y (  t").
        use_cls=False,
    )
    pipeline_options = PdfPipelineOptions(
        do_ocr=True,
        do_table_structure=True,
        ocr_options=ocr_options,
        table_structure_options=TableStructureOptions(
            mode=TableFormerMode.ACCURATE,
            do_cell_matching=True,
        ),
    )
    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
            InputFormat.IMAGE: ImageFormatOption(pipeline_options=pipeline_options),
        }
    )


def page_marker(page_no: int) -> str:
    return f"[Page {page_no}]"


def orientation_note(o: Orientation) -> str:
    """
    A note under the page marker. A page turned with confidence gets an HTML comment, so it
    stays out of the rendered text; an uncertain one gets a visible line asking for a check.
    """
    if not o.confident:
        return f"> **Orientation uncertain:** page {o.describe()}. Check it against the PDF."
    return f"<!-- bakasur: page {o.describe()} before OCR -->"


def document_to_markdown(
    doc: DoclingDocument, orientations: Iterable[Orientation] = ()
) -> str:
    """
    Markdown with a page marker ahead of each page's content, numbered as in the source
    file, so text quoted from the Markdown can be checked against the original.
    Formats without pages (docx, html, ...) are exported without markers. Pages that were
    turned upright, or whose orientation is uncertain, get a note under their marker.
    """
    if not doc.pages:
        return doc.export_to_markdown(traverse_pictures=TRAVERSE_PICTURES)
    notes = {o.page_no: orientation_note(o) for o in orientations if o.rotation or not o.confident}
    sections = []
    for page_no in sorted(doc.pages):
        body = doc.export_to_markdown(page_no=page_no, traverse_pictures=TRAVERSE_PICTURES)
        head = page_marker(page_no)
        if page_no in notes:
            head += f"\n\n{notes[page_no]}"
        sections.append(f"{head}\n\n{body}".rstrip())
    return "\n\n---\n\n".join(sections) + "\n"


def _prepare(
    path: Path,
    cfg: Settings,
    tmp_dir: Path,
    page_range: tuple[int, int] | None,
    detector: OrientationDetector | None,
) -> PreparedPdf:
    """Turn sideways image-based pages of a PDF upright; other inputs pass through untouched."""
    if not cfg.fix_orientation or path.suffix.lower() != ".pdf":
        return PreparedPdf(path)
    try:
        scanned = classify_pages(path)
        images = image_pages(path)
    except Exception:
        return PreparedPdf(path)  # not a readable PDF; let Docling report the real error
    first, last = page_range or (1, len(scanned))
    indices = [n - 1 for n in scanned if (scanned[n] or images.get(n)) and first <= n <= last]
    return prepare_pdf(
        path,
        tmp_dir / f"{path.stem}.upright.pdf",
        orient_indices=indices,
        detector=detector or OrientationDetector(OCR_BACKEND),
    )


def convert_file(
    converter: Any,
    path: Path,
    cfg: Settings,
    *,
    page_range: tuple[int, int] | None = None,
    detector: OrientationDetector | None = None,
) -> tuple[str, list[Orientation]]:
    """Markdown for one file, plus what the orientation check found on its scanned pages."""
    with tempfile.TemporaryDirectory(prefix="bakasur-to-md-") as tmp:
        prepared = _prepare(path, cfg, Path(tmp), page_range, detector)
        kwargs: dict[str, Any] = {"page_range": page_range} if page_range else {}
        doc = converter.convert(str(prepared.path), **kwargs).document
    return document_to_markdown(doc, prepared.orientations), prepared.orientations


def convert_to_markdown(
    path: Path,
    cfg: Settings,
    *,
    force_ocr: bool = False,
    page_range: tuple[int, int] | None = None,
) -> str:
    return convert_to_markdown_with_orientation(
        path, cfg, force_ocr=force_ocr, page_range=page_range
    )[0]


def convert_to_markdown_with_orientation(
    path: Path,
    cfg: Settings,
    *,
    force_ocr: bool = False,
    page_range: tuple[int, int] | None = None,
) -> tuple[str, list[Orientation]]:
    converter = build_markdown_converter(cfg, force_ocr=force_ocr)
    return convert_file(converter, path, cfg, page_range=page_range)
