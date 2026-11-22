"""Any-file to Markdown conversion keeps source page numbers."""

import os
import signal
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
from bakasur.core.config import CoreSettings
from bakasur.core.convert import build_converter
from bakasur.core.export.markdown import (
    convert_to_markdown,
    document_to_markdown,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
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
    converter = build_converter(CoreSettings())
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
    md = convert_to_markdown(SCANNED, CoreSettings(), page_range=(5, 6))
    assert "[Page 1]" not in md
    assert md.index("[Page 5]") < md.index("[Page 6]")
    assert "No Development Zone" in md or "39A" in md



class _StubConverter:
    """
    Stands in for Docling inside the batch's worker process. Logs each call next to the
    input; 'bad' files raise, 'crash' files kill the process, and 'flaky' files kill it
    only the first time.
    """

    def convert(self, path: str):
        src = Path(path)
        with (src.parent / "calls.log").open("a") as log:
            log.write(src.name + "\n")
        marker = src.with_suffix(".crashed")
        if "crash" in src.name or ("flaky" in src.name and not marker.exists()):
            marker.touch()
            os.kill(os.getpid(), signal.SIGKILL)
        if "bad" in src.name:
            raise RuntimeError("cannot read")
        return type("R", (), {"document": _doc({1: [src.stem]})})()


def _stub_converter(cfg, force_ocr=False):
    # Module-level so the spawned worker can unpickle it.
    return _StubConverter()


@pytest.fixture
def batch(tmp_path: Path, monkeypatch):
    src = tmp_path / "in"
    src.mkdir()
    for name in ("MoM 001 (1999).pdf", "MoM 002 (2000).pdf", "notes.txt"):
        (src / name).write_text(name)
    monkeypatch.setattr("bakasur.core.export.batch.build_converter", _stub_converter)

    def run(*args: str):
        return CliRunner().invoke(app, ["to-md-batch", str(src), "-o", str(tmp_path / "out"), *args])

    def calls() -> list[str]:
        log = src / "calls.log"
        return log.read_text().splitlines() if log.exists() else []

    return src, tmp_path / "out", run, calls


def test_batch_gives_each_file_a_folder_with_a_copy_and_its_markdown(batch):
    src, out, run, _ = batch
    result = run()
    assert result.exit_code == 0, result.output
    for stem in ("MoM 001 (1999)", "MoM 002 (2000)"):
        assert (out / stem / f"{stem}.pdf").read_text() == f"{stem}.pdf"
        assert f"[Page 1]\n\n{stem}" in (out / stem / f"{stem}.md").read_text()
    assert not (out / "notes").exists()
    assert (src / "MoM 001 (1999).pdf").exists()
    assert len((out / "_batch.log").read_text().splitlines()) == 2


def test_batch_rerun_skips_finished_files_unless_overwrite(batch):
    _, _, run, calls = batch
    run()
    assert len(calls()) == 2
    run()
    assert len(calls()) == 2
    run("--overwrite")
    assert len(calls()) == 4


def test_batch_continues_past_a_failing_file_and_exits_nonzero(batch):
    src, out, run, _ = batch
    (src / "MoM 000 bad.pdf").write_text("x")
    result = run()
    assert result.exit_code == 1
    assert "failed 1" in result.output
    assert (out / "MoM 001 (1999)" / "MoM 001 (1999).md").exists()
    assert not (out / "MoM 000 bad" / "MoM 000 bad.md").exists()
    # The failure is retried on the next run rather than treated as finished.
    assert run().exit_code == 1


def test_batch_survives_a_crashing_converter_and_retries_it_once(batch):
    src, out, run, calls = batch
    (src / "MoM 000 crash.pdf").write_text("x")
    (src / "MoM 0005 flaky.pdf").write_text("x")
    result = run()
    assert result.exit_code == 1
    assert "converter process died" in result.output
    # A file that crashes twice fails; one that crashes once succeeds on the retry.
    assert calls().count("MoM 000 crash.pdf") == 2
    assert calls().count("MoM 0005 flaky.pdf") == 2
    assert (out / "MoM 0005 flaky" / "MoM 0005 flaky.md").exists()
    for stem in ("MoM 001 (1999)", "MoM 002 (2000)"):
        assert (out / stem / f"{stem}.md").exists()


def test_batch_refuses_to_use_the_input_folder_as_output(batch):
    src, _, _, _ = batch
    result = CliRunner().invoke(app, ["to-md-batch", str(src), "-o", str(src)])
    assert result.exit_code != 0
