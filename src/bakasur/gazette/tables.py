"""Table loading, stitching, and row merging."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from itertools import pairwise
from typing import Any

from bakasur.models import ColumnMap, NotificationSpan, TableVariant

COLUMN_NUMBER_RE = re.compile(r"^\(?(\d{1,2})\)?\.?$")
SR_NO_RE = re.compile(r"^\s*(\d{1,3})\s*[.)]?(?:\s|$)")
# A Sr. No. inside a survey cell, as in "... 136/3- A 2. 203/1 to 5, ..."
EMBEDDED_SR_RE = re.compile(r"\s(\d{1,3})\.\s+(?=\d)")
RUNNING_TEXT_MAX_LEN = 80
HEADER_MATCH_RATIO = 0.8


@dataclass
class StitchedTable:
    header: list[str] | None
    rows: list[list[str]]
    # Sr. Nos. whose survey cell may hold a neighbouring record's text (see _unmerge_first_column).
    suspect_sr: set[int] = field(default_factory=set)


def tables_in_span(
    tables: list[dict[str, Any]],
    span: NotificationSpan,
) -> list[dict[str, Any]]:
    return [
        t
        for t in tables
        if t.get("page_no") is not None
        and span.page_start <= int(t["page_no"]) <= span.page_end
    ]


def _col_count(table: dict[str, Any]) -> int:
    return int(table.get("n_cols") or 0)


def is_running_text(text: str, patterns: Sequence[str]) -> bool:
    """Gazette page furniture (title, series/date line, page number) that OCR tags as body text."""
    text = text.strip()
    if len(text) > RUNNING_TEXT_MAX_LEN:
        return False
    return any(re.search(p, text, re.I) for p in patterns)


def body_text(texts: list[str] | None, running_text_patterns: Sequence[str]) -> list[str]:
    return [t for t in texts or [] if t.strip() and not is_running_text(t, running_text_patterns)]


def _is_column_number_row(row: list[str]) -> bool:
    """Rows like `1 2 3 ...` or `(1) (2) (3) ...` that number the columns."""
    tokens = " ".join(row).split()
    if len(tokens) < 3:
        return False
    nums: list[int] = []
    for tok in tokens:
        m = COLUMN_NUMBER_RE.match(tok)
        if not m:
            return False
        nums.append(int(m.group(1)))
    return all(b > a for a, b in pairwise(nums))


def _is_text_header_row(row: list[str]) -> bool:
    joined = " ".join(c.strip() for c in row if c.strip()).lower()
    if not joined:
        return False
    if "sr" in joined and ("applicant" in joined or "sy" in joined or "survey" in joined):
        return True
    if "sr" in joined and "no development" in joined:
        return True
    return False


def _is_header_like_row(row: list[str]) -> bool:
    return _is_column_number_row(row) or _is_text_header_row(row)


def _text_header(table: dict[str, Any]) -> list[str] | None:
    header = table.get("header")
    if header and any(c.strip() for c in header) and not _is_column_number_row(header):
        return header
    grid = table.get("grid") or []
    if grid and _is_text_header_row(grid[0]):
        return grid[0]
    return None


def _normalize(cells: list[str]) -> str:
    return re.sub(r"\s+", " ", " ".join(cells).lower()).strip()


def _same_header(a: list[str], b: list[str]) -> bool:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio() >= HEADER_MATCH_RATIO


def parse_sr(cell: str | None) -> int | None:
    m = SR_NO_RE.match(cell or "")
    return int(m.group(1)) if m else None


def _sr_number(row: list[str]) -> int | None:
    if not row or _is_column_number_row(row):
        return None
    return parse_sr(row[0])


def _last_sr(chain: list[dict[str, Any]]) -> int | None:
    for table in reversed(chain):
        for row in reversed(table.get("grid") or []):
            n = _sr_number(row)
            if n is not None:
                return n
    return None


def _first_sr(table: dict[str, Any]) -> int | None:
    for row in table.get("grid") or []:
        n = _sr_number(row)
        if n is not None:
            return n
    return None


def _folds_first_column(header: list[str] | None) -> bool:
    """A column-number header showing Docling merged column 1 into 2: `1 2 | 3 | ...` or `2 | 3 | ...`."""
    if not header or not _is_column_number_row(header):
        return False
    first = [m.group(1) for tok in header[0].split() if (m := COLUMN_NUMBER_RE.match(tok))]
    return first in (["1", "2"], ["2"])


def _unmerge_first_column(table: dict[str, Any]) -> dict[str, Any]:
    """Split the Sr. No. back out of the survey cell on pages where Docling merged the two columns.

    A Sr. No. mid-cell follows the previous record's overflow, which becomes its own
    continuation row. A Sr. No. starting the cell is flagged in `suspect_sr`: on such
    pages Docling can also misplace row boundaries inside the survey column (OG19 p5).
    """
    if not _folds_first_column(table.get("header")):
        return table
    n_cols = _col_count(table) + 1
    grid: list[list[str]] = []
    suspect: list[int] = []
    for row in table.get("grid") or []:
        if not row or _is_marker_row(row):
            grid.append(["", *row])
            continue
        first, rest = row[0].strip(), row[1:]
        if m := SR_NO_RE.match(first):
            grid.append([first[: m.end()].strip(), first[m.end() :].strip(), *rest])
            suspect.append(int(m.group(1)))
        elif m := EMBEDDED_SR_RE.search(first):
            grid.append(["", first[: m.start()].strip(), *[""] * len(rest)])
            grid.append([f"{m.group(1)}.", first[m.end() :].strip(), *rest])
        else:
            grid.append(["", first, *rest])
    return {
        **table,
        "n_cols": n_cols,
        "header": [str(i) for i in range(1, n_cols + 1)],
        "grid": grid,
        "suspect_sr": suspect,
    }


def _continues(
    chain: list[dict[str, Any]],
    nxt: dict[str, Any],
    running_text_patterns: Sequence[str],
) -> bool:
    """Whether `nxt` is the overflow of the table chain onto the following page."""
    prev = chain[-1]
    if prev.get("page_no") is None or nxt.get("page_no") is None:
        return False
    if int(nxt["page_no"]) != int(prev["page_no"]) + 1:
        return False
    if _col_count(prev) != _col_count(nxt):
        return False
    if body_text(prev.get("text_after"), running_text_patterns):
        return False
    if body_text(nxt.get("text_before"), running_text_patterns):
        return False

    # A repeated header is fine; a different text header means a different table.
    next_header = _text_header(nxt)
    if next_header is not None:
        chain_header = _text_header(chain[0])
        if chain_header is None or not _same_header(next_header, chain_header):
            return False

    # Missing Sr. Nos. (common with OCR) are inconclusive; a restart or step back is not.
    last, first = _last_sr(chain), _first_sr(nxt)
    if last is not None and first is not None and first <= last:
        return False
    return True


def chain_tables(
    tables: list[dict[str, Any]],
    running_text_patterns: Sequence[str] = (),
) -> list[list[dict[str, Any]]]:
    """Group tables into chains, each chain being one logical table split across pages."""
    ordered = sorted(
        (_unmerge_first_column(t) for t in tables),
        key=lambda t: (t.get("page_no") or 0, t.get("index") or 0),
    )
    chains: list[list[dict[str, Any]]] = []
    for table in ordered:
        if chains and _continues(chains[-1], table, running_text_patterns):
            chains[-1].append(table)
        else:
            chains.append([table])
    return chains


def stitch_tables(
    tables: list[dict[str, Any]],
    running_text_patterns: Sequence[str] = (),
) -> list[StitchedTable]:
    """Merge each chain of page-split tables into one table."""
    stitched: list[StitchedTable] = []
    for chain in chain_tables(tables, running_text_patterns):
        rows: list[list[str]] = []
        suspect: set[int] = set()
        for idx, table in enumerate(chain):
            grid = table.get("grid") or []
            if idx > 0 and grid and _is_header_like_row(grid[0]):
                grid = grid[1:]
            flagged = table.get("suspect_sr") or []
            suspect.update(flagged)
            first_row = next((r for r in grid if not _is_marker_row(r)), None)
            if flagged and idx > 0 and first_row and _sr_number(first_row) is not None:
                # No overflow row precedes the first record, so the previous record's
                # overflow may have been swallowed into it.
                prev = _last_sr(chain[:idx])
                if prev is not None:
                    suspect.add(prev)
            rows.extend(grid)
        if rows:
            stitched.append(StitchedTable(header=chain[0].get("header"), rows=rows, suspect_sr=suspect))
    return stitched


def _is_marker_row(row: list[str]) -> bool:
    if not any(c.strip() for c in row):
        return True
    return _is_column_number_row(row)


def _cell(row: list[str], idx: int | None) -> str:
    if idx is None or idx >= len(row):
        return ""
    return row[idx].strip()


def _is_continuation_row(row: list[str], col_map: ColumnMap) -> bool:
    if col_map.sr_no is None or col_map.sr_no >= len(row):
        return False
    if _cell(row, col_map.sr_no):
        return False
    if col_map.survey is not None and col_map.village_taluka is not None:
        # OCR often drops single-digit Sr. Nos.; a row with its own survey and village is a new record.
        return not (_cell(row, col_map.survey) and _cell(row, col_map.village_taluka))
    return True


def _sequence_verdicts(rows: list[list[str]], sr_idx: int) -> dict[int, bool]:
    """Continuation verdicts that the Sr. No. sequence alone settles, keyed by blank-Sr. No. row index.

    Between records N and M: if M == N + 1, every blank row in between continues N; if the
    gap equals the number of blank rows, each is a record whose Sr. No. OCR dropped. A larger
    gap, numbering that goes backwards, or an unreadable Sr. No. (such as "-") settles nothing.
    """
    anchors = [(i, n) for i, row in enumerate(rows) if (n := parse_sr(_cell(row, sr_idx))) is not None]
    verdicts: dict[int, bool] = {}
    for (lo, n), (hi, m) in pairwise(anchors):
        between = range(lo + 1, hi)
        if m <= n or any(_cell(rows[i], sr_idx) for i in between):
            continue
        if m == n + 1:
            verdicts.update(dict.fromkeys(between, True))
        elif m - n - 1 == len(between):
            verdicts.update(dict.fromkeys(between, False))
    return verdicts


def merge_continuation_rows(
    rows: list[list[str]],
    col_map: ColumnMap,
) -> tuple[list[list[str]], set[int]]:
    """Fold rows without a Sr. No. into the record above when they continue it.

    The Sr. No. sequence decides where it can, and the row contents otherwise. Also returns
    the indices of merged records where the two disagreed, which should be reviewed.
    """
    rows = [r for r in rows if not _is_marker_row(r)]
    verdicts = _sequence_verdicts(rows, col_map.sr_no) if col_map.sr_no is not None else {}
    merged: list[list[str]] = []
    disputed: set[int] = set()
    for idx, row in enumerate(rows):
        by_content = bool(merged) and _is_continuation_row(row, col_map)
        continues = verdicts.get(idx, by_content)
        if continues != by_content:
            # The record above gains or loses this row's text either way, so it is suspect too.
            disputed.add(len(merged) - 1)
            if not continues:
                disputed.add(len(merged))
        if continues:
            prev = merged[-1]
            for i, cell in enumerate(row):
                cell = cell.strip()
                if not cell:
                    continue
                if i < len(prev):
                    prev[i] = (prev[i] + " " + cell).strip() if prev[i] else cell
                else:
                    prev.append(cell)
        else:
            merged.append([c.strip() for c in row])
    return merged, disputed


def detect_header_row(grid: list[list[str]]) -> int | None:
    for i, row in enumerate(grid[:6]):
        if _is_text_header_row(row):
            return i
    return None


def split_header(table: StitchedTable) -> tuple[list[str], list[list[str]]]:
    """Return (header row, data rows); the header is blank when none was found."""
    if table.header and not _is_column_number_row(table.header):
        return table.header, table.rows
    idx = detect_header_row(table.rows)
    if idx is None:
        width = max((len(r) for r in table.rows), default=0)
        return [""] * width, table.rows
    return table.rows[idx], table.rows[idx + 1 :]


def infer_variant(header_row: list[str]) -> TableVariant:
    if "applicant" in " ".join(header_row).lower():
        return TableVariant.CHANGE_OF_ZONE
    return TableVariant.NDZ


def sample_rows(rows: list[list[str]], n: int = 3) -> list[list[str]]:
    samples: list[list[str]] = []
    for row in rows:
        if _is_marker_row(row):
            continue
        samples.append(row)
        if len(samples) >= n:
            break
    return samples


def apply_column_map(
    rows: list[list[str]],
    col_map: ColumnMap,
) -> list[dict[str, str | None]]:
    records: list[dict[str, str | None]] = []
    mapping = col_map.as_dict()
    for row in rows:
        if _is_marker_row(row):
            continue
        record: dict[str, str | None] = {}
        for name, idx in mapping.items():
            record[name] = row[idx].strip() if idx < len(row) else None
        records.append(record)
    return records
