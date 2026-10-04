import json
from pathlib import Path

from bakasur.config import Settings
from bakasur.extract import DISPUTED_SPLIT_REASON, extract_39a_from_artifacts
from bakasur.parse.artifacts import ArtifactStore


def _write_artifacts(root: Path, gazette_id: str, pages: dict[int, str], tables: list[dict]) -> None:
    gdir = root / gazette_id
    (gdir / "pages").mkdir(parents=True)
    (gdir / "tables").mkdir(parents=True)
    (gdir / "meta.json").write_text(
        json.dumps({"gazette_id": gazette_id, "source_filename": "test.pdf", "sha256": "abc"}),
        encoding="utf-8",
    )
    for page_no, text in pages.items():
        (gdir / "pages" / f"{page_no:04d}.txt").write_text(text, encoding="utf-8")
    for table in tables:
        (gdir / "tables" / f"t{table['index']:04d}.json").write_text(json.dumps(table), encoding="utf-8")


def _coz_row(sr: str, name: str, survey: str, village: str) -> list[str]:
    return [sr, name, survey, village, "Natural Cover", "Settlement Zone", "300", "Recommended for change of zone"]


def test_extract_scanned_table_split_across_pages(tmp_path: Path):
    """Mirrors pages 7-8 of the 5th Aug 2026 scanned fixture (OCR drops most Sr. Nos.)."""
    table_line = "| | Name | 1/1 | Siolim | Natural Cover | Settlement Zone | 300 | Recommended for change of zone |"
    closing = "And whereas, in terms of sub-rule (1) of Rule 4 of the Goa Town and Country Planning Rules"
    pages = {
        7: (
            "Notification\n\nNo. 36/18/39A/Notification (70)/TCP/2026/780\n\n"
            "Whereas, ... under sub-section (1) of Section 39A ... for change of zone ...\n\n" + table_line
        ),
        8: "SERIES III No. 19\n\nOFFICIAL GAZETTE - GOVT. OF GOA OFFICIAL GALETTE\n\n" + table_line + "\n\n" + closing,
    }
    tables = [
        {
            "index": 0,
            "page_no": 7,
            "n_cols": 8,
            "header": [
                "Sr. No.",
                "Name of the applicant",
                "Sy.No./ Sub-Div. No./ Ch. No./ P.T.S. No.",
                "Village/ Taluka",
                "Published land use as per RPG 2021/ ODP/Total Area in sq. mts.",
                "Proposed land use",
                "Area proposed in sq. mts.",
                "Decision of the TCP Board",
            ],
            "grid": [
                ["(1)", "(2)", "(3)", "(4)", "(5)", "(6)", "(7)", "(8)"],
                _coz_row("", "Govind Sahadev Kerkar", "490/2-L", "Latambarcem, Bicholim"),
                _coz_row("", "Channappa Holeppanavar", "256/2, Plot No. 51", "Siolim, Bardez"),
                _coz_row("5.", "Mr. Rahul Sayal M/s Nirvana Nest Buildcon", "28/5", "Parra, Bardez"),
            ],
            "text_before": ["Notification", "No. 36/18/39A/Notification (70)/TCP/2026/780"],
            "text_after": [],
        },
        {
            "index": 1,
            "page_no": 8,
            "n_cols": 8,
            "header": ["1", "", "3", "4", "5", "6", "7", "8"],
            "grid": [
                ["", "Pvt Ltd., C/o Shailesh Mandrekar", "", "", "Slope Total Area (2425)", "", "", ""],
                _coz_row("6.", "Augustino Ferrao", "78/5-A (Part)", "Arpora, Bardez"),
                _coz_row("", "Sharmila Rajesh Mahambrey", "199/7-A", "Morjim, Pernem"),
            ],
            "text_before": ["SERIES III No. 19", "OFFICIAL GAZETTE - GOVT. OF GOA OFFICIAL GALETTE"],
            "text_after": [closing],
        },
    ]
    _write_artifacts(tmp_path, "scanned", pages, tables)

    rows, _ = extract_39a_from_artifacts(ArtifactStore(tmp_path), "scanned", Settings(llm_provider="heuristic"))

    assert [r.applicant for r in rows] == [
        "Govind Sahadev Kerkar",
        "Channappa Holeppanavar",
        "Mr. Rahul Sayal M/s Nirvana Nest Buildcon Pvt Ltd., C/o Shailesh Mandrekar",
        "Augustino Ferrao",
        "Sharmila Rajesh Mahambrey",
    ]
    assert {r.notification_no for r in rows} == {"36/18/39A/Notification (70)/TCP/2026/780"}
    assert {(r.page_from, r.page_to) for r in rows} == {(7, 8)}


