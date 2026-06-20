"""Pricing math — par base rate + LLPA grid = the rate used for PITI/DTI.

NEW in decision-os (the edms-simulator pipeline_math.py is a separate,
PITI-focused module). This one resolves the *rate*:

    total_rate = par_base_rate(get_rate_for_product) + LLPA(get_llpa_adjustment)

get_llpa_adjustment() reads the Fannie LLPA grid (llpa_adjustments, P0-E)
keyed on FICO x LTV x property type x purpose.

get_rate_for_product() is PROVISIONAL: it returns a product par base from
rate_sheet_entry (lowest seeded base_rate for the product), falling back to
a documented per-loan-type default. The full "fix rate assumption" work —
replacing the rate_pricing persona's hardcoded _BASE_RATE / ad-hoc LLPA
formula with this table-driven path, effective-dating, ARM handling — is
P0-D. This module is the LLPA half it will build on.
"""
from __future__ import annotations

from typing import Any

# Par base rate per loan type when rate_sheet_entry has no row for the
# product. Provisional — superseded by P0-D's rate-assumption fix.
_DEFAULT_PAR_BASE = {
    "conventional": 6.750,
    "fha": 6.625,
    "va": 6.500,
}
_FALLBACK_PAR_BASE = 6.875

# loan_type -> rate_sheet_entry.product_id prefix
_PRODUCT_PREFIX = {
    "conventional": "PRD-FNMA",
    "fha": "PRD-FHA",
    "va": "PRD-VA",
}


async def get_llpa_adjustment(
    conn,
    agency: str,
    credit_score: int,
    ltv: float,
    property_type: str = "sfr",
    loan_purpose: str = "purchase",
) -> dict[str, Any]:
    """LLPA adjustment (in rate %) for this loan profile, added to the base
    rate. Band convention: credit_score_min <= score <= credit_score_max and
    ltv_min < ltv <= ltv_max."""
    row = await conn.fetchrow(
        """
        SELECT adjustment_pct, description
        FROM llpa_adjustments
        WHERE agency = $1
          AND credit_score_min <= $2
          AND credit_score_max >= $2
          AND ltv_min < $3
          AND ltv_max >= $3
          AND (property_type = $4 OR property_type IS NULL)
          AND (loan_purpose = $5 OR loan_purpose IS NULL)
          AND effective_date <= CURRENT_DATE
        ORDER BY effective_date DESC
        LIMIT 1
        """,
        agency, credit_score, ltv, property_type, loan_purpose,
    )
    if row:
        return {
            "adjustment_pct": float(row["adjustment_pct"]),
            "description": row["description"],
            "found": True,
        }
    return {"adjustment_pct": 0.0, "description": "No LLPA found", "found": False}


async def get_rate_for_product(
    conn,
    loan_type: str,
    term_months: int = 360,
) -> float:
    """PROVISIONAL par base rate for a product (the rate before FICO/LTV
    LLPAs). Reads the lowest seeded base_rate for the product from
    rate_sheet_entry; falls back to a documented per-loan-type default.
    P0-D replaces this with the real rate-assumption source."""
    prefix = _PRODUCT_PREFIX.get(loan_type)
    if prefix is not None:
        base = await conn.fetchval(
            """
            SELECT MIN(base_rate) FROM rate_sheet_entry
            WHERE product_id LIKE $1 AND effective_date <= CURRENT_DATE
            """,
            f"{prefix}%",
        )
        if base is not None:
            return float(base)
    return _DEFAULT_PAR_BASE.get(loan_type, _FALLBACK_PAR_BASE)


async def get_total_rate(
    conn,
    tenant_id: str,
    loan_type: str,
    credit_score: int,
    ltv: float,
    term_months: int = 360,
    property_type: str = "sfr",
    loan_purpose: str = "purchase",
) -> dict[str, Any]:
    """Total rate = par base rate + LLPA. This is the rate used for PITI/DTI."""
    base = await get_rate_for_product(conn, loan_type, term_months)
    agency = "fannie" if loan_type == "conventional" else loan_type
    llpa = await get_llpa_adjustment(
        conn,
        agency=agency,
        credit_score=credit_score,
        ltv=ltv,
        property_type=property_type,
        loan_purpose=loan_purpose,
    )
    total = base + llpa["adjustment_pct"]
    return {
        "base_rate": round(base, 4),
        "llpa_pct": llpa["adjustment_pct"],
        "llpa_description": llpa["description"],
        "total_rate": round(total, 4),
        "loan_type": loan_type,
        "credit_score": credit_score,
        "ltv": ltv,
    }


__all__ = ["get_llpa_adjustment", "get_rate_for_product", "get_total_rate"]
