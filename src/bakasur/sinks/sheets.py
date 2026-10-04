"""Google Sheets sink."""

from __future__ import annotations

from typing import Any

import gspread
from google.oauth2.service_account import Credentials

from bakasur.config import Settings
from bakasur.models import ApplicationRow, PlotRow, ValidationIssue

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class SheetsSink:
    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg
        self._client: gspread.Client | None = None

    def _get_client(self) -> gspread.Client:
        if self._client is None:
            if not self.cfg.google_service_account_file:
                raise RuntimeError("google_service_account_file is not configured")
            creds = Credentials.from_service_account_file(
                str(self.cfg.google_service_account_file),
                scopes=SCOPES,
            )
            self._client = gspread.authorize(creds)
        return self._client

    def _ensure_worksheet(self, title: str, headers: list[str]) -> gspread.Worksheet:
        client = self._get_client()
        sh = client.open_by_key(self.cfg.google_sheet_id)
        try:
            ws = sh.worksheet(title)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=title, rows=1000, cols=len(headers))
            ws.append_row(headers)
        existing = ws.row_values(1)
        if not existing:
            ws.append_row(headers)
        return ws

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.google_sheet_id and self.cfg.google_service_account_file)

    def _tab_for(self, kind: str) -> str:
        return {
            "rows": self.cfg.sheet_tab_rows,
            "plots": self.cfg.sheet_tab_plots,
            "review": self.cfg.sheet_tab_review,
        }[kind]

    @staticmethod
    def to_records(
        rows: list[ApplicationRow],
        plots: list[PlotRow],
        review: list[ValidationIssue],
    ) -> list[tuple[str, dict[str, Any]]]:
        """Flatten rows/plots/issues into (kind, record) pairs for the Sheets outbox."""
        records: list[tuple[str, dict[str, Any]]] = []
        records += [("rows", r.to_dict()) for r in rows]
        records += [("plots", p.to_dict()) for p in plots]
        records += [
            (
                "review",
                {
                    "reason": i.reason,
                    "severity": i.severity,
                    "gazette_id": i.row.gazette_id if i.row else "",
                    "sr_no": i.row.sr_no if i.row else "",
                    "survey_raw": i.row.survey_raw if i.row else "",
                },
            )
            for i in review
        ]
        return records

    def append_records(self, kind: str, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        headers = list(records[0].keys())
        ws = self._ensure_worksheet(self._tab_for(kind), headers)
        ws.append_rows([[d.get(h) for h in headers] for d in records])

    def append_rows(
        self,
        rows: list[ApplicationRow],
        plots: list[PlotRow],
        review: list[ValidationIssue],
    ) -> int:
        if not self.enabled:
            return 0
        by_kind: dict[str, list[dict[str, Any]]] = {}
        for kind, record in self.to_records(rows, plots, review):
            by_kind.setdefault(kind, []).append(record)
        for kind, records in by_kind.items():
            self.append_records(kind, records)
        return len(rows)
