"""Credit Fact Resolver — EV-B3.

  document_index (credit report(s), primary + co-borrower)
    -> EvidenceNode per credit field (per-bureau scores, obligations, derogs)
      -> FactNode: governing_credit_score = min(all borrowers' mid scores)
         (Fannie Mae B3-5.1-01 — the worst-case score governs)

Full tradeline analysis is Phase 3 (CR-A..CR-F); this captures the core
credit facts personas need. conflicts_found=True when any derogatory mark
(bankruptcy / foreclosure / collections / charge-off / derogatory count) is
present on any borrower.
"""
from __future__ import annotations

import json
from typing import Optional

from ..models import EvidenceNode, FactNode
from ..store import EvidenceStore

_SCORE_FIELDS = {
    "mid_score": ("mid_score", "median_score", "middle_score", "credit_score"),
    "equifax_score": ("equifax_score", "equifax", "score_equifax"),
    "experian_score": ("experian_score", "experian", "score_experian"),
    "transunion_score": ("transunion_score", "transunion", "score_transunion", "tu_score"),
}
_OBLIGATION_KEYS = ("monthly_obligations", "total_monthly_obligations",
                    "monthly_debt_payments", "total_obligations")
_DEROG_FIELDS = ("active_bankruptcy", "derogatory_count", "derogatory_marks",
                 "foreclosure_last_36_months", "foreclosure_last_7_years",
                 "collections_count", "charge_offs_count", "mortgage_late_12mo")


def _to_float(val) -> Optional[float]:
    try:
        return float(str(val).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return None


def _flag_numeric(val) -> Optional[float]:
    """A derogatory flag value -> numeric: bool->1/0, count->float, else None."""
    if isinstance(val, bool):
        return 1.0 if val else 0.0
    return _to_float(val)


class CreditFactResolver:
    def __init__(self, conn):
        self.conn = conn
        self.store = EvidenceStore(conn)

    async def resolve(self, application_id: str, tenant_id: str) -> dict:
        docs = await self._load_credit_docs(application_id, tenant_id)
        if not docs:
            return {}

        # Idempotency: drop prior credit evidence (edges cascade) before rebuild.
        await self.conn.execute(
            "DELETE FROM evidence_nodes WHERE application_id=$1 AND tenant_id=$2 "
            "AND evidence_category='credit'",
            application_id, tenant_id,
        )

        nodes = await self._build_evidence_nodes(application_id, tenant_id, docs)
        facts: dict = {}
        score_fact = self._resolve_governing_score(application_id, tenant_id, nodes)
        if score_fact:
            await self.store.save_fact_node(score_fact)
            facts["governing_credit_score"] = score_fact
        return facts

    async def _load_credit_docs(self, application_id, tenant_id) -> list:
        rows = await self.conn.fetch(
            """
            SELECT document_id, document_type, borrower_role,
                   extracted_fields, confidence_score
            FROM document_index
            WHERE application_id = $1 AND tenant_id = $2
              AND document_type ILIKE '%CREDIT%' AND is_current = true
            ORDER BY borrower_role
            """,
            application_id, tenant_id,
        )
        docs = []
        for r in rows:
            fields = r["extracted_fields"]
            if isinstance(fields, str):
                fields = json.loads(fields)
            docs.append({
                "document_id": r["document_id"],
                "document_type": r["document_type"],
                "borrower_role": (r["borrower_role"] or "primary"),
                "fields": fields or {},
                "confidence": float(r["confidence_score"] or 0),
            })
        return docs

    async def _build_evidence_nodes(self, application_id, tenant_id, docs) -> dict:
        nodes: dict = {}

        async def add(field_name, raw, numeric, conf, doc_id, doc_type, meta=None):
            node = EvidenceNode(
                application_id=application_id, tenant_id=tenant_id,
                node_type="document_field", evidence_category="credit",
                field_name=field_name, raw_value=raw, numeric_value=numeric,
                confidence=conf, source_document_id=doc_id,
                source_document_type=doc_type, extraction_method="textract",
                metadata=meta or {},
            )
            await self.store.save_evidence_node(node)
            nodes[field_name] = node

        for doc in docs:
            fields, doc_id, doc_type, conf = (
                doc["fields"], doc["document_id"], doc["document_type"], doc["confidence"]
            )
            # Primary vs co-borrower comes from the borrower_role COLUMN.
            role = doc["borrower_role"].lower()
            is_co = "co" in role
            prefix = "co_" if is_co else "primary_"

            for score_field, keys in _SCORE_FIELDS.items():
                val = next((fields[k] for k in keys if fields.get(k) is not None), None)
                num = _to_float(val) if val is not None else None
                if num is not None:
                    await add(f"{prefix}{score_field}", str(val), num, conf, doc_id, doc_type)

            for key in _OBLIGATION_KEYS:
                if fields.get(key) is not None:
                    num = _to_float(fields[key])
                    if num is not None:
                        await add(f"{prefix}monthly_obligations", str(fields[key]), num,
                                  conf, doc_id, doc_type)
                    break

            for fld in _DEROG_FIELDS:
                if fields.get(fld) is not None:
                    await add(f"{prefix}{fld}", str(fields[fld]), _flag_numeric(fields[fld]),
                              conf, doc_id, doc_type, meta={"flag": True})

        return nodes

    def _resolve_governing_score(self, application_id, tenant_id, nodes) -> Optional[FactNode]:
        """Fannie Mae: governing score = minimum mid score across all borrowers."""
        primary_mid = nodes.get("primary_mid_score")
        co_mid = nodes.get("co_mid_score")
        if not primary_mid:
            return None

        evidence_ids = [primary_mid.id]
        scores_used = [primary_mid.numeric_value]
        score_nodes = [primary_mid]
        notes = [f"Primary mid score: {primary_mid.numeric_value:.0f}"]

        if co_mid and co_mid.numeric_value:
            evidence_ids.append(co_mid.id)
            scores_used.append(co_mid.numeric_value)
            score_nodes.append(co_mid)
            notes.append(f"Co-borrower mid score: {co_mid.numeric_value:.0f}")

        governing = min(scores_used)
        confidence = min(n.confidence for n in score_nodes)

        if len(scores_used) > 1:
            notes.append(f"Governing score: {governing:.0f} (minimum - Fannie Mae B3-5.1-01)")
            method = "min(primary_mid, co_mid) (Fannie Mae B3-5.1-01)"
        else:
            notes.append(f"Governing score: {governing:.0f} (single borrower)")
            method = "primary_mid_score"

        # Derogatory marks across any borrower (count > 0 or boolean flag set).
        derog_keys = [k for k in nodes if any(t in k for t in
                      ("bankruptcy", "foreclosure", "derogatory", "collections",
                       "charge_off", "mortgage_late"))]
        derog_hit = [k for k in derog_keys
                     if nodes[k].numeric_value and nodes[k].numeric_value > 0]
        has_derogatory = len(derog_hit) > 0
        evidence_ids.extend(nodes[k].id for k in derog_hit)
        if has_derogatory:
            notes.append(f"Derogatory marks detected: {', '.join(sorted(derog_hit))}")

        return FactNode(
            application_id=application_id, tenant_id=tenant_id,
            fact_type="governing_credit_score", fact_value=governing,
            confidence=confidence, resolution_method=method,
            evidence_ids=evidence_ids, conflicts_found=has_derogatory,
            resolution_notes="\n".join(notes),
            agency_treatment={"fannie": "minimum mid score of all borrowers",
                              "fha": "minimum mid score of all borrowers",
                              "va": "minimum mid score of all borrowers"},
        )


__all__ = ["CreditFactResolver"]
