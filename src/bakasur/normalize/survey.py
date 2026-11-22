"""Survey number parsing and expansion."""

from __future__ import annotations

import re
from dataclasses import dataclass


RANGE_RE = re.compile(
    r"(\d+)/(\d+)\s+to\s+(\d+)(?:\s*\((P|Part)\))?",
    re.I,
)
SINGLE_RE = re.compile(
    r"(\d+)/(\d+(?:-[A-Za-z0-9]+)?)(?:\s*\((P|Part)\))?",
    re.I,
)
PLOT_RE = re.compile(r"Plot\s+No\.?\s*([A-Za-z0-9\-]+)", re.I)
PLOT_LABEL_RE = re.compile(r"Plot\s*(?:No\.?)?\s*([A-Za-z0-9][A-Za-z0-9\-]*)?", re.I)
# "(P)", "(Part)", or a named part such as "(Part A)".
PART_RE = re.compile(r"\(\s*(?:P|Part|pt)\.?(?:\s+([A-Za-z0-9\-]+))?\s*\)", re.I)
# Docling keeps the hyphen of a survey number wrapped across lines: "49/1- -A75", "196A/1- D".
WRAPPED_HYPHEN_RE = re.compile(r"(?<=\w)-\s*(?:-\s*)?(?=\w)")


def split_survey(survey_raw: str | None) -> tuple[str, str]:
    """("74/1, Plot No. 16 (Part)") -> ("74/1", "(part) (plot 16)"), for "S. No." and "Sub -Div"."""
    text = WRAPPED_HYPHEN_RE.sub("-", re.sub(r"\s+", " ", survey_raw or ""))
    parts = [f"(part {m.group(1)})" if m.group(1) else "(part)" for m in PART_RE.finditer(text)]
    plots = [m.group(1) for m in PLOT_LABEL_RE.finditer(text) if m.group(1)]
    survey = PLOT_LABEL_RE.sub("", PART_RE.sub("", text))
    qualifiers = list(dict.fromkeys(parts)) + [f"(plot {p})" for p in plots]
    return re.sub(r"\s+", " ", survey).strip(" ,"), " ".join(qualifiers)


def leading_survey_number(survey: str | None) -> int | None:
    m = re.match(r"\s*(\d+)", survey or "")
    return int(m.group(1)) if m else None


@dataclass
class SurveyEntry:
    survey_number: str
    is_part: bool = False


def expand_survey_raw(survey_raw: str | None) -> list[SurveyEntry]:
    if not survey_raw:
        return []

    entries: list[SurveyEntry] = []
    text = survey_raw.replace("\n", " ")

    for m in RANGE_RE.finditer(text):
        base = m.group(1)
        start = int(m.group(2))
        end = int(m.group(3))
        is_part = bool(m.group(4))
        for n in range(start, end + 1):
            entries.append(SurveyEntry(f"{base}/{n}", is_part=is_part))

    remainder = RANGE_RE.sub("", text)
    tokens = [t.strip() for t in re.split(r",", remainder) if t.strip()]
    for token in tokens:
        token = re.sub(r"\s+", " ", token.strip())
        if token in {"(P)", "(Part)"}:
            continue
        m = SINGLE_RE.match(token)
        if m:
            entries.append(
                SurveyEntry(
                    f"{m.group(1)}/{m.group(2)}",
                    is_part=bool(m.group(3)),
                )
            )
            continue
        m = re.match(r"(\d+)/(\d+(?:-[A-Za-z0-9]+)?)\s+\((P|Part)\)", token, re.I)
        if m:
            entries.append(
                SurveyEntry(
                    f"{m.group(1)}/{m.group(2)}",
                    is_part=True,
                )
            )
            continue
        m = PLOT_RE.search(token)
        if m:
            entries.append(SurveyEntry(f"Plot No. {m.group(1)}"))

    seen: set[str] = set()
    deduped: list[SurveyEntry] = []
    for e in entries:
        if e.survey_number not in seen:
            seen.add(e.survey_number)
            deduped.append(e)
    return deduped
