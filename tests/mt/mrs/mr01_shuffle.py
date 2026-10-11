"""MR1, shuffle rows (contracts/Testing.md 5).

Family: invariance. Transformation: a seeded permutation of the rows of
``listings_df`` (the seed is the base's drawn ``MR1.permutation_seed``).
Assert: the whole report except ``trace``, ``diagnostics`` and ``metadata`` is
**bit-exact**; ``metadata.topology`` and ``metadata.n_scanners`` are equal too
(Testing.md 1). Skip: never.
Targeted fault: order-dependent aggregation; non-deterministic worker merges (I-ORDER).
"""

from __future__ import annotations

import pandas as pd

from tests.mt.generator import Base
from tests.mt.harness import MR, Diff, FollowUp, bit_exact, diff, exact, keyed

IGNORED = ("trace", "diagnostics", "metadata")


def transform(base: Base, df: pd.DataFrame) -> FollowUp:
    seed = base.params["MR1"]["permutation_seed"]
    shuffled = df.sample(frac=1, random_state=seed).reset_index(drop=True)  # a new frame
    return FollowUp(base.to_criteria(), shuffled, seeds={"permutation": seed})


def check(src: dict, fu: dict, base: Base) -> list[Diff]:
    strip = lambda d: keyed({k: v for k, v in d.items() if k not in IGNORED})
    out = diff(strip(src), strip(fu), bit_exact)
    for f in ("topology", "n_scanners"):
        out += diff(src["metadata"][f], fu["metadata"][f], exact, f"metadata.{f}")
    return out


MR1 = MR(name="MR1", family="invariance", transform=transform, check=check)
