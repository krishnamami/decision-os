"""Monthly-obligation resolver (OB-A).

Decomposes a borrower's monthly debt obligations by type and computes the
qualifying monthly payment for each per Fannie B3-6-02 / B3-6-05, returning a
per-type breakdown + the excluded items. SYNC + DB-LESS (RULES 5/6); every
threshold from the injected ``rules`` dict (catalogue), SAFE_DEFAULTS fallback
(RULE 9). Returns findings in memory; never touches the DB.

ROUTING (one entry per obligation, dispatched on ``type``):
  student_loan      -> uses the PRE-COMPUTED payment (TradelineAnalyzer already
                       applies the deferred-1%/IBR/PSLF rules in credit_assessment;
                       this resolver does NOT recompute it).
  alimony_paid       -> AlimonyChildSupportResolver.treat_alimony_paid (INC-F)
  child_support_paid -> AlimonyChildSupportResolver.treat_child_support_paid (INC-F)
  installment        -> actual payment, else balance / months_remaining; EXCLUDED
                        when months_remaining <= months_remaining_exclusion (B3-6-05)
  revolving          -> reported min payment, else balance * revolving_payment_factor_pct
  heloc              -> actual payment, else (draw period / $0 payment) credit_limit
                        or balance * heloc_payment_factor_pct
  business_debt      -> EXCLUDED only if business-paid >= business_debt_exclusion_months
                        (12) with no 30-day delinquency; else INCLUDED + docs_needed (OB-B)
  rental_property    -> rental_net_monthly - pitia_monthly; >=0 positive offset (not a DTI
                        obligation), <0 shortfall added to DTI (Fannie B3-3.1-08) (OB-B)

ADVISORY (OB-A): wired into dti_calculation as an output_payload breakdown only —
it does NOT change dti_front / dti_back / the DTI ratio (that is a later OB slice).
Live per-obligation inputs (tradelines, decree) are attached on PATH 2; meridian's
dti bundle carries only the aggregate, so the breakdown is foundation there.
"""
from __future__ import annotations

from typing import Optional

_CITE = "Fannie B3-6-02"


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


# Catalogue rule names this resolver reads through rule_loader.
OBLIGATION_RULE_KEYS = [
    "revolving_payment_factor_pct",
    "heloc_payment_factor_pct",
    "months_remaining_exclusion",
    "business_debt_exclusion_months",      # OB-B
    # alimony-paid treatment is read by the delegated AlimonyChildSupportResolver
    "alimony_paid_dti_treatment",
]


async def load_obligation_rules(conn, tenant_id: str, agency: str = "fannie") -> dict:
    """Resolve the OB-A obligation rules from the catalogue via rule_loader.
    Returns {'values': {key: applied}, 'trace': {...}}. ASYNC snapshot path
    (runner) only; injected into ObligationResolver. Mirrors load_asset_rules."""
    from core.catalogue.rule_loader import get_rule
    values, trace = {}, {}
    for key in OBLIGATION_RULE_KEYS:
        r = await get_rule(conn, key, tenant_id, agency=agency)
        values[key] = r.get("applied")
        trace[key] = {
            "applied":     r.get("applied"),
            "governed_by": r.get("governed_by"),
            "layers":      r.get("layers", {}),
        }
    return {"values": values, "trace": trace}


