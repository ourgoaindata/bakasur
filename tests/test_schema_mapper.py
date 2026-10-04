import json

import httpx
import pytest

from bakasur.config import Settings
from bakasur.llm.schema_mapper import (
    HeuristicFirstMapper,
    OllamaMapper,
    OpenAICompatMapper,
    _mapper_from_json,
    get_mapper,
    heuristic_map_columns,
)
from bakasur.models import MapperResult, TableVariant

COZ_HEADER = [
    "Sr. No.",
    "Name of the applicant",
    "Sy. No.",
    "Village/Taluka",
    "Published land use",
    "Proposed land use",
    "Area proposed",
    "Decision",
]

GOOD_LLM_JSON = {
    "is_39a": True,
    "variant": "change_of_zone",
    "column_map": {
        "sr_no": 0,
        "applicant": 1,
        "survey": 2,
        "village_taluka": 3,
        "existing_use": 4,
        "proposed_use": 5,
        "area_proposed": 6,
        "decision": 7,
    },
}

# First data row of OG19's change-of-zone table.
COZ_SAMPLE = [
    "1.",
    "Govind Sahadev Kerkar & Sharmila Govind Kerkar",
    "490/2-L",
    "Latambarcem, Bicholim",
    "Natural Cover with Irrigation Command Area Total Area (319)",
    "Settlement Zone",
    "319",
    "Recommended for change of zone subject to comments from Water Resource Department.",
]

# The map qwen2.5:7b returned for that table: existing_use dropped, later fields shifted left.
SHIFTED_LLM_JSON = {
    **GOOD_LLM_JSON,
    "column_map": {
        **GOOD_LLM_JSON["column_map"],
        "existing_use": None,
        "proposed_use": 4,
        "area_proposed": 5,
        "decision": 6,
    },
}


def test_heuristic_maps_standard_header():
    result = heuristic_map_columns(COZ_HEADER, [])
    assert result.is_39a
    assert result.variant == TableVariant.CHANGE_OF_ZONE
    assert result.column_map.as_dict() == GOOD_LLM_JSON["column_map"]


def test_heuristic_prefers_specific_alias_over_bare_name():
    header = ["Sr. No.", "Name of Village", "Name of the applicant", "Sy. No.", "Decision"]
    col_map = heuristic_map_columns(header, []).column_map
    assert col_map.village_taluka == 1
    assert col_map.applicant == 2


def test_heuristic_anchors_aliases_at_word_start():
    # "approach." contains "ch." and "easy" contains "sy", but neither is a survey column.
    header = ["Sr. No.", "Approach. road", "Easy access", "Decision"]
    assert not heuristic_map_columns(header, []).is_39a


def test_mapper_from_json_accepts_valid_map():
    result = _mapper_from_json(GOOD_LLM_JSON, ncols=8)
    assert result.is_39a
    assert result.column_map.decision == 7


def test_mapper_from_json_respects_not_39a():
    assert not _mapper_from_json({"is_39a": False}, ncols=8).is_39a


@pytest.mark.parametrize(
    "data",
    [
        {"columns": {}},  # wrong shape, no is_39a
        {**GOOD_LLM_JSON, "column_map": {**GOOD_LLM_JSON["column_map"], "decision": 8}},
        {**GOOD_LLM_JSON, "column_map": {**GOOD_LLM_JSON["column_map"], "survey": None}},
        {**GOOD_LLM_JSON, "column_map": {**GOOD_LLM_JSON["column_map"], "survey": "2"}},
        {**GOOD_LLM_JSON, "column_map": {**GOOD_LLM_JSON["column_map"], "decision": 2}},
        {**GOOD_LLM_JSON, "variant": "something_else"},
    ],
)
def test_mapper_from_json_rejects_bad_output(data):
    with pytest.raises(ValueError):
        _mapper_from_json(data, ncols=8)


def test_mapper_from_json_accepts_map_matching_samples():
    assert _mapper_from_json(GOOD_LLM_JSON, ncols=8, samples=[COZ_SAMPLE]).is_39a


def test_mapper_from_json_rejects_shifted_map():
    with pytest.raises(ValueError, match="decision column"):
        _mapper_from_json(SHIFTED_LLM_JSON, ncols=8, samples=[COZ_SAMPLE])


def test_mapper_from_json_rejects_area_without_number():
    swapped = {
        **GOOD_LLM_JSON,
        "column_map": {**GOOD_LLM_JSON["column_map"], "proposed_use": 6, "area_proposed": 5},
    }
    with pytest.raises(ValueError, match="area_proposed"):
        _mapper_from_json(swapped, ncols=8, samples=[COZ_SAMPLE])


