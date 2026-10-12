"""Rule-based sentence parser: the Planner's fallback when the model fails (CONTRACT.md 5.4).

Deterministic regular expressions only. It produces a ``Criteria`` and nothing
else; money words become INR (1 lakh = 100,000, 1 crore = 10,000,000, contract
5.2). Anything it cannot read is left null; a value it reads but that is not
valid (an inverted band, an out-of-range month) is passed on for the L1 loop.
"""

from __future__ import annotations

import re

from plotline.contract import CANONICAL_LOCALITIES, Criteria
from plotline.state import DataInfo

_UNIT_INR = {"lakh": 100_000, "crore": 10_000_000}  # contract 5.2

# Canonical names plus the raw-data misspellings of data.md R1 and a few spaced forms.
_LOCALITY_ALIASES = {
    **{name.lower(): name for name in CANONICAL_LOCALITIES},
    "chrompt": "Chrompet", "chrmpet": "Chrompet", "chormpet": "Chrompet",
    "tnagar": "T Nagar", "t. nagar": "T Nagar",
    "karapakam": "Karapakkam",
    "ana nagar": "Anna Nagar", "ann nagar": "Anna Nagar", "annanagar": "Anna Nagar",
    "velchery": "Velachery",
    "adyr": "Adyar",
    "kknagar": "KK Nagar", "k k nagar": "KK Nagar",
}
_SALE_COND_WORDS = [
    (r"\bab\s?normal\b", "AbNormal"),
    (r"\badj(?:acent)?\s?land\b", "AdjLand"),
    (r"\bfamily\b", "Family"),
    (r"\bnormal\s+sales?\b", "Normal Sale"),
    (r"\bpartial\b", "Partial"),
]
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_DOMAIN_WORDS = re.compile(
    r"\b(house|houses|housing|home|homes|flat|flats|apartment|apartments|propert(?:y|ies)|"
    r"sales?|sold|prices?|trends?|listings?|chennai|market)\b"
)

_NUM = r"(\d+(?:\.\d+)?)"
_UNIT = r"(lakhs?|lacs?|l|crores?|cr)(?![a-z])"
_LATEST = re.compile(r"\b(last|past|previous)\s+(year|12\s+months|twelve\s+months)\b|\bthis\s+year\b")
_ISO_MONTH = re.compile(r"\b(\d{4})-(0[1-9]|1[0-2])\b")
_NAMED_MONTH = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*,?\s*(\d{4})\b")
_YEAR = re.compile(r"\b(?:in|during|for|ending|end of|year)\s+(\d{4})\b")
_BHK = re.compile(r"((?:\b\d\b\s*(?:,|/|or|and|&|-|to)?\s*)+)\s*(?:bhk|bed(?:room)?s?|br)\b")
_RANGE_MONEY = re.compile(rf"(?:between\s+)?{_NUM}\s*(?:{_UNIT})?\s*(?:-|–|to|and)\s*{_NUM}\s*{_UNIT}")
_BELOW_MONEY = re.compile(rf"\b(?:under|below|less than|upto|up to|within|max(?:imum)?|cheaper than)\s+(?:rs\.?\s*|₹\s*)?{_NUM}\s*{_UNIT}")
_SQFT_UNIT = r"(?:sq\.?\s*ft|sqft|square\s+feet|sq\s+feet)\b"
_RANGE_SQFT = re.compile(rf"(?:between\s+)?(\d+)\s*(?:{_SQFT_UNIT})?\s*(?:-|–|to|and)\s*(\d+)\s*{_SQFT_UNIT}")
_BELOW_SQFT = re.compile(rf"\b(?:under|below|less than|upto|up to|within)\s+(\d+)\s*{_SQFT_UNIT}")


def _unit_factor(word: str) -> int:
    return _UNIT_INR["crore"] if word.startswith("c") else _UNIT_INR["lakh"]


def _money(value: str, unit: str) -> int | float:
    inr = float(value) * _unit_factor(unit)
    return int(inr) if inr.is_integer() else inr


def _localities(text: str) -> list[str] | None:
    found = set()
    for alias, name in _LOCALITY_ALIASES.items():
        if re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", text):
            found.add(name)
    return sorted(found) or None


def _window_end(text: str, info: DataInfo) -> str | None:
    if _LATEST.search(text):
        return info.latest_month
    m = _ISO_MONTH.search(text)
    if m:
        return f"{m[1]}-{m[2]}"
    m = _NAMED_MONTH.search(text)
    if m:
        return f"{m[2]}-{_MONTHS[m[1]]:02d}"
    m = _YEAR.search(text)
    if m:
        return f"{m[1]}-12"
    return None


def _bhk(text: str) -> list[int] | None:
    values: set[int] = set()
    for m in _BHK.finditer(text):
        digits = [int(d) for d in re.findall(r"\d", m[1])]
        if re.search(r"\d\s*(?:-|to)\s*\d", m[1]) and len(digits) == 2:
            digits = list(range(min(digits), max(digits) + 1))
        values.update(digits)
    return sorted(values) or None


def _price_band(text: str) -> list[int | float] | None:
    m = _RANGE_MONEY.search(text)
    if m:
        lo_unit = m[2] or m[4]  # "70 to 90 lakh": the unit is written once
        return [_money(m[1], lo_unit), _money(m[3], m[4])]
    m = _BELOW_MONEY.search(text)
    if m:
        return [0, _money(m[1], m[2])]
    return None  # "above X" has no upper bound and is not represented (as in the model prompt)


def _sqft_range(text: str) -> list[int] | None:
    m = _RANGE_SQFT.search(text)
    if m:
        return [int(m[1]), int(m[2])]
    m = _BELOW_SQFT.search(text)
    if m:
        return [0, int(m[1])]
    return None


def _sale_cond(text: str) -> list[str] | None:
    found = {name for pattern, name in _SALE_COND_WORDS if re.search(pattern, text)}
    return sorted(found) or None


def parse(sentence: str, info: DataInfo) -> Criteria | None:
    """``Criteria`` read from the sentence, or None when it says nothing usable."""
    text = " ".join(sentence.lower().split())
    criteria = Criteria(
        localities=_localities(text),
        window_end=_window_end(text, info),
        bhk=_bhk(text),
        price_band=_price_band(text),
        sqft_range=_sqft_range(text),
        sale_cond=_sale_cond(text),
        price_unit="inr",
    )
    if criteria == Criteria() and not _DOMAIN_WORDS.search(text):
        return None
    return criteria
