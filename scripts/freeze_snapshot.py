"""Freeze the Chennai snapshot exactly as CONTRACT.md section 3 specifies.

Usage: python scripts/freeze_snapshot.py RAW_CSV [OUT_CSV]
Prints the raw hash, every cleaning count, and the SHA256 of the snapshot.
"""
import hashlib
import sys

import pandas as pd

AREA_FIX = {
    "Chrompt": "Chrompet", "Chrmpet": "Chrompet", "Chormpet": "Chrompet",
    "TNagar": "T Nagar", "Karapakam": "Karapakkam", "Ana Nagar": "Anna Nagar",
    "Ann Nagar": "Anna Nagar", "Velchery": "Velachery", "Adyr": "Adyar",
    "KKNagar": "KK Nagar",
}
COND_FIX = {"Adj Land": "AdjLand", "Ab Normal": "AbNormal",
            "Partiall": "Partial", "PartiaLl": "Partial"}
LOCALITIES = {"Adyar", "Anna Nagar", "Chrompet", "KK Nagar", "Karapakkam",
              "T Nagar", "Velachery"}
CONDS = {"AbNormal", "AdjLand", "Family", "Normal Sale", "Partial"}
COLUMNS = ["listing_id", "locality", "sqft", "sale_date", "bhk", "sale_cond", "price"]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main(raw, out):
    print("raw sha256 :", sha256(raw))
    d = pd.read_csv(raw)
    print("raw rows   :", len(d))
    d["AREA"] = d["AREA"].str.strip()
    d["SALE_COND"] = d["SALE_COND"].str.strip()
    print("R1 AREA rows repaired      :", int(d["AREA"].isin(AREA_FIX).sum()))
    d["AREA"] = d["AREA"].replace(AREA_FIX)
    print("R2 SALE_COND rows repaired :", int(d["SALE_COND"].isin(COND_FIX).sum()))
    d["SALE_COND"] = d["SALE_COND"].replace(COND_FIX)
    assert set(d["AREA"]) == LOCALITIES, set(d["AREA"]) ^ LOCALITIES
    assert set(d["SALE_COND"]) == CONDS, set(d["SALE_COND"]) ^ CONDS
    n_nan = int(d["N_BEDROOM"].isna().sum())
    print("R3 rows dropped (no bedroom):", n_nan)
    d = d.dropna(subset=["N_BEDROOM"])
    assert d["PRT_ID"].is_unique
    assert (d["SALES_PRICE"] > 0).all() and (d["INT_SQFT"] > 0).all()
    date = pd.to_datetime(d["DATE_SALE"], format="%d-%m-%Y", errors="raise")
    s = pd.DataFrame({
        "listing_id": d["PRT_ID"],
        "locality": d["AREA"],
        "sqft": d["INT_SQFT"].astype(int),
        "sale_date": date.dt.strftime("%Y-%m-%d"),
        "bhk": d["N_BEDROOM"].astype(int),
        "sale_cond": d["SALE_COND"],
        "price": d["SALES_PRICE"].astype(int),
    })[COLUMNS].sort_values("listing_id").reset_index(drop=True)
    assert set(s["bhk"]) <= {1, 2, 3, 4}
    s.to_csv(out, index=False, lineterminator="\n")
    print("snapshot rows:", len(s), " date range:", s["sale_date"].min(), "to", s["sale_date"].max())
    print("per locality :", s["locality"].value_counts().sort_index().to_dict())
    print("snapshot sha256:", sha256(out))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "data/chennai_snapshot.csv")
