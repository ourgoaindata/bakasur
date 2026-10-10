from bakasur.models import ApplicationRow, TableVariant
from bakasur.validate import partition_rows


def _row(
    sr_no: str,
    notification_no: str | None,
    survey: str | None = "74/1",
    taluka: str | None = "Salcete",
) -> ApplicationRow:
    return ApplicationRow(
        gazette_id="g1",
        source_filename="g1.pdf",
        notification_no=notification_no,
        table_variant=TableVariant.CHANGE_OF_ZONE,
        sr_no=sr_no,
        applicant="A",
        survey_raw=survey,
        village="Guirdolim",
        taluka=taluka,
        existing_use=None,
        total_area_sqm=None,
        proposed_use=None,
        area_proposed_sqm=None,
        decision=None,
        page_from=1,
        page_to=1,
    )


def test_same_sr_no_in_different_notifications_is_not_duplicate():
    rows = [_row("1.", "N1"), _row("2.", "N1"), _row("1.", "N2"), _row("2.", "N2")]
    good, issues = partition_rows(rows)
    assert len(good) == 4
    assert issues == []


def test_duplicate_sr_no_within_notification_is_rejected():
    rows = [_row("1.", "N1"), _row("1.", "N1")]
    good, issues = partition_rows(rows)
    assert len(good) == 1
    assert any("Duplicate sr_no" in i.reason for i in issues)


def test_gap_reported_per_notification():
    rows = [_row("1.", "N1"), _row("3.", "N1"), _row("10.", "N2"), _row("11.", "N2")]
    good, issues = partition_rows(rows)
    assert len(good) == 4
    gaps = [i for i in issues if "gap" in i.reason]
    assert len(gaps) == 1
    assert "N1" in gaps[0].reason


def test_missing_survey_is_rejected():
    good, _ = partition_rows([_row("1.", "N1", survey=None)])
    assert good == []


def test_row_flagged_at_extraction_is_held_for_review():
    flagged = _row("2.", "N1")
    flagged.review_reason = "Survey numbers may be mixed"
    good, issues = partition_rows([_row("1.", "N1"), flagged])
    assert len(good) == 1 and good[0] is not flagged
    assert [(i.row, i.reason, i.severity) for i in issues] == [(flagged, "Survey numbers may be mixed", "error")]


def test_missing_taluka_is_rejected():
    # OCR can drop the taluka from "Marcaim, Ponda", leaving just "Pontaim,".
    good, issues = partition_rows([_row("1.", "N1", taluka=None)])
    assert good == []
    assert [(i.reason, i.severity) for i in issues] == [("Missing taluka", "error")]


def test_unknown_taluka_is_rejected():
    good, issues = partition_rows([_row("1.", "N1", taluka="Pontaim")])
    assert good == []
    assert [(i.reason, i.severity) for i in issues] == [("Unknown taluka: Pontaim", "error")]


def test_known_taluka_is_case_and_whitespace_insensitive():
    good, issues = partition_rows([_row("1.", "N1", taluka=" ponda ")])
    assert len(good) == 1
    assert issues == []
