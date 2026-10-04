from bakasur.config import Settings
from bakasur.gazette.anchors import (
    NOTIFICATION_RE,
    AnchorConfig,
    find_notification_spans,
)
from bakasur.models import TableVariant


def _cfg() -> AnchorConfig:
    s = Settings()
    return AnchorConfig(
        anchor_patterns=s.anchor_patterns,
        span_end_patterns=s.span_end_patterns,
        running_text_patterns=s.running_text_patterns,
    )


def _table(page: int, **extra) -> dict:
    return {"page_no": page, "index": page, "n_cols": 8, "grid": [["1.", "x"]], **extra}


TABLE_LINE = "| 6. | Augustino | 78/5-A | Arpora | Cultivable | Settlement | 1999 | Recommended for change of zone |"


def test_notification_number_with_parenthesized_suffix():
    text = (
        "Notification\r\n"
        "No. 36/18/39A/Notification (19N)/TCP/2026/851 \r\n"
        "Whereas, The Government of Goa has issued direction"
    )
    m = NOTIFICATION_RE.search(text)
    assert m.group(1).strip() == "36/18/39A/Notification (19N)/TCP/2026/851"


def test_find_notification_span():
    pages = {
        10: "Section 39A of the Goa Town and Country Planning Act\nNotification No. 36/18/39A/Notification",
        11: "Sr. No. Name of the applicant Sy. No.",
        12: "1. Goldshield Real Estates 113/1 Guirdolim",
        13: "And whereas, in terms of sub-rule (1) of rule 4 of the said Rules",
    }
    cfg = AnchorConfig(
        anchor_patterns=[r"Section\s+39A", r"39A/Notification"],
        span_end_patterns=[r"And whereas, in terms of sub-rule \(1\) of rule 4"],
    )
    spans = find_notification_spans(pages, cfg)
    assert len(spans) == 1
    assert spans[0].page_start == 10
    assert spans[0].page_end >= 11
    assert spans[0].variant_hint == TableVariant.CHANGE_OF_ZONE


def test_table_cells_do_not_start_new_spans():
    pages = {
        7: "Notification\n\nNo. 36/18/39A/Notification (70)/TCP/2026/780\n\nchange of zone\n\n" + TABLE_LINE,
        8: "SERIES III No. 19\n\n" + TABLE_LINE,
        9: "SERIES III No. 19\n\n" + TABLE_LINE,
    }
    spans = find_notification_spans(pages, _cfg())
    assert [(s.page_start, s.page_end) for s in spans] == [(7, 9)]
    assert spans[0].notification_no == "36/18/39A/Notification (70)/TCP/2026/780"


def test_span_ends_where_table_is_followed_by_text():
    pages = {
        7: "No. 36/18/39A/Notification (70)/TCP/2026/780\n\n" + TABLE_LINE,
        8: "SERIES III No. 19\n\n" + TABLE_LINE + "\n\nBy order and in the name of the Governor of Goa.",
        9: "Some unrelated notice",
        10: "More unrelated text",
    }
    tables = [
        _table(7),
        _table(8, text_before=["SERIES III No. 19"], text_after=["By order and in the name of the Governor of Goa."]),
    ]
    spans = find_notification_spans(pages, _cfg(), tables)
    assert [(s.page_start, s.page_end) for s in spans] == [(7, 8)]


def test_span_ends_when_next_page_starts_with_text():
    pages = {
        2: "No. 36/18/39A/Notification (19N)/TCP/2026/851\n\nNo Development Zone\n\n" + TABLE_LINE,
        3: TABLE_LINE,
        4: "Unrelated notice text",
    }
    tables = [_table(2), _table(3), _table(4, text_before=["Unrelated notice text"])]
    spans = find_notification_spans(pages, _cfg(), tables)
    assert [(s.page_start, s.page_end) for s in spans] == [(2, 3)]


def test_closing_page_mentioning_section_39a_is_not_a_new_notification():
    closing = "And whereas, in terms of sub-rule (1) of rule 4 ... Section 39A of the said Act."
    pages = {
        7: "No. 36/18/39A/Notification (70)/TCP/2026/780\n\n" + TABLE_LINE,
        8: TABLE_LINE,
        9: TABLE_LINE + "\n\n" + closing,
    }
    tables = [_table(7), _table(8), _table(9, text_after=[closing])]
    spans = find_notification_spans(pages, _cfg(), tables)
    assert [(s.page_start, s.page_end) for s in spans] == [(7, 9)]


def test_new_notification_starting_on_closing_page():
    closing = "And whereas, in terms of sub-rule (1) of rule 4 of the said Rules"
    new_header = "Notification No. 36/18/39A/Notification (72)/TCP/2026/854"
    pages = {
        2: "Notification No. 36/18/39A/Notification (19N)/TCP/2026/851\n\n" + TABLE_LINE,
        3: TABLE_LINE,
        4: TABLE_LINE + "\n\n" + closing + "\n\n" + new_header,
        5: "Sr. No. Name of the applicant\n\n" + TABLE_LINE,
    }
    tables = [
        _table(2),
        _table(3),
        {**_table(4), "index": 40, "text_after": [closing, new_header]},
        _table(5, text_before=["Sr. No. Name of the applicant"]),
    ]
    spans = find_notification_spans(pages, _cfg(), tables)
    assert [(s.notification_no, s.page_start, s.page_end) for s in spans] == [
        ("36/18/39A/Notification (19N)/TCP/2026/851", 2, 4),
        ("36/18/39A/Notification (72)/TCP/2026/854", 4, 5),
    ]
