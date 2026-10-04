"""39A extraction from artifact store."""

from __future__ import annotations

from bakasur.config import Settings
from bakasur.gazette.anchors import AnchorConfig, find_notification_spans
from bakasur.gazette.tables import (
    apply_column_map,
    infer_variant,
    merge_continuation_rows,
    parse_sr,
    sample_rows,
    split_header,
    stitch_tables,
    tables_in_span,
)
from bakasur.llm.schema_mapper import get_mapper
from bakasur.models import ApplicationRow, PlotRow, TableVariant
from bakasur.normalize.rows import build_application_row, explode_plots
from bakasur.parse.artifacts import ArtifactStore

MIXED_SURVEY_REASON = (
    "Survey numbers may be mixed with a neighbouring record's: the parser merged the "
    "Sr. No. and survey columns on this page. Check against the PDF."
)
DISPUTED_SPLIT_REASON = (
    "Unsure where this record ends: for a row without a Sr. No., the Sr. No. sequence and "
    "the row's contents disagree on whether it continues the record above. Check against the PDF."
)


def extract_39a_from_artifacts(
    store: ArtifactStore,
    gazette_id: str,
    cfg: Settings,
) -> tuple[list[ApplicationRow], list[PlotRow]]:
    meta = store.load_meta(gazette_id)
    page_texts = store.load_page_texts(gazette_id)
    tables = store.load_tables(gazette_id)
    mapper = get_mapper(cfg)

    anchor_cfg = AnchorConfig(
        anchor_patterns=cfg.anchor_patterns,
        span_end_patterns=cfg.span_end_patterns,
        running_text_patterns=cfg.running_text_patterns,
    )
    spans = find_notification_spans(page_texts, anchor_cfg, tables)

    rows: list[ApplicationRow] = []
    for span in spans:
        span_tables = tables_in_span(tables, span)
        for table in stitch_tables(span_tables, cfg.running_text_patterns):
            header_row, data_rows = split_header(table)
            if not data_rows:
                continue
            mapped = mapper.map_columns(
                header_row,
                sample_rows(data_rows),
                variant_hint=span.variant_hint,
            )
            if not mapped.is_39a or not mapped.column_map:
                continue
            variant = mapped.variant or infer_variant(header_row)
            merged, disputed = merge_continuation_rows(data_rows, mapped.column_map)
            # Merged rows hold no marker rows, so raw_rows lines up with them index for index.
            raw_rows = apply_column_map(merged, mapped.column_map)
            for idx, raw in enumerate(raw_rows):
                if variant == TableVariant.NDZ:
                    raw["applicant"] = None
                row = build_application_row(
                    gazette_id=gazette_id,
                    source_filename=meta["source_filename"],
                    notification_no=span.notification_no,
                    table_variant=variant,
                    raw=raw,
                    page_from=span.page_start,
                    page_to=span.page_end,
                    confidence=mapped.confidence,
                )
                reasons = []
                if parse_sr(raw.get("sr_no")) in table.suspect_sr:
                    reasons.append(MIXED_SURVEY_REASON)
                if idx in disputed:
                    reasons.append(DISPUTED_SPLIT_REASON)
                row.review_reason = " ".join(reasons) or None
                rows.append(row)

    plots: list[PlotRow] = []
    for row in rows:
        plots.extend(explode_plots(row))
    return rows, plots
