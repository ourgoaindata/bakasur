"""Any-file to Markdown conversion keeps source page numbers."""

from pathlib import Path

import pytest
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import RapidOcrOptions
from docling_core.types.doc import (
    BoundingBox,
    DocItemLabel,
    DoclingDocument,
    ProvenanceItem,
    Size,
)
from typer.testing import CliRunner

from bakasur.cli import app
from bakasur.config import Settings
from bakasur.parse.markdown import (
    build_markdown_converter,
    convert_to_markdown,
    document_to_markdown,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SCANNED = FIXTURES / (
    "2026-08-06_SIII-OG19_39A(57)-5th Aug 2026_(2 nos - new + ndz+ corrigendum).pdf"
)


def _doc(pages: dict[int, list[str]]) -> DoclingDocument:
    doc = DoclingDocument(name="t")
    for page_no, texts in pages.items():
        doc.add_page(page_no=page_no, size=Size(width=100, height=100))
        for text in texts:
            prov = ProvenanceItem(
                page_no=page_no,
                bbox=BoundingBox(l=0, t=0, r=10, b=10),
                charspan=(0, len(text)),
            )
            doc.add_text(label=DocItemLabel.TEXT, text=text, prov=prov)
    return doc


def test_each_page_is_marked_with_its_source_page_number():
    # A page range keeps the original numbering, so markers must not restart at 1.
    md = document_to_markdown(_doc({7: ["alpha"], 5: ["beta", "gamma"]}))
    assert md == "[Page 5]\n\nbeta\n\ngamma\n\n---\n\n[Page 7]\n\nalpha\n"


def test_empty_page_still_gets_a_marker():
    md = document_to_markdown(_doc({1: ["alpha"], 2: [], 3: ["beta"]}))
    assert "[Page 2]" in md
    assert md.index("[Page 1]") < md.index("alpha") < md.index("[Page 2]") < md.index("[Page 3]")


def test_document_without_pages_has_no_markers():
    doc = DoclingDocument(name="t")
    doc.add_text(label=DocItemLabel.TEXT, text="alpha")
    assert document_to_markdown(doc).strip() == "alpha"


def test_converter_ocrs_pdfs_and_images_with_rapidocr():
    converter = build_markdown_converter(Settings())
    for fmt in (InputFormat.PDF, InputFormat.IMAGE):
        ocr = converter.format_to_options[fmt].pipeline_options.ocr_options
        assert isinstance(ocr, RapidOcrOptions)
        assert ocr.use_cls is False


def test_to_md_refuses_to_overwrite_markdown_input(tmp_path: Path):
    src = tmp_path / "notes.md"
    src.write_text("# keep me\n")
    result = CliRunner().invoke(app, ["to-md", str(src)])
    assert result.exit_code != 0
    assert src.read_text() == "# keep me\n"


@pytest.mark.slow
def test_scanned_page_range_keeps_page_numbers():
    md = convert_to_markdown(SCANNED, Settings(), page_range=(5, 6))
    assert "[Page 1]" not in md
    assert md.index("[Page 5]") < md.index("[Page 6]")
    assert "No Development Zone" in md or "39A" in md
