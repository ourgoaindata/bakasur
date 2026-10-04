"""Docling spike tests validating plan decision gates."""

from pathlib import Path

import pytest

from bakasur.config import Settings
from bakasur.parse.runner import convert_pdf, convert_pdf_batched

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DIGITAL = FIXTURES / (
    "2026-08-20_SIII-OG21_39A(59)-19th Aug 2026_(two 39As - new + new ndz).pdf"
)
SCANNED = FIXTURES / (
    "2026-08-06_SIII-OG19_39A(57)-5th Aug 2026_(2 nos - new + ndz+ corrigendum).pdf"
)


@pytest.mark.slow
def test_digital_fixture_yields_tables():
    cfg = Settings()
    doc, _ = convert_pdf(DIGITAL, cfg, page_range=(1, 15))
    assert doc.num_pages() == 15
    assert len(doc.tables) > 0
    first_page = min(doc.pages.keys())
    text = doc.export_to_text(page_no=first_page, traverse_pictures=True)
    assert len(text) > 100


@pytest.mark.slow
def test_scanned_fixture_yields_tables_on_ndz_pages():
    cfg = Settings(preprocess_scans=False)
    doc, _ = convert_pdf(SCANNED, cfg, page_range=(5, 6))
    assert sorted(doc.pages.keys()) == [5, 6]
    assert len(doc.tables) >= 1
    df = doc.tables[0].export_to_dataframe(doc=doc)
    assert df.shape[0] >= 1
    page_text = doc.export_to_text(page_no=5, traverse_pictures=True)
    assert "No Development Zone" in page_text or "39A" in page_text.lower()


@pytest.mark.slow
def test_page_range_preserves_original_page_numbers():
    cfg = Settings(preprocess_scans=False)
    doc, _ = convert_pdf(SCANNED, cfg, page_range=(5, 6))
    assert sorted(doc.pages.keys()) == [5, 6]
    if doc.tables:
        assert doc.tables[0].prov[0].page_no in {5, 6}
