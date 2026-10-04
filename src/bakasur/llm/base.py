"""LLM mapper protocol."""

from __future__ import annotations

from typing import Protocol

from bakasur.models import MapperResult, TableVariant


class ColumnMapper(Protocol):
    def map_columns(
        self,
        header_row: list[str],
        sample_rows: list[list[str]],
        variant_hint: TableVariant | None = None,
    ) -> MapperResult: ...
