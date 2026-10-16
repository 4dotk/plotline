"""MR11, repair invariance (added 10-16, contract 1.2.0).

Family: invariance. Transformation: plant every repairable defect the base
allows, all at once, the way users write them: each locality name lower-cased
with spaces around it ("  adyar "), the price band written high to low, and an
out-of-range BHK (7) added to the BHK list. Parameters drawn: none.
Assert: the follow-up answers exactly the source's question. The whole report is
bit-exact (records, summary, flags, coverage, ``effective_criteria``, status)
except ``trace``, ``diagnostics``, ``metadata``, ``criteria_in`` and ``notices``
(the follow-up rightly tells the user what was repaired). And L1 fires exactly
once: every defect is repaired in one pass.
Skip: precondition "nothing to plant" (no localities, no band and no BHK set).
Targeted fault: wrong L1 repairs (a band not swapped, a locality matched to the
wrong place, a valid BHK dropped), repairs that take more than one pass, and
anything that makes a repaired request answer differently from a clean one.
Why: in Mode A the generator only draws valid criteria, so before MR11 the MT
campaign never ran L1 (0 of 7,059 runs, 10-16).
"""

from __future__ import annotations

import pandas as pd

from plotline.contract import Criteria
from tests.mt.generator import Base
from tests.mt.harness import MR, Diff, FollowUp, bit_exact, diff, keyed

IGNORED = ("trace", "diagnostics", "metadata", "criteria_in", "notices")
OUT_OF_RANGE_BHK = 7


def precondition(base: Base, df: pd.DataFrame) -> str | None:
    c = base.criteria
    if c["localities"] is None and c["price_band"] is None and c["bhk"] is None:
        return "nothing to plant (no localities, band or BHK)"
    return None


def transform(base: Base, df: pd.DataFrame) -> FollowUp:
    c = dict(base.criteria)
    if c["localities"] is not None:
        c["localities"] = [f"  {name.lower()} " for name in c["localities"]]
    if c["price_band"] is not None:
        c["price_band"] = list(reversed(c["price_band"]))
    if c["bhk"] is not None:
        c["bhk"] = [*c["bhk"], OUT_OF_RANGE_BHK]
    return FollowUp(Criteria.model_validate(c), df.copy())


def check(src: dict, fu: dict, base: Base) -> list[Diff]:
    strip = lambda d: keyed({k: v for k, v in d.items() if k not in IGNORED})  # noqa: E731
    out = diff(strip(src), strip(fu), bit_exact)
    l1 = fu["metadata"]["loop_counters"]["L1_repairs"]
    if l1 != 1:
        out.append(Diff("metadata.loop_counters.L1_repairs", 1, l1))
    if not any(n["kind"] == "repaired" for n in fu.get("notices", [])):
        out.append(Diff("notices", "a 'repaired' notice", fu.get("notices", [])))
    return out


MR11 = MR(name="MR11", family="invariance", transform=transform, check=check, precondition=precondition)
