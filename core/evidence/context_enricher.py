"""Context Enricher — EV-E.

Enriches the persona context bundle with the evidence trace (fact_nodes via
EvidenceTraceBuilder). This is a PARALLEL enrichment layer: every existing
field from the vw_*_context views is preserved untouched, and the evidence
facts are added alongside, so nothing breaks. Personas can begin reading
context['evidence'] (or the promoted top-level evidence_* fields) and migrate
off raw entity_states fields incrementally.

  context['qualifying_income']            -> entity_states (current behavior)
  context['evidence']['income']           -> fact_nodes (evidence graph)
  context['evidence_qualifying_monthly']  -> promoted fact value
"""
from __future__ import annotations

from .trace_builder import EvidenceTraceBuilder


class ContextEnricher:
    def __init__(self, conn):
        self.conn = conn
        self.builder = EvidenceTraceBuilder(conn)

    async def enrich_context(self, application_id: str, tenant_id: str,
                             existing_context: dict) -> dict:
        """Return existing_context plus an evidence layer (non-destructive)."""
        trace = await self.builder.build_trace(application_id, tenant_id)

        enriched = dict(existing_context)
        enriched["evidence"] = trace
        enriched["evidence_available"] = True
        enriched["requires_uw_review"] = trace.get("requires_uw_review", False)
        enriched["fraud_signals"] = trace.get("fraud_signals", [])
        enriched["overall_evidence_confidence"] = trace.get("overall_confidence", 0.0)

        # Promote key fact values to top level so personas can read them
        # directly without changing their existing access patterns.
        income = trace.get("income", {}).get("qualifying_monthly")
        if income:
            enriched["evidence_qualifying_monthly"] = income["value"]
            enriched["evidence_income_confidence"] = income["confidence"]
            enriched["evidence_income_conflicts"] = income["conflicts"]

        credit = trace.get("credit", {}).get("governing_score")
        if credit:
            enriched["evidence_governing_score"] = credit["value"]
            enriched["evidence_credit_conflicts"] = credit["conflicts"]

        assets = trace.get("assets", {}).get("verified_total")
        if assets:
            enriched["evidence_verified_assets"] = assets["value"]
            enriched["evidence_asset_conflicts"] = assets["conflicts"]

        employment = trace.get("employment", {}).get("continuity")
        if employment:
            enriched["evidence_employment_status"] = employment["text"]
            enriched["evidence_employment_conflicts"] = employment["conflicts"]

        return enriched

    async def get_fact_summary(self, application_id: str, tenant_id: str) -> str:
        """One-line evidence summary for logging / monitoring."""
        trace = await self.builder.build_trace(application_id, tenant_id)
        income = trace.get("income", {}).get("qualifying_monthly", {}) or {}
        credit = trace.get("credit", {}).get("governing_score", {}) or {}
        assets = trace.get("assets", {}).get("verified_total", {}) or {}
        return (
            f"income=${float(income.get('value') or 0):,.0f}/mo "
            f"score={float(credit.get('value') or 0):.0f} "
            f"assets=${float(assets.get('value') or 0):,.0f} "
            f"conf={trace['overall_confidence']:.2f} "
            f"review={trace['requires_uw_review']}"
        )


__all__ = ["ContextEnricher"]
