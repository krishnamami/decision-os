"""Alimony + child-support resolver (INC-F).

Handles both directions per Fannie B3-3.1-09 (income received: 3-yr continuance)
and B3-6-05 (alimony paid: monthly debt vs income reduction):
  qualify_alimony_received / qualify_child_support_received — RECEIVED income
  treat_alimony_paid / treat_child_support_paid             — PAID liability

SYNC + DB-LESS (RULES 5/6). Thresholds from the injected ``rules`` dict
(catalogue via load_alimony_rules), falling back to rule_loader.SAFE_DEFAULTS
(RULE 9). Returns findings in memory; never touches the DB. SEPARATE module from
the W2 / retirement resolvers.

INPUT shape = the DIVORCE_DECREE Vision extractor fields (RA-EX-D):
  alimony_monthly, alimony_receiving, alimony_termination_date,
  child_support_monthly, child_support_paying.

SCOPE (INC-F): catalogue-driven calculators + unit tests. Meridian carries NO
decree docs, so every method returns not_applicable there — advisory/foundation
only. Live data flows on PATH 2 (ingest_document -> income_sources) via a separate
extraction prompt.
"""
from __future__ import annotations

from typing import Optional

_CITE_INCOME = "Fannie B3-3.1-09"
_CITE_PAID = "Fannie B3-6-05"
_CONFIDENCE = 0.90  # method-confidence heuristic, not a lending value

# Catalogue rule names this resolver reads through rule_loader.
ALIMONY_RULE_KEYS = [
    "alimony_continuance_months_required",
    "child_support_continuance_months_required",
    "alimony_paid_dti_treatment",
]


async def load_alimony_rules(conn, tenant_id: str, agency: str = "fannie") -> dict:
    """Resolve the INC-F rules from the catalogue via rule_loader. Returns
    {'values': {key: applied}, 'trace': {...}}. ASYNC snapshot path (runner) only;
    injected into AlimonyChildSupportResolver. Mirrors load_asset_rules (RA-4A)."""
    from core.catalogue.rule_loader import get_rule
    values, trace = {}, {}
    for key in ALIMONY_RULE_KEYS:
        r = await get_rule(conn, key, tenant_id, agency=agency)
        values[key] = r.get("applied")
        trace[key] = {
            "applied":     r.get("applied"),
            "governed_by": r.get("governed_by"),
            "layers":      r.get("layers", {}),
        }
    return {"values": values, "trace": trace}


