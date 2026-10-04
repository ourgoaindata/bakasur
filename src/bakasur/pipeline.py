"""End-to-end gazette processing pipeline."""

from __future__ import annotations

import json
import logging
import shutil
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, TypedDict

from bakasur.config import Settings
from bakasur.extract import extract_39a_from_artifacts
from bakasur.ledger import Ledger
from bakasur.models import GazetteStatus, PipelineOutcome
from bakasur.normalize.rows import explode_plots
from bakasur.notify.email import EmailNotifier
from bakasur.parse.artifacts import ArtifactStore
from bakasur.parse.runner import parse_gazette_pdf
from bakasur.sinks.files import FileSink
from bakasur.sinks.sheets import SheetsSink
from bakasur.utils import gazette_id_from_path, sha256_file
from bakasur.validate import partition_rows

logger = logging.getLogger(__name__)


class SkippedResult(TypedDict):
    status: Literal[PipelineOutcome.SKIPPED]
    gazette_id: str
    reason: Literal["duplicate"]


class CompletedResult(TypedDict):
    status: Literal[PipelineOutcome.COMPLETED]
    gazette_id: str
    rows: int
    plots: int
    review_issues: int
    file_sink_rows: int
    sheets_pending: int


class FailedResult(TypedDict):
    status: Literal[PipelineOutcome.FAILED]
    gazette_id: str
    error: str


class SheetsSyncResult(TypedDict):
    pushed: int
    pending: int
    error: str | None


PipelineResult = SkippedResult | CompletedResult | FailedResult


class Pipeline:
    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg
        cfg.ensure_dirs()
        self.ledger = Ledger(cfg.db_path)
        self.store = ArtifactStore(cfg.gazettes_dir)
        self.files = FileSink(cfg.out_dir)
        self.sheets = SheetsSink(cfg)
        self.email = EmailNotifier(cfg)

    def process_pdf(self, pdf_path: Path) -> PipelineResult:
        pdf_path = pdf_path.resolve()
        sha = sha256_file(pdf_path)
        existing = self.ledger.get_by_sha256(sha)
        if existing is not None and existing["status"] == GazetteStatus.COMPLETED.value:
            return {
                "status": PipelineOutcome.SKIPPED,
                "gazette_id": existing["gazette_id"],
                "reason": "duplicate",
            }

        gazette_id = gazette_id_from_path(pdf_path, sha)
        self.ledger.upsert_gazette(
            gazette_id,
            pdf_path.name,
            str(pdf_path),
            sha,
            GazetteStatus.PROCESSING,
        )

        try:
            if not self.store.exists(gazette_id):
                doc, timings, scanned = parse_gazette_pdf(pdf_path, self.cfg)
                artifact_dir = self.store.write(
                    gazette_id,
                    pdf_path,
                    doc,
                    sha256=sha,
                    timings=timings,
                    scanned_pages=scanned,
                )
                self.ledger.update_status(
                    gazette_id,
                    GazetteStatus.PARSED,
                    artifact_dir=str(artifact_dir),
                    page_count=doc.num_pages(),
                )
            else:
                meta = self.store.load_meta(gazette_id)
                self.ledger.update_status(
                    gazette_id,
                    GazetteStatus.PARSED,
                    artifact_dir=str(self.store.gazette_dir(gazette_id)),
                    page_count=meta.get("page_count"),
                )

            rows, _ = extract_39a_from_artifacts(self.store, gazette_id, self.cfg)
            good_rows, issues = partition_rows(rows)
            # Plots only from rows that passed validation, so rejected rows don't leak through.
            plots = [p for r in good_rows for p in explode_plots(r)]

            new_rows = [
                r for r in good_rows if not self.ledger.is_row_emitted(r.row_hash)
            ]
            new_plots = [
                p
                for p in plots
                if not self.ledger.is_row_emitted(p.row_hash)
            ]

            appended = self.files.append_rows(new_rows, new_plots, issues)
            # Queue for Sheets in the same transaction that marks rows emitted, so a
            # Sheets outage can't lose them; sync_sheets() retries until accepted.
            self.ledger.record_emitted(
                [*new_rows, *new_plots],
                self.sheets.to_records(new_rows, new_plots, issues)
                if self.sheets.enabled
                else (),
            )
            sheets = self.sync_sheets()

            self.ledger.update_status(gazette_id, GazetteStatus.COMPLETED)
            self._move_pdf(pdf_path, success=True)
        except Exception as exc:
            tb = traceback.format_exc()
            self.ledger.update_status(
                gazette_id,
                GazetteStatus.FAILED,
                error_message=str(exc)[:2000],
            )
            self._notify(self.email.send_failure, gazette_id, tb)
            self._move_pdf(pdf_path, success=False)
            return {
                "status": PipelineOutcome.FAILED,
                "gazette_id": gazette_id,
                "error": str(exc),
            }

        sheet_url = (
            f"https://docs.google.com/spreadsheets/d/{self.cfg.google_sheet_id}"
            if self.cfg.google_sheet_id
            else None
        )
        self._notify(
            self.email.send_digest,
            gazette_id,
            new_rows,
            issues,
            extracted=len(rows),
            sheet_url=sheet_url,
            sheets_pending=sheets["pending"],
            sheets_error=sheets["error"],
        )
        return {
            "status": PipelineOutcome.COMPLETED,
            "gazette_id": gazette_id,
            "rows": len(new_rows),
            "plots": len(new_plots),
            "review_issues": len(issues),
            "file_sink_rows": appended,
            "sheets_pending": sheets["pending"],
        }

    def sync_sheets(self) -> SheetsSyncResult:
        """Push queued records to Google Sheets; failed kinds stay queued for the next run."""
        if not self.sheets.enabled:
            return {"pushed": 0, "pending": 0, "error": None}
        by_kind: dict[str, list] = {}
        for item in self.ledger.pending_sheets():
            by_kind.setdefault(item["kind"], []).append(item)
        if not by_kind:
            return {"pushed": 0, "pending": 0, "error": None}

        pushed = 0
        error: str | None = None
        for kind, items in by_kind.items():
            ids = [i["id"] for i in items]
            try:
                self.sheets.append_records(kind, [json.loads(i["payload"]) for i in items])
            except Exception as exc:
                logger.warning("Google Sheets append failed for %s: %r", kind, exc)
                error = repr(exc)
                self.ledger.mark_sheets_failed(ids, error)
                continue
            self.ledger.mark_sheets_done(ids)
            pushed += len(ids)
        return {
            "pushed": pushed,
            "pending": self.ledger.count_pending_sheets(),
            "error": error,
        }

    @staticmethod
    def _notify(send: Callable[..., None], *args: Any, **kwargs: Any) -> None:
        """Email is best-effort: a notification failure must never change a gazette's outcome."""
        try:
            send(*args, **kwargs)
        except Exception:
            logger.exception("Email notification failed")

    def _move_pdf(self, pdf_path: Path, *, success: bool) -> None:
        dest_dir = self.cfg.processed_dir if success else self.cfg.failed_dir
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / pdf_path.name
        if pdf_path.exists() and pdf_path.parent.resolve() != dest_dir.resolve():
            if dest.exists():
                dest.unlink()
            shutil.move(str(pdf_path), str(dest))
