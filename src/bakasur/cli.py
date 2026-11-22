"""
``bakasur``: core commands at the top level, one sub-app per use case.

To add a document type, create ``usecases/<name>/cli.py`` with a ``typer.Typer`` app and
add it to ``USE_CASES``. Nothing under ``core/`` changes.
"""

from __future__ import annotations

import typer

from bakasur.core.cli import app as core_app
from bakasur.usecases.gczma_mom.cli import app as mom_app
from bakasur.usecases.land_conversion_39a import cli as lc

USE_CASES: dict[str, typer.Typer] = {
    "39a": lc.app,
    "mom": mom_app,
}

app = typer.Typer(no_args_is_help=True, help="Parse Goa government documents with Docling.")
app.add_typer(core_app)
for name, sub_app in USE_CASES.items():
    app.add_typer(sub_app, name=name)

# Pre-reorganisation names of the 39A commands, kept hidden so existing scripts still run.
for old_name, command in {
    "run": lc.run,
    "watch": lc.watch_cmd,
    "parse": lc.parse,
    "extract-39a": lc.extract_cmd,
    "export-master": lc.export_master_cmd,
    "sync-sheets": lc.sync_sheets_cmd,
    "status": lc.status,
}.items():
    app.command(old_name, hidden=True)(command)


if __name__ == "__main__":
    app()
