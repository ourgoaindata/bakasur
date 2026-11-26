"""Rows in the 39A master sheet's layout ("Substantive Objections" tab)."""

import csv
from datetime import date

import pytest

from bakasur.usecases.land_conversion_39a.gazette.header import gazette_info, notification_date
from bakasur.usecases.land_conversion_39a.models import ApplicationRow, GazetteInfo, NotificationSpan, TableVariant
from bakasur.usecases.land_conversion_39a.normalize.decision import format_area, recommended_area, tcp_comments
from bakasur.usecases.land_conversion_39a.normalize.survey import split_survey
from bakasur.usecases.land_conversion_39a.normalize.villages import VillageLookup
from bakasur.usecases.land_conversion_39a.normalize.zones import overlays, zone_codes
from bakasur.usecases.land_conversion_39a.sinks.files import FileSink
from bakasur.usecases.land_conversion_39a.sinks.master import MASTER_HEADER, gazette_reference, master_rows

OG28 = GazetteInfo(series="III", issue_no="28", published=date(2026, 10, 8))


@pytest.fixture(scope="module")
def lookup() -> VillageLookup:
    return VillageLookup()


def _row(**fields) -> ApplicationRow:
    base = dict(
        gazette_id="g",
        source_filename="g.pdf",
        notification_no="36/18/39A/Notification (77)/TCP/2026/1114",
        table_variant=TableVariant.CHANGE_OF_ZONE,
        sr_no="1.",
        applicant="Ashley Edward Rebello & Amrit Kaur",
        survey_raw="49/1- -A75 (Part)",
        village="Guirdolim",
        taluka="Salcete",
        existing_use="Partly Orchard (405m2), Partly Paddy Field (42m2) Total Area (447)",
        total_area_sqm=447,
        proposed_use="Settlement Zone",
        area_proposed_sqm=447,
        decision="Recommended for change of Zone an area of 405m2 from Orchard to Settlement Zone.",
        page_from=1,
        page_to=3,
        notification_date=date(2026, 10, 7),
    )
    return ApplicationRow(**{**base, **fields})


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("49/1- -A75 (Part)", ("49/1-A75", "(part)")),
        ("196A/1- D", ("196A/1-D", "")),
        ("74/1, Plot No. 16 (Part)", ("74/1", "(part) (plot 16)")),
        ("14/2 Plot A", ("14/2", "(plot A)")),
        ("204/0 (Part A)", ("204/0", "(part A)")),
        ("256/2, Plot No.", ("256/2", "")),
    ],
)
def test_split_survey(raw, expected):
    assert split_survey(raw) == expected


@pytest.mark.parametrize(
    "text, settlement, expected",
    [
        ("Partly Orchard (405m2), Partly Paddy Field (42m2) Total Area (447)", "S-3", ["A-2", "A-1"]),
        ("Natural Cover with No Development Slope Total Area (364)", "S-3", ["A-2"]),
        ("Partly Settlement (2797m2), Partly Orchard with No Development Slope (649m2)", "S-2", ["S-2", "A-2"]),
        ("Partly Settlement (160m2) Partly Natural Cover (414m2)", None, ["Settlement", "A-2"]),
        ("Protected/ Reserved Forest with Irrigation Command Area Total Area (520)", "S-3", ["FOREST"]),
        # Codes printed in the gazette win over the words around them, OCR splits included.
        ("Partly Residential (S4) (3722m2), Partly Natural Reserve/Orchard (A2) (6738m2)", "S-3", ["S-4", "A-2"]),
        ("Residentia l (S1)", "S-3", ["S-1"]),
        ("Settlement Zone", "S-2", ["S-2"]),
    ],
)
def test_zone_codes(text, settlement, expected):
    assert zone_codes(text, settlement) == expected


def test_overlays():
    assert overlays("Natural Cover with Irrigation Command Area Total Area (260)") == ["NC", "CADA"]
    assert overlays("Orchard with No Development Slope within Disaster Management Site") == ["NDS", "DMS"]
    assert overlays(
        "Partly Orchard (30426m2), Partly Orchard with No Development Slope (170m2) "
        "Property is partly within 500 HTL Total Area (30596)"
    ) == ["NDS", "CRZ"]
    assert overlays("Orchard Total Area (400)") == []


def test_recommended_area_sums_the_areas_the_decision_lists():
    decision = (
        "Recommended for change of zone an area of 2435m2 from Orchard to Settlement zone and an area "
        "of 1579m2 from Orchard with No Development Slope to Settlement zone being within permissible gradient"
    )
    assert recommended_area(decision, 4200) == 4014
    assert recommended_area("Recommended for change of zone an area of 199.56m2 from Orchard to Settlement zone.", 320) == 199.56
    assert recommended_area("Recommended for change of zone.", 340) == 340
    assert recommended_area("Not recommended for change of zone.", 340) is None


def test_tcp_comments():
    decision = (
        "Recommended for change of Zone an area of 1985m2 from Cultivable land with Irrigation Command Area "
        "to Settlement zone and an area of 175m2 from Orchard to Settlement Zone subject to comments from "
        "Water Resources Department and GCZMA"
    )
    assert tcp_comments(decision) == (
        "1,985 sqm from Cultivable land with Irrigation Command Area to Settlement zone\n"
        "175 sqm from Orchard to Settlement Zone\n"
        "Subject to comments from WRD and GCZMA"
    )
    assert tcp_comments("Recommended for change of zone being within permissible gradient.") == (
        "For being within permissible gradient"
    )
    assert tcp_comments("Recommended for change of zone.") == ""
    assert tcp_comments(
        "Recommended for change of zone being not low lying paddy field subject to comments from "
        "Water Resources Department."
    ) == "Being not low lying paddy field\nSubject to comments from WRD"
    assert tcp_comments("Recommended for change of zone being not low lying.") == "Being not low lying"


