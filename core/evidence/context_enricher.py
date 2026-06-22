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

    # Live fact_type -> the context key personas will read (RA-3B / EV-F).
    # employment is textual (fact_text); the others are numeric (fact_value).
    EVIDENCE_KEYS = {
        "qualifying_income":      "evidence_qualifying_monthly",
        "governing_credit_score": "evidence_governing_score",
        "verified_assets":        "evidence_verified_assets",
        "employment_continuity":  "evidence_employment_status",
    }

    async def evidence_facts(
        self, application_id: str, tenant_id: str
    ) -> dict:
        """Return the RA-3B evidence_* keys from CURRENT (non-superseded)
        fact_nodes for one application.

        Adds, exactly:
          evidence_qualifying_monthly  <- qualifying_income.fact_value
          evidence_governing_score     <- governing_credit_score.fact_value
          evidence_verified_assets     <- verified_assets.fact_value
          evidence_employment_status   <- employment_continuity.fact_text
          evidence_overall_confidence  <- min() of the present confidences
          evidence_any_conflicts       <- any conflicts_found = true
          evidence_populated           <- bool, any current facts exist

        Graceful: never raises; returns evidence_populated=False with all
        values None when no facts exist. Non-destructive — the caller merges
        these alongside existing context keys.
        """
        base = {
            "evidence_qualifying_monthly": None,
            "evidence_governing_score":    None,
            "evidence_verified_assets":    None,
            "evidence_employment_status":  None,
            "evidence_overall_confidence": None,
            "evidence_any_conflicts":      False,
            "evidence_populated":          False,
            # Per-fact detail for persona consumption (RA-3D onward).
            "ev_income_value":             None,
            "ev_income_confidence":        None,
            "ev_income_method":            None,
            "ev_income_conflicts":         False,
            "ev_income_conflict_ids":      None,
            "ev_employment_confidence":    None,
            "ev_employment_conflicts":     False,
        }
        try:
            rows = await self.conn.fetch(
                """
                SELECT fact_type, fact_value, fact_text,
                       confidence, conflicts_found,
                       resolution_method, conflict_ids
                FROM fact_nodes
                WHERE application_id = $1
                  AND tenant_id = $2
                  AND superseded_by IS NULL
                  AND fact_type = ANY($3::text[])
                """,
                application_id, tenant_id,
                list(self.EVIDENCE_KEYS),
            )
        except Exception:
            return base

        if not rows:
            return base

        # Defensive: if more than one current row per type slips through,
        # keep the highest-confidence one.
        best: dict = {}
        for r in rows:
            ft = r["fact_type"]
            cur = best.get(ft)
            if cur is None or float(r["confidence"] or 0) > float(
                cur["confidence"] or 0
            ):
                best[ft] = r

        confidences = []
        any_conflict = False
        for ft, key in self.EVIDENCE_KEYS.items():
            r = best.get(ft)
            if r is None:
                continue
            if ft == "employment_continuity":
                base[key] = r["fact_text"]
            else:
                base[key] = (
                    float(r["fact_value"])
                    if r["fact_value"] is not None else None
                )
            if r["confidence"] is not None:
                confidences.append(float(r["confidence"]))
            if r["conflicts_found"]:
                any_conflict = True

            # Per-fact detail the personas read (income + employment first).
            if ft == "qualifying_income":
                base["ev_income_value"] = (
                    float(r["fact_value"])
                    if r["fact_value"] is not None else None
                )
                base["ev_income_confidence"] = (
                    float(r["confidence"])
                    if r["confidence"] is not None else None
                )
                base["ev_income_method"] = r["resolution_method"]
                base["ev_income_conflicts"] = bool(r["conflicts_found"])
                base["ev_income_conflict_ids"] = (
                    list(r["conflict_ids"]) if r["conflict_ids"] else None
                )
            elif ft == "employment_continuity":
                base["ev_employment_confidence"] = (
                    float(r["confidence"])
                    if r["confidence"] is not None else None
                )
                base["ev_employment_conflicts"] = bool(r["conflicts_found"])

        base["evidence_populated"] = True
        base["evidence_any_conflicts"] = any_conflict
        base["evidence_overall_confidence"] = (
            round(min(confidences), 3) if confidences else None
        )
        return base

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