class ObligationResolver:
    def __init__(self, rules: Optional[dict] = None):
        from core.catalogue.rule_loader import SAFE_DEFAULTS
        r = dict(SAFE_DEFAULTS)
        if rules:
            r.update({k: v for k, v in rules.items() if v is not None})
        self._rules = r  # passed through to the delegated INC-F resolver
        self._revolving_pct = float(r.get("revolving_payment_factor_pct", 5))
        self._heloc_pct = float(r.get("heloc_payment_factor_pct", 1))
        self._months_remaining_exclusion = int(
            float(r.get("months_remaining_exclusion", 10)))
        self._business_debt_exclusion_months = int(
            float(r.get("business_debt_exclusion_months", 12)))

    # ── per-type calculators ────────────────────────────────────────────
    def compute_installment(self, obl: dict) -> dict:
        obl = obl or {}
        payment = _f(obl.get("monthly_payment"))
        balance = _f(obl.get("balance"))
        months_remaining = obl.get("months_remaining")
        if not payment and balance and months_remaining:
            payment = round(balance / max(1, int(months_remaining)), 2)
        if months_remaining is not None and \
                int(months_remaining) <= self._months_remaining_exclusion:
            return {"type": "installment", "monthly_obligation": 0, "included": False,
                    "excluded_reason": (f"{months_remaining}mo remaining <= "
                                        f"{self._months_remaining_exclusion} (B3-6-05)"),
                    "method": "installment_months_remaining_excluded", "citation": "Fannie B3-6-05"}
        return {"type": "installment", "monthly_obligation": round(payment, 2),
                "included": payment > 0, "method": "installment_actual_or_balance_div_months",
                "citation": _CITE}

    def compute_revolving(self, obl: dict) -> dict:
        obl = obl or {}
        payment = _f(obl.get("monthly_payment") or obl.get("minimum_payment"))
        balance = _f(obl.get("balance"))
        if payment:
            return {"type": "revolving", "monthly_obligation": round(payment, 2),
                    "included": True, "method": "revolving_reported_min_payment",
                    "citation": _CITE}
        computed = round(balance * self._revolving_pct / 100, 2)
        return {"type": "revolving", "monthly_obligation": computed,
                "included": computed > 0,
                "method": f"revolving_{self._revolving_pct:.0f}pct_of_balance",
                "citation": _CITE}

    def compute_heloc(self, obl: dict) -> dict:
        obl = obl or {}
        payment = _f(obl.get("monthly_payment"))
        balance = _f(obl.get("balance"))
        credit_limit = _f(obl.get("credit_limit"))
        if payment:
            return {"type": "heloc", "monthly_obligation": round(payment, 2),
                    "included": True, "method": "heloc_actual_payment", "citation": _CITE}
        base = balance or credit_limit
        computed = round(base * self._heloc_pct / 100, 2)
        return {"type": "heloc", "monthly_obligation": computed, "included": computed > 0,
                "method": f"heloc_{self._heloc_pct:.0f}pct_of_balance_or_limit",
                "citation": _CITE}

    def compute_business_debt(self, obl: dict) -> dict:
        """OB-B — business-debt exclusion (Fannie B3-6-05). A debt is EXCLUDED from
        DTI only when the business has paid it >= business_debt_exclusion_months
        with no 30-day delinquency. is_business_paying / months_business_paid are
        not in any data source today -> default to NOT proving the exclusion, so
        the debt is INCLUDED with a docs_needed condition (the UW must supply the
        12-month cancelled-check/bank-statement evidence to exclude). monthly_payment
        / balance / delinquency_30 come from CREDIT_REPORT.tradelines."""
        obl = obl or {}
        payment = _f(obl.get("monthly_payment"))
        balance = _f(obl.get("current_balance") or obl.get("balance"))
        is_business_paying = bool(obl.get("is_business_paying", False))
        months_business_paid = int(obl.get("months_business_paid", 0) or 0)
        delinquent = bool(obl.get("delinquency_30", False))

        if (is_business_paying and not delinquent
                and months_business_paid >= self._business_debt_exclusion_months):
            return {"type": "business_debt", "monthly_obligation": 0, "included": False,
                    "excluded_reason": (f"business-paid {months_business_paid}mo >= "
                                        f"{self._business_debt_exclusion_months}mo, no "
                                        f"30-day delinquency (B3-6-05)"),
                    "method": "business_debt_excluded_business_paid", "citation": "Fannie B3-6-05"}
        docs = ["12-month business-paid evidence (cancelled checks / business bank "
                "statements) + no 30-day delinquency to exclude from DTI"]
        if delinquent:
            docs.append("30-day delinquency present — cannot exclude even if "
                        "business-paid (B3-6-05)")
        return {"type": "business_debt", "monthly_obligation": round(payment, 2),
                "included": payment > 0, "balance": balance,
                "method": "business_debt_included_no_exclusion_evidence",
                "citation": "Fannie B3-6-05", "docs_needed": docs}

    def compute_rental_offset(self, rental: dict) -> dict:
        """OB-B — rental mortgage offset (Fannie B3-3.1-08). net = rental_net_monthly
        - pitia_monthly. net >= 0 -> positive offset (NOT a DTI obligation; the
        surplus is income handled by income_verification). net < 0 -> the shortfall
        is added to DTI obligations. rental_net_monthly comes from RA-4G (not yet on
        the bundle) and pitia_monthly is per-rental-property (not on the bundle) —
        both default 0 -> not_applicable (no meridian app carries rental offset
        data; 16/16 by construction)."""
        rental = rental or {}
        rental_net = _f(rental.get("rental_net_monthly"))
        pitia = _f(rental.get("pitia_monthly"))
        if not rental_net and not pitia:
            return {"type": "rental_property", "monthly_obligation": 0, "included": False,
                    "method": "rental_offset_not_applicable",
                    "note": "no rental_net_monthly / pitia_monthly on the bundle "
                            "(RA-4G not wired + per-property PITIA absent)"}
        net = round(rental_net - pitia, 2)
        if net >= 0:
            return {"type": "rental_property", "monthly_obligation": 0, "included": False,
                    "net_offset": net, "income_contribution": net,
                    "method": "rental_positive_offset", "citation": "Fannie B3-3.1-08",
                    "note": f"net rental ${net:,.0f}/mo offsets PITIA — not a DTI obligation"}
        return {"type": "rental_property", "monthly_obligation": round(abs(net), 2),
                "included": True, "net_offset": net,
                "method": "rental_negative_added_to_dti", "citation": "Fannie B3-3.1-08"}

    # ── routing ─────────────────────────────────────────────────────────
    def _route_one(self, obl: dict) -> dict:
        otype = (obl or {}).get("type")
        if otype == "student_loan":
            # PRE-COMPUTED by TradelineAnalyzer (credit_assessment) — never recompute.
            pay = _f(obl.get("computed_payment") or obl.get("monthly_payment"))
            included = bool(obl.get("included_in_dti", pay > 0))
            return {"type": "student_loan", "monthly_obligation": round(pay, 2) if included else 0,
                    "included": included,
                    "method": "student_loan_precomputed_tradeline_analyzer",
                    "citation": "Fannie B3-6-05",
                    **({} if included else {"excluded_reason": obl.get("exclusion_reason",
                                                                       "excluded by tradeline analyzer")})}
        if otype in ("alimony_paid", "child_support_paid"):
            from core.income.alimony_resolver import AlimonyChildSupportResolver
            acs = AlimonyChildSupportResolver(rules=self._rules)
            res = (acs.treat_alimony_paid(obl) if otype == "alimony_paid"
                   else acs.treat_child_support_paid(obl))
            return {"type": otype, "monthly_obligation": _f(res.get("monthly_obligation")),
                    "income_reduction": _f(res.get("income_reduction")),
                    "treatment": res.get("treatment"), "included": res.get("treatment") == "monthly_debt",
                    "method": res.get("method"), "citation": res.get("citation", "Fannie B3-6-05")}
        if otype == "installment":
            return self.compute_installment(obl)
        if otype == "revolving":
            return self.compute_revolving(obl)
        if otype == "heloc":
            return self.compute_heloc(obl)
        if otype == "business_debt":
            return self.compute_business_debt(obl)
        if otype in ("rental_property", "rental_offset"):
            return self.compute_rental_offset(obl)
        return {"type": otype or "unknown", "monthly_obligation": 0, "included": False,
                "excluded_reason": f"unrecognized obligation type: {otype}",
                "method": "unrouted"}

    def resolve(self, obligations: list) -> dict:
        """Route each obligation, summing the included monthly payments. Returns
        total_qualifying_obligations + per_type breakdown + excluded list."""
        per_type: list = []
        excluded: list = []
        total = 0.0
        for obl in (obligations or []):
            r = self._route_one(obl)
            per_type.append(r)
            if r.get("included"):
                total += _f(r.get("monthly_obligation"))
            else:
                excluded.append({"type": r.get("type"),
                                 "reason": r.get("excluded_reason", "not included")})
        return {
            "total_qualifying_obligations": round(total, 2),
            "per_type": per_type,
            "excluded": excluded,
            "obligation_count": len(obligations or []),
            "citation": _CITE,
        }


__all__ = ["ObligationResolver", "OBLIGATION_RULE_KEYS", "load_obligation_rules"]
