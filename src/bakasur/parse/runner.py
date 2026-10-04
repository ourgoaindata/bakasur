"""Docling full-document parse runner."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    OcrMacOptions,
    PdfPipelineOptions,
    TableFormerMode,
    TableStructureOptions,
)
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.settings import settings
from docling_core.types.doc import DoclingDocument

from bakasur.config import Settings
from bakasur.parse.pageinfo import classify_pages, page_count
from bakasur.parse.preprocess import build_preprocessed_pdf


def build_converter(cfg: Settings) -> DocumentConverter:
    ocr_options = OcrMacOptions(lang=["en-US"], scale=cfg.ocr_scale)
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


def resolve_input_pdf(pdf_path: Path, cfg: Settings) -> Path:
    """Optionally preprocess scanned PDFs before conversion."""
    if not cfg.preprocess_scans:
        return pdf_path
    scanned = classify_pages(pdf_path)
    if not any(scanned.values()):
        return pdf_path
    out = pdf_path.parent / f"{pdf_path.stem}.preprocessed.pdf"
    return build_preprocessed_pdf(pdf_path, out)


def parse_gazette_pdf(
    pdf_path: Path,
    cfg: Settings,
) -> tuple[DoclingDocument, dict[str, Any], dict[int, bool]]:
    input_pdf = resolve_input_pdf(pdf_path, cfg)
    doc, timings = convert_pdf_batched(input_pdf, cfg)
    scanned_map = classify_pages(pdf_path)
    return doc, timings, scanned_map