def test_mapper_from_json_tolerates_one_area_cell_without_number():
    # OG19: OCR put one row's area into the proposed-use cell, leaving "Total Area".
    misplaced = COZ_SAMPLE[:5] + ["No Development (5,96,055) Zone", "Total Area", COZ_SAMPLE[7]]
    assert _mapper_from_json(GOOD_LLM_JSON, ncols=8, samples=[misplaced, COZ_SAMPLE]).is_39a


def test_mapper_from_json_rejects_zone_code_as_area():
    proposed_as_area = {
        **GOOD_LLM_JSON,
        "column_map": {**GOOD_LLM_JSON["column_map"], "proposed_use": 6, "area_proposed": 5},
    }
    sample = COZ_SAMPLE[:5] + ["Residential (S1)"] + COZ_SAMPLE[6:]
    with pytest.raises(ValueError, match="area_proposed"):
        _mapper_from_json(proposed_as_area, ncols=8, samples=[sample])


def test_mapper_from_json_allows_decision_without_recommend():
    deferred = COZ_SAMPLE[:7] + ["Deferred."]
    assert _mapper_from_json(GOOD_LLM_JSON, ncols=8, samples=[deferred]).is_39a


class _RecordingMapper:
    def __init__(self, result: MapperResult):
        self.result = result
        self.calls = 0

    def map_columns(self, header_row, sample_rows, variant_hint=None):
        self.calls += 1
        return self.result


def test_heuristic_first_skips_llm_when_heuristic_maps():
    llm = _RecordingMapper(MapperResult(is_39a=False, variant=None, confidence=0.5))
    result = HeuristicFirstMapper(llm).map_columns(COZ_HEADER, [COZ_SAMPLE])
    assert result.is_39a
    assert llm.calls == 0


def test_heuristic_first_asks_llm_when_heuristic_cannot_map():
    llm_answer = _mapper_from_json(GOOD_LLM_JSON, ncols=8)
    llm = _RecordingMapper(llm_answer)
    result = HeuristicFirstMapper(llm).map_columns([""] * 8, [COZ_SAMPLE])
    assert llm.calls == 1
    assert result is llm_answer


@pytest.mark.parametrize("provider", ["ollama", "openai_compat"])
def test_get_mapper_wraps_llm_providers(provider):
    assert isinstance(get_mapper(Settings(llm_provider=provider)), HeuristicFirstMapper)


def test_ollama_sends_indexed_columns_at_temperature_zero(monkeypatch):
    sent: list = []

    def fake_post(url, **kwargs):
        sent.append(kwargs["json"])
        body = {"response": json.dumps(GOOD_LLM_JSON)}
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    result = OllamaMapper(Settings(llm_provider="ollama")).map_columns(COZ_HEADER, [COZ_SAMPLE])
    assert result.confidence == 0.85
    assert sent[0]["options"] == {"temperature": 0}
    table = json.loads(sent[0]["prompt"].split("Table:\n", 1)[1])
    assert table["columns"][7] == {"index": 7, "header": "Decision", "samples": [COZ_SAMPLE[7]]}


def _fake_openai_response(content: dict, sent: list):
    def fake_post(url, **kwargs):
        sent.append(kwargs["json"])
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(content)}}]},
            request=request,
        )

    return fake_post


def test_openai_compat_sends_schema_and_uses_answer(monkeypatch):
    sent: list = []
    monkeypatch.setattr(httpx, "post", _fake_openai_response(GOOD_LLM_JSON, sent))
    cfg = Settings(llm_provider="openai_compat", openai_compat_base_url="http://llm")
    result = OpenAICompatMapper(cfg).map_columns(COZ_HEADER, [])
    assert result.confidence == 0.85
    prompt = sent[0]["messages"][0]["content"]
    assert '"is_39a"' in prompt and '"column_map"' in prompt


def test_openai_compat_falls_back_to_heuristic_on_bad_answer(monkeypatch, caplog):
    sent: list = []
    monkeypatch.setattr(httpx, "post", _fake_openai_response({"columns": {}}, sent))
    cfg = Settings(llm_provider="openai_compat", openai_compat_base_url="http://llm")
    result = OpenAICompatMapper(cfg).map_columns(COZ_HEADER, [])
    assert result.is_39a
    assert result.confidence == 0.9  # heuristic confidence
    assert "using heuristic" in caplog.text
