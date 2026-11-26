"""Devanagari on scanned pages is found, read with an Indic reader, and flagged in output."""

import json
from pathlib import Path

from docling_core.types.doc import (
    BoundingBox,
    DocItemLabel,
    DoclingDocument,
    ProvenanceItem,
    Size,
)
from PIL import Image

from bakasur.core.config import CoreSettings
from bakasur.core.convert import PageScript
from bakasur.core.convert.converter import read_scripts
from bakasur.core.convert.script import count_devanagari_words, find_devanagari_pages, judge
from bakasur.core.export.batch import BatchResult
from bakasur.core.export.markdown import MarkdownResult, document_to_markdown

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "script"
# Occupant names from Form I & XIV, scanned (MoM 518, p. 70); RapidOCR read them as "GRR".
DEVANAGARI = FIXTURES / "mom518_p70_devanagari.png"
# Serif English whose fused letter pairs ("rm", "ary") once passed for headline words.
LATIN = FIXTURES / "mom529_p56_latin.png"


def _pdf(tmp_path: Path, *images: Path) -> Path:
    """A scanned PDF: one page per image, no text layer."""
    pages = [Image.open(p).convert("RGB") for p in images]
    out = tmp_path / "scan.pdf"
    pages[0].save(out, save_all=True, append_images=pages[1:], resolution=150)
    return out


class _FakeReader:
    def __init__(self, text: str = "", fail: bool = False):
        self.text, self.fail, self.calls = text, fail, 0

    def read(self, image) -> str:
        self.calls += 1
        if self.fail:
            raise RuntimeError("model not available")
        return self.text


def test_devanagari_words_are_found_and_serif_english_is_not():
    assert count_devanagari_words(Image.open(DEVANAGARI)) >= 4
    assert count_devanagari_words(Image.open(LATIN)) == 0


def test_only_pages_with_devanagari_are_flagged(tmp_path: Path):
    pdf = _pdf(tmp_path, LATIN, DEVANAGARI, LATIN)
    assert list(find_devanagari_pages(pdf)) == [2]


def test_judge_tells_real_marathi_from_garbled_and_missing_script():
    assert judge("1). जयराम नागा शेटगांवकर 2). वासु नागा शेटगांवकर") == "indic_ocr"
    assert judge("सरकार") == "indic_ocr"  # short, but real
    # English names typed in a Devanagari font (MoM 415, p. 69): almost no vowel signs.
    assert judge("रमझतलरन हडसमजत, फतनहसस हबद, आनतललम फनतरहडस") == "garbled_source"
    assert judge("The page came back in English only") == "unrecognised"


def test_flagged_pages_are_read_and_judged(tmp_path: Path):
    pdf = _pdf(tmp_path, LATIN, DEVANAGARI)
    cfg = CoreSettings()
    reader = _FakeReader("1). जयराम नागा शेटगांवकर")
    [found] = read_scripts(pdf, cfg, reader=reader)
    assert (found.page_no, found.status, found.markdown) == (2, "indic_ocr", reader.text)
    assert reader.calls == 1  # the English page is not sent to the slow reader

    [garbled] = read_scripts(pdf, cfg, reader=_FakeReader("फनतरहडस हडसमजत सनततन"))
    assert garbled.status == "garbled_source"
    [other] = read_scripts(pdf, cfg, reader=_FakeReader("| 1 | 182/1 | |"))
    assert other.status == "unrecognised"


def test_pages_stay_flagged_without_a_reader_or_when_it_fails(tmp_path: Path):
    pdf = _pdf(tmp_path, DEVANAGARI)
    cfg = CoreSettings()
    [off] = read_scripts(pdf, cfg, reader=None)
    assert off.status == "not_read" and off.markdown is None
    [failed] = read_scripts(pdf, cfg, reader=_FakeReader(fail=True))
    assert failed.status == "not_read" and "model not available" in failed.error
    assert read_scripts(pdf, CoreSettings(detect_scripts=False), reader=_FakeReader()) == []
    assert read_scripts(pdf, cfg, page_range=(2, 3), reader=_FakeReader()) == []


def _doc(pages: dict[int, str]) -> DoclingDocument:
    doc = DoclingDocument(name="t")
    for page_no, text in pages.items():
        doc.add_page(page_no=page_no, size=Size(width=100, height=100))
        prov = ProvenanceItem(
            page_no=page_no, bbox=BoundingBox(l=0, t=0, r=10, b=10), charspan=(0, len(text))
        )
        doc.add_text(label=DocItemLabel.TEXT, text=text, prov=prov)
    return doc


def test_markdown_uses_the_indic_read_and_flags_what_needs_a_check():
    scripts = [
        PageScript(2, 9, "indic_ocr", "1). जयराम नागा शेटगांवकर"),
        PageScript(3, 40, "garbled_source", "फनतरहडस"),
        PageScript(4, 3, "unrecognised", "x"),
        PageScript(5, 6, "not_read", error="IndicOCR is off"),
    ]
    doc = _doc({1: "a", 2: "1). GRR", 3: "c", 4: "docling text", 5: "e"})
    pages = document_to_markdown(doc, scripts=scripts).rstrip().split("\n\n---\n\n")
    assert pages[0] == "[Page 1]\n\na"
    assert pages[1].startswith("[Page 2]\n\n<!-- bakasur: Devanagari, read with IndicOCR")
    assert pages[1].endswith("1). जयराम नागा शेटगांवकर") and "GRR" not in pages[1]
    assert "> **Garbled Devanagari:** page 3" in pages[2] and pages[2].endswith("फनतरहडस")
    assert "> **Unrecognised script:** page 4" in pages[3]
    assert pages[3].endswith("docling text")  # nothing better to put in its place
    assert "> **Devanagari not read:** page 5" in pages[4] and "IndicOCR is off" in pages[4]


def test_meta_and_batch_log_list_script_pages():
    scripts = [PageScript(70, 12, "indic_ocr", "md"), PageScript(48, 7, "garbled_source", "md")]
    meta = MarkdownResult("md", scripts=scripts).meta()
    assert json.loads(json.dumps(meta, ensure_ascii=False))["scripts"] == [
        {"page_no": 70, "devanagari_words": 12, "status": "indic_ocr"},
        {"page_no": 48, "devanagari_words": 7, "status": "garbled_source"},
    ]
    summary = BatchResult(Path("x.pdf"), "converted", scripts=scripts).script_summary()
    assert summary == "IndicOCR p70; garbled Devanagari p48"
