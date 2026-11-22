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
from bakasur.parse.markdown import (
    BatchResult,
    convert_directory,
    convert_to_markdown_with_orientation,
)
from bakasur.parse.runner import parse_gazette_pdf
from bakasur.pipeline import Pipeline
from bakasur.rag.chunk import chunk_from_artifact
from bakasur.utils import gazette_id_from_path, sha256_file

app = typer.Typer(no_args_is_help=True, help="Goa Gazette 39A extractor")
console = Console()
err_console = Console(stderr=True)


def _parse_page_range(page_range: str | None) -> tuple[int, int] | None:
    if not page_range:
        return None
    start_s, end_s = page_range.split("-", 1)
    return int(start_s), int(end_s)


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
    doc, timings, scanned, orientations = parse_gazette_pdf(pdf, cfg)
    store = ArtifactStore(cfg.gazettes_dir)
    out = store.write(
        gid,
        pdf,
        doc,
        sha256=sha,
        timings=timings,
        scanned_pages=scanned,
        page_orientation=orientations,
    )
    console.print(f"Wrote artifacts to {out} ({doc.num_pages()} pages)")
    if timings:
        console.print(f"Timings: {timings}")


@app.command("to-md")
def to_md_cmd(
    file: Path = typer.Argument(..., exists=True, dir_okay=False, help="Any file Docling can read"),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Markdown path (default: next to input); '-' for stdout"
    ),
    force_ocr: bool = typer.Option(
        False, "--force-ocr", help="OCR every page, ignoring any embedded text layer"
    ),
    page_range: str | None = typer.Option(None, help="e.g. 1-5"),
) -> None:
    """Convert any file to Markdown with Docling, OCRing scans with RapidOCR."""
    out = output or file.with_suffix(".md")
    if out.resolve() == file.resolve():
        raise typer.BadParameter("output would overwrite the input; pass --output", param_hint="--output")
    cfg = get_settings()
    with err_console.status(f"Converting {file.name}..."):
        markdown, orientations = convert_to_markdown_with_orientation(
            file, cfg, force_ocr=force_ocr, page_range=_parse_page_range(page_range)
        )
    for o in orientations:
        if o.rotation or not o.confident:
            colour = "yellow" if not o.confident else "cyan"
            err_console.print(f"[{colour}]Page {o.page_no}: {o.describe()}[/{colour}]")
    if str(out) == "-":
        typer.echo(markdown)
        return
    out.write_text(markdown, encoding="utf-8")
    err_console.print(f"Wrote {out} ({len(markdown):,} chars)")


@app.command("to-md-batch")
def to_md_batch_cmd(
    input_dir: Path = typer.Argument(
        ..., exists=True, file_okay=False, help="Folder of files to convert (not recursive)"
    ),
    output_dir: Path = typer.Option(
        ..., "--output-dir", "-o", help="Each file goes to <output-dir>/<name>/ with its Markdown"
    ),
    glob: str = typer.Option("*.pdf", "--glob", help="Which files in input_dir to convert"),
    force_ocr: bool = typer.Option(
        False, "--force-ocr", help="OCR every page, ignoring any embedded text layer"
    ),
    overwrite: bool = typer.Option(
        False, "--overwrite", help="Reconvert files that already have a Markdown output"
    ),
    limit: int | None = typer.Option(None, help="Convert only the first N matching files"),
) -> None:
    """Convert every matching file in a folder to Markdown, loading the models once."""
    if output_dir.resolve() == input_dir.resolve():
        raise typer.BadParameter("output would overwrite the input folder", param_hint="--output-dir")
    files = sorted(p for p in input_dir.glob(glob) if p.is_file())
    if limit is not None:
        files = files[:limit]
    if not files:
        err_console.print(f"[red]No files match {glob!r} in {input_dir}[/red]")
        raise typer.Exit(1)

    cfg = get_settings()
    output_dir.mkdir(parents=True, exist_ok=True)
    total = len(files)
    seen = 0

    with (output_dir / "_batch.log").open("a", encoding="utf-8") as log:

        def report(result: BatchResult) -> None:
            nonlocal seen
            seen += 1
            detail = result.error or f"{result.chars:,} chars"
            if note := result.orientation_summary():
                detail += f"  ({note})"
            line = f"{result.status:<9} {result.seconds:7.1f}s  {result.path.name}  {detail}"
            err_console.print(f"[{seen}/{total}] {line}", markup=False)
            log.write(line + "\n")
            log.flush()

        err_console.print(f"Converting {total} file(s) to {output_dir}...")
        results = convert_directory(
            files, output_dir, cfg, force_ocr=force_ocr, overwrite=overwrite, on_result=report
        )

    failed = [r for r in results if r.status == "failed"]
    counts = {s: sum(r.status == s for r in results) for s in ("converted", "skipped", "failed")}
    console.print(
        f"Converted {counts['converted']}, skipped {counts['skipped']}, failed {counts['failed']}"
    )
    for r in failed:
        console.print(f"  failed: {r.path.name}: {r.error}", markup=False)
    if failed:
        raise typer.Exit(1)


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
    pr = _parse_page_range(page_range)

    from docling.datamodel.settings import settings as docling_settings

    docling_settings.debug.profile_pipeline_timings = True

    if pr:
        from bakasur.parse.runner import convert_pdf

        doc, timings = convert_pdf(pdf, cfg, page_range=pr)
    else:
        doc, timings, _, _ = parse_gazette_pdf(pdf, cfg)

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
