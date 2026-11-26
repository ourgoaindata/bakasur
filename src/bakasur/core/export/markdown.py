"""Convert any Docling-supported file to Markdown with source page markers."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from docling_core.types.doc import DoclingDocument

from bakasur.core.config import CoreSettings
from bakasur.core.convert import Orientation, OrientationDetector, build_converter, convert

# Include text OCR'd inside pictures; scanned pages are one big picture.
TRAVERSE_PICTURES = True


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


def convert_file(
    converter: Any,
    path: Path,
    cfg: CoreSettings,
    *,
    page_range: tuple[int, int] | None = None,
    detector: OrientationDetector | None = None,
) -> tuple[str, list[Orientation]]:
    """Markdown for one file, plus what the orientation check found on its scanned pages."""
    converted = convert(path, cfg, converter=converter, page_range=page_range, detector=detector)
    return document_to_markdown(converted.document, converted.orientations), converted.orientations


def convert_to_markdown(
    path: Path,
    cfg: CoreSettings,
    *,
    force_ocr: bool = False,
    page_range: tuple[int, int] | None = None,
) -> str:
    return convert_to_markdown_with_orientation(
        path, cfg, force_ocr=force_ocr, page_range=page_range
    )[0]


def convert_to_markdown_with_orientation(
    path: Path,
    cfg: CoreSettings,
    *,
    force_ocr: bool = False,
    page_range: tuple[int, int] | None = None,
) -> tuple[str, list[Orientation]]:
    converter = build_converter(cfg, force_ocr=force_ocr)
    return convert_file(converter, path, cfg, page_range=page_range)
