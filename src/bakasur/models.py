"""Shared data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TableVariant(str, Enum):
    CHANGE_OF_ZONE = "change_of_zone"
    NDZ = "ndz"


class GazetteStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    PARSED = "parsed"
    EXTRACTED = "extracted"
    COMPLETED = "completed"
    FAILED = "failed"


class PipelineOutcome(str, Enum):
    SKIPPED = "skipped"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class GazetteMetadata:
    gazette_id: str
    source_filename: str
    sha256: str
    page_count: int = 0
    series: str | None = None
    issue_no: str | None = None
    gazette_date: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class NotificationSpan:
    notification_no: str | None
    page_start: int
    page_end: int
    variant_hint: TableVariant | None = None


@dataclass
class ColumnMap:
    sr_no: int | None = None
    applicant: int | None = None
    survey: int | None = None
    village_taluka: int | None = None
    existing_use: int | None = None
    proposed_use: int | None = None
    area_proposed: int | None = None
    decision: int | None = None

    def as_dict(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for key in (
            "sr_no",
            "applicant",
            "survey",
            "village_taluka",
            "existing_use",
            "proposed_use",
            "area_proposed",
            "decision",
        ):
            val = getattr(self, key)
            if val is not None:
                out[key] = val
        return out


@dataclass
class MapperResult:
    is_39a: bool
    variant: TableVariant | None
    column_map: ColumnMap | None = None
    confidence: float = 1.0


@dataclass
class ApplicationRow:
    gazette_id: str
    source_filename: str
    notification_no: str | None
    table_variant: TableVariant
    sr_no: str | None
    applicant: str | None
    survey_raw: str | None
    village: str | None
    taluka: str | None
    existing_use: str | None
    total_area_sqm: int | None
    proposed_use: str | None
    area_proposed_sqm: int | None
    decision: str | None
    page_from: int
    page_to: int
    confidence: float = 1.0
    row_hash: str = ""
    # Set when extraction suspects the row's data; validation then holds it for review.
    review_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "gazette_id": self.gazette_id,
            "source_filename": self.source_filename,
            "notification_no": self.notification_no,
            "table_variant": self.table_variant.value,
            "sr_no": self.sr_no,
            "applicant": self.applicant,
            "survey_raw": self.survey_raw,
            "village": self.village,
            "taluka": self.taluka,
            "existing_use": self.existing_use,
            "total_area_sqm": self.total_area_sqm,
            "proposed_use": self.proposed_use,
            "area_proposed_sqm": self.area_proposed_sqm,
            "decision": self.decision,
            "page_from": self.page_from,
            "page_to": self.page_to,
            "confidence": self.confidence,
            "row_hash": self.row_hash,
        }


@dataclass
class PlotRow:
    gazette_id: str
    notification_no: str | None
    sr_no: str | None
    survey_number: str
    is_part: bool
    village: str | None
    taluka: str | None
    row_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "gazette_id": self.gazette_id,
            "notification_no": self.notification_no,
            "sr_no": self.sr_no,
            "survey_number": self.survey_number,
            "is_part": self.is_part,
            "village": self.village,
            "taluka": self.taluka,
            "row_hash": self.row_hash,
        }


@dataclass
class ValidationIssue:
    row: ApplicationRow | None
    reason: str
    severity: str = "error"
