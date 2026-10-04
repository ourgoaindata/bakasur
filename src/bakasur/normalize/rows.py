"""Build normalized application and plot rows."""

from __future__ import annotations

from bakasur.models import ApplicationRow, PlotRow, TableVariant
from bakasur.normalize.area import extract_total_area, parse_indian_int
from bakasur.normalize.place import split_village_taluka
from bakasur.normalize.survey import expand_survey_raw
from bakasur.utils import sha256_text


def build_application_row(
    *,
    gazette_id: str,
    source_filename: str,
    notification_no: str | None,
    table_variant: TableVariant,
    raw: dict[str, str | None],
    page_from: int,
    page_to: int,
    confidence: float,
) -> ApplicationRow:
    village, taluka = split_village_taluka(raw.get("village_taluka"))
    existing = raw.get("existing_use")
    proposed = raw.get("proposed_use")
    row = ApplicationRow(
        gazette_id=gazette_id,
        source_filename=source_filename,
        notification_no=notification_no,
        table_variant=table_variant,
        sr_no=raw.get("sr_no"),
        applicant=raw.get("applicant"),
        survey_raw=raw.get("survey"),
        village=village,
        taluka=taluka,
        existing_use=existing,
        total_area_sqm=extract_total_area(existing),
        proposed_use=proposed,
        area_proposed_sqm=parse_indian_int(raw.get("area_proposed")),
        decision=raw.get("decision"),
        page_from=page_from,
        page_to=page_to,
        confidence=confidence,
    )
    key = "|".join(
        [
            gazette_id,
            notification_no or "",
            row.sr_no or "",
            row.survey_raw or "",
            row.decision or "",
        ]
    )
    row.row_hash = sha256_text(key)
    return row


def explode_plots(row: ApplicationRow) -> list[PlotRow]:
    plots: list[PlotRow] = []
    for entry in expand_survey_raw(row.survey_raw):
        plot = PlotRow(
            gazette_id=row.gazette_id,
            notification_no=row.notification_no,
            sr_no=row.sr_no,
            survey_number=entry.survey_number,
            is_part=entry.is_part,
            village=row.village,
            taluka=row.taluka,
        )
        plot.row_hash = sha256_text(
            f"{plot.gazette_id}|{plot.notification_no}|{plot.sr_no}|{plot.survey_number}"
        )
        plots.append(plot)
    return plots
