"""Commands that work on any document: Markdown conversion, RAG chunking, a parse spike."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from bakasur.core.config import CoreSettings
from bakasur.core.convert import convert
from bakasur.core.export.batch import BatchResult, convert_directory
from bakasur.core.export.markdown import convert_to_markdown_with_orientation
from bakasur.core.rag.chunk import chunk_from_artifact

app = typer.Typer()
console = Console()
err_console = Console(stderr=True)


def parse_page_range(page_range: str | None) -> tuple[int, int] | None:
    if not page_range:
        return None
    start_s, end_s = page_range.split("-", 1)
    return int(start_s), int(end_s)


def run_markdown_batch(
    input_dir: Path,
    output_dir: Path,
    cfg: CoreSettings,
    *,
    glob: str,
    force_ocr: bool = False,
    overwrite: bool = False,
    limit: int | None = None,
) -> None:
    """Convert matching files with progress on stderr and in ``_batch.log``; exit 1 on failures."""
    if output_dir.resolve() == input_dir.resolve():
        raise typer.BadParameter("output would overwrite the input folder", param_hint="--output-dir")
    files = sorted(p for p in input_dir.glob(glob) if p.is_file())
    if limit is not None:
        files = files[:limit]
    if not files:
        err_console.print(f"[red]No files match {glob!r} in {input_dir}[/red]")
        raise typer.Exit(1)

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
    """Convert any file to Markdown with Docling, OCRing scans."""
    out = output or file.with_suffix(".md")
    if out.resolve() == file.resolve():
        raise typer.BadParameter("output would overwrite the input; pass --output", param_hint="--output")
    cfg = CoreSettings()
    with err_console.status(f"Converting {file.name}..."):
        markdown, orientations = convert_to_markdown_with_orientation(
            file, cfg, force_ocr=force_ocr, page_range=parse_page_range(page_range)
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
    run_markdown_batch(
        input_dir,
        output_dir,
        CoreSettings(),
        glob=glob,
        force_ocr=force_ocr,
        overwrite=overwrite,
        limit=limit,
    )


@app.command("chunk-rag")
def chunk_rag_cmd(
    artifact: Path = typer.Argument(
        ..., exists=True, help="An artifact folder (e.g. data/gazettes/<id>) or its docling.json"
    ),
    max_tokens: int = typer.Option(512, help="Chunk max tokens"),
) -> None:
    """Smoke-test RAG chunking from a saved docling.json."""
    path = artifact / "docling.json" if artifact.is_dir() else artifact
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
    cfg = CoreSettings(profile_timings=True)
    converted = convert(pdf, cfg, page_range=parse_page_range(page_range), page_images=True)
    doc, timings = converted.document, converted.timings

    first_page = min(doc.pages.keys()) if doc.pages else 1
    text_default = doc.export_to_text(page_no=first_page, traverse_pictures=False)
    text_traverse = doc.export_to_text(page_no=first_page, traverse_pictures=True)
    console.print(f"Pages: {doc.num_pages()}, page keys: {sorted(doc.pages.keys())}")
    console.print(f"Tables: {len(doc.tables)}")
    console.print(f"Page {first_page} text (default): {len(text_default)} chars")
    console.print(f"Page {first_page} text (traverse_pictures): {len(text_traverse)} chars")
    if doc.tables:
        df = doc.tables[0].export_to_dataframe(doc=doc)
        console.print(f"First table shape: {df.shape}")
    console.print(f"Timings: {timings}")
