from bakasur.normalize.area import extract_total_area, parse_indian_int
from bakasur.normalize.place import is_known_taluka, split_village_taluka
from bakasur.normalize.survey import expand_survey_raw


def test_parse_indian_int():
    assert parse_indian_int("13,80,498") == 1380498
    assert parse_indian_int("301.68") == 301


def test_extract_total_area():
    assert extract_total_area("Total Area (13,80,498)") == 1380498


def test_split_village_taluka():
    village, taluka = split_village_taluka("Guirdolim, Salcete")
    assert village == "Guirdolim"
    assert taluka == "Salcete"
    assert is_known_taluka(taluka)


def test_expand_survey_range():
    entries = expand_survey_raw("201/1 to 41, 193/0 (P)")
    nums = {e.survey_number for e in entries}
    assert "201/1" in nums
    assert "201/41" in nums
    assert any(e.is_part for e in entries if e.survey_number == "193/0")
