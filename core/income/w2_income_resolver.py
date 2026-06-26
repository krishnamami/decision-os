"""W2 / salaried base-income resolver (INC-B).

Qualifies W2 base salary + paystub gross into a qualifying_monthly figure, and
checks the Fannie 2-year employment-history requirement. SYNC + DB-LESS
(ARCHITECTURE RULES 5/6): the persona calls these with values; the resolver
returns findings in memory and NEVER touches the DB. Every threshold comes from
the injected ``rules`` dict (catalogue-resolved), with rule_loader.SAFE_DEFAULTS
as the only fallback (RULE 9) — no resolver-local lending literals.

SCOPE — base salary ONLY. Variable income (overtime/bonus/commission) is OUT of
scope here because the extraction fields it needs do not exist yet; see
VARIABLE_INCOME_TODO.

DATA SOURCES (diagnostic-confirmed):
  W2:      document_index.W2_CURRENT.extracted_fields.box1_wages (annual)
  Paystub: document_index.PAYSTUB_CURRENT.extracted_fields.gross_pay / ytd_gross
  Employ:  entity_states.borrower.employment JSONB {period_start, ...}
  Meridian keeps using the seeded entity_states.qualifying_monthly (unchanged);
  real tenants flow through income_sources (INC-A) once doc fields are attached.
"""
from __future__ import annotations

from typing import Optional

# Citations are documentation labels (not lending values).
_CITE_INCOME = "Fannie B3-3.1-01"
_CITE_HISTORY = "Fannie B3-3.1-01"

# Pay-frequency -> periods per year (calendar facts, not lending thresholds).
FREQ_MULTIPLIER = {
    "weekly":       52,
    "bi-weekly":    26,
    "semi-monthly": 24,
    "monthly":      12,
}

# Method-confidence heuristics (how reliable the derivation is — analogous to
# fact_node confidences; NOT lending thresholds).
_W2_CONFIDENCE = 0.97
_PAYSTUB_CONFIDENCE = 0.90

VARIABLE_INCOME_TODO = (
    "Overtime/bonus/commission qualification requires extraction fields not yet "
    "present in document_index. Paystub extractor needs: overtime_ytd, bonus_ytd, "
    "commission_ytd, hourly_rate, hours_per_week. Add in a future extraction "
    "prompt before INC-B variable income."
)

# Catalogue rule names the income personas read through rule_loader. The W2
# resolver uses employment_history_months_required (INC-B); the INC-E retirement
# resolver's keys ride on the SAME bundle key (income_rules) so one runner load
# covers all income rules. Resolvers remain SEPARATE modules — only the key list
# is unified here.
from core.income.alimony_resolver import ALIMONY_RULE_KEYS
from core.income.multi_borrower_resolver import MULTI_BORROWER_RULE_KEYS
from core.income.multi_unit_income_resolver import MULTI_UNIT_RULE_KEYS
from core.income.retirement_income_resolver import RETIREMENT_INCOME_RULE_KEYS

# De-dup while preserving order — rental_vacancy_factor_pct is shared with INC-D.
def _dedup(seq):
    seen, out = set(), []
    for k in seq:
        if k not in seen:
            seen.add(k); out.append(k)
    return out


INCOME_RULE_KEYS = _dedup([
    "employment_history_months_required",
] + RETIREMENT_INCOME_RULE_KEYS + ALIMONY_RULE_KEYS + MULTI_UNIT_RULE_KEYS
  + MULTI_BORROWER_RULE_KEYS)


async def load_income_rules(conn, tenant_id: str, agency: str = "fannie") -> dict:
    """Resolve every income rule from the catalogue via rule_loader. Returns
    {'values': {key: applied}, 'trace': {key: {applied, governed_by, layers}}}.
    Called on the ASYNC snapshot path (runner) — never inside the sync persona —
    and injected into W2IncomeResolver. Mirrors load_asset_rules (RA-4A)."""
    from core.catalogue.rule_loader import get_rule
    values, trace = {}, {}
    for key in INCOME_RULE_KEYS:
        r = await get_rule(conn, key, tenant_id, agency=agency)
        values[key] = r.get("applied")
        trace[key] = {
            "applied":     r.get("applied"),
            "governed_by": r.get("governed_by"),
            "layers":      r.get("layers", {}),
        }
    return {"values": values, "trace": trace}


