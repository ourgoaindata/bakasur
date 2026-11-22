"""Sideways and upside-down scanned pages are detected and turned upright before OCR."""

import ctypes
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pypdfium2 as pdfium
import pytest
from PIL import Image

from bakasur.config import Settings
from bakasur.parse.markdown import BatchResult, document_to_markdown
from bakasur.core.convert.orientation import REC_DPI, Orientation, OrientationDetector
from bakasur.core.convert.pageinfo import classify_pages, count_page_chars, image_pages
from bakasur.core.convert import prepare_input
from bakasur.core.convert.preprocess import prepare_pdf

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SCANNED = FIXTURES / (
    "2026-08-06_SIII-OG19_39A(57)-5th Aug 2026_(2 nos - new + ndz+ corrigendum).pdf"
)
DIGITAL = FIXTURES / (
    "2026-08-20_SIII-OG21_39A(59)-19th Aug 2026_(two 39As - new + new ndz).pdf"
)


# --- decision logic, with a stand-in for RapidOCR ---------------------------------------


class _FakeEngine:
    """Returns the given line boxes from detection, and a fixed read score per crop angle."""

    def __init__(self, boxes: list[tuple[float, float]], read: dict[str, float]):
        # boxes as (width, height), laid out down the page
        self.boxes = [
            [[10, 10 + 40 * i], [10 + w, 10 + 40 * i], [10 + w, 10 + 40 * i + h], [10, 10 + 40 * i + h]]
            for i, (w, h) in enumerate(boxes)
        ]
        self.read = read

    def __call__(self, img, use_det=True, use_cls=False, use_rec=True):
        if use_det:
            return SimpleNamespace(boxes=self.boxes)
        h, w = img.shape[:2]
        # Crops come in rotated; a crop is "readable" if its shape matches what `read` says.
        key = "wide" if w >= h else "tall"
        return SimpleNamespace(txts=["text"], scores=[self.read.get(key, 0.0)])


def _detector(engine) -> OrientationDetector:
    detector = OrientationDetector()
    detector._engine = engine
    return detector


def _detect(boxes, read=None) -> Orientation:
    # The fake engine works in detection coordinates; detect_image scales boxes up by
    # REC_DPI / DET_DPI, so the canvas only needs to be big enough to crop from.
    image = Image.new("L", (2000, 4000), 255)
    return _detector(_FakeEngine(boxes, read or {})).detect_image(image)


def test_page_with_too_little_text_is_left_alone():
    o = _detect([(80, 10)] * 3)
    assert (o.rotation, o.confident) == (0, True)
    assert "too little text" in o.reason


def test_square_boxes_do_not_count_as_lines():
    # Single characters and stamps are near-square and say nothing about direction.
    o = _detect([(12, 12)] * 30)
    assert "too little text" in o.reason


def test_mixed_line_directions_are_uncertain_and_left_alone():
    o = _detect([(80, 10)] * 10 + [(10, 80)] * 10)
    assert (o.rotation, o.confident) == (0, False)
    assert o.reason == "mixed line directions"


def test_sideways_page_with_unclear_direction_still_gets_the_better_guess():
    # Both directions read alike: a page known to be sideways is never left sideways.
    o = _detect([(10, 80)] * 10, read={"wide": 0.9})
    assert o.rotation in (90, 270)
    assert o.confident is False
    assert "direction is unclear" in o.reason


def test_uncertain_page_is_described_as_needing_a_check():
    o = Orientation(12, 0, False, "mixed line directions")
    assert "check by hand" in o.describe()
    assert "check by hand" not in Orientation(38, 90, True, "lines run vertically").describe()


# --- the real models, on a scanned fixture page turned each way --------------------------


@pytest.fixture(scope="module")
def upright_page() -> Image.Image:
    doc = pdfium.PdfDocument(str(SCANNED))
    try:
        return doc[1].render(scale=REC_DPI / 72.0).to_pil().convert("L")
    finally:
        doc.close()


@pytest.fixture(scope="module")
def detector() -> OrientationDetector:
    return OrientationDetector()


@pytest.mark.parametrize(
    "turned_ccw, expected",
    [(0, 0), (270, 90), (90, 270), (180, 180)],
    ids=["upright", "content-turned-clockwise", "content-turned-anticlockwise", "upside-down"],
)
def test_real_page_orientation_is_detected(upright_page, detector, turned_ccw, expected):
    page = upright_page.rotate(turned_ccw, expand=True) if turned_ccw else upright_page
    o = detector.detect_image(page)
    assert o.rotation == expected
    assert o.confident, o


def test_blank_page_is_not_flagged(detector):
    o = detector.detect_image(Image.new("L", (1275, 1650), 255))
    assert (o.rotation, o.confident) == (0, True)


# --- applying the result to the PDF ------------------------------------------------------


class _FixedDetector:
    """Reports the given rotation for every page."""

    def __init__(self, rotation: int, confident: bool = True):
        self.rotation, self.confident = rotation, confident

    def detect_page(self, page, page_no):
        return Orientation(page_no, self.rotation, self.confident, "test")


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


def _sizes(path: Path) -> list[tuple[float, float]]:
    doc = pdfium.PdfDocument(str(path))
    try:
        return [doc[i].get_size() for i in range(len(doc))]
    finally:
        doc.close()