def test_format_area():
    assert format_area(1777) == "1,777 sqm"
    assert format_area(199.56) == "199.56 sqm"
    assert format_area(None) == ""


def test_village_lookup_matches_on_taluka_and_gazette_spelling(lookup):
    (boma,) = lookup.find("Boma", "Ponda")
    assert (boma.vp_name, boma.constituency, boma.settlement_code) == ("Bhoma Adcolna", "Priol", "S-3")
    # Boma in Sanguem is a different village.
    (sanguem_boma,) = lookup.find("Boma", "Sanguem")
    assert sanguem_boma.vp_name == "Calem"
    assert lookup.find("Atlantis", "Bardez") == []


@pytest.mark.parametrize(
    "village, survey_no, panchayat",
    [
        ("Calangute", 76, "Candolim"),  # S. Nos 50-84 are in Candolim panchayat
        ("Calangute", 96, "Calangute"),
        ("Siolim", 360, "Siolim Marna"),
        ("Siolim", 256, "Sodiem-Siolim"),
    ],
)
def test_village_split_between_panchayats_uses_survey_number(lookup, village, survey_no, panchayat):
    (info,) = lookup.find(village, "Bardez", survey_no)
    assert info.vp_name == panchayat


def test_gazette_info_reads_the_masthead():
    page1 = (
        "SERIES I No. 28\n\n( EXTRAORDINARY )\n\nPanaji, O6th August, 2026 (Sravana 15, 1948)\n\n"
        "SERIES III No. 19\n\nGAZETTE"
    )
    info = gazette_info({1: page1, 2: "..."}, {})
    assert info == GazetteInfo(series="III", issue_no="19", published=date(2026, 8, 6))


def test_gazette_info_falls_back_to_filename_metadata():
    info = gazette_info({1: "no masthead"}, {"series": "SIII", "issue_no": "28", "gazette_date": "2026-10-08"})
    assert info == OG28


def test_notification_date_is_the_signature_after_its_number():
    pages = {
        3: "No. 36/18/39A/Notification (18N)/TCP/2026/776\n...\nPanaji, 5th August, 2026.",
        4: "No. 36/18/39A/Notification (70)/TCP/2026/780\n| table |",
        5: "By order...\n\nPanaji, 19 th August, 2026.\n\nPanaji, 30th July, 2026.— The Special Notary",
    }
    span = NotificationSpan(notification_no="36/18/39A/Notification (70)/TCP/2026/780", page_start=4, page_end=4)
    assert notification_date(pages, span) == date(2026, 8, 19)


def test_gazette_reference():
    assert gazette_reference(OG28, "36/18/39A/Notification (77)/TCP/2026/1114", date(2026, 10, 7)) == (
        "SIII No 28\n39A/(77)/2026/1114\ndtd 7-Oct-2026"
    )


def test_master_rows_fill_the_sheet_columns(lookup):
    rows = master_rows([_row(), _row(sr_no="17.", village="Boma", taluka="Ponda")], OG28, lookup)
    assert all(len(r) == len(MASTER_HEADER) == 28 for r in rows)
    first = dict(zip(MASTER_HEADER, rows[0]))
    assert first["Sr No"] == "1"
    assert (first["S. No."], first["Sub -Div"]) == ("49/1-A75", "(part)")
    assert (first["Old Zone (Primary)"], first["New Zone"]) == ("A-2, A-1", "S-3")
    assert (first["VP"], first["AC"]) == ("Guirdolim", "Cuncolim")
    assert (first["Area requested"], first["Area recommended"]) == ("447 sqm", "405 sqm")
    assert first["Deadline"] == "7-November-26"  # 30 days after publication
    assert first["Gaz Date"] == "8-October-26"
    assert first["Gazette link"] == "SIII No 28\n39A/(77)/2026/1114\ndtd 7-Oct-2026"
    assert first["TCP Comments"] == "405 sqm from Orchard to Settlement Zone"
    assert rows[1][0] == "2"  # Sr No counts rows in the file, not the gazette's numbering
    assert rows[1][MASTER_HEADER.index("VP")] == "Bhoma Adcolna"


def test_unknown_village_leaves_vp_columns_blank(lookup):
    (row,) = master_rows([_row(village="Atlantis")], OG28, lookup)
    out = dict(zip(MASTER_HEADER, row))
    assert (out["VP"], out["AC"], out["New Zone"]) == ("", "", "Settlement")


def test_file_sink_writes_master_csv(tmp_path, lookup):
    FileSink(tmp_path).append_rows([_row()], [], [], master=master_rows([_row()], OG28, lookup))
    (path,) = tmp_path.glob("*.master.csv")
    with path.open(encoding="utf-8", newline="") as f:
        header, *data = list(csv.reader(f))
    assert header == MASTER_HEADER
    assert len(data) == 1 and data[0][MASTER_HEADER.index("Rev Village")] == "Guirdolim"
