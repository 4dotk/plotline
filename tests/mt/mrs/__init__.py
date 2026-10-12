"""The metamorphic relations, by name (contracts/Testing.md 5)."""

from tests.mt.mrs.mr01_shuffle import MR1

MRS = {mr.name: mr for mr in (MR1,)}
