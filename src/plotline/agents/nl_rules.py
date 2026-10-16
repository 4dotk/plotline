"""Rule-based sentence parser: the Planner's fallback when the model fails (CONTRACT.md 5.4).

Deterministic regular expressions only. It produces a ``Criteria`` and nothing
else; money words become INR (1 lakh = 100,000, 1 crore = 10,000,000, contract
5.2). Anything it cannot read is left null; a value it reads but that is not
valid (an inverted band, an out-of-range month) is passed on for the L1 loop.
"""

from __future__ import annotations

import difflib
import re
from decimal import Decimal

from plotline.contract import BHK_VALUES, CANONICAL_LOCALITIES, Criteria
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
    "thyagaraya nagar": "T Nagar", "thyagaraya": "T Nagar",  # T Nagar's full name
}
# Places people ask about that this data does not hold (other cities, Chennai areas outside the 7).
# Kept as written so the Inspector refuses them with a reason, instead of the query
# silently becoming "every locality" (1.2.0).
_OTHER_PLACES = {
    "hyderabad": "Hyderabad", "bangalore": "Bangalore", "bengaluru": "Bengaluru", "mumbai": "Mumbai",
    "bombay": "Bombay", "delhi": "Delhi", "pune": "Pune", "kolkata": "Kolkata", "coimbatore": "Coimbatore",
    "madurai": "Madurai", "kochi": "Kochi", "mylapore": "Mylapore", "nungambakkam": "Nungambakkam",
    "tambaram": "Tambaram", "porur": "Porur", "guindy": "Guindy", "sholinganallur": "Sholinganallur",
    "perungudi": "Perungudi", "besant nagar": "Besant Nagar", "ashok nagar": "Ashok Nagar", "egmore": "Egmore",
    "vadapalani": "Vadapalani", "saidapet": "Saidapet", "ambattur": "Ambattur", "pallavaram": "Pallavaram",
    "madipakkam": "Madipakkam", "medavakkam": "Medavakkam", "mogappair": "Mogappair", "alwarpet": "Alwarpet",
}
_SALE_COND_WORDS = [
    (r"\bab\s?normal\b", "AbNormal"),
    (r"\badj(?:acent)?\s?land\b", "AdjLand"),
    (r"\bfamily\s+(?:sales?|transfers?)\b", "Family"),  # not "for my family"
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
# a single digit, also glued to the word ("2bhk", "2-bhk"); never a digit of a longer number (F2)
_BHK = re.compile(r"((?:(?<!\d)\d(?!\d)\s*(?:,|/|or|and|&|-|to)?\s*)+)\s*(?:bhk|bed(?:room)?s?|br)\b")
_BHK_WORD_OR_DIGIT = r"(?<!\d)(\d)(?!\d)"
_BHK_NOUN = r"(?:bhk|bed(?:room)?s?|br)\b"
_BHK_AT_LEAST = re.compile(rf"(?:at\s*least|min(?:imum)?)\s+{_BHK_WORD_OR_DIGIT}\s*{_BHK_NOUN}"
                           rf"|{_BHK_WORD_OR_DIGIT}\s*\+\s*{_BHK_NOUN}"
                           rf"|{_BHK_WORD_OR_DIGIT}\s*{_BHK_NOUN}\s+(?:or|and)\s+(?:more|above|bigger|larger)\b")
_STUDIO = re.compile(r"\bstudios?\b|\b1\s*rk\b")
_BHK_WORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6"}
_BHK_WORD = re.compile(r"\b(one|two|three|four|five|six)(?=\s*-?\s*(?:bhk|bed|br\b))")
_RANGE_MONEY = re.compile(rf"(?:between\s+)?{_NUM}\s*(?:{_UNIT})?\s*(?:-|–|down to|to|and)\s*{_NUM}\s*{_UNIT}")
_BELOW_MONEY = re.compile(rf"\b(?:under|below|less than|upto|up to|within|max(?:imum)?|cheaper than)\s+(?:rs\.?\s*|₹\s*)?{_NUM}\s*{_UNIT}")
_MAX_AFTER_MONEY = re.compile(rf"{_NUM}\s*{_UNIT}\s*(?:max(?:imum)?|or less|or below|and below|at most|tops)\b")
_SQFT_UNIT = r"(?:sq\.?\s*ft|sqft|square\s+feet|sq\s+feet)\b"
_RANGE_SQFT = re.compile(rf"(?:between\s+)?(\d+)\s*(?:{_SQFT_UNIT})?\s*(?:-|–|to|and)\s*(\d+)\s*{_SQFT_UNIT}")
_BELOW_SQFT = re.compile(rf"\b(?:under|below|less than|upto|up to|within)\s+(\d+)\s*{_SQFT_UNIT}")


def _unit_factor(word: str) -> int:
    return _UNIT_INR["crore"] if word.startswith("c") else _UNIT_INR["lakh"]


def _money(value: str, unit: str) -> int | float:
    # Decimal, not float: float("140.1948") * 100000 is 14019479.999999998, which drops a row priced at the edge.
    inr = Decimal(value) * _unit_factor(unit)
    return int(inr) if inr == inr.to_integral_value() else float(inr)


_EXCLUDE = re.compile(r"\b(?:except|excluding|exclude|other than|apart from|not)\s+(?:in\s+)?$")
_FUZZY_CUTOFF = 0.85  # a misspelling outside the alias list ("anna nagr", "velacherry"); found 10-16


def _localities(text: str) -> list[str] | None:
    """Canonical names, known misspellings and close spellings; "except X" removes X."""
    text = " ".join(text.replace(".", " ").split())  # "t.nagar" -> "t nagar", "k.k. nagar" -> "k k nagar"
    found: set[str] = set()
    excluded: set[str] = set()

    def add(name: str, start: int) -> None:
        (excluded if _EXCLUDE.search(text[max(0, start - 15):start]) else found).add(name)

    covered: list[tuple[int, int]] = []
    for place, name in _OTHER_PLACES.items():  # outside the data: kept, never matched to a locality
        for m in re.finditer(rf"(?<![a-z]){re.escape(place)}(?![a-z])", text):
            found.add(name)
            covered.append(m.span())
    for alias, name in _LOCALITY_ALIASES.items():
        for m in re.finditer(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", text):
            add(name, m.start())
            covered.append(m.span())
    # close spellings, only for words no exact match used; "nagar" alone names no place
    words = [w for w in re.finditer(r"[a-z]+", text) if not any(a <= w.start() < b for a, b in covered)]
    for i, w in enumerate(words):
        pair = i + 1 < len(words) and words[i + 1].start() == w.end() + 1
        for cand, start in [(w[0], w.start())] + ([(f"{w[0]} {words[i + 1][0]}", w.start())] if pair else []):
            if len(cand) >= 5 and cand != "nagar" and cand not in _LOCALITY_ALIASES:
                match = difflib.get_close_matches(cand, list(_LOCALITY_ALIASES), n=1, cutoff=_FUZZY_CUTOFF)
                if match:
                    add(_LOCALITY_ALIASES[match[0]], start)
    if excluded:
        return sorted((found or set(CANONICAL_LOCALITIES)) - excluded) or None
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
    text = _BHK_WORD.sub(lambda m: _BHK_WORDS[m[1]], text)  # "two bhk" -> "2 bhk"
    if _STUDIO.search(text):  # not 1-4 BHK: read as 0 so the request is refused with a reason
        values.add(0)
    for m in _BHK_AT_LEAST.finditer(text):  # "at least 3 bhk", "3+ bhk", "3 bhk or more" -> 3..4
        n = int(next(g for g in m.groups() if g))
        values.update(range(n, max(BHK_VALUES) + 1) if n <= max(BHK_VALUES) else [n])
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
    m = _BELOW_MONEY.search(text) or _MAX_AFTER_MONEY.search(text)  # "under 80 lakh", "80 lakh max"
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


# Parse audit: what a sentence mentions, so a filter that was read nowhere is reported, not dropped.
_MENTIONS_BHK = re.compile(r"(?:bhk|bed(?:room)?s?)\b|\d\s*br\b")
_MONEY = re.compile(rf"(?:rs\.?\s*|₹\s*)?{_NUM}\s*{_UNIT}|₹\s*\d")
_ONE_SIDED = re.compile(r"\b(?:above|over|more than|at least|atleast|min(?:imum)?|starting(?: from| at)?)\s*(?:rs\.?\s*|₹\s*)?$")
_MENTIONS_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_MENTIONS_SQFT = re.compile(rf"\d\s*{_SQFT_UNIT}")


def unread(sentence: str, criteria: Criteria) -> list[str]:
    """Filters the sentence mentions but ``criteria`` leaves null (BHK, price, year, size).

    A one-sided "above X" is not counted: the contract leaves it null on purpose (5.4)."""
    text = " ".join(sentence.lower().split())
    out = []
    if criteria.bhk is None and _MENTIONS_BHK.search(text):
        out.append("bhk")
    if criteria.price_band is None and any(not _ONE_SIDED.search(text[max(0, m.start() - 25):m.start()])
                                           for m in _MONEY.finditer(text)):
        out.append("price_band")
    if criteria.window_end is None and _MENTIONS_YEAR.search(text):
        out.append("window_end")
    if criteria.sqft_range is None and _MENTIONS_SQFT.search(text):
        out.append("sqft_range")
    return out


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
