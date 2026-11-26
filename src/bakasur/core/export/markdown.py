"""Convert any Docling-supported file to Markdown with source page markers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docling_core.types.doc import DoclingDocument

from bakasur.core.config import CoreSettings
from bakasur.core.convert import (
    IndicReader,
    Orientation,
    OrientationDetector,
    PageScript,
    build_converter,
    build_indic_reader,
    convert,
)
from bakasur.core.export.pagesplit import split_across_pages

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


def script_note(s: PageScript) -> str:
    """
    A note under the page marker. A clean IndicOCR read gets an HTML comment; anything a
    person should check (garbled source, unknown script, not read) gets a visible line.
    """
    if s.status == "indic_ocr":
        return f"<!-- bakasur: {s.describe()} ({s.devanagari_words} words found) -->"
    label = {
        "garbled_source": "Garbled Devanagari",
        "unrecognised": "Unrecognised script",
        "not_read": "Devanagari not read",
    }[s.status]
    return f"> **{label}:** page {s.page_no} has {s.describe()}. Check it against the PDF."


def document_to_markdown(
    doc: DoclingDocument,
    orientations: Iterable[Orientation] = (),
    scripts: Iterable[PageScript] = (),
) -> str:
    """
    Markdown with a page marker ahead of each page's content, numbered as in the source
    file, so text quoted from the Markdown can be checked against the original.
    Formats without pages (docx, html, ...) are exported without markers. Pages that were
    turned upright, or whose orientation is uncertain, get a note under their marker, as do
    pages carrying Devanagari. A page IndicOCR read takes its text from that read instead
    of Docling's, which has the Devanagari blank or as junk letters. A paragraph that runs
    across a page break is cut there, so each part sits under its page.
    """
    if not doc.pages:
        return doc.export_to_markdown(traverse_pictures=TRAVERSE_PICTURES)
    doc = split_across_pages(doc)
    notes: dict[int, list[str]] = {}
    for o in orientations:
        if o.rotation or not o.confident:
            notes.setdefault(o.page_no, []).append(orientation_note(o))
    replaced = {}
    for s in scripts:
        notes.setdefault(s.page_no, []).append(script_note(s))
        if s.markdown and s.status in ("indic_ocr", "garbled_source"):
            replaced[s.page_no] = s.markdown
    sections = []
    for page_no in sorted(doc.pages):
        body = replaced.get(page_no) or doc.export_to_markdown(
            page_no=page_no, traverse_pictures=TRAVERSE_PICTURES
        )
        head = "\n\n".join([page_marker(page_no), *notes.get(page_no, [])])
        sections.append(f"{head}\n\n{body}".rstrip())
    return "\n\n---\n\n".join(sections) + "\n"


@dataclass
class MarkdownResult:
    """A file's Markdown, and what the checks found on its pages."""

    markdown: str
    orientations: list[Orientation] = field(default_factory=list)
    scripts: list[PageScript] = field(default_factory=list)

    def meta(self) -> dict[str, Any]:
        """Per-page findings worth keeping next to the Markdown."""
        turned = [o for o in self.orientations if o.rotation or not o.confident]
        return {
            "orientations": [o.to_dict() for o in turned],
            "scripts": [s.to_dict() for s in self.scripts],
        }


def convert_file(
    converter: Any,
    path: Path,
    cfg: CoreSettings,
    *,
    page_range: tuple[int, int] | None = None,
    detector: OrientationDetector | None = None,
    indic_reader: IndicReader | None = None,
) -> MarkdownResult:
    """Markdown for one file, plus what the orientation and script checks found."""
    converted = convert(
        path,
        cfg,
        converter=converter,
        page_range=page_range,
        detector=detector,
        check_scripts=True,
        indic_reader=indic_reader,
    )
    markdown = document_to_markdown(converted.document, converted.orientations, converted.scripts)
    return MarkdownResult(markdown, converted.orientations, converted.scripts)


def convert_to_markdown(
    path: Path,
    cfg: CoreSettings,
    *,
    force_ocr: bool = False,
    page_range: tuple[int, int] | None = None,
) -> str:
    result = convert_to_markdown_result(path, cfg, force_ocr=force_ocr, page_range=page_range)
    return result.markdown


def convert_to_markdown_result(
    path: Path,
    cfg: CoreSettings,
    *,
    force_ocr: bool = False,
    page_range: tuple[int, int] | None = None,
) -> MarkdownResult:
    converter = build_converter(cfg, force_ocr=force_ocr)
    return convert_file(
        converter, path, cfg, page_range=page_range, indic_reader=build_indic_reader(cfg)
    )
