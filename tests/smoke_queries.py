"""The 20 smoke queries for the AI-mode Planner, with the filters each should give.

``EXPECT`` is what a correct reading is (CONTRACT.md 5.2, 5.4). Hard fields
(localities, window_end, bhk) are compared on ``effective_criteria`` (after the L1
repair, which is allowed to fix spelling and clamp the window); soft fields
(price_band, sqft_range, sale_cond) on ``criteria_in`` (L2 may widen them later).
``window_end`` None means "latest month".
"""

LAKH, CRORE = 100_000, 10_000_000
LATEST = "2015-02"


def exp(localities=None, window_end=LATEST, bhk=None, price_band=None, sqft_range=None, sale_cond=None):
    return dict(localities=localities, window_end=window_end, bhk=bhk, price_band=price_band,
                sqft_range=sqft_range, sale_cond=sale_cond)


HARD = ("localities", "window_end", "bhk")
SOFT = ("price_band", "sqft_range", "sale_cond")

# (sentence, expected filters, L1 repairs these filters need; the last two sentences are bad on purpose)
QUERIES: list[tuple[str, dict, int]] = [
    ("Show houses in Adyar up to May 2012.", exp(["Adyar"], "2012-05"), 0),
    ("2 bhk flats in Anna Nagar last year", exp(["Anna Nagar"], bhk=[2]), 0),
    ("Velachery 3 BHK under 80 lakh", exp(["Velachery"], bhk=[3], price_band=[0, 80 * LAKH]), 0),
    ("Price trend in T Nagar for 2011", exp(["T Nagar"], "2011-12"), 0),
    ("1 BHK in Adyar between 70 and 90 lakh, 12 months ending December 2010",
     exp(["Adyar"], "2010-12", [1], [70 * LAKH, 90 * LAKH]), 0),
    ("Show me Chrompet and Karapakkam sales for the past year", exp(["Chrompet", "Karapakkam"]), 0),
    ("houses in KK Nagar sold under 1 crore", exp(["KK Nagar"], price_band=[0, CRORE]), 0),
    ("3 or 4 BHK homes in Velachery, 1500 to 2500 sqft",
     exp(["Velachery"], bhk=[3, 4], sqft_range=[1500, 2500]), 0),
    ("family sales in Anna Nagar in 2013", exp(["Anna Nagar"], "2013-12", sale_cond=["Family"]), 0),
    ("Normal sale apartments in Adyar this year", exp(["Adyar"], sale_cond=["Normal Sale"]), 0),
    ("Trends across all localities in the last 12 months", exp(), 0),
    ("Chennai housing prices", exp(), 0),
    ("2 bhk in Velchery last year", exp(["Velachery"], bhk=[2]), 0),  # misspelt: model or L1 fixes it
    ("Anna Nagar, Adyar and T Nagar 2 BHK in March 2012",
     exp(["Adyar", "Anna Nagar", "T Nagar"], "2012-03", [2]), 0),
    ("Karapakam 1 bhk flats under 50 lakh", exp(["Karapakkam"], bhk=[1], price_band=[0, 50 * LAKH]), 0),
    ("Sales in Chrompet from 40 lakh to 60 lakh in the 12 months ending June 2013",
     exp(["Chrompet"], "2013-06", price_band=[40 * LAKH, 60 * LAKH]), 0),
    ("4 bhk T Nagar under 3000 sqft last year", exp(["T Nagar"], bhk=[4], sqft_range=[0, 3000]), 0),
    ("Adyar and Velachery abnormal sales last year", exp(["Adyar", "Velachery"], sale_cond=["AbNormal"]), 0),
    ("Adyar prices up to December 2020", exp(["Adyar"], LATEST), 1),  # window past the data: L1 clamps
    ("Velachery between 90 lakh and 50 lakh last year", exp(["Velachery"], price_band=[90 * LAKH, 50 * LAKH]), 1),  # inverted band as asked; L1 swaps it
]
assert len(QUERIES) == 20
