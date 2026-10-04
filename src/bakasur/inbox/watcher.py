"""Inbox folder watcher."""

from __future__ import annotations

import time
from pathlib import Path

from rich.console import Console

from bakasur.config import Settings
from bakasur.ledger import Ledger
from bakasur.models import GazetteStatus, PipelineOutcome
from bakasur.pipeline import Pipeline
from bakasur.utils import sha256_file

console = Console()


class InboxWatcher:
    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg
        self.pipeline = Pipeline(cfg)
        self.ledger = Ledger(cfg.db_path)

    def list_pending_pdfs(self) -> list[Path]:
        pdfs = sorted(self.cfg.inbox_dir.glob("*.pdf"))
        pending: list[Path] = []
        for pdf in pdfs:
            sha = sha256_file(pdf)
            existing = self.ledger.get_by_sha256(sha)
            if existing is None or existing["status"] != GazetteStatus.COMPLETED.value:
                pending.append(pdf)
        return pending

    def process_once(self) -> list[dict]:
        self.ledger.reset_stale_processing()
        sync = self.pipeline.sync_sheets()
        if sync["pushed"]:
            console.print(f"[green]Synced[/green] {sync['pushed']} queued record(s) to Google Sheets")
        if sync["error"]:
            console.print(
                f"[red]Google Sheets sync failed[/red] ({sync['pending']} queued): {sync['error']}"
            )
        results: list[dict] = []
        for pdf in self.list_pending_pdfs():
            console.print(f"[cyan]Processing[/cyan] {pdf.name}")
            result = self.pipeline.process_pdf(pdf)
            results.append(result)
            if result["status"] == PipelineOutcome.COMPLETED:
                console.print(
                    f"[green]Done[/green] {pdf.name} — "
                    f"{result.get('rows', 0)} rows, "
                    f"{result.get('review_issues', 0)} review issue(s)"
                )
            elif result["status"] == PipelineOutcome.SKIPPED:
                console.print(f"[yellow]Skipped[/yellow] {pdf.name} ({result.get('reason')})")
            else:
                console.print(f"[red]Failed[/red] {pdf.name}: {result.get('error')}")
        return results

    def watch(self) -> None:
        console.print(
            f"Watching [bold]{self.cfg.inbox_dir}[/bold] "
            f"(every {self.cfg.poll_interval_seconds}s)"
        )
        while True:
            self.process_once()
            time.sleep(self.cfg.poll_interval_seconds)