def test_extract_holds_record_for_review_when_sr_sequence_and_contents_disagree(tmp_path: Path):
    closing = "And whereas, in terms of sub-rule (1) of Rule 4 of the Goa Town and Country Planning Rules"
    pages = {
        7: (
            "No. 36/18/39A/Notification (70)/TCP/2026/780\n\n"
            "Whereas, ... under sub-section (1) of Section 39A ... for change of zone ...\n\n" + closing
        ),
    }
    tables = [
        {
            "index": 0,
            "page_no": 7,
            "n_cols": 8,
            "header": ["Sr. No.", "Name of the applicant", "Sy.No.", "Village/ Taluka", "Published land use", "Proposed land use", "Area proposed in sq. mts.", "Decision of the TCP Board"],
            "grid": [
                _coz_row("5.", "Rahul Sayal", "28/5,", "Parra,"),
                ["", "Nirvana Nest", "28/6", "Bardez", "", "", "", ""],  # looks like a record, but 5 then 6
                _coz_row("6.", "Augustino Ferrao", "78/5-A", "Arpora, Bardez"),
            ],
            "text_before": ["No. 36/18/39A/Notification (70)/TCP/2026/780"],
            "text_after": [closing],
        },
    ]
    _write_artifacts(tmp_path, "disputed", pages, tables)

    rows, _ = extract_39a_from_artifacts(ArtifactStore(tmp_path), "disputed", Settings(llm_provider="heuristic"))

    assert [(r.applicant, r.review_reason) for r in rows] == [
        ("Rahul Sayal Nirvana Nest", DISPUTED_SPLIT_REASON),
        ("Augustino Ferrao", None),
    ]


def _ndz_row(sr: str, survey: str, village: str) -> list[str]:
    return [sr, survey, village, "Paddy Fields", "No Development Zone", "Total Area (100)", "Recommended for Non Developable Area."]


def test_extract_flags_rows_from_page_with_merged_sr_column(tmp_path: Path):
    """Mirrors pages 4-5 of the 5th Aug 2026 fixture: page 5 folds the Sr. No. column into the survey column."""
    closing = "And whereas, in terms of sub-rule (1) of Rule 4 of the Goa Town and Country Planning Rules"
    pages = {
        4: "No. 36/18/39A/Notification (19N)/TCP/2026/700\n\nWhereas, ... Section 39A ... No Development Zone ...",
        5: "SERIES III No. 19\n\n" + closing,
    }
    tables = [
        {
            "index": 0,
            "page_no": 4,
            "n_cols": 7,
            "header": ["Sr. No.", "Sy.No./ Sub-Div. No.", "Village/ Taluka", "Published land use", "Proposed land use", "Area proposed in sq. mts.", "Decision of the TCP Board"],
            "grid": [_ndz_row("5.", "73/1 to 38 (P)", "Nuvem, Salcete"), _ndz_row("6.", "25, 22/1 & 2", "Raia, Salcete")],
            "text_before": ["No. 36/18/39A/Notification (19N)/TCP/2026/700"],
            "text_after": [],
        },
        {
            "index": 1,
            "page_no": 5,
            "n_cols": 6,
            "header": ["2", "3", "4", "5", "6", "7"],
            "grid": [_ndz_row("", "7. pt, 172/1 28/1 to 18", "Rachol, Salcete")[1:]],
            "text_before": ["SERIES III No. 19"],
            "text_after": [closing],
        },
    ]
    _write_artifacts(tmp_path, "merged", pages, tables)

    rows, _ = extract_39a_from_artifacts(ArtifactStore(tmp_path), "merged", Settings(llm_provider="heuristic"))

    assert [(r.village, r.review_reason is not None) for r in rows] == [
        ("Nuvem", False),
        ("Raia", True),
        ("Rachol", True),
    ]


def test_extract_from_mock_artifacts(tmp_path: Path):
    gazette_id = "test_gazette"
    gdir = tmp_path / gazette_id
    (gdir / "pages").mkdir(parents=True)
    (gdir / "tables").mkdir(parents=True)

    (gdir / "meta.json").write_text(
        json.dumps(
            {
                "gazette_id": gazette_id,
                "source_filename": "test.pdf",
                "sha256": "abc",
                "page_count": 2,
            }
        ),
        encoding="utf-8",
    )
    (gdir / "pages" / "0001.txt").write_text(
        "Section 39A of the Goa Town and Country Planning Act\n"
        "Notification No. 36/18/39A/Notification (19N)/TCP/2026/851\n"
        "change of zone in the Regional Plan",
        encoding="utf-8",
    )
    (gdir / "pages" / "0002.txt").write_text(
        "And whereas, in terms of sub-rule (1) of rule 4 of the said Rules",
        encoding="utf-8",
    )
    table = {
        "index": 0,
        "page_no": 1,
        "n_rows": 3,
        "n_cols": 8,
        "grid": [
            ["Sr. No.", "Name of the applicant", "Sy. No.", "Village/Taluka", "Published land use", "Proposed land use", "Area proposed", "Decision"],
            ["1", "2", "3", "4", "5", "6", "7", "8"],
            [
                "19.",
                "Anil Albuquerque & others",
                "74/1, Plot No. 14",
                "Guirdolim, Salcete",
                "Orchard Total Area (301.68)",
                "Settlement Zone",
                "301.68",
                "Recommended for change of zone.",
            ],
        ],
    }
    (gdir / "tables" / "t0000.json").write_text(json.dumps(table), encoding="utf-8")

    cfg = Settings(llm_provider="heuristic")
    store = ArtifactStore(tmp_path)
    rows, plots = extract_39a_from_artifacts(store, gazette_id, cfg)

    assert len(rows) == 1
    assert rows[0].applicant == "Anil Albuquerque & others"
    assert rows[0].village == "Guirdolim"
    assert rows[0].taluka == "Salcete"
    assert "74/1" in (rows[0].survey_raw or "")