class W2IncomeResolver:
    """Base W2/salaried income qualification. All thresholds from ``rules``."""

    INCOME_TYPES = ["W2", "HOURLY", "SALARY"]

    def __init__(self, rules: Optional[dict] = None):
        """``rules`` is the catalogue-resolved {key: value} map. When absent
        (tests / non-enriched callers) fall back to rule_loader.SAFE_DEFAULTS —
        the single sanctioned fallback; no resolver-local hardcoded values."""
        from core.catalogue.rule_loader import SAFE_DEFAULTS
        self._rules = dict(SAFE_DEFAULTS)
        if rules:
            self._rules.update({k: v for k, v in rules.items() if v is not None})
        self._employment_history_months = int(
            self._rules.get("employment_history_months_required", 24))

    # ── W2 document ─────────────────────────────────────────────────────
    def qualify_from_w2_doc(self, extracted_fields: dict) -> dict:
        ef = extracted_fields or {}
        box1_wages = float(ef.get("box1_wages", 0) or 0)
        tax_year = ef.get("tax_year", "")
        employer = ef.get("employer_name", "")

        if not box1_wages:
            return {
                "qualifying_monthly": 0,
                "confidence": 0,
                "method": "W2_no_wages_found",
                "citation": _CITE_INCOME,
                "docs_needed": ["W2 showing box 1 wages"],
                "excluded_reason": "box1_wages not found or zero",
            }

        return {
            "income_type":        "W2",
            "qualifying_monthly": round(box1_wages / 12, 2),
            "annual_amount":      box1_wages,
            "employer_name":      employer,
            "tax_year":           tax_year,
            "method":             "W2 box1_wages / 12",
            "confidence":         _W2_CONFIDENCE,
            "citation":           _CITE_INCOME,
            "docs_needed":        [],
        }

    # ── Paystub ─────────────────────────────────────────────────────────
    def qualify_from_paystub(self, extracted_fields: dict) -> dict:
        ef = extracted_fields or {}
        gross_pay = float(ef.get("gross_pay", 0) or 0)
        ytd_gross = float(ef.get("ytd_gross", 0) or 0)
        pay_frequency = ef.get("pay_frequency", "bi-weekly")
        employer = ef.get("employer_name", "")

        multiplier = FREQ_MULTIPLIER.get(pay_frequency, 26)
        annual_from_gross = gross_pay * multiplier

        return {
            "income_type":        "W2",
            "qualifying_monthly": round(annual_from_gross / 12, 2),
            "annual_amount":      annual_from_gross,
            "employer_name":      employer,
            "ytd_gross":          ytd_gross,
            "pay_frequency":      pay_frequency,
            "method":             f"paystub gross {gross_pay} x {multiplier} / 12",
            "confidence":         _PAYSTUB_CONFIDENCE,
            "citation":           _CITE_INCOME,
            "docs_needed":        [],
        }

    # ── Employment history (2-year requirement, catalogue-driven) ───────
    def check_employment_history(self, employment: dict) -> dict:
        from datetime import date, datetime
        employment = employment or {}
        period_start = employment.get("period_start")
        if isinstance(period_start, str):
            try:
                period_start = datetime.fromisoformat(period_start).date()
            except ValueError:
                period_start = None
        elif isinstance(period_start, datetime):
            period_start = period_start.date()

        if not period_start:
            return {
                "history_sufficient": False,
                "history_months": 0,
                "required_months": self._employment_history_months,
                "docs_needed": ["Employment history documentation required"],
                "citation": _CITE_HISTORY,
            }

        today = date.today()
        months = (today.year - period_start.year) * 12 + \
                 (today.month - period_start.month)
        sufficient = months >= self._employment_history_months
        return {
            "history_sufficient": sufficient,
            "history_months": months,
            "required_months": self._employment_history_months,
            "docs_needed": [] if sufficient else [
                f"2-year employment history required "
                f"({months} months documented)"
            ],
            "citation": _CITE_HISTORY,
        }

    # ── Selection (lesser of W2 vs paystub, conservative) ───────────────
    def select_qualifying_income(
        self, w2_result: dict, paystub_result: dict,
    ) -> dict:
        w2_monthly = (w2_result or {}).get("qualifying_monthly", 0) or 0
        paystub_monthly = (paystub_result or {}).get("qualifying_monthly", 0) or 0

        if w2_monthly and paystub_monthly:
            qualifying = min(w2_monthly, paystub_monthly)
            method = (f"lesser of W2 ({w2_monthly}/mo) "
                      f"and paystub ({paystub_monthly}/mo)")
            confidence = min(w2_result.get("confidence", 0),
                             paystub_result.get("confidence", 0))
        elif w2_monthly:
            qualifying = w2_monthly
            method = "W2 only (no paystub)"
            confidence = w2_result.get("confidence", _W2_CONFIDENCE)
        elif paystub_monthly:
            qualifying = paystub_monthly
            method = "Paystub only (no W2)"
            confidence = paystub_result.get("confidence", _PAYSTUB_CONFIDENCE)
        else:
            qualifying = 0
            method = "no income documents found"
            confidence = 0

        return {
            "qualifying_monthly": qualifying,
            "method": method,
            "confidence": confidence,
            "citation": _CITE_INCOME,
        }


__all__ = ["W2IncomeResolver", "VARIABLE_INCOME_TODO",
           "INCOME_RULE_KEYS", "load_income_rules"]
