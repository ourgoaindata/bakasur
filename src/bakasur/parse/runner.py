"""Docling full-document parse runner."""

from __future__ import annotations

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
from bakasur.parse.pageinfo import classify_pages, page_count
from bakasur.parse.preprocess import build_preprocessed_pdf


def build_ocr_options(cfg: Settings) -> OcrOptions:
    if cfg.ocr_engine == "ocrmac":
        return OcrMacOptions(lang=["en-US"], scale=cfg.ocr_scale)
    if cfg.ocr_engine == "rapidocr":
        # PaddleOCR (PP-OCR) models run through RapidOCR.
        return RapidOcrOptions(lang=["en"], backend=cfg.rapidocr_backend, scale=cfg.ocr_scale)
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
    pdf_path: Path, cfg: Settings, scanned: dict[int, bool], out_dir: Path
) -> Path:
    """
    Optionally preprocess the scanned pages before conversion; digital pages pass through.
    The preprocessed copy goes in out_dir, never next to the source: the source usually
    sits in the watched inbox, where a new PDF would be picked up as another gazette.
    """
    if not cfg.preprocess_scans:
        return pdf_path
    scanned_indices = [page_no - 1 for page_no, is_scanned in scanned.items() if is_scanned]
    if not scanned_indices:
        return pdf_path
    out = out_dir / f"{pdf_path.stem}.preprocessed.pdf"
    return build_preprocessed_pdf(pdf_path, out, page_indices=scanned_indices)


def parse_gazette_pdf(
    pdf_path: Path,
    cfg: Settings,
) -> tuple[DoclingDocument, dict[str, Any], dict[int, bool]]:
    scanned_map = classify_pages(pdf_path)
    with tempfile.TemporaryDirectory(prefix="bakasur-preprocess-") as tmp:
        input_pdf = resolve_input_pdf(pdf_path, cfg, scanned_map, Path(tmp))
        doc, timings = convert_pdf_batched(input_pdf, cfg)
    return doc, timings, scanned_map
