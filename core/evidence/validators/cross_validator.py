"""Cross-Document Validator — EV-C.

Validates evidence ACROSS document types — conflicts no single-doc resolver
can see:
  1. Income consistency : W2 box1 vs URLA stated income
  2. Employer consistency: W2 vs paystub vs URLA
  3. Property value      : appraisal vs purchase price (URLA-stated value)

Each conflict writes a cross_validation/conflict EvidenceNode; fraud-level
gaps surface as fraud_signals for the fraud_screening persona (FR-B), the
decision trace (EV-D), and persona escalation (EV-E).
"""
from __future__ import annotations

import json
from typing import Optional

from ..models import EvidenceNode
from ..store import EvidenceStore

INCOME_CONFLICT_PCT = 0.10
INCOME_FRAUD_PCT = 0.25
VALUE_CONFLICT_PCT = 0.05
VALUE_FRAUD_PCT = 0.15

# URLA income keys treated as MONTHLY (multiplied by 12 to annualize).
_URLA_MONTHLY_INCOME = ("monthly_income_stated", "stated_monthly_income",
                        "base_income", "gross_monthly_income")
_URLA_ANNUAL_INCOME = ("annual_income", "total_income")


def _money(val) -> Optional[float]:
    try:
        return float(str(val).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return None


class CrossDocumentValidator:
    def __init__(self, conn):
        self.conn = conn
        self.store = EvidenceStore(conn)

    async def validate_all(self, application_id: str, tenant_id: str) -> dict:
        results = {"income_conflict": False, "employer_conflict": False,
                   "value_conflict": False, "fraud_signals": [], "conflicts": []}
        docs = await self._load_all_docs(application_id, tenant_id)
        if not docs:
            return results

        # Idempotency: clear only EV-C nodes (cross_validation/conflict), leaving
        # the EV-B document_field / derived_fact evidence intact.
        await self.conn.execute(
            "DELETE FROM evidence_nodes WHERE application_id=$1 AND tenant_id=$2 "
            "AND node_type IN ('cross_validation','conflict')",
            application_id, tenant_id,
        )

        for key, signal, fn in (
            ("income_conflict", "income_inflation", self._validate_income_consistency),
            ("employer_conflict", "employer_mismatch", self._validate_employer_consistency),
            ("value_conflict", "value_inflation", self._validate_property_value),
        ):
            res = await fn(application_id, tenant_id, docs)
            if res["conflict"]:
                results[key] = True
                results["conflicts"].append(res)
                if res.get("fraud_signal"):
                    results["fraud_signals"].append(signal)
        return results

    async def _load_all_docs(self, application_id, tenant_id) -> dict:
        rows = await self.conn.fetch(
            "SELECT document_type, extracted_fields, document_id, confidence_score "
            "FROM document_index WHERE application_id=$1 AND tenant_id=$2 AND is_current=true",
            application_id, tenant_id,
        )
        docs: dict = {}
        for r in rows:
            fields = r["extracted_fields"]
            if isinstance(fields, str):
                fields = json.loads(fields)
            docs.setdefault(r["document_type"], []).append({
                "document_id": r["document_id"], "fields": fields or {},
                "confidence": float(r["confidence_score"] or 0),
            })
        return docs

    @staticmethod
    def _first(docs, doc_type, keys):
        for doc in docs.get(doc_type, []):
            for k in keys:
                if doc["fields"].get(k) is not None:
                    return doc["fields"][k]
        return None

    async def _validate_income_consistency(self, application_id, tenant_id, docs) -> dict:
        res = {"validation": "income_consistency", "conflict": False,
               "fraud_signal": False, "details": ""}
        w2 = _money(self._first(docs, "W2_CURRENT", ("box1_wages", "wages_tips_compensation")))

        urla_annual = None
        for doc in docs.get("URLA_1003", []):
            for k in _URLA_MONTHLY_INCOME:
                if doc["fields"].get(k) is not None:
                    v = _money(doc["fields"][k])
                    urla_annual = v * 12 if v is not None else None
                    break
            if urla_annual is None:
                for k in _URLA_ANNUAL_INCOME:
                    if doc["fields"].get(k) is not None:
                        urla_annual = _money(doc["fields"][k])
                        break
            if urla_annual is not None:
                break

        if not w2 or not urla_annual:
            res["details"] = f"Cannot validate: W2={w2}, URLA_annual={urla_annual}"
            return res

        diff = (urla_annual - w2) / w2
        res["details"] = (f"W2 ${w2:,.0f} vs URLA ${urla_annual:,.0f} ({diff:+.1%})")
        if abs(diff) <= INCOME_CONFLICT_PCT:
            return res
        res["conflict"] = True
        res["details"] = "Income conflict: " + res["details"]
        if diff > INCOME_FRAUD_PCT:
            res["fraud_signal"] = True
            res["details"] += " FRAUD SIGNAL: URLA overstates income >25%"
        await self._create_node(application_id, tenant_id, "cross_validation",
                                "income", "income_w2_vs_urla", res["details"], diff)
        return res

    async def _validate_employer_consistency(self, application_id, tenant_id, docs) -> dict:
        res = {"validation": "employer_consistency", "conflict": False,
               "fraud_signal": False, "details": ""}
        employers = {}
        for src, dt, keys in (
            ("W2", "W2_CURRENT", ("employer_name", "employer")),
            ("PAYSTUB", "PAYSTUB_CURRENT", ("employer_name", "company_name", "employer")),
            ("URLA", "URLA_1003", ("employer_name", "current_employer", "employer")),
        ):
            val = self._first(docs, dt, keys)
            if val:
                employers[src] = str(val).strip().upper()

        if len(employers) < 2:
            res["details"] = f"Only {len(employers)} employer source(s): {list(employers)}"
            return res
        unique = set(employers.values())
        if len(unique) == 1:
            res["details"] = f"Employer consistent across {list(employers)}: {next(iter(unique))}"
            return res

        # Tolerate typos: if the names share a meaningful word, treat as same.
        stop = {"LLC", "INC", "CORP", "CO", "THE", "AND", "OF"}
        def words(n):
            return {w for w in n.split() if len(w) > 2 and w not in stop}
        sets = [words(n) for n in unique]
        common = set.intersection(*sets) if sets else set()
        if common:
            res["details"] = f"Employer likely same: {list(unique)} (shared: {common})"
            return res

        res["conflict"] = True
        res["fraud_signal"] = True
        res["details"] = f"Employer mismatch: {employers}"
        await self._create_node(application_id, tenant_id, "conflict",
                                "employment", "employer_name_mismatch", res["details"], None)
        return res

    async def _validate_property_value(self, application_id, tenant_id, docs) -> dict:
        res = {"validation": "property_value", "conflict": False,
               "fraud_signal": False, "details": ""}
        appraised = _money(self._first(docs, "APPRAISAL_URAR",
                           ("appraised_value", "market_value", "indicated_value", "final_value")))
        # No purchase_price exists in meridian docs; fall back to the borrower's
        # URLA-stated appraised_value (over-stating it is the fraud signal here).
        purchase = _money(self._first(docs, "URLA_1003",
                          ("purchase_price", "sales_price", "contract_price")))
        basis = "purchase price"
        if purchase is None:
            purchase = _money(self._first(docs, "URLA_1003", ("appraised_value",)))
            basis = "URLA-stated value"

        if not appraised or not purchase:
            res["details"] = f"Cannot validate: appraised={appraised}, {basis}={purchase}"
            return res
        diff = (appraised - purchase) / purchase
        res["details"] = (f"Appraised ${appraised:,.0f} vs {basis} ${purchase:,.0f} ({diff:+.1%})")
        if abs(diff) <= VALUE_CONFLICT_PCT:
            return res
        res["conflict"] = True
        res["details"] = "Value gap: " + res["details"]
        if abs(diff) > VALUE_FRAUD_PCT:
            res["fraud_signal"] = True
            res["details"] += " FRAUD SIGNAL: value gap >15%"
        await self._create_node(application_id, tenant_id, "cross_validation",
                                "property", "appraisal_vs_stated_value", res["details"], diff)
        return res

    async def _create_node(self, application_id, tenant_id, node_type, category,
                           field_name, notes, numeric_value):
        await self.store.save_evidence_node(EvidenceNode(
            application_id=application_id, tenant_id=tenant_id, node_type=node_type,
            evidence_category=category, field_name=field_name, raw_value=notes,
            numeric_value=numeric_value, confidence=1.0, extraction_method="derived",
            metadata={"validator": "CrossDocumentValidator"},
        ))


__all__ = ["CrossDocumentValidator"]
