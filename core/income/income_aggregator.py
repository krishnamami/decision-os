"""Income aggregation across streams + borrowers (INC-A).

The income entity model (income_sources / employment_history, INC-A migration)
replaces the single entity_states.qualifying_monthly scalar with one row per
income stream per borrower. This module reads that model back:

  get_qualifying_income() — sum current streams across borrower roles, with a
                            per-role + per-stream breakdown.
  get_employment_gaps()   — gaps > 30 days from vw_employment_gaps (Fannie).

Pure DB reads — no writes, no decision logic. Income-type / borrower-role strings
are NOT inlined; use the constants below (the catalogue of allowed values).
"""
from __future__ import annotations

from typing import Optional

# Allowed income_sources.income_type values (no magic strings at call sites).
INCOME_TYPES = (
    "W2",               # W2 employment income
    "HOURLY",           # hourly + overtime + bonus
    "SELF_EMPLOYED",    # Schedule C / S-Corp / partnership
    "RENTAL",           # Schedule E rental income
    "RETIREMENT",       # pension / 401k distributions
    "SOCIAL_SECURITY",  # SS retirement / disability / survivor
    "ASSET_DEPLETION",  # asset-depletion income
    "ALIMONY",          # alimony received (3yr continuance)
    "CHILD_SUPPORT",    # child support received (3yr continuance)
    "OTHER",            # any other qualifying income
)

# Allowed borrower_role values.
BORROWER_ROLES = (
    "primary",       # primary borrower
    "co_borrower",   # co-borrower (stacks with primary)
    "non_occupant",  # non-occupant co-borrower (special LTV rules)
)

# Roles that count toward qualifying income by default (non_occupant excluded —
# special LTV handling is a downstream concern, INC-B+).
DEFAULT_QUALIFYING_ROLES = ["primary", "co_borrower"]


async def get_qualifying_income(
    conn,
    application_id: str,
    tenant_id: str,
    borrower_roles: Optional[list] = None,
) -> dict:
    """Aggregate current income streams into a qualifying-monthly total with a
    per-role + per-stream breakdown. Reads income_sources only — additive to
    entity_states.qualifying_monthly, never a substitute write."""
    if borrower_roles is None:
        borrower_roles = list(DEFAULT_QUALIFYING_ROLES)

    rows = await conn.fetch(
        """
        SELECT borrower_role, income_type, monthly_amount, confidence
        FROM income_sources
        WHERE application_id = $1
          AND tenant_id = $2
          AND borrower_role = ANY($3)
          AND is_current = true
        ORDER BY borrower_role, income_type
        """,
        application_id, tenant_id, borrower_roles,
    )

    by_role: dict = {}
    for r in rows:
        role = r["borrower_role"]
        bucket = by_role.setdefault(role, {"total": 0.0, "streams": []})
        amount = float(r["monthly_amount"] or 0)
        bucket["total"] += amount
        bucket["streams"].append({
            "type": r["income_type"],
            "monthly": amount,
            "confidence": float(r["confidence"] or 0),
        })

    for bucket in by_role.values():
        bucket["total"] = round(bucket["total"], 2)

    total = round(sum(b["total"] for b in by_role.values()), 2)

    return {
        "qualifying_monthly": total,
        "by_role": by_role,
        "stream_count": len(rows),
        "borrower_roles": list(by_role.keys()),
    }


async def get_employment_gaps(
    conn,
    application_id: str,
    tenant_id: str,
) -> list:
    """Return employment gaps > 30 days (Fannie written-explanation trigger),
    from vw_employment_gaps."""
    rows = await conn.fetch(
        """
        SELECT gap_days, from_employer, to_employer, gap_start, gap_end
        FROM vw_employment_gaps
        WHERE application_id = $1 AND tenant_id = $2
        """,
        application_id, tenant_id,
    )
    return [{
        "gap_days": int(r["gap_days"]) if r["gap_days"] is not None else None,
        "from_employer": r["from_employer"],
        "to_employer": r["to_employer"],
        "gap_start": str(r["gap_start"]) if r["gap_start"] else None,
        "gap_end": str(r["gap_end"]) if r["gap_end"] else None,
    } for r in rows]


__all__ = [
    "INCOME_TYPES", "BORROWER_ROLES", "DEFAULT_QUALIFYING_ROLES",
    "get_qualifying_income", "get_employment_gaps",
]
