"""``bakasur mom ...``: Minutes of Meetings of the Goa Coastal Zone Management Authority."""

from __future__ import annotations

from pathlib import Path

import typer

from bakasur.core.cli import run_markdown_batch
from bakasur.core.config import CoreSettings

# Files are named like "MoM 274 (2021-10-07).pdf".
MOM_GLOB = "MoM*.pdf"

app = typer.Typer(
    no_args_is_help=True,
    help="GCZMA Minutes of Meetings (MoM).",
)


@app.command("convert")
def convert_cmd(
    input_dir: Path = typer.Argument(
        ..., exists=True, file_okay=False, help="Folder holding the MoM PDFs"
    ),
    output_dir: Path = typer.Option(
        ..., "--output-dir", "-o", help="Each MoM goes to <output-dir>/<name>/ with its Markdown"
    ),
    glob: str = typer.Option(MOM_GLOB, "--glob", help="Which files in input_dir are minutes"),
    overwrite: bool = typer.Option(
        False, "--overwrite", help="Reconvert minutes that already have a Markdown output"
    ),
    limit: int | None = typer.Option(None, help="Convert only the first N minutes"),
) -> None:
    """
    Convert a folder of minutes to Markdown with page markers. The minutes are scans with
    a poor embedded OCR layer; orientation is checked on every page, so tables printed
    sideways come out readable.
    """
    run_markdown_batch(
        input_dir, output_dir, CoreSettings(), glob=glob, overwrite=overwrite, limit=limit
    )