class AlimonyChildSupportResolver:
    def __init__(self, rules: Optional[dict] = None):
        from core.catalogue.rule_loader import SAFE_DEFAULTS
        r = dict(SAFE_DEFAULTS)
        if rules:
            r.update({k: v for k, v in rules.items() if v is not None})
        self._alimony_continuance = int(
            r.get("alimony_continuance_months_required", 36))
        self._child_support_continuance = int(
            r.get("child_support_continuance_months_required", 36))
        self._alimony_paid_treatment = str(
            r.get("alimony_paid_dti_treatment", "monthly_debt"))

    # ── RECEIVED income ─────────────────────────────────────────────────
    def qualify_alimony_received(self, decree_data: dict) -> dict:
        decree_data = decree_data or {}
        monthly_amount = float(decree_data.get("alimony_monthly", 0) or 0)
        is_receiving = decree_data.get("alimony_receiving", False)
        termination_date = decree_data.get("alimony_termination_date")
        continuance_months = int(decree_data.get("continuance_months_remaining", 0) or 0)

        if not is_receiving or not monthly_amount:
            return {
                "income_type": "ALIMONY", "qualifying_monthly": 0, "confidence": 0,
                "method": "alimony_not_applicable", "citation": _CITE_INCOME,
                "docs_needed": [],
                "note": "Borrower is not receiving alimony or amount is zero",
            }
        if continuance_months < self._alimony_continuance:
            return {
                "income_type": "ALIMONY", "qualifying_monthly": 0,
                "confidence": _CONFIDENCE,
                "method": "alimony_excluded_insufficient_continuance",
                "citation": _CITE_INCOME,
                "docs_needed": [
                    "3-year continuance required from closing date",
                    "Divorce decree showing alimony termination date",
                    "Documentation that alimony will continue for 3+ years",
                ],
                "excluded_reason": (f"Alimony continuance {continuance_months}mo < "
                                    f"{self._alimony_continuance}mo required"),
                "termination_date": termination_date,
            }
        return {
            "income_type": "ALIMONY",
            "qualifying_monthly": round(monthly_amount, 2),
            "annual_amount": round(monthly_amount * 12, 2),
            "method": "alimony_received_3yr_continuance_confirmed",
            "citation": _CITE_INCOME, "confidence": _CONFIDENCE,
            "termination_date": termination_date,
            "docs_needed": ["Divorce decree", "12-month payment history"],
        }

    def qualify_child_support_received(self, decree_data: dict) -> dict:
        decree_data = decree_data or {}
        monthly_amount = float(decree_data.get("child_support_monthly", 0) or 0)
        is_paying = decree_data.get("child_support_paying", True)
        continuance_months = int(decree_data.get("continuance_months_remaining", 0) or 0)

        if is_paying or not monthly_amount:
            return {
                "income_type": "CHILD_SUPPORT", "qualifying_monthly": 0,
                "confidence": 0, "method": "child_support_not_applicable",
                "citation": _CITE_INCOME, "docs_needed": [],
                "note": "Borrower is paying child support (not receiving) or amount is zero",
            }
        if continuance_months < self._child_support_continuance:
            return {
                "income_type": "CHILD_SUPPORT", "qualifying_monthly": 0,
                "confidence": _CONFIDENCE,
                "method": "child_support_excluded_insufficient_continuance",
                "citation": _CITE_INCOME,
                "docs_needed": [
                    "3-year continuance required from closing date",
                    "Court order showing child support termination date",
                ],
                "excluded_reason": (f"Child support continuance {continuance_months}mo "
                                    f"< {self._child_support_continuance}mo required"),
            }
        return {
            "income_type": "CHILD_SUPPORT",
            "qualifying_monthly": round(monthly_amount, 2),
            "annual_amount": round(monthly_amount * 12, 2),
            "method": "child_support_received_3yr_continuance_confirmed",
            "citation": _CITE_INCOME, "confidence": _CONFIDENCE,
            "docs_needed": ["Court order", "12-month payment history"],
        }

    # ── PAID liability ──────────────────────────────────────────────────
    def treat_alimony_paid(self, decree_data: dict) -> dict:
        decree_data = decree_data or {}
        monthly_amount = float(decree_data.get("alimony_monthly", 0) or 0)
        is_paying = not decree_data.get("alimony_receiving", True)

        if not is_paying or not monthly_amount:
            return {
                "treatment": "not_applicable", "monthly_obligation": 0,
                "income_reduction": 0, "method": "alimony_paid_not_applicable",
            }
        if self._alimony_paid_treatment == "reduce_income":
            return {
                "treatment": "reduce_income", "monthly_obligation": 0,
                "income_reduction": round(monthly_amount, 2),
                "method": "alimony_paid_deducted_from_gross_income",
                "citation": _CITE_PAID,
                "note": "Alimony reduces gross qualifying income, not DTI obligations",
            }
        return {
            "treatment": "monthly_debt",
            "monthly_obligation": round(monthly_amount, 2), "income_reduction": 0,
            "method": "alimony_paid_counted_as_monthly_debt", "citation": _CITE_PAID,
        }

    def treat_child_support_paid(self, decree_data: dict) -> dict:
        decree_data = decree_data or {}
        monthly_amount = float(decree_data.get("child_support_monthly", 0) or 0)
        is_paying = decree_data.get("child_support_paying", False)

        if not is_paying or not monthly_amount:
            return {
                "treatment": "not_applicable", "monthly_obligation": 0,
                "method": "child_support_paid_not_applicable",
            }
        return {
            "treatment": "monthly_debt",
            "monthly_obligation": round(monthly_amount, 2),
            "method": "child_support_paid_counted_as_monthly_debt",
            "citation": _CITE_PAID,
            "note": "Child support paid always counts as a monthly obligation",
        }


__all__ = ["AlimonyChildSupportResolver", "ALIMONY_RULE_KEYS", "load_alimony_rules"]
