"""CR-F — medical/non-medical collections + mortgage-late treatment.

Scans CREDIT_REPORT tradelines and applies catalogue-driven treatment for the three
adverse-credit cases CR-C classified but left to prose notes / a hardcoded flag:

  1. Medical collections     — ignored (medical_collection_excluded, Fannie B3-5.3-09)
  2. Non-medical collections — LOE if a single account > $250 / payoff if aggregate
                               > $1,000 (Fannie B3-5.3-09)
  3. Mortgage 30-day lates   — HARD BLOCK (conventional) / LOE (FHA/VA), Fannie
                               B3-5.3-01 — read from the catalogue, NOT the hardcoded
                               `fannie_hard_block` flag (RULE 1 fix).

Sync + DB-less (RULE 5/6); thresholds from the injected catalogue rules with
SAFE_DEFAULTS fallback (RULE 1/9); RULE 11 (data_source + missing_inputs) on every
output. Standalone — NOT wired into the 16/16-critical credit_assessment persona.

DATA NOTE: tradelines carry account_type / account_status / current_balance /
creditor_name / delinquency_30 — but NO `is_medical` field, so medical classification
falls back to a creditor-name heuristic and surfaces that in missing_inputs.
"""
from __future__ import annotations

from typing import Optional

COLLECTIONS_RULE_KEYS = [
    "medical_collection_excluded",
    "medical_collection_ignore_amt",
    "non_medical_collection_loe_threshold",
    "non_medical_collection_aggregate_payoff",
    "mortgage_late_30day_12mo_conventional_blocks",
]

MEDICAL_CREDITOR_PATTERNS = [
    "hospital", "medical", "health", "clinic", "doctor", "physician", "dental",
    "surgery", "radiology", "laboratory", "lab ", "pharma", "urgent care",
    "emergency", "ambulance", "pathology", "oncology", "orthopedic",
]
_COLLECTION_STATUSES = {"collection", "collections", "in collection", "charge-off",
                        "chargeoff", "charged off"}
_MORTGAGE_TYPES = {"mortgage", "real estate", "home equity", "heloc"}


async def load_collections_rules(conn, tenant_id: str, agency: str = "fannie") -> dict:
    from core.catalogue.rule_loader import get_rule
    values, trace = {}, {}
    for key in COLLECTIONS_RULE_KEYS:
        r = await get_rule(conn, key, tenant_id, agency=agency)
        values[key] = r.get("applied")
        trace[key] = {"applied": r.get("applied"), "governed_by": r.get("governed_by")}
    return {"values": values, "trace": trace}


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


