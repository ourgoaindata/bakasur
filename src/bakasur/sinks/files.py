"""CSV and JSON file sink."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from bakasur.models import ApplicationRow, PlotRow, ValidationIssue
from bakasur.sinks.base import OutputSink


class FileSink:
    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def append_rows(
        self,
        rows: list[ApplicationRow],
        plots: list[PlotRow],
        review: list[ValidationIssue],
    ) -> int:
        if not rows and not review:
            return 0
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        base = self.out_dir / f"run_{stamp}"

        if rows:
            self._write_json(base.with_suffix(".rows.json"), [r.to_dict() for r in rows])
            self._write_csv(
                base.with_suffix(".rows.csv"),
                [r.to_dict() for r in rows],
            )
        if plots:
            self._write_json(base.with_suffix(".plots.json"), [p.to_dict() for p in plots])
        if review:
            self._write_json(
                base.with_suffix(".review.json"),
                [
                    {
                        "reason": i.reason,
                        "severity": i.severity,
                        "row": i.row.to_dict() if i.row else None,
                    }
                    for i in review
                ],
            )
        return len(rows)

    @staticmethod
    def _write_json(path: Path, data: list[dict]) -> None:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _write_csv(path: Path, rows: list[dict]) -> None:
        if not rows:
            return
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
