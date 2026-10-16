"""The metamorphic relations, by name (contracts/Testing.md 5)."""

from tests.mt.mrs.mr01_shuffle import MR1
from tests.mt.mrs.mr02_unit_change import MR2
from tests.mt.mrs.mr03_duplicate import MR3a, MR3b
from tests.mt.mrs.mr04_add_month import MR4
from tests.mt.mrs.mr05_widen_band import MR5
from tests.mt.mrs.mr06_subregion import MR6
from tests.mt.mrs.mr07_shift_window import MR7
from tests.mt.mrs.mr08_scale_prices import MR8
from tests.mt.mrs.mr09_paraphrase import MR9
from tests.mt.mrs.mr10_bhk_partition import MR10
from tests.mt.mrs.mr11_repair import MR11

MRS = {mr.name: mr for mr in (MR1, MR2, MR3a, MR3b, MR4, MR5, MR6, MR7, MR8, MR9, MR10, MR11)}
