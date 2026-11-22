"""One Docling converter and one entry point serve every use case."""

from pathlib import Path

import pypdfium2 as pdfium
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import OcrMacOptions, OcrMode, RapidOcrOptions

from bakasur.config import Settings
from bakasur.core.convert import build_converter, build_ocr_options, convert, prepare_input

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DIGITAL = FIXTURES / (
    "2026-08-20_SIII-OG21_39A(59)-19th Aug 2026_(two 39As - new + new ndz).pdf"
)
SCANNED = FIXTURES / (
    "2026-08-06_SIII-OG19_39A(57)-5th Aug 2026_(2 nos - new + ndz+ corrigendum).pdf"
)


def test_default_engine_is_rapidocr_without_line_classifier():
    opts = build_ocr_options(Settings())
    assert isinstance(opts, RapidOcrOptions)
    assert opts.use_cls is False


def test_ocrmac_is_still_selectable():
    assert isinstance(build_ocr_options(Settings(ocr_engine="ocrmac")), OcrMacOptions)


def test_converter_options():
    plain = build_converter(Settings())
    tuned = build_converter(Settings(), force_ocr=True, page_images=True)
    for fmt in (InputFormat.PDF, InputFormat.IMAGE):
        assert plain.format_to_options[fmt].pipeline_options.generate_page_images is False
        assert plain.format_to_options[fmt].pipeline_options.ocr_options.mode != OcrMode.FULL_PAGE
        assert tuned.format_to_options[fmt].pipeline_options.generate_page_images is True
        assert tuned.format_to_options[fmt].pipeline_options.ocr_options.mode == OcrMode.FULL_PAGE


class _RecordingConverter:
    def __init__(self):
        self.calls: list[tuple[Path, dict]] = []

    def convert(self, path: str, **kwargs):
        self.calls.append((Path(path), kwargs))
        return type("R", (), {"document": "doc"})()


def test_non_pdf_input_is_converted_as_is(tmp_path: Path):
    src = tmp_path / "notes.docx"
    src.write_bytes(b"not really a docx")
    converter = _RecordingConverter()
    out = convert(src, Settings(preprocess_scans=True), converter=converter)
    assert converter.calls == [(src, {})]
    assert (out.document, out.scanned, out.orientations) == ("doc", {}, [])


def test_page_range_is_passed_to_docling(tmp_path: Path):
    converter = _RecordingConverter()
    out = convert(DIGITAL, Settings(), converter=converter, page_range=(2, 3))
    assert converter.calls == [(DIGITAL, {"page_range": (2, 3)})]
    assert out.scanned and not any(out.scanned.values())


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


def test_only_pages_in_the_page_range_are_prepared(tmp_path: Path):
    src = _mixed_pdf(tmp_path / "mixed.pdf")
    cfg = Settings(preprocess_scans=True, fix_orientation=False)
    assert prepare_input(src, cfg, tmp_path, page_range=(1, 1)).path == src
    assert prepare_input(src, cfg, tmp_path, page_range=(2, 3)).path != src
