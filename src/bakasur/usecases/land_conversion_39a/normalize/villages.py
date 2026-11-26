"""Revenue village -> panchayat, assembly constituency and VP1/VP2 status.

Source: the team's "List of all Villages in Goa" sheet, copied to data/goa_villages.csv
(one row per panchayat, spelling slips fixed). A village split between panchayats lists
its survey numbers in `survey_ranges` for the panchayat that holds those numbers.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

VILLAGES_CSV = Path(__file__).resolve().parent.parent / "data" / "goa_villages.csv"

# Gazette spellings that differ from the reference list, keyed by normalized taluka.
VILLAGE_ALIASES = {
    ("ponda", "boma"): "bhoma",
    ("bicholim", "arvalem"): "arvelem",
    ("bicholim", "curchirem"): "cudchirem",
    ("pernem", "arambol"): "harmal",
    ("bardez", "sircaim"): "sirsaim",
    ("mormugao", "cotarlim"): "cortalim",
}
TALUKA_ALIASES = {
    "satari": "sattari",
    "marmugao": "mormugao",
    "murmugao": "mormugao",
    "salsete": "salcete",
    "dharbondora": "dharbandora",
}
_PANCHAYAT_SUFFIX_RE = re.compile(r"\s*(village\s+)?pa?n?cha+yat\s*$", re.I)
_PAREN_RE = re.compile(r"\([^)]*\)")


def _norm(text: str | None) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", _PAREN_RE.sub("", text).lower())


def _norm_taluka(text: str | None) -> str:
    key = _norm(text)
    return TALUKA_ALIASES.get(key, key)


def _parse_ranges(spec: str) -> list[tuple[int, int | None]]:
    """"200,355-364" -> [(200, 200), (355, 364)]; "105-" is open-ended."""
    out: list[tuple[int, int | None]] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        lo, sep, hi = part.partition("-")
        if not sep:
            out.append((int(lo), int(lo)))
        else:
            out.append((int(lo), int(hi) if hi.strip() else None))
    return out


@dataclass(frozen=True)
class VillageInfo:
    panchayat: str
    constituency: str
    vp_status: str  # "VP1", "VP2", "ODP" or "" for municipal areas

    @property
    def vp_name(self) -> str:
        """Panchayat name as the master sheet writes it, without "Panchayat"."""
        return _PANCHAYAT_SUFFIX_RE.sub("", self.panchayat).strip()

    @property
    def settlement_code(self) -> str | None:
        """Legend: S-2 is VP1 settlement, S-3 is VP2 settlement."""
        return {"VP1": "S-2", "VP2": "S-3"}.get(self.vp_status.upper())


@dataclass(frozen=True)
class _Entry:
    info: VillageInfo
    ranges: tuple[tuple[int, int | None], ...]  # empty: this panchayat holds the rest

    def holds(self, survey_no: int) -> bool:
        return any(lo <= survey_no and (hi is None or survey_no <= hi) for lo, hi in self.ranges)


class VillageLookup:
    def __init__(self, path: Path = VILLAGES_CSV) -> None:
        self._entries: dict[tuple[str, str], list[_Entry]] = {}
        with path.open(encoding="utf-8", newline="") as f:
            for rec in csv.DictReader(f):
                self._add(rec)

    def _add(self, rec: dict[str, str]) -> None:
        ranges = {
            _norm(village): tuple(_parse_ranges(spec))
            for village, _, spec in (
                item.partition(":") for item in rec["survey_ranges"].split(";") if item.strip()
            )
        }
        constituencies = {
            _norm(village): ac.strip()
            for village, _, ac in (
                item.partition(":") for item in rec["village_constituency"].split(";") if item.strip()
            )
        }
        taluka = _norm_taluka(rec["taluka"])
        for village in rec["revenue_villages"].split(","):
            key = _norm(village)
            if not key:
                continue
            info = VillageInfo(
                panchayat=rec["panchayat"].strip(),
                constituency=constituencies.get(key, rec["constituency"].strip()),
                vp_status=rec["vp_status"].strip(),
            )
            self._entries.setdefault((taluka, key), []).append(
                _Entry(info=info, ranges=ranges.get(key, ()))
            )

    def find(self, village: str | None, taluka: str | None, survey_no: int | None = None) -> list[VillageInfo]:
        """Every panchayat the village may belong to; one entry when the match is certain."""
        t = _norm_taluka(taluka)
        v = _norm(village)
        v = VILLAGE_ALIASES.get((t, v), v)
        entries = self._entries.get((t, v), [])
        if len(entries) > 1 and survey_no is not None:
            holding = [e for e in entries if e.holds(survey_no)]
            rest = [e for e in entries if not e.ranges]
            entries = holding or rest or entries
        return [e.info for e in entries]
