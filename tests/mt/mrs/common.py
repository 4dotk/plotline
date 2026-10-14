"""Report-field helpers shared by the MRs (contracts/Testing.md 3, 5.2, 5.3).

Everything here reads plain report dicts (``harness.report_dict``). Records are
compared by key ``month/region_key`` and flags as a set on
``month/region_key/kind``, never by list position.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

from plotline.contract import ABS_TOL, ANOMALY_PCT, MIN_BUCKET_N
from tests.mt.harness import Diff, abs_tol, abs_tol_pct, diff, exact, keyed, rel_tol

ALL = "ALL"
COUNTS = ("listing_count", "n_in_bucket")
MEDIANS = ("median_price", "median_price_per_sqft")
PCT = "pct_change_price_per_sqft"
STATS = ("price", "price_per_sqft")
Cmp = Callable[[Any, Any], bool]
# every record field with its Testing.md 3 comparator
RECORD_CMP: dict[str, Cmp] = {"listing_count": exact, "n_in_bucket": exact, "low_sample": exact,
                              "median_price": rel_tol, "median_price_per_sqft": rel_tol, PCT: abs_tol}


def records(report: dict) -> dict[str, dict]:
    return keyed(report)["records"]


def month_of(key: str) -> str:
    return key.split("/", 1)[0]


def region_of(key: str) -> str:
    return key.split("/", 1)[1]


def l2_attempts(report: dict) -> int:
    return report["metadata"]["loop_counters"]["L2_attempts"]


def all_series(report: dict) -> list[dict]:
    """The ``ALL`` records in month order."""
    return sorted((r for r in report["records"] if r["region_key"] == ALL), key=lambda r: r["month"])


def scaled(x: Any, f: Callable[[float], float]) -> Any:
    return None if x is None else f(x)


def compare_records(src: dict, fu: dict, fields: dict[str, Cmp], *,
                    expect: dict[str, Callable[[Any], Any]] | None = None,
                    keys: Iterable[str] | None = None,
                    skip_field: Callable[[str, str], bool] = lambda key, f: False) -> list[Diff]:
    """Records compared field by field on ``keys`` (default: every key of either report).
    ``expect[f]`` maps the source value to the expected follow-up value; a key missing
    from one side is a violation on ``records.<key>``."""
    a, b = records(src), records(fu)
    expect = expect or {}
    out: list[Diff] = []
    for k in sorted(set(a) | set(b) if keys is None else keys):
        if k not in a or k not in b:
            out.append(Diff(f"records.{k}", a.get(k, "<missing>"), b.get(k, "<missing>")))
            continue
        for f, cmp in fields.items():
            if skip_field(k, f):
                continue
            want = scaled(a[k][f], expect[f]) if f in expect else a[k][f]
            out += diff(want, b[k][f], cmp, f"records.{k}.{f}")
    return out


def compare_flags(src: dict, fu: dict, months: Iterable[str] | None = None) -> list[Diff]:
    """Anomaly flags as a set on identity, ``value`` by REL_TOL (Testing.md 3);
    only flags whose month is in ``months`` when given."""
    keep = (lambda k: True) if months is None else (lambda k, ms=set(months): month_of(k) in ms)
    a = {k: f for k, f in keyed(src)["anomaly_flags"].items() if keep(k)}
    b = {k: f for k, f in keyed(fu)["anomaly_flags"].items() if keep(k)}
    out: list[Diff] = []
    if set(a) != set(b):
        out.append(Diff("anomaly_flags", sorted(a), sorted(b)))
    for k in sorted(set(a) & set(b)):
        out += diff(a[k]["value"], b[k]["value"], rel_tol, f"anomaly_flags.{k}.value")
    return out


def compare_summary(src: dict, fu: dict, *, scale: Callable[[float], float] = lambda x: x,
                    n_rows: Callable[[int], int] | None = lambda n: n, direction: bool = True) -> list[Diff]:
    """``summary``: start/end vs ``scale(source)`` (REL_TOL), ``change_pct`` (ABS_TOL_PCT),
    ``direction`` EXACT when asked, ``n_rows`` vs ``n_rows(source)`` EXACT unless None."""
    a, b = src["summary"], fu["summary"]
    out: list[Diff] = []
    if n_rows is not None:
        out += diff(n_rows(a["n_rows"]), b["n_rows"], exact, "summary.n_rows")
    for stat in STATS:
        x, y = a[stat], b[stat]
        if x is None or y is None:
            out += diff(x, y, exact, f"summary.{stat}")
            continue
        out += diff(scale(x["start"]), y["start"], rel_tol, f"summary.{stat}.start")
        out += diff(scale(x["end"]), y["end"], rel_tol, f"summary.{stat}.end")
        out += diff(x["change_pct"], y["change_pct"], abs_tol_pct, f"summary.{stat}.change_pct")
        if direction:
            out += diff(x["direction"], y["direction"], exact, f"summary.{stat}.direction")
    return out


def flag_margin(report: dict) -> str | None:
    """MR2 / MR8 skip: any ``||pct| - ANOMALY_PCT| < 1e-9`` (written as ABS_TOL: same value and unit, no literal)."""
    for r in all_series(report):
        pct = r[PCT]
        if pct is not None and abs(abs(pct) - ANOMALY_PCT) < ABS_TOL:
            return f"flag margin at {r['month']}"
    return None


def l2_skip(*reports: dict) -> str | None:
    return "L2_attempts > 0" if any(l2_attempts(r) > 0 for r in reports) else None


def all_reasons(*reasons: str | None) -> str | None:
    """Every reason that applies, deduplicated, in order and joined with `` + ``; None if none.
    All of them are recorded so a base that trips two skips (e.g. the gate and L2) counts under both."""
    found = list(dict.fromkeys(r for r in reasons if r is not None))
    return " + ".join(found) or None


def gate_margin(n: int) -> bool:
    """MR3: doubling ``n`` crosses the ``MIN_BUCKET_N`` gate (n in {3, 4} for 5)."""
    return n < MIN_BUCKET_N <= 2 * n
