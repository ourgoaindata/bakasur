import pytest

from bakasur.config import Settings
from bakasur.gazette.tables import (
    StitchedTable,
    apply_column_map,
    merge_continuation_rows,
    split_header,
    stitch_tables,
)
from bakasur.models import ColumnMap

RUNNING = Settings().running_text_patterns
HEADER = [
    "Sr. No.",
    "Name of the applicant",
    "Sy.No./ Sub-Div. No.",
    "Village/ Taluka",
    "Published land use",
    "Proposed land use",
    "Area proposed in sq. mts.",
    "Decision of the TCP Board",
]
COZ_MAP = ColumnMap(
    sr_no=0,
    applicant=1,
    survey=2,
    village_taluka=3,
    existing_use=4,
    proposed_use=5,
    area_proposed=6,
    decision=7,
)


def _row(sr: str, name: str, survey: str = "1/1", village: str = "Siolim, Bardez") -> list[str]:
    return [sr, name, survey, village, "Orchard", "Settlement Zone", "300", "Recommended"]


def _table(page: int, grid: list[list[str]], **extra) -> dict:
    return {"page_no": page, "index": page, "n_cols": len(grid[0]), "grid": grid, **extra}


def test_stitch_adjacent_tables():
    t1 = {
        "page_no": 5,
        "index": 0,
        "n_cols": 7,
        "grid": [["1", "2", "3"], ["7.", "206/1", "Curchirem"]],
    }
    t2 = {
        "page_no": 6,
        "index": 1,
        "n_cols": 7,
        "grid": [["1", "2", "3"], ["", "194/13", "more surveys"]],
    }
    stitched = stitch_tables([t1, t2])
    assert len(stitched) == 1
    assert len(stitched[0].rows) >= 2


def test_stitch_ignores_running_page_header_and_column_number_header():
    t1 = _table(7, [_row("5.", "Rahul Sayal")], header=HEADER)
    t2 = _table(
        8,
        [_row("6.", "Augustino Ferrao")],
        header=["1", "", "3", "4", "5", "6", "7", "8"],
        text_before=["SERIES III No. 19", "OFFICIAL GAZETTE - GOVT. OF GOA OFFICIAL GALETTE"],
    )
    stitched = stitch_tables([t1, t2], RUNNING)
    assert len(stitched) == 1
    assert stitched[0].header == HEADER


def test_no_stitch_when_text_follows_table():
    t1 = _table(7, [_row("5.", "A")], text_after=["And whereas, in terms of sub-rule (1) of rule 4"])
    t2 = _table(8, [_row("6.", "B")])
    assert len(stitch_tables([t1, t2], RUNNING)) == 2


def test_no_stitch_when_text_precedes_next_table():
    t1 = _table(7, [_row("5.", "A")])
    t2 = _table(8, [_row("6.", "B")], text_before=["SERIES III No. 19", "Notice", "The following budget"])
    assert len(stitch_tables([t1, t2], RUNNING)) == 2


def test_long_body_text_mentioning_gazette_is_not_running_text():
    t1 = _table(7, [_row("5.", "A")], text_after=["OFFICIAL GAZETTE - GOVT. OF GOA " + "x" * 100])
    t2 = _table(8, [_row("6.", "B")])
    assert len(stitch_tables([t1, t2], RUNNING)) == 2


def test_no_stitch_when_next_table_has_different_header():
    t1 = _table(7, [_row("5.", "A")], header=HEADER)
    t2 = _table(8, [["x"] * 8], header=["Book No.", "Receipt Range", "Receipts", "Sub-Total", "", "", "", ""])
    assert len(stitch_tables([t1, t2], RUNNING)) == 2


def test_repeated_header_stitches():
    t1 = _table(7, [_row("5.", "A")], header=HEADER)
    t2 = _table(8, [_row("6.", "B")], header=[h.upper() for h in HEADER])
    assert len(stitch_tables([t1, t2], RUNNING)) == 1


def test_no_stitch_when_sr_no_restarts():
    t1 = _table(7, [_row("4.", "A"), _row("5.", "B")])
    t2 = _table(8, [_row("1.", "C"), _row("2.", "D")])
    assert len(stitch_tables([t1, t2], RUNNING)) == 2


