"""Docling full-document parse runner."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    OcrMacOptions,
    OcrOptions,
    PdfPipelineOptions,
    RapidOcrOptions,
    TableFormerMode,
    TableStructureOptions,
)
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.settings import settings
from docling_core.types.doc import DoclingDocument

from bakasur.config import Settings
from bakasur.parse.pageinfo import classify_pages, image_pages, page_count
from bakasur.parse.orientation import Orientation, OrientationDetector
from bakasur.parse.preprocess import PreparedPdf, prepare_pdf

logger = logging.getLogger(__name__)


def build_ocr_options(cfg: Settings) -> OcrOptions:
    if cfg.ocr_engine == "ocrmac":
        return OcrMacOptions(lang=["en-US"], scale=cfg.ocr_scale)
    if cfg.ocr_engine == "rapidocr":
        # PaddleOCR (PP-OCR) models run through RapidOCR. The 180° line classifier is off: it
        # flips wide, letter-spaced lines in Docling's crops, and read "10/1" as "101".
        return RapidOcrOptions(
            lang=["en"], backend=cfg.rapidocr_backend, scale=cfg.ocr_scale, use_cls=False
        )
    raise ValueError(f"Unknown ocr_engine {cfg.ocr_engine!r}; expected 'ocrmac' or 'rapidocr'")


def build_converter(cfg: Settings) -> DocumentConverter:
    ocr_options = build_ocr_options(cfg)
    pipeline_options = PdfPipelineOptions(
        do_ocr=True,
        do_table_structure=True,
        ocr_options=ocr_options,
        table_structure_options=TableStructureOptions(
            mode=TableFormerMode.ACCURATE,
            do_cell_matching=True,
        ),
        generate_page_images=True,
    )
    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
        }
    )


def _enable_profiling(enabled: bool) -> None:
    settings.debug.profile_pipeline_timings = enabled


def convert_pdf(
    pdf_path: Path,
    cfg: Settings,
    *,
    page_range: tuple[int, int] | None = None,
) -> tuple[DoclingDocument, dict[str, Any]]:
    """Convert a PDF (or page range) with Docling."""
    _enable_profiling(cfg.profile_timings)
    converter = build_converter(cfg)
    kwargs: dict[str, Any] = {}
    if page_range:
        kwargs["page_range"] = page_range
    result = converter.convert(str(pdf_path), **kwargs)
    timings = {
        stage: {"count": item.count, "total_s": item.total(), "avg_s": item.avg()}
        for stage, item in (result.timings or {}).items()
    }
    return result.document, timings


def convert_pdf_batched(
    pdf_path: Path,
    cfg: Settings,
) -> tuple[DoclingDocument, dict[str, Any]]:
    """
    Convert the full PDF in one Docling pass.

    DoclingDocument.concatenate() renumbers pages from 1..n, which breaks
    table provenance for page-range batches. A single full-document conversion
    keeps original page numbers intact for anchor search and table stitching.
    """
    return convert_pdf(pdf_path, cfg)


def resolve_input_pdf(
    pdf_path: Path,
    cfg: Settings,
    scanned: dict[int, bool],
    out_dir: Path,
    detector: OrientationDetector | None = None,
) -> PreparedPdf:
    """
    Turn sideways scanned pages upright and optionally binarize them before conversion;
    digital pages pass through. Orientation is checked on every image-based page, including
    scans with an embedded text layer; binarization only touches pages without text. Any corrected copy goes in out_dir, never next to the
    source: the source usually sits in the watched inbox, where a new PDF would be picked
    up as another gazette.
    """
    scanned_indices = [page_no - 1 for page_no, is_scanned in scanned.items() if is_scanned]
    orient_indices: list[int] = []
    if cfg.fix_orientation:
        # Scans with an embedded text layer are not "scanned" by character count.
        images = image_pages(pdf_path)
        orient_indices = [n - 1 for n in scanned if scanned[n] or images.get(n)]
    return prepare_pdf(
        pdf_path,
        out_dir / f"{pdf_path.stem}.preprocessed.pdf",
        binarize_indices=scanned_indices if cfg.preprocess_scans else [],
        orient_indices=orient_indices,
        detector=detector or OrientationDetector(cfg.rapidocr_backend),
    )


def parse_gazette_pdf(
    pdf_path: Path,
    cfg: Settings,
) -> tuple[DoclingDocument, dict[str, Any], dict[int, bool], list[Orientation]]:
    """Returns the document, timings, page -> is_scanned, and each scanned page's orientation."""
    scanned_map = classify_pages(pdf_path)
    with tempfile.TemporaryDirectory(prefix="bakasur-preprocess-") as tmp:
        prepared = resolve_input_pdf(pdf_path, cfg, scanned_map, Path(tmp))
        doc, timings = convert_pdf_batched(prepared.path, cfg)
    for o in prepared.uncertain:
        logger.warning("%s page %d: %s", pdf_path.name, o.page_no, o.describe())
    return doc, timings, scanned_map, prepared.orientations
