"""Google Sheets sink: rows, exploded plots and the review queue, one tab each."""

from __future__ import annotations

from typing import Any

from bakasur.core.sinks.sheets import SheetsClient
from bakasur.usecases.land_conversion_39a.config import Settings
from bakasur.usecases.land_conversion_39a.models import ApplicationRow, PlotRow, ValidationIssue


class SheetsSink:
    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg
        self.client = SheetsClient(cfg.google_service_account_file, cfg.google_sheet_id)

    @property
    def enabled(self) -> bool:
        return self.client.enabled

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
        self.client.append_records(self._tab_for(kind), records)

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
