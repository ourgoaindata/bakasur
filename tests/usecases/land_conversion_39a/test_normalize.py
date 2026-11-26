from bakasur.usecases.land_conversion_39a.normalize.area import extract_total_area, parse_area
from bakasur.usecases.land_conversion_39a.normalize.place import is_known_taluka, split_village_taluka
from bakasur.usecases.land_conversion_39a.normalize.survey import expand_survey_raw


def test_parse_area():
    assert parse_area("13,80,498") == 1380498
    assert parse_area("301.68") == 301.68
    assert parse_area("447") == 447 and isinstance(parse_area("447"), int)
    assert parse_area("-") is None


def test_extract_total_area():
    assert extract_total_area("Total Area (13,80,498)") == 1380498
    assert extract_total_area("Partly Orchard (199.56m2) Total Area (319.56)") == 319.56


def test_split_village_taluka():
    village, taluka = split_village_taluka("Guirdolim, Salcete")
    assert village == "Guirdolim"
    assert taluka == "Salcete"
    assert split_village_taluka("Salvador- do-Mundo, Bardez") == ("Salvador-do-Mundo", "Bardez")
    assert is_known_taluka(taluka)


def test_expand_survey_range():
    entries = expand_survey_raw("201/1 to 41, 193/0 (P)")
    nums = {e.survey_number for e in entries}
    assert "201/1" in nums
    assert "201/41" in nums
    assert any(e.is_part for e in entries if e.survey_number == "193/0")
