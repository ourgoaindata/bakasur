"""Heuristic and LLM-backed column mappers."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from bakasur.config import Settings
from bakasur.llm.base import ColumnMapper
from bakasur.models import ColumnMap, MapperResult, TableVariant

logger = logging.getLogger(__name__)


HEADER_ALIASES: dict[str, list[str]] = {
    "sr_no": ["sr", "sr.", "sr no", "s.no"],
    "applicant": ["applicant", "name of the applicant", "name"],
    "survey": ["sy", "survey", "sub-div", "sub div", "ch.", "pts"],
    "village_taluka": ["village", "taluka"],
    "existing_use": ["published", "existing", "rpg", "odp", "total area"],
    "proposed_use": ["proposed land", "proposed"],
    "area_proposed": ["area proposed", "in sq"],
    "decision": ["decision", "tcp board", "recommended"],
}

COLUMN_FIELDS = tuple(HEADER_ALIASES)

LLM_INSTRUCTIONS = """\
You map the columns of a table extracted from the Goa Official Gazette.
Decide whether it is a Section 39A table and, if so, which column holds
each field. Section 39A tables come in two variants, and both count as
is_39a = true:
- "change_of_zone": has an applicant (name) column.
- "ndz": No Development Zone table; has no applicant column, so applicant is null.

The table is given column by column: each column has its index, its header
text (which may be empty) and sample values from the first rows. Use those
indices in column_map.

