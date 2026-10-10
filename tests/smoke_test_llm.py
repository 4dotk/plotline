#!/usr/bin/env python3
"""Contract-aligned, one-query smoke test for the local LangChain model.

Run from repository root:
    uv run python scripts/smoke_test_llm.py

Optional query:
    uv run python scripts/smoke_test_llm.py "Show Adyar 1 BHK houses last year"

This script tests the LLM Planner boundary only: natural-language query ->
Criteria JSON -> filtering the frozen snapshot. It does not run the full
12-month trend application/orchestrator.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "chennai_snapshot.csv"

LOCALITIES = [
    "Adyar",
    "Anna Nagar",
    "Chrompet",
    "KK Nagar",
    "Karapakkam",
    "T Nagar",
    "Velachery",
]
SALE_CONDITIONS = ["AbNormal", "AdjLand", "Family", "Normal Sale", "Partial"]


class Criteria(BaseModel):
    """Fields and constraints from GLOBAL_CONTRACT.md section 5.2."""

    model_config = ConfigDict(extra="forbid")

    localities: list[str] | None = None
    window_end: str = "2015-02"
    bhk: list[int] | None = None
    price_band: list[float] | None = Field(default=None, min_length=2, max_length=2)
    sqft_range: list[float] | None = Field(default=None, min_length=2, max_length=2)
    sale_cond: list[str] | None = None
    price_unit: Literal["inr", "lakh"] = "inr"

    @model_validator(mode="after")
    def validate_values(self) -> "Criteria":
        if not isinstance(self.window_end, str) or len(self.window_end) != 7:
            raise ValueError("window_end must have YYYY-MM format")
        try:
            year, month = (int(part) for part in self.window_end.split("-"))
        except (ValueError, TypeError):
            raise ValueError("window_end must have YYYY-MM format")
        if not 1 <= month <= 12:
            raise ValueError("window_end month must be 01..12")
        if not (year, month) >= (2004, 12) or not (year, month) <= (2015, 2):
            raise ValueError("window_end must be between 2004-12 and 2015-02")
        if self.localities is not None:
            unknown = sorted(set(self.localities) - set(LOCALITIES))
            if unknown:
                raise ValueError(f"Unknown localities: {unknown}")
        if self.bhk is not None and any(
            isinstance(value, bool) or value not in {1, 2, 3, 4}
            for value in self.bhk
        ):
            raise ValueError("bhk values must be in 1..4")
        if self.sale_cond is not None:
            unknown = sorted(set(self.sale_cond) - set(SALE_CONDITIONS))
            if unknown:
                raise ValueError(f"Unknown sale_cond values: {unknown}")
        for name in ("price_band", "sqft_range"):
            bounds = getattr(self, name)
            if bounds is not None:
                if len(bounds) != 2:
                    raise ValueError(f"{name} must contain [lo, hi]")
                if bounds[0] < 0 or bounds[1] < 0:
                    raise ValueError(f"{name} bounds must be non-negative")
                if bounds[0] > bounds[1]:
                    raise ValueError(f"{name} lower bound cannot exceed upper bound")
        return self


SYSTEM_PROMPT = f"""You are the Query Planner for a Chennai housing-trends application.
Convert the user's sentence into exactly one JSON Criteria object. Return JSON only.
Schema:
{{
  "localities": list of canonical locality strings or null,
  "window_end": "YYYY-MM",
  "bhk": list of integers from 1 to 4 or null,
  "price_band": [inclusive lower price, inclusive upper price] or null,
  "sqft_range": [inclusive lower sqft, inclusive upper sqft] or null,
  "sale_cond": list of canonical sale-condition strings or null,
  "price_unit": "inr" or "lakh"
}}
Canonical localities: {", ".join(LOCALITIES)}.
Canonical sale conditions: {", ".join(SALE_CONDITIONS)}.
Rules:
- Default window_end is "2015-02", the latest month in this frozen snapshot.
- "last year", "past year", "last 12 months", and "this year" resolve to window_end "2015-02".
- A named window such as "12 months ending March 2011" resolves to "2011-03".
- Money words are converted to INR: 1 lakh = 100000 INR; 1 crore = 10000000 INR.
- price_band is expressed in price_unit. Use price_unit "inr" by default.
- "below X" means a price_band [0, X]; "above X" means [X, a sufficiently large upper bound only if explicitly required by schema interpretation]. If a single-sided constraint cannot be represented faithfully, use [0, X] only for "below", otherwise set price_band null.
- Locality, BHK, and window are hard filters. Do not add unstated constraints.
- Use null for unspecified optional filters.
"""


def apply_criteria(df: pd.DataFrame, criteria: Criteria) -> pd.DataFrame:
    """Apply Criteria filters to snapshot columns; prices are INR in the snapshot."""
    result = df.copy()

    if criteria.localities is not None:
        result = result[result["locality"].isin(criteria.localities)]
    if criteria.bhk is not None:
        result = result[result["bhk"].isin(criteria.bhk)]
    if criteria.sale_cond is not None:
        result = result[result["sale_cond"].isin(criteria.sale_cond)]
    if criteria.sqft_range is not None:
        lo, hi = criteria.sqft_range
        result = result[result["sqft"].between(lo, hi, inclusive="both")]
    if criteria.price_band is not None:
        lo, hi = criteria.price_band
        # The snapshot stores INR. Criteria price_unit tells us how to read
        # the input band; convert the band for this smoke-test filter only.
        factor = 100_000 if criteria.price_unit == "lakh" else 1
        result = result[result["price"].between(lo * factor, hi * factor, inclusive="both")]

    start = pd.Period(criteria.window_end, freq="M") - 11
    end = pd.Period(criteria.window_end, freq="M")
    months = pd.to_datetime(result["sale_date"], errors="coerce").dt.to_period("M")
    return result[(months >= start) & (months <= end)]


def parse_response(text: str) -> Criteria:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Model response did not contain a JSON object")
    obj: Any = json.loads(cleaned[start : end + 1])
    return Criteria.model_validate(obj)


def main() -> int:
    load_dotenv(ROOT / ".env", override=False)

    if os.getenv("LLM_TYPE", "LOCAL").strip().upper() != "LOCAL":
        print("ERROR: this smoke test expects LLM_TYPE=LOCAL", file=sys.stderr)
        return 2
    if os.getenv("LLM_MODE", "live").strip().lower() != "live":
        print("ERROR: this smoke test requires LLM_MODE=live", file=sys.stderr)
        return 2
    if not SNAPSHOT.is_file():
        print(f"ERROR: snapshot not found: {SNAPSHOT}", file=sys.stderr)
        return 2

    query = " ".join(sys.argv[1:]).strip() or "Show houses in Adyar up to May 2012."
    llm = ChatOpenAI(
        base_url=os.getenv("LLM_BASE_URL", "http://127.0.0.1:8088/v1"),
        model=os.getenv("LLM_MODEL", "gemma-4-e4b"),
        api_key=os.getenv("LLM_API_KEY", "").strip() or "not-needed",
        temperature=0,
        max_tokens=int(os.getenv("LLM_MAX_TOKENS", "256")),
        timeout=120,
        max_retries=0,
    )

    print(f"Endpoint: {os.getenv('LLM_BASE_URL', 'http://127.0.0.1:8088/v1')}")
    print(f"Model: {os.getenv('LLM_MODEL', 'gemma-4-e4b')}")
    print(f"Query: {query}")
    print("Calling model...")

    raw_text = ""
    criteria: Criteria | None = None
    errors: list[str] = []
    for attempt in range(1, 4):  # initial attempt + up to 2 retries
        prompt = SYSTEM_PROMPT
        if errors:
            prompt += "\nYour previous output failed validation. Correct these errors:\n" + "\n".join(errors)
        response = llm.invoke([("system", prompt), ("human", query)])
        raw_text = response.content if isinstance(response.content, str) else str(response.content)
        try:
            criteria = parse_response(raw_text)
            break
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            errors.append(f"Attempt {attempt}: {exc}")

    print("\nRAW MODEL RESPONSE:")
    print(raw_text)

    if criteria is None:
        print("\nVALIDATION FAILED after 3 attempts:")
        print("\n".join(errors))
        print("Contract behaviour: application should use its rule-based parser fallback here.")
        return 1

    print("\nVALIDATED CRITERIA JSON:")
    print(criteria.model_dump_json(indent=2))

    df = pd.read_csv(SNAPSHOT)
    matches = apply_criteria(df, criteria)
    print(f"\nSnapshot rows: {len(df)}")
    print(f"Matching rows in the 12-month window: {len(matches)}")
    print("\nMATCHING RECORDS (first 10, JSON):")
    print(matches.head(10).to_json(orient="records", indent=2, force_ascii=False))
    print("\nSMOKE TEST PASSED: model responded, Criteria validated, snapshot filtering ran.")
    print("Scope: this does not run the full TrendReport agents/orchestrator.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