def test_missing_sr_nos_do_not_block_stitch():
    t1 = _table(7, [_row("5.", "A"), _row("", "B")])
    t2 = _table(8, [_row("", "C"), _row("", "D")])
    assert len(stitch_tables([t1, t2], RUNNING)) == 1


def test_no_stitch_across_non_adjacent_pages_or_column_mismatch():
    t1 = _table(7, [_row("5.", "A")])
    t2 = _table(9, [_row("6.", "B")])
    t3 = _table(10, [_row("7.", "C")[:6]])
    assert len(stitch_tables([t1, t2, t3], RUNNING)) == 3


NDZ_HEADER = ["Sr. No.", "Sy.No.", "Village/ Taluka", "Published land use", "Proposed land use", "Area", "Decision"]
NDZ_MAP = ColumnMap(sr_no=0, survey=1, village_taluka=2, existing_use=3, proposed_use=4, area_proposed=5, decision=6)


def _ndz_tail(village: str) -> list[str]:
    return [village, "Paddy Fields", "No Development Zone", "Total Area (100)", "Recommended for Non Developable Area."]


def test_merged_sr_column_mid_cell_splits_off_overflow_exactly():
    """OG21 p3: Docling folds column 1 into 2 and the next Sr. No. sits mid-cell after the overflow."""
    t1 = _table(2, [["1.", "48/7 to 9, 196/1 to 8,", *_ndz_tail("Guirdolim, Salcete")]], header=NDZ_HEADER)
    t2 = _table(
        3,
        [["194/13, 136/3- A 2. 203/1 to 5, 79/1 to 21", *_ndz_tail("Navelim, Salcete")]],
        header=["1 2", "3", "4", "5", "6", "7"],
    )
    [stitched] = stitch_tables([t1, t2], RUNNING)
    assert stitched.suspect_sr == set()
    merged, disputed = merge_continuation_rows(stitched.rows, NDZ_MAP)
    assert disputed == set()
    assert [(r[0], r[1], r[2]) for r in merged] == [
        ("1.", "48/7 to 9, 196/1 to 8, 194/13, 136/3- A", "Guirdolim, Salcete"),
        ("2.", "203/1 to 5, 79/1 to 21", "Navelim, Salcete"),
    ]


def test_merged_sr_column_at_cell_start_flags_rows_and_previous_record():
    """OG19 p5: Sr. Nos. start the merged cells, and Docling misplaced the row boundaries."""
    t1 = _table(4, [["6.", "25, 22/1 & 2, 173/4", *_ndz_tail("Raia, Salcete")]], header=NDZ_HEADER)
    t2 = _table(
        5,
        [
            ["7. pt, 172/1, 119/7 to 11 28/1 to 18, 21/1 to 3,", *_ndz_tail("Rachol, Salcete")],
            ["8. 18/1 to 7, 2/1 (P) 496/1-B, 296/2", *_ndz_tail("Latambarcem, Bicholim")],
        ],
        header=["2", "3", "4", "5", "6", "7"],
    )
    t3 = _table(6, [["9.", "206/1", *_ndz_tail("Curchirem, Bicholim")]], header=["1", "2", "3", "4", "5", "6", "7"])
    [stitched] = stitch_tables([t1, t2, t3], RUNNING)
    assert [r[:3] for r in stitched.rows][1:3] == [
        ["7.", "pt, 172/1, 119/7 to 11 28/1 to 18, 21/1 to 3,", "Rachol, Salcete"],
        ["8.", "18/1 to 7, 2/1 (P) 496/1-B, 296/2", "Latambarcem, Bicholim"],
    ]
    assert stitched.suspect_sr == {6, 7, 8}


def test_merge_continuation_row():
    grid = [
        ["7.", "206/1", "Curchirem, Bicholim", "Paddy", "NDZ", "Total Area (1380498)", "Recommended"],
        ["", "194/13, 194/14", "", "", "", "", ""],
    ]
    col_map = ColumnMap(
        sr_no=0,
        survey=1,
        village_taluka=2,
        existing_use=3,
        proposed_use=4,
        area_proposed=5,
        decision=6,
    )
    merged, _ = merge_continuation_rows(grid, col_map)
    assert len(merged) == 1
    assert "194/13" in merged[0][1]


