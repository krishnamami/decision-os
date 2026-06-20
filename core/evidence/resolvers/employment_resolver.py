"""Employment Fact Resolver — EV-B4.

  document_index (W2 + paystub: employer_name, W2 box1_wages)
  + entity_states.borrower.employment (reconciliation_status,
    continuity_coverage_pct, max_gap_days, period) — the derived
    employment facts; document_index itself carries no tenure / status /
    start-date fields for meridian, only employer_name.
    -> EvidenceNode per employment field
      -> FactNode: employment_continuity
         (stable / self_employed / gap_detected / employed / unknown)

Deep reconciliation (job change same industry, contract workers) stays in
the employment_reconciliation persona; this captures the base facts.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Optional

from ..models import EvidenceNode, FactNode
from ..store import EvidenceStore

GAP_THRESHOLD_DAYS = 30
DOC_TYPES = ("W2_CURRENT", "W2_PRIOR", "PAYSTUB_CURRENT", "PAYSTUB_PRIOR")
_EMP_BLOCK_FIELDS = ("reconciliation_status", "continuity_coverage_pct",
                     "max_gap_days", "employer_name", "period_start", "period_end")


def _to_float(val) -> Optional[float]:
    try:
        return float(str(val).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return None


def _years_between(start, end) -> Optional[float]:
    try:
        s = date.fromisoformat(str(start)[:10])
        e = date.fromisoformat(str(end)[:10])
        return round((e - s).days / 365.25, 1)
    except (ValueError, TypeError):
        return None


class EmploymentFactResolver:
    def __init__(self, conn):
        self.conn = conn
        self.store = EvidenceStore(conn)

    async def resolve(self, application_id: str, tenant_id: str) -> dict:
        docs = await self._load_employment_docs(application_id, tenant_id)
        emp_block = await self._load_employment_block(application_id, tenant_id)
        if not docs and not emp_block:
            return {}

        await self.conn.execute(
            "DELETE FROM evidence_nodes WHERE application_id=$1 AND tenant_id=$2 "
            "AND evidence_category='employment'",
            application_id, tenant_id,
        )

        nodes = await self._build_evidence_nodes(application_id, tenant_id, docs, emp_block)
        facts: dict = {}
        fact = self._resolve_employment_continuity(application_id, tenant_id, nodes, emp_block)
        if fact:
            await self.store.save_fact_node(fact)
            facts["employment_continuity"] = fact
        return facts

    async def _load_employment_docs(self, application_id, tenant_id) -> list:
        rows = await self.conn.fetch(
            """
            SELECT document_id, document_type, extracted_fields, confidence_score
            FROM document_index
            WHERE application_id = $1 AND tenant_id = $2 AND is_current = true
              AND document_type = ANY($3)
            ORDER BY document_type
            """,
            application_id, tenant_id, list(DOC_TYPES),
        )
        docs = []
        for r in rows:
            fields = r["extracted_fields"]
            if isinstance(fields, str):
                fields = json.loads(fields)
            docs.append({
                "document_id": r["document_id"],
                "document_type": r["document_type"],
                "fields": fields or {},
                "confidence": float(r["confidence_score"] or 0),
            })
        return docs

    async def _load_employment_block(self, application_id, tenant_id) -> dict:
        row = await self.conn.fetchrow(
            "SELECT borrower->'employment' AS emp FROM entity_states "
            "WHERE application_id=$1 AND tenant_id=$2",
            application_id, tenant_id,
        )
        emp = row["emp"] if row else None
        if isinstance(emp, str):
            emp = json.loads(emp)
        return emp or {}

    async def _build_evidence_nodes(self, application_id, tenant_id, docs, emp_block) -> dict:
        nodes: dict = {}

        async def add(field_name, raw, numeric, conf, doc_id, doc_type, ntype, method, meta=None):
            if field_name in nodes:
                return
            node = EvidenceNode(
                application_id=application_id, tenant_id=tenant_id,
                node_type=ntype, evidence_category="employment",
                field_name=field_name, raw_value=raw, numeric_value=numeric,
                confidence=conf, source_document_id=doc_id,
                source_document_type=doc_type, extraction_method=method,
                metadata=meta or {},
            )
            await self.store.save_evidence_node(node)
            nodes[field_name] = node

        # Document evidence: employer_name + W2 box1 (self-employed signal).
        for doc in docs:
            f, doc_id, dt, conf = doc["fields"], doc["document_id"], doc["document_type"], doc["confidence"]
            if f.get("employer_name"):
                await add(f"employer_name_{dt.lower()}", str(f["employer_name"]), None,
                          conf, doc_id, dt, "document_field", "textract")
            if dt == "W2_CURRENT" and f.get("box1_wages") is not None:
                await add("w2_box1_wages", str(f["box1_wages"]), _to_float(f["box1_wages"]),
                          conf, doc_id, dt, "document_field", "textract",
                          meta={"note": "0 => no W2 wages (self-employment signal)"})

        # Derived evidence: the entity_states employment-reconciliation block.
        for k in _EMP_BLOCK_FIELDS:
            if emp_block.get(k) is not None:
                await add(f"emp_{k}", str(emp_block[k]), _to_float(emp_block[k]),
                          1.0, None, "entity_states_employment", "derived_fact", "derived")

        return nodes

    def _resolve_employment_continuity(self, application_id, tenant_id, nodes, emp_block) -> Optional[FactNode]:
        evidence_ids = [n.id for n in nodes.values()]
        if not evidence_ids:
            return None

        w2 = nodes.get("w2_box1_wages")
        box1 = w2.numeric_value if w2 else None
        recon_status = (emp_block.get("reconciliation_status") or "").lower()
        max_gap = _to_float(emp_block.get("max_gap_days"))
        coverage = _to_float(emp_block.get("continuity_coverage_pct"))
        employer = emp_block.get("employer_name")
        years = _years_between(emp_block.get("period_start"), emp_block.get("period_end"))

        conflicts = False
        notes: list[str] = []
        if employer:
            notes.append(f"Employer: {employer}")
        if years is not None:
            notes.append(f"Verified coverage window: {years:.1f} yr "
                         f"({emp_block.get('period_start')}..{emp_block.get('period_end')})")

        # W2 with zero box1 wages => self-employed (no W2 income).
        if w2 is not None and box1 == 0:
            continuity = "self_employed"
            conflicts = True
            notes.append("W2 box1_wages = 0 -> self-employed. Schedule C/K1 income "
                         "resolution required (INC-C).")
        elif max_gap is not None and max_gap > GAP_THRESHOLD_DAYS:
            continuity = "gap_detected"
            conflicts = True
            notes.append(f"Employment gap {max_gap:.0f} days (> {GAP_THRESHOLD_DAYS}) - verify.")
        elif recon_status in ("conflict", "missing"):
            continuity = "gap_detected"
            conflicts = True
            notes.append(f"Reconciliation status '{recon_status}' - escalate for review.")
        elif recon_status == "auto_verified":
            continuity = "stable"
            cov = f"{coverage:.0%}" if coverage is not None else "n/a"
            notes.append(f"Auto-verified, max gap {max_gap or 0:.0f}d, coverage {cov}.")
        elif employer:
            continuity = "employed"
            notes.append("Employer confirmed; tenure not established - request VOE.")
        else:
            continuity = "unknown"
            notes.append("Insufficient employment evidence.")

        confidence = min((n.confidence for n in nodes.values()), default=0.0)
        return FactNode(
            application_id=application_id, tenant_id=tenant_id,
            fact_type="employment_continuity", fact_text=continuity, fact_value=years,
            confidence=confidence,
            resolution_method="employer_name + W2 box1 (docs) + reconciliation block (entity_states)",
            evidence_ids=evidence_ids, conflicts_found=conflicts,
            resolution_notes="\n".join(notes),
            agency_treatment={"fannie": "2yr employment history required (B3-3.1-01)",
                              "fha": "2yr employment history required (4000.1 II.A.4)"},
        )


__all__ = ["EmploymentFactResolver"]
