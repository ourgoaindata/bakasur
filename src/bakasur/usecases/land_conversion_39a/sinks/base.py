"""Output sink protocol."""

from __future__ import annotations

from typing import Protocol

from bakasur.usecases.land_conversion_39a.models import ApplicationRow, PlotRow, ValidationIssue


class OutputSink(Protocol):
    def append_rows(
        self,
        rows: list[ApplicationRow],
        plots: list[PlotRow],
        review: list[ValidationIssue],
    ) -> int: ...