Return ONLY a JSON object of this shape:
{
  "is_39a": true | false,
  "variant": "change_of_zone" | "ndz",
  "column_map": {
    "sr_no": int, "applicant": int | null, "survey": int,
    "village_taluka": int, "existing_use": int, "proposed_use": int,
    "area_proposed": int, "decision": int
  }
}
Use null for a field with no matching column. Omit column_map when is_39a is false.
"""


def _normalize_header(cell: str) -> str:
    return re.sub(r"\s+", " ", cell.strip().lower())


def _alias_match_len(header: str, aliases: list[str]) -> int:
    """Length of the longest alias found at a word start in header, else 0."""
    # Anchoring at a word start keeps "sy" out of "easy" and "ch." out of "approach.".
    return max(
        (len(a) for a in aliases if re.search(rf"(?<![a-z0-9]){re.escape(a)}", header)),
        default=0,
    )


def heuristic_map_columns(
    header_row: list[str],
    sample_rows: list[list[str]],
    variant_hint: TableVariant | None = None,
) -> MapperResult:
    joined_headers = [_normalize_header(c) for c in header_row]
    col_map = ColumnMap()
    used: set[int] = set()

    candidates: list[tuple[int, int, str]] = []
    for field, aliases in HEADER_ALIASES.items():
        if field == "applicant" and variant_hint == TableVariant.NDZ:
            continue
        for idx, header in enumerate(joined_headers):
            match_len = _alias_match_len(header, aliases)
            if match_len:
                candidates.append((match_len, idx, field))

    # Most specific alias claims a column first, so "name of village" goes to
    # village_taluka rather than applicant via the bare "name" alias.
    candidates.sort(key=lambda c: (-c[0], c[1]))
    for _, idx, field in candidates:
        if idx in used or getattr(col_map, field) is not None:
            continue
        setattr(col_map, field, idx)
        used.add(idx)

    ncols = len(header_row)
    variant = variant_hint or (
        TableVariant.CHANGE_OF_ZONE if col_map.applicant is not None else TableVariant.NDZ
    )

    if variant == TableVariant.NDZ and col_map.applicant is None:
        if ncols == 7 and col_map.survey is None:
            col_map.sr_no = 0
            col_map.survey = 1
            col_map.village_taluka = 2
            col_map.existing_use = 3
            col_map.proposed_use = 4
            col_map.area_proposed = 5
            col_map.decision = 6
    elif variant == TableVariant.CHANGE_OF_ZONE and ncols >= 8 and col_map.survey is None:
        col_map.sr_no = 0
        col_map.applicant = 1
        col_map.survey = 2
        col_map.village_taluka = 3
        col_map.existing_use = 4
        col_map.proposed_use = 5
        col_map.area_proposed = 6
        col_map.decision = 7

    is_39a = col_map.survey is not None and col_map.decision is not None
    confidence = 0.9 if is_39a else 0.3
    return MapperResult(
        is_39a=is_39a,
        variant=variant if is_39a else None,
        column_map=col_map if is_39a else None,
        confidence=confidence,
    )


class HeuristicMapper:
    def map_columns(
        self,
        header_row: list[str],
        sample_rows: list[list[str]],
        variant_hint: TableVariant | None = None,
    ) -> MapperResult:
        return heuristic_map_columns(header_row, sample_rows, variant_hint)


def _llm_prompt(
    header_row: list[str],
    sample_rows: list[list[str]],
    variant_hint: TableVariant | None,
) -> str:
    # Column-wise, with explicit indices, so the model never counts positions in a row.
    columns = [
        {
            "index": i,
            "header": header,
            "samples": [row[i] if i < len(row) else "" for row in sample_rows[:3]],
        }
        for i, header in enumerate(header_row)
    ]
    table = {
        "columns": columns,
        "variant_hint": variant_hint.value if variant_hint else None,
    }
    return LLM_INSTRUCTIONS + "\nTable:\n" + json.dumps(table)


class OllamaMapper:
    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg

    def map_columns(
        self,
        header_row: list[str],
        sample_rows: list[list[str]],
        variant_hint: TableVariant | None = None,
    ) -> MapperResult:
        try:
            resp = httpx.post(
                f"{self.cfg.ollama_base_url.rstrip('/')}/api/generate",
                json={
                    "model": self.cfg.llm_model,
                    "prompt": _llm_prompt(header_row, sample_rows, variant_hint),
                    "stream": False,
                    "format": "json",
                    # Ollama samples at 0.8 by default, giving a different map per run.
                    "options": {"temperature": 0},
                },
                timeout=120.0,
            )
            resp.raise_for_status()
            body = resp.json()
            data = json.loads(body.get("response", "{}"))
            return _mapper_from_json(data, len(header_row), sample_rows)
        except Exception as exc:
            logger.warning("Ollama column mapping failed, using heuristic: %r", exc)
            return heuristic_map_columns(header_row, sample_rows, variant_hint)


class OpenAICompatMapper:
    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg

    def map_columns(
        self,
        header_row: list[str],
        sample_rows: list[list[str]],
        variant_hint: TableVariant | None = None,
    ) -> MapperResult:
        if not self.cfg.openai_compat_base_url:
            logger.warning("openai_compat_base_url is not set, using heuristic column mapping")
            return heuristic_map_columns(header_row, sample_rows, variant_hint)
        try:
            resp = httpx.post(
                f"{self.cfg.openai_compat_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {self.cfg.openai_compat_api_key}"},
                json={
                    "model": self.cfg.llm_model,
                    "messages": [
                        {
                            "role": "user",
                            "content": _llm_prompt(header_row, sample_rows, variant_hint),
                        }
                    ],
                    "response_format": {"type": "json_object"},
                },
                timeout=120.0,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return _mapper_from_json(json.loads(content), len(header_row), sample_rows)
        except Exception as exc:
            logger.warning("OpenAI-compatible column mapping failed, using heuristic: %r", exc)
            return heuristic_map_columns(header_row, sample_rows, variant_hint)


def _check_sample_content(indices: dict[str, int | None], samples: list[list[str]]) -> None:
    """Raise ValueError if mapped columns hold the wrong kind of value, e.g. a map shifted by one."""

    def cell(row: list[str], idx: int | None) -> str:
        return row[idx] if idx is not None and idx < len(row) else ""

    for row in samples:
        decision = cell(row, indices["decision"])
        if "recommend" not in decision.lower() and any("recommend" in c.lower() for c in row):
            raise ValueError(f"LLM decision column {indices['decision']} misses the decision text: {row!r}")

    # Any one sample suffices: OCR sometimes moves a row's area into a neighbouring cell.
    # Two digits, so zone codes such as "Residential (S1)" do not pass as an area.
    areas = [a for a in (cell(row, indices["area_proposed"]) for row in samples) if a.strip()]
    if areas and not any(re.search(r"\d{2}", a) for a in areas):
        raise ValueError(f"LLM area_proposed column {indices['area_proposed']} has no numbers: {areas!r}")


def _mapper_from_json(
    data: dict[str, Any],
    ncols: int,
    samples: list[list[str]] | None = None,
) -> MapperResult:
    """Build a MapperResult from LLM JSON, raising ValueError if it is unusable."""
    if not isinstance(data, dict) or "is_39a" not in data:
        raise ValueError(f"LLM response missing is_39a: {data!r}")
    if not data["is_39a"]:
        return MapperResult(is_39a=False, variant=None, column_map=None, confidence=0.5)

    raw = data.get("column_map") or {}
    indices: dict[str, int | None] = {}
    for field in COLUMN_FIELDS:
        idx = raw.get(field)
        # bool is an int subclass; reject it explicitly.
        if idx is not None and (isinstance(idx, bool) or not isinstance(idx, int) or not 0 <= idx < ncols):
            raise ValueError(f"LLM gave invalid index for {field}: {idx!r} (ncols={ncols})")
        indices[field] = idx
    if indices["survey"] is None or indices["decision"] is None:
        raise ValueError(f"LLM column_map lacks survey/decision: {raw!r}")
    assigned = [i for i in indices.values() if i is not None]
    if len(assigned) != len(set(assigned)):
        raise ValueError(f"LLM mapped several fields to one column: {raw!r}")
    _check_sample_content(indices, samples or [])

    variant = TableVariant(data.get("variant") or "change_of_zone")
    return MapperResult(
        is_39a=True,
        variant=variant,
        column_map=ColumnMap(**indices),
        confidence=0.85,
    )


class HeuristicFirstMapper:
    """Use the heuristic map when it finds one; ask the LLM only for tables it cannot map.

    The heuristic is reliable on tables it recognises, while a small LLM can return
    a confident wrong answer that validation cannot catch, so the LLM only adds tables.
    """

    def __init__(self, llm: ColumnMapper) -> None:
        self.llm = llm

    def map_columns(
        self,
        header_row: list[str],
        sample_rows: list[list[str]],
        variant_hint: TableVariant | None = None,
    ) -> MapperResult:
        result = heuristic_map_columns(header_row, sample_rows, variant_hint)
        if result.is_39a:
            return result
        return self.llm.map_columns(header_row, sample_rows, variant_hint)


def get_mapper(cfg: Settings) -> ColumnMapper:
    if cfg.llm_provider == "ollama":
        return HeuristicFirstMapper(OllamaMapper(cfg))
    if cfg.llm_provider == "openai_compat":
        return HeuristicFirstMapper(OpenAICompatMapper(cfg))
    return HeuristicMapper()
