"""Scan preprocessing only touches scanned pages."""

from pathlib import Path

import pypdfium2 as pdfium

from bakasur.config import Settings
from bakasur.parse import runner
from bakasur.parse.pageinfo import classify_pages, count_page_chars
from bakasur.parse.preprocess import build_preprocessed_pdf
from bakasur.parse.runner import parse_gazette_pdf, resolve_input_pdf

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DIGITAL = FIXTURES / (
    "2026-08-20_SIII-OG21_39A(59)-19th Aug 2026_(two 39As - new + new ndz).pdf"
)
SCANNED = FIXTURES / (
    "2026-08-06_SIII-OG19_39A(57)-5th Aug 2026_(2 nos - new + ndz+ corrigendum).pdf"
)


def _mixed_pdf(path: Path) -> Path:
    """Digital page, scanned page, digital page."""
    out = pdfium.PdfDocument.new()
    digital = pdfium.PdfDocument(str(DIGITAL))
    scanned = pdfium.PdfDocument(str(SCANNED))
    try:
        out.import_pages(digital, [0])
        out.import_pages(scanned, [1])
        out.import_pages(digital, [1])
        out.save(str(path))
    finally:
        out.close()
        digital.close()
        scanned.close()
    return path


def _page_sizes(path: Path) -> list[tuple[float, float]]:
    doc = pdfium.PdfDocument(str(path))
    try:
        return [doc[i].get_size() for i in range(len(doc))]
    finally:
        doc.close()


def test_only_scanned_pages_are_rasterized(tmp_path: Path):
    src = _mixed_pdf(tmp_path / "mixed.pdf")
    assert classify_pages(src) == {1: False, 2: True, 3: False}

    out = resolve_input_pdf(src, Settings(preprocess_scans=True), classify_pages(src), tmp_path)

    assert out != src
    assert _page_sizes(out) == _page_sizes(src)
    # Digital pages keep their text layer verbatim.
    for idx in (0, 2):
        assert count_page_chars(out, idx) == count_page_chars(src, idx) > 50
    assert count_page_chars(out, 1) == 0


def test_rasterized_page_is_binarized(tmp_path: Path):
    src = _mixed_pdf(tmp_path / "mixed.pdf")
    out = build_preprocessed_pdf(src, tmp_path / "out.pdf", page_indices=[1])

    doc = pdfium.PdfDocument(str(out))
    try:
        (image,) = doc[1].get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_IMAGE])
        bitmap = image.get_bitmap().to_pil().convert("L")
    finally:
        doc.close()
    assert bitmap.width > 2000  # 300 DPI, not the source's native resolution
    assert {v for _, v in bitmap.getcolors()} <= {0, 255}


def test_digital_pdf_is_not_preprocessed(tmp_path: Path):
    cfg = Settings(preprocess_scans=True)
    assert resolve_input_pdf(DIGITAL, cfg, classify_pages(DIGITAL), tmp_path) == DIGITAL


def test_preprocessed_pdf_is_not_left_next_to_source(tmp_path: Path, monkeypatch):
    # The inbox watcher would pick a leftover PDF up as a new gazette.
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    src = _mixed_pdf(inbox / "mixed.pdf")
    converted: list[Path] = []

    def fake_convert(pdf_path: Path, cfg: Settings):
        assert pdf_path.exists()
        converted.append(pdf_path)
        return None, {}

    monkeypatch.setattr(runner, "convert_pdf_batched", fake_convert)
    parse_gazette_pdf(src, Settings(preprocess_scans=True))

    assert len(converted) == 1 and converted[0] != src
    assert converted[0].parent != inbox
    assert not converted[0].exists()
    assert list(inbox.iterdir()) == [src]
