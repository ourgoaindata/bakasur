"""Zone codes for the 39A master sheet, read from the gazette's land-use wording.

Codes follow the master sheet's legend: A-1 agriculture / cultivated / paddy, A-2 orchard
(natural cover and CADA are overlays on orchard), S-2 / S-3 settlement in a VP1 / VP2
village, R recreation, P public / institutional, T transport, I industry. A code printed in
the gazette, such as "Residential (S4)", is used as printed.
"""

from __future__ import annotations

import re

SETTLEMENT = "Settlement"  # when the village's VP1/VP2 status is unknown

_TOTAL_AREA_RE = re.compile(r"Total\s+Area\s*\([^)]*\)", re.I)
# Land-use phrases are separated by "Partly" or by commas.
_PHRASE_SPLIT_RE = re.compile(r"\bpartly\b|,", re.I)
_PRINTED_CODE_RE = re.compile(r"\(\s*([ACSRPTI])\s*-?\s*(\d)\s*\)")
_ZONE_WORDS = [
    (re.compile(r"orchard|natural\s+(?:cover|reserve)", re.I), "A-2"),
    (re.compile(r"cultivable|paddy|agricultur", re.I), "A-1"),
    (re.compile(r"forest", re.I), "FOREST"),
    (re.compile(r"settlement", re.I), SETTLEMENT),
    (re.compile(r"recreation|open\s+space", re.I), "R"),
    (re.compile(r"institutional", re.I), "P"),
    (re.compile(r"transport|warehous", re.I), "T"),
    (re.compile(r"industr", re.I), "I"),
    (re.compile(r"commercial", re.I), "Commercial"),
    (re.compile(r"residential", re.I), "Residential"),
]
# Eco-sensitive overlays and constraints for "Old Zone -2 (eco zone)".
_OVERLAYS = [
    (re.compile(r"natural\s+cover", re.I), "NC"),
    (re.compile(r"no\s+development\s+slope|\bNDS\b", re.I), "NDS"),
    (re.compile(r"irrigation\s+command|\bCADA\b", re.I), "CADA"),
    (re.compile(r"disaster\s+management", re.I), "DMS"),
    (re.compile(r"\bHTL\b|\bCRZ\b", re.I), "CRZ"),
    (re.compile(r"\bnall?ah?\b", re.I), "Nallah"),
    (re.compile(r"\briver\b", re.I), "River"),
    (re.compile(r"mangrove", re.I), "Mangroves"),
    (re.compile(r"khazan", re.I), "Khazan"),
    (re.compile(r"archaeolog", re.I), "Archaeology"),
    (re.compile(r"wild\s*life|\(WL\)", re.I), "WLS buffer"),
    (re.compile(r"\bNH\b|national\s+highway|\broad\b", re.I), "Road"),
]


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def zone_codes(text: str | None, settlement_code: str | None = None) -> list[str]:
    """Every zone the text names, in order; "Settlement" becomes S-2/S-3 when known."""
    codes: list[str] = []
    for phrase in _PHRASE_SPLIT_RE.split(_TOTAL_AREA_RE.sub("", text or "")):
        printed = [f"{letter}-{num}" for letter, num in _PRINTED_CODE_RE.findall(phrase)]
        if printed:
            codes.extend(printed)
            continue
        hits = sorted((m.start(), code) for rx, code in _ZONE_WORDS if (m := rx.search(phrase)))
        codes.extend(code for _, code in hits)
    if settlement_code:
        codes = [settlement_code if c == SETTLEMENT else c for c in codes]
    return _unique(codes)


def overlays(text: str | None) -> list[str]:
    text = text or ""
    hits = sorted((m.start(), label) for rx, label in _OVERLAYS if (m := rx.search(text)))
    return _unique([label for _, label in hits])
