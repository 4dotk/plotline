"""Realistic sentences that need the L1 repair loop (10-16).

Not typos: what ordinary users write that the data or the criteria cannot hold
as asked. The data ends in 2015-02, so any question about a recent year is out
of range; the data has 1-4 BHK only; budgets are often said top-down; people
use local names. Same format as ``tests/smoke_queries.py``: (sentence,
expected, L1 repairs the rule parser needs). ``expected`` is the reading after
L1 (hard fields) or as read (soft fields, compared in either order), or the
error code a correct run ends with. Whether L1 fires with the model depends on
whether the model already fixed the value itself; both count as right.

Run with ``scripts/smoke_20_queries.py --queries tests.nl_l1_scenarios [--rules-only]``.
Rows marked POLICY are the team's reading of a case the contract leaves open.
"""

from tests.smoke_queries import CRORE, LAKH, LATEST, exp

FIRST_END = "2004-12"  # earliest window_end with 12 months of data

QUERIES: list[tuple[str, object, int]] = [
    # -- a recent (or very old) year: window_out_of_range -> clamp ------------------------------
    ("How much were 2BHK flats going for in Adyar in 2023?", exp(["Adyar"], LATEST, [2]), 1),
    ("I'm planning to buy in T Nagar next year, what did prices look like in 2024?", exp(["T Nagar"]), 1),
    ("Chrompet prices for the 12 months ending March 2021", exp(["Chrompet"]), 1),
    ("Post-covid trend for Velachery 3 BHK in 2021", exp(["Velachery"], bhk=[3]), 1),
    ("What did houses in KK Nagar sell for back in 2002?", exp(["KK Nagar"], FIRST_END), 1),

    # -- more bedrooms than the data has: bhk_out_of_range -> drop, or error ----------------------
    ("Any 5 BHK independent houses sold in Adyar?", "E_INVALID_CRITERIA", 0),
    ("3, 4 or 5 BHK homes in Anna Nagar", exp(["Anna Nagar"], bhk=[3, 4]), 1),
    ("Big family home, 4 or 5 bedrooms, in Velachery under 2 crore",
     exp(["Velachery"], bhk=[4], price_band=[0, 2 * CRORE]), 1),
    ("Studio apartments near Chrompet", "E_INVALID_CRITERIA", 0),  # POLICY: a studio is not 1-4 BHK

    # -- budget said top-down: band_inverted -> swap ------------------------------------------------
    ("Flats in KK Nagar, budget between 1 crore and 75 lakh", exp(["KK Nagar"], price_band=[75 * LAKH, CRORE]), 1),
    ("Anything from 1.5 cr down to 90 lakhs in T Nagar?", exp(["T Nagar"], price_band=[90 * LAKH, 15 * CRORE // 10]), 1),
    ("2 BHK in Adyar priced 90 to 65 lakh", exp(["Adyar"], bhk=[2], price_band=[65 * LAKH, 90 * LAKH]), 1),

    # -- local names for the 7 localities: locality_unknown -> canonical name -----------------------
    ("3 BHK in K.K. Nagar", exp(["KK Nagar"], bhk=[3]), 0),
    ("Anna Nagar West 2 BHK flats", exp(["Anna Nagar"], bhk=[2]), 0),  # POLICY: a sub-area -> its locality
    ("Thyagaraya Nagar property prices last year", exp(["T Nagar"]), 0),  # POLICY: T Nagar's full name
    ("Homes along OMR near Karapakkam under 60 lakh", exp(["Karapakkam"], price_band=[0, 60 * LAKH]), 0),

    # -- several at once: one L1 pass repairs them all ----------------------------------------------
    ("Looking for 4-5 BHK independent houses in Adyar, budget 3 crore to 2 crore, what did they go for in 2022?",
     exp(["Adyar"], bhk=[4], price_band=[2 * CRORE, 3 * CRORE]), 1),
    ("My parents want a 2BHK in T Nagar, max 80 lakh, what were prices in 2025?",
     exp(["T Nagar"], bhk=[2], price_band=[0, 80 * LAKH]), 1),
]