class CollectionsLatesResolver:
    def __init__(self, rules: Optional[dict] = None, loan_type: str = "conventional"):
        from core.catalogue.rule_loader import SAFE_DEFAULTS
        r = dict(SAFE_DEFAULTS)
        if rules:
            r.update({k: v for k, v in rules.items() if v is not None})
        self._medical_excluded = bool(r.get("medical_collection_excluded", True))
        self._medical_ignore_amt = _f(r.get("medical_collection_ignore_amt", 2000))
        self._loe_threshold = _f(r.get("non_medical_collection_loe_threshold", 250))
        self._aggregate_payoff = _f(r.get("non_medical_collection_aggregate_payoff", 1000))
        self._mortgage_late_blocks = bool(r.get("mortgage_late_30day_12mo_conventional_blocks", True))
        self._loan_type = str(loan_type or "conventional").lower()

    def _is_medical(self, tl: dict):
        if tl.get("is_medical") is not None:
            return bool(tl["is_medical"]), 1.0, "explicit_field"
        creditor = str(tl.get("creditor_name") or "").lower()
        for p in MEDICAL_CREDITOR_PATTERNS:
            if p in creditor:
                return True, 0.80, f"creditor_name_heuristic:{p.strip()}"
        return False, 0.90, "creditor_name_heuristic:no_match"

    # ── collections ────────────────────────────────────────────────────────────
    def resolve_collections(self, tradelines: list) -> dict:
        ds = "CREDIT_REPORT.extracted_fields.tradelines"
        if not tradelines:
            return self._coll_empty("no_collections", "no_tradelines_provided", ds,
                                    ["tradelines not extracted from credit report"])
        collections = [t for t in tradelines
                       if str(t.get("account_status", "")).lower() in _COLLECTION_STATUSES]
        if not collections:
            return self._coll_empty("no_adverse_collections", "no_collections_found", ds, [])

        results, medical_count, non_medical_total, loe, missing = [], 0, 0.0, [], []
        for tl in collections:
            bal = _f(tl.get("current_balance") or tl.get("balance"))
            is_med, conf, method = self._is_medical(tl)
            if tl.get("is_medical") is None:
                missing.append(f"{tl.get('creditor_name','unknown')}: is_medical not extracted "
                               f"— heuristic ({conf:.0%})")
            if is_med:
                medical_count += 1
                action = "ignored" if self._medical_excluded else "loe_required"
                reason = ("medical collection excluded (B3-5.3-09)" if self._medical_excluded
                          else "medical_collection_excluded=false (overlay)")
            else:
                non_medical_total += bal
                if bal > self._loe_threshold:
                    action, reason = "loe_required", f"balance ${bal:,.0f} > ${self._loe_threshold:,.0f}"
                    loe.append(tl.get("creditor_name"))
                else:
                    action, reason = "monitor", f"balance ${bal:,.0f} <= ${self._loe_threshold:,.0f}"
            results.append({"creditor": tl.get("creditor_name"), "balance": bal,
                            "is_medical": is_med, "classification_confidence": conf,
                            "classification_method": method, "action": action, "reason": reason})

        payoff = non_medical_total > self._aggregate_payoff
        overall = "payoff_required" if payoff else ("loe_required" if loe else "none")
        docs = ([f"Letter of Explanation for: {', '.join(c for c in loe if c)}"] if loe else []) + \
               ([f"Pay off non-medical collections (aggregate ${non_medical_total:,.0f} > "
                 f"${self._aggregate_payoff:,.0f})"] if payoff else [])
        return {
            "status": "collections_found", "collections": results,
            "medical_count": medical_count, "non_medical_count": len(collections) - medical_count,
            "non_medical_aggregate": round(non_medical_total, 2),
            "aggregate_threshold": self._aggregate_payoff, "loe_required": loe,
            "payoff_required": payoff, "action": overall, "docs_needed": docs,
            "method": (f"{len(collections)} collections: {medical_count} medical (ignored), "
                       f"{len(collections) - medical_count} non-medical "
                       f"(aggregate ${non_medical_total:,.0f})"),
            "citation": "Fannie B3-5.3-09", "data_source": ds, "missing_inputs": missing}

    @staticmethod
    def _coll_empty(status, method, ds, missing) -> dict:
        return {"status": status, "collections": [], "medical_count": 0, "non_medical_count": 0,
                "non_medical_aggregate": 0.0, "action": "none", "method": method,
                "docs_needed": [], "citation": "Fannie B3-5.3-09", "data_source": ds,
                "missing_inputs": missing}

    # ── mortgage lates ───────────────────────────────────────────────────────
    def resolve_mortgage_lates(self, tradelines: list, lookback_months: int = 12) -> dict:
        ds = "CREDIT_REPORT.extracted_fields.tradelines"
        if not tradelines:
            return self._late_empty("not_applicable", "no_tradelines_provided", ds,
                                    ["tradelines not extracted from credit report"])
        mortgages = [t for t in tradelines
                     if str(t.get("account_type", "")).lower() in _MORTGAGE_TYPES]
        if not mortgages:
            return self._late_empty("no_mortgage_tradelines", "no_mortgage_accounts_found", ds, [])

        lates, missing = [], []
        for tl in mortgages:
            d30 = tl.get("delinquency_30")
            if d30 is None:
                missing.append(f"{tl.get('creditor_name','mortgage')}: delinquency_30 not extracted")
                continue
            if int(d30) > 0:
                lates.append({"creditor": tl.get("creditor_name"), "delinquency_30": int(d30),
                              "account_type": tl.get("account_type"),
                              "last_reported": tl.get("reported_date") or tl.get("last_reported_date")})
        if not lates:
            return {"status": "clean_mortgage_history", "mortgage_lates": [], "hard_block": False,
                    "method": f"0 mortgage 30-day lates in {lookback_months}-month window",
                    "citation": "Fannie B3-5.3-01", "data_source": ds, "missing_inputs": missing}

        is_conv = "conventional" in self._loan_type or self._loan_type in ("conventional", "conforming", "other")
        hard_block = is_conv and self._mortgage_late_blocks
        docs = (["Conventional hard block: 30-day mortgage late in last 12 months — loan "
                 "ineligible for conventional financing."] if hard_block
                else [f"Letter of Explanation required for {len(lates)} mortgage late(s)"])
        return {
            "status": "mortgage_lates_found", "mortgage_lates": lates, "late_count": len(lates),
            "hard_block": hard_block, "loan_type": self._loan_type,
            "action": "HARD_BLOCK" if hard_block else "LOE_REQUIRED", "docs_needed": docs,
            "method": (f"{len(lates)} mortgage 30-day late(s); "
                       f"{'HARD BLOCK' if hard_block else 'LOE required'} "
                       f"(catalogue mortgage_late_30day_12mo_conventional_blocks="
                       f"{self._mortgage_late_blocks})"),
            "citation": "Fannie B3-5.3-01", "data_source": ds, "missing_inputs": missing}

    @staticmethod
    def _late_empty(status, method, ds, missing) -> dict:
        return {"status": status, "mortgage_lates": [], "hard_block": False, "method": method,
                "citation": "Fannie B3-5.3-01", "data_source": ds, "missing_inputs": missing}

    # ── combined ─────────────────────────────────────────────────────────────
    def resolve_all(self, tradelines: list) -> dict:
        coll = self.resolve_collections(tradelines)
        lates = self.resolve_mortgage_lates(tradelines)
        hard_block = lates.get("hard_block", False)
        has_adverse = coll.get("action") not in ("none", None) or hard_block
        return {
            "status": "hard_block" if hard_block else ("adverse_findings" if has_adverse else "clean"),
            "collections": coll, "mortgage_lates": lates, "hard_block": hard_block,
            "has_adverse": has_adverse,
            "docs_needed": coll.get("docs_needed", []) + lates.get("docs_needed", []),
            "citation": "Fannie B3-5.3-09 + B3-5.3-01",
            "data_source": "CREDIT_REPORT.extracted_fields.tradelines",
            "missing_inputs": coll.get("missing_inputs", []) + lates.get("missing_inputs", [])}


__all__ = ["CollectionsLatesResolver", "load_collections_rules", "COLLECTIONS_RULE_KEYS"]