def test_sideways_scanned_page_is_rewritten_upright(tmp_path: Path):
    src = _mixed_pdf(tmp_path / "mixed.pdf")
    cfg = Settings(fix_orientation=True)
    prepared = prepare_input(
        src, cfg, tmp_path, scanned=classify_pages(src), detector=_FixedDetector(90)
    )

    assert prepared.path != src
    assert [o.page_no for o in prepared.rotated] == [2]  # only the scanned page is checked
    (w0, h0), (w1, h1), (w2, h2) = _sizes(src)
    assert _sizes(prepared.path) == [(w0, h0), (h1, w1), (w2, h2)]
    for idx in (0, 2):  # digital pages keep their text layer
        assert count_page_chars(prepared.path, idx) == count_page_chars(src, idx) > 50


def test_upright_scans_are_not_copied(tmp_path: Path):
    src = _mixed_pdf(tmp_path / "mixed.pdf")
    prepared = prepare_input(
        src, Settings(), tmp_path, scanned=classify_pages(src), detector=_FixedDetector(0)
    )
    assert prepared.path == src
    assert len(prepared.orientations) == 1
    assert list(tmp_path.iterdir()) == [src]


def test_orientation_check_can_be_turned_off(tmp_path: Path):
    src = _mixed_pdf(tmp_path / "mixed.pdf")
    cfg = Settings(fix_orientation=False)
    prepared = prepare_input(
        src, cfg, tmp_path, scanned=classify_pages(src), detector=_FixedDetector(90)
    )
    assert prepared.path == src and prepared.orientations == []


def test_uncertain_pages_are_reported(tmp_path: Path):
    src = _mixed_pdf(tmp_path / "mixed.pdf")
    prepared = prepare_pdf(
        src, tmp_path / "out.pdf", orient_indices=[1], detector=_FixedDetector(0, confident=False)
    )
    assert [o.page_no for o in prepared.uncertain] == [2]


# --- reporting ---------------------------------------------------------------------------


def _doc(pages):
    from docling_core.types.doc import (
        BoundingBox, DocItemLabel, DoclingDocument, ProvenanceItem, Size,
    )

    doc = DoclingDocument(name="t")
    for page_no, text in pages.items():
        doc.add_page(page_no=page_no, size=Size(width=100, height=100))
        prov = ProvenanceItem(
            page_no=page_no, bbox=BoundingBox(l=0, t=0, r=10, b=10), charspan=(0, len(text))
        )
        doc.add_text(label=DocItemLabel.TEXT, text=text, prov=prov)
    return doc


def test_markdown_notes_rotated_and_uncertain_pages():
    orientations = [
        Orientation(1, 0, True, "lines run horizontally"),
        Orientation(2, 90, True, "lines run vertically"),
        Orientation(3, 0, False, "mixed line directions"),
    ]
    md = document_to_markdown(_doc({1: "a", 2: "b", 3: "c"}), orientations)
    page1, page2, page3 = md.split("\n\n---\n\n")
    assert page1 == "[Page 1]\n\na"  # nothing to say about an upright page
    assert page2.startswith("[Page 2]\n\n<!-- bakasur: page rotated 90°")
    assert page3.startswith("[Page 3]\n\n> **Orientation uncertain:**")


def test_batch_log_summarises_orientation():
    result = BatchResult(
        Path("x.pdf"),
        "converted",
        orientations=[
            Orientation(38, 90, True, "r"),
            Orientation(12, 0, False, "r"),
            Orientation(1, 0, True, "r"),
        ],
    )
    assert result.orientation_summary() == "rotated p38; orientation uncertain p12"
    assert BatchResult(Path("y.pdf"), "converted").orientation_summary() == ""


def _add_text_layer(src: Path, out: Path, page_index: int, text: str) -> Path:
    """Put invisible-to-us text on a page, like the OCR layer a scanner adds."""
    data = (text + "\0").encode("utf-16-le")
    wide = ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_ushort))
    doc = pdfium.PdfDocument(str(src))
    try:
        page = doc[page_index]
        obj = pdfium.raw.FPDFPageObj_NewTextObj(doc.raw, b"Helvetica", 12.0)
        pdfium.raw.FPDFText_SetText(obj, wide)
        pdfium.raw.FPDFPage_InsertObject(page.raw, obj)
        page.gen_content()
        doc.save(str(out))
    finally:
        doc.close()
    return out


def test_scan_with_embedded_text_layer_is_still_checked(tmp_path: Path):
    # GCZMA minutes are scans carrying a (poor) OCR text layer: plenty of characters, so
    # classify_pages calls them digital, but each page is one full-page image.
    src = _mixed_pdf(tmp_path / "mixed.pdf")
    layered = _add_text_layer(src, tmp_path / "layered.pdf", 1, "garbled layer " * 10)
    assert classify_pages(layered)[2] is False  # counted as digital...
    assert image_pages(layered) == {1: False, 2: True, 3: False}  # ...but it is an image

    prepared = prepare_input(

        layered, Settings(), tmp_path, scanned=classify_pages(layered), detector=_FixedDetector(90)

    )
    assert [o.page_no for o in prepared.orientations] == [2]
    assert prepared.path != layered
    assert count_page_chars(prepared.path, 1) == 0  # the sideways text layer is dropped
