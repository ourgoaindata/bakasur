"""RAG chunking smoke test from saved docling.json."""

import json
from pathlib import Path

import pytest

from bakasur.config import Settings
from bakasur.parse.artifacts import ArtifactStore
from bakasur.parse.runner import convert_pdf
from bakasur.rag.chunk import chunk_from_artifact

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DIGITAL = FIXTURES / (
    "2026-08-20_SIII-OG21_39A(59)-19th Aug 2026_(two 39As - new + new ndz).pdf"
)


@pytest.mark.slow
def test_chunk_from_saved_artifact(tmp_path: Path):
    cfg = Settings()
    from bakasur.parse.pageinfo import classify_pages

    doc, timings = convert_pdf(DIGITAL, cfg, page_range=(1, 5))
    scanned = classify_pages(DIGITAL)
    store = ArtifactStore(tmp_path)
    gazette_id = "rag_test"
    store.write(
        gazette_id,
        DIGITAL,
        doc,
        sha256="testsha",
        timings=timings,
        scanned_pages=scanned,
    )
    chunks = chunk_from_artifact(tmp_path / gazette_id / "docling.json", max_tokens=256)
    assert len(chunks) > 0
    assert chunks[0].text
    assert chunks[0].pages