def test_row_with_own_survey_and_village_is_new_record_despite_missing_sr():
    rows = [
        _row("5.", "Rahul Sayal", survey="28/5", village="Parra, Bardez"),
        ["", "Pvt Ltd., C/o Shailesh", "", "", "Slope", "", "", "zone"],
        _row("", "Sharmila Mahambrey", survey="199/7-A", village="Morjim, Pernem"),
    ]
    merged, _ = merge_continuation_rows(rows, COZ_MAP)
    assert [r[1] for r in merged] == [
        "Rahul Sayal Pvt Ltd., C/o Shailesh",
        "Sharmila Mahambrey",
    ]


def test_sr_sequence_and_content_agree_on_dropped_sr_and_overflow():
    rows = [
        _row("5.", "A", survey="28/5", village="Parra, Bardez"),
        ["", "A cont.", "", "", "Slope", "", "", ""],  # 5 then 6: overflow
        _row("6.", "B"),
        _row("", "C", survey="199/7-A", village="Morjim, Pernem"),  # 6 then 8: Sr. No. 7 dropped
        _row("8.", "D"),
    ]
    merged, disputed = merge_continuation_rows(rows, COZ_MAP)
    assert [r[1] for r in merged] == ["A A cont.", "B", "C", "D"]
    assert disputed == set()


def test_sr_sequence_overrides_content_when_next_number_follows():
    # The overflow carries a survey and a village fragment (wrapped across the page break),
    # which alone looks like a record whose Sr. No. was dropped; 5 then 6 says it isn't.
    rows = [
        _row("5.", "A", survey="28/5,", village="Parra,"),
        ["", "A cont.", "28/6", "Bardez", "", "", "", ""],
        _row("6.", "B"),
    ]
    merged, disputed = merge_continuation_rows(rows, COZ_MAP)
    assert [r[1] for r in merged] == ["A A cont.", "B"]
    assert merged[0][3] == "Parra, Bardez"
    assert disputed == {0}


def test_sr_sequence_overrides_content_when_gap_matches_blank_rows():
    # No village (OCR lost it), so by content this continues 8; 8 then 10 says it is record 9.
    rows = [
        _row("8.", "A"),
        _row("", "B", survey="206/1", village=""),
        _row("10.", "C"),
    ]
    merged, disputed = merge_continuation_rows(rows, COZ_MAP)
    assert [r[1] for r in merged] == ["A", "B", "C"]
    assert disputed == {0, 1}


WRAPPED = ["", "X", "28/6", "Bardez", "", "", "", ""]  # own survey and village: a record by content


@pytest.mark.parametrize(
    ("rows", "names"),
    [
        # Nothing numbered above: OG19's change-of-zone rows 1-4 lost their Sr. Nos.
        ([_row("", "A"), WRAPPED, _row("5.", "B")], ["A", "X", "B"]),
        # An unreadable Sr. No. ("-" in OG19) in between.
        ([_row("1.", "A"), _row("-", "B"), WRAPPED, _row("3.", "C")], ["A", "B", "X", "C"]),
        # Numbering goes backwards.
        ([_row("5.", "A"), WRAPPED, _row("2.", "B")], ["A", "X", "B"]),
    ],
)
def test_content_decides_when_sr_sequence_is_inconclusive(rows, names):
    merged, disputed = merge_continuation_rows(rows, COZ_MAP)
    assert [r[1] for r in merged] == names
    assert disputed == set()


def test_parenthesised_column_number_row_is_skipped():
    table = StitchedTable(
        header=HEADER,
        rows=[
            ["(1)", "(2)", "(3)", "(4)", "(5)", "(6)", "(7)", "(8)"],
            _row("", "Govind Kerkar", survey="490/2-L", village="Latambarcem, Bicholim"),
            _row("", "Channappa Holeppanavar", survey="256/2", village="Siolim, Bardez"),
        ],
    )
    header, data = split_header(table)
    assert header == HEADER
    records = apply_column_map(merge_continuation_rows(data, COZ_MAP)[0], COZ_MAP)
    assert [r["applicant"] for r in records] == ["Govind Kerkar", "Channappa Holeppanavar"]


def test_split_header_without_header_keeps_first_data_row():
    table = StitchedTable(header=["1", "2", "3", "4", "5", "6", "7", "8"], rows=[_row("11.", "Realcon")])
    header, data = split_header(table)
    assert header == [""] * 8
    assert data == [_row("11.", "Realcon")]
