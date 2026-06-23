"""ATR / QM verification (RA-7A) — 12 CFR 1026.43.

Ability-to-Repay (ATR, §1026.43(c)) requires the creditor to verify 8 underwriting
factors before consummation. Qualified Mortgage (QM, §1026.43(e)) classification
determines the lender's liability shield: Safe Harbor, Rebuttable Presumption, or
Non-QM (ATR must be proven case-by-case).

Pure + DB-less, in keeping with the resolver contract (Architecture RULE 6): the
verifier receives an ``entity`` dict (entity_states scalars + a derived
``employment_verified`` bool) and a ``rules`` dict loaded from the catalogue by
the enricher (RULE 4). All thresholds come from the catalogue; SAFE_DEFAULTS is
the ONLY Python fallback (RULE 9) and mirrors the federal regulatory_rules values
(used only if the catalogue lookup failed).
"""
from __future__ import annotations

from typing import Any, Optional

# RULE 9 fallback only — these mirror the federal regulatory_rules rows
# (atr_required_factors=8, QM Safe Harbor DTI=43, qm_points_fees_max_pct=3,
# hpml_rate_threshold_1st_lien=150). The live values come from the catalogue.
SAFE_DEFAULTS = {
    "atr_required_factors": 8,
    "qm_dti_max": 43.0,
    "qm_points_fees_max": 3.0,
    "hpml_threshold_bps": 150.0,
}


def _num(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class ATRVerifier:
    # The 8 ATR factors, in 12 CFR 1026.43(c)(2) order.
    ATR_FACTORS = [
        "income_verified",                 # (c)(2)(i)   current income/assets
        "employment_verified",             # (c)(2)(ii)  current employment
        "monthly_payment_computed",        # (c)(2)(iii) payment on this loan
        "mortgage_obligations_verified",   # (c)(2)(iv)  mortgage-related obligations
        "debt_obligations_verified",       # (c)(2)(v)   debts, alimony, child support
        "dti_computed",                    # (c)(2)(vi)  DTI or residual income
        "credit_history_reviewed",         # (c)(2)(vii) credit history
        "cltv_computed",                   # (c)(2)(viii) (C)LTV
    ]

    def __init__(self, rules: Optional[dict] = None):
        rules = rules or {}

        def _r(key):
            v = _num(rules.get(key))
            return v if v is not None else SAFE_DEFAULTS[key]

        self.required_factors = int(_r("atr_required_factors"))
        self.qm_dti_max = _r("qm_dti_max")
        self.qm_points_fees_max = _r("qm_points_fees_max")
        self.hpml_threshold_bps = _r("hpml_threshold_bps")

    def verify(self, entity: dict) -> dict:
        """Run the 8-factor ATR checklist against an application's verified data."""
        qm = _num(entity.get("qualifying_monthly"))
        piti = _num(entity.get("piti_monthly"))

        checks = {
            "income_verified": qm is not None and qm > 0,
            "employment_verified": bool(entity.get("employment_verified")),
            "monthly_payment_computed": piti is not None and piti > 0,
            "mortgage_obligations_verified": piti is not None,
            "debt_obligations_verified": _num(entity.get("monthly_obligations")) is not None,
            "dti_computed": _num(entity.get("dti_back")) is not None,
            "credit_history_reviewed": _num(entity.get("mid_credit_score")) is not None,
            "cltv_computed": _num(entity.get("ltv")) is not None,
        }
        failed = [k for k, v in checks.items() if not v]
        return {
            "atr_satisfied": not failed,
            "factors_checked": len(self.ATR_FACTORS),
            "factors_passed": sum(1 for v in checks.values() if v),
            "factors_failed": failed,
            "checks": checks,
            "citation": "12 CFR 1026.43(c)",
        }

    def classify_qm(self, entity: dict) -> dict:
        """Classify the loan for QM safe-harbor protection."""
        dti_raw = _num(entity.get("dti_back"))
        dti = dti_raw if dti_raw is not None else 0.0
        # Points & fees aren't captured in entity_states yet; absent data is
        # treated as 0 (passes). TODO: wire real fee data when available.
        points_fees_pct = _num(entity.get("points_fees_pct")) or 0.0
        rate = _num(entity.get("interest_rate")) or 0.0
        apor = _num(entity.get("apor_rate")) or 0.0

        # Without a verified DTI we cannot claim safe harbor — be conservative.
        dti_pass = dti_raw is not None and dti_raw <= self.qm_dti_max
        points_fees_pass = points_fees_pct <= self.qm_points_fees_max
        # HPML = APR exceeds APOR by >= threshold bps. Only computable with APOR.
        is_hpml = ((rate - apor) * 100) >= self.hpml_threshold_bps if apor > 0 else False

        if dti_pass and points_fees_pass and not is_hpml:
            classification, protected = "QM_SAFE_HARBOR", True
        elif dti_pass and points_fees_pass and is_hpml:
            classification, protected = "QM_REBUTTABLE_PRESUMPTION", True
        else:
            classification, protected = "NON_QM", False

        return {
            "qm_classification": classification,
            "safe_harbor_protected": protected,
            "dti_check": {"value": round(dti, 2), "max": self.qm_dti_max,
                          "passes": dti_pass, "data_available": dti_raw is not None},
            "points_fees_check": {
                "pct": points_fees_pct, "max": self.qm_points_fees_max,
                "passes": points_fees_pass, "data_available": entity.get("points_fees_pct") is not None,
            },
            "hpml_flag": is_hpml,
            "hpml_computable": apor > 0,
            "citation": "12 CFR 1026.43(e)",
        }


__all__ = ["ATRVerifier", "SAFE_DEFAULTS"]
