"""
The one Docling converter, and the conversion entry point every use case goes through.

``convert`` prepares a PDF (turns sideways scanned pages upright, optionally binarizes
scans), runs Docling on it and returns the document with what the preparation found.
Other inputs Docling reads (images, docx, pptx, html, xlsx, ...) are converted as they are.
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    OcrMacOptions,
    OcrMode,
    OcrOptions,
    PdfPipelineOptions,
    RapidOcrOptions,
    TableFormerMode,
    TableStructureOptions,
)
from docling.datamodel.settings import settings
from docling.document_converter import DocumentConverter, ImageFormatOption, PdfFormatOption
from docling_core.types.doc import DoclingDocument

from bakasur.core.config import CoreSettings
from bakasur.core.convert.indic import RENDER_DPI as INDIC_DPI
from bakasur.core.convert.indic import IndicReader
from bakasur.core.convert.orientation import Orientation, OrientationDetector
from bakasur.core.convert.pageinfo import classify_pages, image_pages
from bakasur.core.convert.preprocess import PreparedPdf, prepare_pdf
from bakasur.core.convert.script import (
    PageScript,
    find_devanagari_pages,
    judge,
    pages_with_images,
    render_page,
)

logger = logging.getLogger(__name__)


def build_ocr_options(cfg: CoreSettings, *, force_ocr: bool = False) -> OcrOptions:
    # Full-page OCR ignores any embedded text layer; the default OCRs only image regions.
    mode = {"mode": OcrMode.FULL_PAGE} if force_ocr else {}
    if cfg.ocr_engine == "ocrmac":
        return OcrMacOptions(lang=["en-US"], scale=cfg.ocr_scale, **mode)
    if cfg.ocr_engine == "rapidocr":
        # PaddleOCR (PP-OCR) models run through RapidOCR. The 180° line classifier is off: it
        # flips wide, letter-spaced lines in Docling's crops, read "10/1" as "101" and garbled
        # "MANAGEMENT AUTHORITY (GCZMA) HELD ON ..." into "M  O Y (  t".
        return RapidOcrOptions(
            lang=["en"],
            backend=cfg.rapidocr_backend,
            scale=cfg.ocr_scale,
            use_cls=False,
            **mode,
        )
    raise ValueError(f"Unknown ocr_engine {cfg.ocr_engine!r}; expected 'ocrmac' or 'rapidocr'")


def build_converter(
    cfg: CoreSettings, *, force_ocr: bool = False, page_images: bool = False
) -> DocumentConverter:
    """
    PDFs and images go through layout, TableFormer (accurate mode) and OCR; other formats
    use Docling's native backends. ``force_ocr`` ignores any embedded text layer;
    ``page_images`` keeps a rendered image of each page in the document.
    """
    pipeline_options = PdfPipelineOptions(
        do_ocr=True,
        do_table_structure=True,
        ocr_options=build_ocr_options(cfg, force_ocr=force_ocr),
        table_structure_options=TableStructureOptions(
            mode=TableFormerMode.ACCURATE,
            do_cell_matching=True,
        ),
        generate_page_images=page_images,
    )
    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
            InputFormat.IMAGE: ImageFormatOption(pipeline_options=pipeline_options),
        }
    )


@dataclass
class Converted:
    """A converted document, and what was found while preparing it."""

    document: DoclingDocument
    timings: dict[str, Any] = field(default_factory=dict)
    # page_no -> whether the page has no text layer (PDFs only)
    scanned: dict[int, bool] = field(default_factory=dict)
    # One entry per image-based page that was checked (PDFs only)
    orientations: list[Orientation] = field(default_factory=list)
    # One entry per page found to carry Devanagari (PDFs only)
    scripts: list[PageScript] = field(default_factory=list)

    @property
    def uncertain(self) -> list[Orientation]:
        return [o for o in self.orientations if not o.confident]


def prepare_input(
    path: Path,
    cfg: CoreSettings,
    out_dir: Path,
    *,
    scanned: dict[int, bool] | None = None,
    page_range: tuple[int, int] | None = None,
    detector: OrientationDetector | None = None,
) -> PreparedPdf:
    """
    Turn sideways image-based pages of a PDF upright (``cfg.fix_orientation``) and binarize
    scanned pages (``cfg.preprocess_scans``); digital pages and non-PDF inputs pass through.
    Orientation is checked on every image-based page, including scans with an embedded text
    layer, which ``classify_pages`` counts as digital. Any corrected copy goes in
    ``out_dir``, never next to the source: the source may sit in a watched inbox, where a
    new PDF would be picked up as another document.
    """
    if path.suffix.lower() != ".pdf" or not (cfg.fix_orientation or cfg.preprocess_scans):
        return PreparedPdf(path)
    try:
        scanned = classify_pages(path) if scanned is None else scanned
        images = image_pages(path) if cfg.fix_orientation else {}
    except Exception:
        return PreparedPdf(path)  # not a readable PDF; let Docling report the real error
    first, last = page_range or (1, max(scanned, default=0))
    in_range = [n for n in sorted(scanned) if first <= n <= last]
    orient = [n - 1 for n in in_range if scanned[n] or images.get(n)] if cfg.fix_orientation else []
    binarize = [n - 1 for n in in_range if scanned[n]] if cfg.preprocess_scans else []
    return prepare_pdf(
        path,
        out_dir / f"{path.stem}.preprocessed.pdf",
        binarize_indices=binarize,
        orient_indices=orient,
        detector=detector or OrientationDetector(cfg.rapidocr_backend),
    )


def build_indic_reader(cfg: CoreSettings) -> IndicReader | None:
    """The Indic reader the settings ask for; it loads its model on first use."""
    if not (cfg.detect_scripts and cfg.indic_ocr):
        return None
    return IndicReader(cfg.indic_ocr_path, cfg.indic_ocr_device)


def read_scripts(
    path: Path,
    cfg: CoreSettings,
    *,
    page_range: tuple[int, int] | None = None,
    reader: IndicReader | None = None,
) -> list[PageScript]:
    """
    Find the pages of a PDF that carry Devanagari and read each with ``reader``. Pass the
    prepared (upright) PDF: the shape check needs the lines horizontal. A page the reader
    fails on, or every page when there is no reader, is kept as ``not_read`` so it is still
    flagged; Docling's text stays in place for those.
    """
    if not cfg.detect_scripts or path.suffix.lower() != ".pdf":
        return []
    try:
        pages = pages_with_images(path)
        if page_range:
            pages = {n for n in pages if page_range[0] <= n <= page_range[1]}
        found = find_devanagari_pages(path, pages)
    except Exception:
        return []  # not a readable PDF; Docling reports the real error
    scripts = []
    for page_no, words in found.items():
        if reader is None:
            scripts.append(PageScript(page_no, words, "not_read", error="IndicOCR is off"))
            continue
        try:
            markdown = reader.read(render_page(path, page_no, INDIC_DPI))
        except Exception as exc:
            logger.warning("%s page %d: IndicOCR failed: %s", path.name, page_no, exc)
            error = f"{type(exc).__name__}: {exc}"
            scripts.append(PageScript(page_no, words, "not_read", error=error))
            continue
        scripts.append(PageScript(page_no, words, judge(markdown), markdown))
    return scripts


def _scanned_pages(path: Path) -> dict[int, bool]:
    if path.suffix.lower() != ".pdf":
        return {}
    try:
        return classify_pages(path)
    except Exception:
        return {}


def convert(
    path: Path,
    cfg: CoreSettings,
    *,
    converter: Any = None,
    page_range: tuple[int, int] | None = None,
    detector: OrientationDetector | None = None,
    force_ocr: bool = False,
    page_images: bool = False,
    check_scripts: bool = False,
    indic_reader: IndicReader | None = None,
) -> Converted:
    """
    Prepare and convert one file. Pass ``converter`` (and ``detector``) to reuse models
    across files; otherwise a converter is built from ``force_ocr`` and ``page_images``.
    ``check_scripts`` looks for Devanagari on image pages (``cfg.detect_scripts`` must
    also be on) and reads those pages with ``indic_reader`` if one is given.
    A whole PDF is converted in one Docling pass: concatenating page-range batches would
    renumber pages from 1, breaking page provenance.
    """
    settings.debug.profile_pipeline_timings = cfg.profile_timings
    converter = converter or build_converter(cfg, force_ocr=force_ocr, page_images=page_images)
    scanned = _scanned_pages(path)
    with tempfile.TemporaryDirectory(prefix="bakasur-convert-") as tmp:
        prepared = prepare_input(
            path, cfg, Path(tmp), scanned=scanned, page_range=page_range, detector=detector
        )
        kwargs: dict[str, Any] = {"page_range": page_range} if page_range else {}
        result = converter.convert(str(prepared.path), **kwargs)
        scripts = (
            read_scripts(prepared.path, cfg, page_range=page_range, reader=indic_reader)
            if check_scripts
            else []
        )
    timings = {
        stage: {"count": item.count, "total_s": item.total(), "avg_s": item.avg()}
        for stage, item in (getattr(result, "timings", None) or {}).items()
    }
    out = Converted(result.document, timings, scanned, prepared.orientations, scripts)
    for o in out.uncertain:
        logger.warning("%s page %d: %s", path.name, o.page_no, o.describe())
    for sc in scripts:
        if sc.status != "indic_ocr":
            logger.warning("%s page %d: %s", path.name, sc.page_no, sc.describe())
    return out
