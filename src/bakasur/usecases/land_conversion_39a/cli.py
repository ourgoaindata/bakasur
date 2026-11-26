"""``bakasur 39a ...``: process gazettes, extract 39A rows, publish them."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from bakasur.core.convert import convert
from bakasur.core.hashing import doc_id_from_path, sha256_file
from bakasur.core.store.artifacts import ArtifactStore
from bakasur.usecases.land_conversion_39a.config import get_settings
from bakasur.usecases.land_conversion_39a.extract import extract_39a_from_artifacts
from bakasur.usecases.land_conversion_39a.gazette.header import gazette_info
from bakasur.usecases.land_conversion_39a.ledger import Ledger
from bakasur.usecases.land_conversion_39a.pipeline import (
    Pipeline,
    publishable_rows,
    write_artifacts,
)
from bakasur.usecases.land_conversion_39a.sinks.files import write_master_csv
from bakasur.usecases.land_conversion_39a.sinks.master import master_rows
from bakasur.usecases.land_conversion_39a.watcher import InboxWatcher

app = typer.Typer(
    no_args_is_help=True,
    help="Section 39A land conversions (change of zone, NDZ) in the Official Gazette.",
)
console = Console()


@app.command()
def run(
    once: bool = typer.Option(True, "--once/--watch", help="Process inbox once or watch"),
) -> None:
    """Process gazette PDFs from the inbox folder."""
    watcher = InboxWatcher(get_settings())
    if once:
        watcher.process_once()
    else:
        watcher.watch()


@app.command("watch")
def watch_cmd() -> None:
    """Watch the inbox folder continuously."""
    InboxWatcher(get_settings()).watch()


@app.command()
def parse(
    pdf: Path = typer.Argument(..., help="PDF to parse into artifacts"),
    gazette_id: str | None = typer.Option(None, help="Override gazette id"),
) -> None:
    """Parse a PDF with Docling and write artifacts only."""
    cfg = get_settings()
    cfg.ensure_dirs()
    sha = sha256_file(pdf)
    gid = gazette_id or doc_id_from_path(pdf, sha)
    converted = convert(pdf, cfg, page_images=True)
    out = write_artifacts(ArtifactStore(cfg.gazettes_dir), gid, pdf, converted, sha)
    console.print(f"Wrote artifacts to {out} ({converted.document.num_pages()} pages)")
    if converted.timings:
        console.print(f"Timings: {converted.timings}")


@app.command("extract")
def extract_cmd(
    gazette_id: str = typer.Argument(..., help="Gazette id in artifact store"),
) -> None:
    """Extract 39A rows from existing artifacts."""
    cfg = get_settings()
    rows, plots = extract_39a_from_artifacts(Pipeline(cfg).store, gazette_id, cfg)
    console.print(f"Extracted {len(rows)} application rows, {len(plots)} plot rows")


@app.command("export-master")
def export_master_cmd(
    gazette_id: str = typer.Argument(..., help="Gazette id in artifact store"),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="CSV path (default: data/out/<gazette_id>.master.csv)"
    ),
) -> None:
    """Write a gazette's change-of-zone rows in the 39A master sheet's layout."""
    cfg = get_settings()
    pipeline = Pipeline(cfg)
    extracted, _ = extract_39a_from_artifacts(pipeline.store, gazette_id, cfg)
    rows, issues = publishable_rows(extracted)
    gazette = gazette_info(
        pipeline.store.load_page_texts(gazette_id), pipeline.store.load_meta(gazette_id)
    )
    out = output or cfg.out_dir / f"{gazette_id}.master.csv"
    write_master_csv(out, master_rows(rows, gazette, pipeline.villages))
    console.print(f"Wrote {len(rows)} row(s) to {out}")
    if issues:
        console.print(f"[yellow]{len(issues)} record(s) held for review and left out[/yellow]")


@app.command("sync-sheets")
def sync_sheets_cmd() -> None:
    """Retry pushing queued rows to Google Sheets."""
    result = Pipeline(get_settings()).sync_sheets()
    console.print(f"Pushed {result['pushed']} record(s); {result['pending']} still queued")
    if result["error"]:
        console.print(f"[red]Last error:[/red] {result['error']}")
        raise typer.Exit(1)


@app.command()
def status() -> None:
    """Show ledger status summary."""
    ledger = Ledger(get_settings().db_path)
    table = Table(title="Gazettes")
    table.add_column("Gazette ID")
    table.add_column("File")
    table.add_column("Status")
    table.add_column("Pages")
    for row in ledger.list_gazettes()[:50]:
        table.add_row(
            row["gazette_id"],
            row["source_filename"],
            row["status"],
            str(row["page_count"] or ""),
        )
    console.print(table)
