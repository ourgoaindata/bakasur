"""Typer CLI entry point."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from bakasur.config import Settings, get_settings
from bakasur.inbox.watcher import InboxWatcher
from bakasur.ledger import Ledger
from bakasur.models import GazetteStatus
from bakasur.parse.artifacts import ArtifactStore
from bakasur.parse.runner import parse_gazette_pdf
from bakasur.pipeline import Pipeline
from bakasur.rag.chunk import chunk_from_artifact
from bakasur.utils import gazette_id_from_path, sha256_file

app = typer.Typer(no_args_is_help=True, help="Goa Gazette 39A extractor")
console = Console()


@app.command()
def run(
    once: bool = typer.Option(True, "--once/--watch", help="Process inbox once or watch"),
) -> None:
    """Process gazette PDFs from the inbox folder."""
    cfg = get_settings()
    watcher = InboxWatcher(cfg)
    if once:
        watcher.process_once()
    else:
        watcher.watch()


@app.command("watch")
def watch_cmd() -> None:
    """Watch the inbox folder continuously."""
    cfg = get_settings()
    InboxWatcher(cfg).watch()


@app.command()
def parse(
    pdf: Path = typer.Argument(..., help="PDF to parse into artifacts"),
    gazette_id: str | None = typer.Option(None, help="Override gazette id"),
) -> None:
    """Parse a PDF with Docling and write artifacts only."""
    cfg = get_settings()
    cfg.ensure_dirs()
    sha = sha256_file(pdf)
    gid = gazette_id or gazette_id_from_path(pdf, sha)
    doc, timings, scanned = parse_gazette_pdf(pdf, cfg)
    store = ArtifactStore(cfg.gazettes_dir)
    out = store.write(
        gid,
        pdf,
        doc,
        sha256=sha,
        timings=timings,
        scanned_pages=scanned,
    )
    console.print(f"Wrote artifacts to {out} ({doc.num_pages()} pages)")
    if timings:
        console.print(f"Timings: {timings}")


@app.command("extract-39a")
def extract_39a_cmd(
    gazette_id: str = typer.Argument(..., help="Gazette id in artifact store"),
) -> None:
    """Extract 39A rows from existing artifacts."""
    cfg = get_settings()
    pipeline = Pipeline(cfg)
    rows, plots = __import__("bakasur.extract", fromlist=["extract_39a_from_artifacts"]).extract_39a_from_artifacts(
        pipeline.store, gazette_id, cfg
    )
    console.print(f"Extracted {len(rows)} application rows, {len(plots)} plot rows")


@app.command("sync-sheets")
def sync_sheets_cmd() -> None:
    """Retry pushing queued rows to Google Sheets."""
    cfg = get_settings()
    result = Pipeline(cfg).sync_sheets()
    console.print(f"Pushed {result['pushed']} record(s); {result['pending']} still queued")
    if result["error"]:
        console.print(f"[red]Last error:[/red] {result['error']}")
        raise typer.Exit(1)


@app.command()
def status() -> None:
    """Show ledger status summary."""
    cfg = get_settings()
    ledger = Ledger(cfg.db_path)
    rows = ledger.list_gazettes()
    table = Table(title="Gazettes")
    table.add_column("Gazette ID")
    table.add_column("File")
    table.add_column("Status")
    table.add_column("Pages")
    for row in rows[:50]:
        table.add_row(
            row["gazette_id"],
            row["source_filename"],
            row["status"],
            str(row["page_count"] or ""),
        )
    console.print(table)


@app.command("chunk-rag")
def chunk_rag_cmd(
    gazette_id: str = typer.Argument(..., help="Gazette id"),
    max_tokens: int = typer.Option(512, help="Chunk max tokens"),
) -> None:
    """Smoke-test RAG chunking from saved docling.json."""
    cfg = get_settings()
    path = ArtifactStore(cfg.gazettes_dir).gazette_dir(gazette_id) / "docling.json"
    chunks = chunk_from_artifact(path, max_tokens=max_tokens)
    console.print(f"Produced {len(chunks)} chunks from {path}")
    if chunks:
        sample = chunks[0]
        console.print(f"First chunk pages={sample.pages} headings={sample.headings}")
        console.print(sample.text[:200])


@app.command("spike-parse")
def spike_parse_cmd(
    pdf: Path = typer.Argument(..., help="Fixture PDF"),
    page_range: str | None = typer.Option(None, help="e.g. 1-5"),
) -> None:
    """Decision-gate spike: tables, text export, optional page range."""
    cfg = get_settings()
    cfg.profile_timings = True
    pr: tuple[int, int] | None = None
    if page_range:
        start_s, end_s = page_range.split("-", 1)
        pr = (int(start_s), int(end_s))

    from docling.datamodel.settings import settings as docling_settings

    docling_settings.debug.profile_pipeline_timings = True

    if pr:
        from bakasur.parse.runner import convert_pdf

        doc, timings = convert_pdf(pdf, cfg, page_range=pr)
    else:
        doc, timings, _ = parse_gazette_pdf(pdf, cfg)

    first_page = min(doc.pages.keys()) if doc.pages else 1
    text_default = doc.export_to_text(page_no=first_page, traverse_pictures=False)
    text_traverse = doc.export_to_text(page_no=first_page, traverse_pictures=True)
    console.print(f"Pages: {doc.num_pages()}, page keys: {sorted(doc.pages.keys())}")
    console.print(f"Tables: {len(doc.tables)}")
    console.print(
        f"Page {first_page} text (default): {len(text_default)} chars"
    )
    console.print(
        f"Page {first_page} text (traverse_pictures): {len(text_traverse)} chars"
    )
    if doc.tables:
        df = doc.tables[0].export_to_dataframe(doc=doc)
        console.print(f"First table shape: {df.shape}")
    console.print(f"Timings: {timings}")


if __name__ == "__main__":
    app()
