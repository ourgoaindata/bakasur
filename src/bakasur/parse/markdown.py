"""Convert any Docling-supported file to Markdown, OCRing with RapidOCR."""

from __future__ import annotations

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


def build_markdown_converter(cfg: Settings, *, force_ocr: bool = False) -> DocumentConverter:
    """
    Converter for arbitrary inputs. PDFs and images go through layout, TableFormer and
    RapidOCR; other formats (docx, pptx, html, xlsx, ...) use Docling's native backends.
    """
    ocr_options = RapidOcrOptions(
        lang=["en"],
        # torch ships with docling; RapidOCR's default onnxruntime is not installed.
        backend="torch",
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


def document_to_markdown(doc: DoclingDocument) -> str:
    """
    Markdown with a page marker ahead of each page's content, numbered as in the source
    file, so text quoted from the Markdown can be checked against the original.
    Formats without pages (docx, html, ...) are exported without markers.
    """
    if not doc.pages:
        return doc.export_to_markdown(traverse_pictures=TRAVERSE_PICTURES)
    sections = []
    for page_no in sorted(doc.pages):
        body = doc.export_to_markdown(page_no=page_no, traverse_pictures=TRAVERSE_PICTURES)
        sections.append(f"{page_marker(page_no)}\n\n{body}".rstrip())
    return "\n\n---\n\n".join(sections) + "\n"


def convert_to_markdown(
    path: Path,
    cfg: Settings,
    *,
    force_ocr: bool = False,
    page_range: tuple[int, int] | None = None,
) -> str:
    converter = build_markdown_converter(cfg, force_ocr=force_ocr)
    kwargs: dict[str, Any] = {}
    if page_range:
        kwargs["page_range"] = page_range
    result = converter.convert(str(path), **kwargs)
    return document_to_markdown(result.document)
