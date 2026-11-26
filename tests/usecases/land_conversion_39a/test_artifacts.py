"""A freshly parsed gazette is stored with its issue details and recorded in the ledger."""

import json
from pathlib import Path

from docling_core.types.doc import DoclingDocument, Size

import bakasur.usecases.land_conversion_39a.pipeline as pipeline_mod
from bakasur.core.convert import Converted
from bakasur.usecases.land_conversion_39a.config import Settings
from bakasur.usecases.land_conversion_39a.pipeline import Pipeline

NAME = "2026-08-20_SIII-OG21_39A(59)-19th Aug 2026.pdf"


def test_new_gazette_is_parsed_stored_and_counted(tmp_path: Path, monkeypatch):
    cfg = Settings(
        data_dir=tmp_path,
        inbox_dir=tmp_path / "inbox",
        processed_dir=tmp_path / "processed",
        failed_dir=tmp_path / "failed",
        gazettes_dir=tmp_path / "gazettes",
        out_dir=tmp_path / "out",
        db_path=tmp_path / "test.db",
    )
    doc = DoclingDocument(name="g")
    for n in (1, 2, 3):
        doc.add_page(page_no=n, size=Size(width=100, height=100))
    monkeypatch.setattr(pipeline_mod, "convert", lambda *a, **k: Converted(doc))
    monkeypatch.setattr(pipeline_mod, "extract_39a_from_artifacts", lambda *a: ([], []))
    p = Pipeline(cfg)
    pdf = cfg.inbox_dir / NAME
    pdf.write_bytes(b"%PDF-1.4 stub")

    result = p.process_pdf(pdf)

    assert result["status"] == "completed", result
    gazette = p.ledger.list_gazettes()[0]
    assert gazette["page_count"] == 3
    meta = json.loads((cfg.gazettes_dir / result["gazette_id"] / "meta.json").read_text())
    assert meta["gazette_id"] == result["gazette_id"]
    assert (meta["series"], meta["issue_no"], meta["gazette_date"]) == ("SIII", "21", "2026-08-20")
    assert meta["page_count"] == 3 and meta["source_filename"] == NAME
