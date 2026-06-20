"""Evidence Trace Builder — EV-D.

Assembles the evidence chain for a decision from fact_nodes + evidence_nodes
and attaches it to decision_outputs.evidence_trace. This is what the AI
explanation engine reads to narrate *why* a decision was made:

    "Your W2 shows $102,000 in box 1 wages -> $8,500/mo qualifying. Your
     paystub confirms within 2%. No conflicts found."

trace = {
  income/assets/credit/employment: {<fact>: {value, confidence, method,
      sources:[{doc, field, value, year, conf}], conflicts, notes, agency}},
  fraud_signals: [...], cross_validations: [...],
  overall_confidence, requires_uw_review,
}
"""
from __future__ import annotations

import json
from typing import Optional


class EvidenceTraceBuilder:
    def __init__(self, conn):
        self.conn = conn

    async def build_trace(self, application_id: str, tenant_id: str) -> dict:
        facts = await self.conn.fetch(
            """
            SELECT fact_type, fact_value, fact_text, confidence, resolution_method,
                   evidence_ids, conflicts_found, resolution_notes, agency_treatment
            FROM fact_nodes
            WHERE application_id=$1 AND tenant_id=$2 AND superseded_by IS NULL
            ORDER BY fact_type
            """,
            application_id, tenant_id,
        )
        cross_nodes = await self.conn.fetch(
            """
            SELECT field_name, raw_value, numeric_value, evidence_category
            FROM evidence_nodes
            WHERE application_id=$1 AND tenant_id=$2
              AND node_type IN ('cross_validation','conflict')
            ORDER BY created_at
            """,
            application_id, tenant_id,
        )

        trace: dict = {
            "income": {}, "assets": {}, "credit": {}, "employment": {},
            "fraud_signals": [], "cross_validations": [],
            "overall_confidence": 0.0, "requires_uw_review": False,
        }
        section_key = {
            "qualifying_income": ("income", "qualifying_monthly"),
            "verified_assets": ("assets", "verified_total"),
            "funds_to_close": ("assets", "funds_to_close"),
            "governing_credit_score": ("credit", "governing_score"),
            "employment_continuity": ("employment", "continuity"),
        }

        confidences: list[float] = []
        has_conflicts = False

        for fact in facts:
            conf = float(fact["confidence"] or 0)
            confidences.append(conf)
            if fact["conflicts_found"]:
                has_conflicts = True

            sources = []
            for ev in await self._sources(fact["evidence_ids"]):
                sources.append({
                    "doc": ev["source_document_type"], "field": ev["field_name"],
                    "value": ev["raw_value"], "year": ev["tax_year"],
                    "conf": float(ev["confidence"] or 0),
                })

            entry = {
                "value": fact["fact_value"], "text": fact["fact_text"],
                "confidence": conf, "method": fact["resolution_method"],
                "sources": sources, "conflicts": fact["conflicts_found"],
                "notes": fact["resolution_notes"], "agency": fact["agency_treatment"],
            }
            target = section_key.get(fact["fact_type"])
            if target:
                trace[target[0]][target[1]] = entry

        for node in cross_nodes:
            entry = {"check": node["field_name"], "result": node["raw_value"],
                     "category": node["evidence_category"]}
            # raw_value carries "FRAUD SIGNAL" (any case) when it's fraud-level.
            if "fraud" in (node["raw_value"] or "").lower():
                trace["fraud_signals"].append(entry)
            else:
                trace["cross_validations"].append(entry)

        trace["overall_confidence"] = round(min(confidences), 2) if confidences else 0.0
        trace["requires_uw_review"] = has_conflicts or len(trace["fraud_signals"]) > 0
        return trace

    async def _sources(self, evidence_ids):
        if not evidence_ids:
            return []
        return await self.conn.fetch(
            """
            SELECT field_name, raw_value, numeric_value, source_document_type,
                   tax_year, confidence
            FROM evidence_nodes WHERE id = ANY($1::uuid[])
            ORDER BY source_document_type
            """,
            list(evidence_ids),
        )

    async def attach_to_decision(self, application_id, tenant_id, decision_row_id) -> bool:
        """Attach the evidence trace to a decision_outputs row (by row id)."""
        await self.conn.execute(
            "ALTER TABLE decision_outputs ADD COLUMN IF NOT EXISTS evidence_trace JSONB DEFAULT '{}'"
        )
        trace = await self.build_trace(application_id, tenant_id)
        # default=str makes Decimal / UUID / datetime JSON-safe.
        await self.conn.execute(
            "UPDATE decision_outputs SET evidence_trace = $1::jsonb WHERE id = $2",
            json.dumps(trace, default=str), decision_row_id,
        )
        return True

    def format_for_explanation(self, trace: dict) -> str:
        """Human-readable evidence summary for the AI explanation engine."""
        lines: list[str] = []

        inc = trace.get("income", {}).get("qualifying_monthly")
        if inc:
            val = float(inc.get("value") or 0)
            lines.append(f"INCOME: ${val:,.2f}/mo qualifying")
            lines.append(f"  Method: {inc.get('method', '')}")
            lines.append(f"  Confidence: {inc['confidence']:.2f}")
            for src in inc.get("sources", [])[:2]:
                lines.append(f"  Source: {src['doc']} {src['field']}={src['value']}")
            if inc.get("conflicts"):
                lines.append("  ** CONFLICTS FOUND")

        cr = trace.get("credit", {}).get("governing_score")
        if cr and cr.get("value") is not None:
            lines.append(f"CREDIT: {float(cr['value']):.0f} governing score")
            lines.append(f"  Method: {cr.get('method', '')}")
            if cr.get("conflicts"):
                lines.append("  ** DEROGATORY MARKS")

        ast = trace.get("assets", {}).get("verified_total")
        if ast:
            val = float(ast.get("value") or 0)
            lines.append(f"ASSETS: ${val:,.2f} verified")
            if ast.get("conflicts"):
                lines.append("  ** LARGE DEPOSIT NEEDS SOURCING")

        emp = trace.get("employment", {}).get("continuity")
        if emp:
            lines.append(f"EMPLOYMENT: {emp.get('text', 'unknown')}")
            if emp.get("conflicts"):
                lines.append("  ** EMPLOYMENT NEEDS REVIEW")

        for sig in trace.get("fraud_signals", []):
            lines.append(f"** FRAUD SIGNAL: {sig['check']}: {sig['result']}")

        lines.append(f"OVERALL CONFIDENCE: {trace['overall_confidence']:.2f}")
        lines.append(f"UW REVIEW REQUIRED: {trace['requires_uw_review']}")
        return "\n".join(lines)


__all__ = ["EvidenceTraceBuilder"]
