"""Income Fact Resolver — EV-B1.

  document_index (W2 + paystub)
    -> EvidenceNode per income field
      -> cross-validate (corroborates / conflicts_with)
        -> FactNode: qualifying_income
          -> fact_nodes (via EvidenceStore)

Primary qualifying figure is box1_wages / 12 (Fannie B3-3.1-01, W2 salaried).
The paystub is corroboration: its YTD gross is ANNUALIZED (YTD x 365 / days
elapsed in the year) before being compared to the W2 annual wage — comparing
a partial-year YTD against an annual W2 would flag a false conflict on every
W2 borrower.

Self-employed / Schedule C income is out of scope here (later sub-prompt).
"""
from __future__ import annotations

import json
from datetime import date
from typing import Optional

from ..models import EvidenceEdge, EvidenceNode, FactNode
from ..store import EvidenceStore

CONFLICT_THRESHOLD = 0.10      # >10% annualized difference => conflict
CORROBORATE_THRESHOLD = 0.10   # within 10% => corroborates

W2_TYPES = ("W2_CURRENT", "W2_PRIOR")
PAYSTUB_TYPES = ("PAYSTUB_CURRENT", "PAYSTUB_PRIOR")


def _to_float(val) -> Optional[float]:
    try:
        return float(str(val).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return None


def _annualize_ytd(ytd: float, pay_date_str) -> Optional[float]:
    """Annualize a YTD gross by the fraction of the year elapsed at pay_date.
    Returns None if the date can't be parsed."""
    try:
        d = date.fromisoformat(str(pay_date_str)[:10])
    except (ValueError, TypeError):
        return None
    elapsed_days = (d - date(d.year, 1, 1)).days + 1
    if elapsed_days <= 0:
        return None
    return round(ytd * 365.0 / elapsed_days, 2)


class IncomeFactResolver:
    def __init__(self, conn):
        self.conn = conn
        self.store = EvidenceStore(conn)

    async def resolve(self, application_id: str, tenant_id: str) -> Optional[FactNode]:
        """Read income docs, build evidence + edges, resolve qualifying_income.
        Idempotent: clears this application's existing income evidence first so
        re-runs don't accumulate duplicate nodes (the fact is superseded)."""
        docs = await self._load_income_docs(application_id, tenant_id)
        if not docs:
            return None

        # Idempotency: drop prior income evidence (edges cascade) before rebuild.
        await self.conn.execute(
            "DELETE FROM evidence_nodes WHERE application_id=$1 AND tenant_id=$2 "
            "AND evidence_category='income'",
            application_id, tenant_id,
        )

        nodes = await self._build_evidence_nodes(application_id, tenant_id, docs)
        edges, conflicts = await self._cross_validate(application_id, tenant_id, nodes)
        fact = self._resolve_qualifying_income(application_id, tenant_id, nodes, edges, conflicts)
        if fact:
            await self.store.save_fact_node(fact)
        return fact

    async def _load_income_docs(self, application_id, tenant_id) -> list:
        rows = await self.conn.fetch(
            """
            SELECT document_id, document_type, extracted_fields,
                   confidence_score, received_at
            FROM document_index
            WHERE application_id = $1 AND tenant_id = $2 AND is_current = TRUE
              AND document_type = ANY($3)
            ORDER BY received_at DESC
            """,
            application_id, tenant_id, list(W2_TYPES + PAYSTUB_TYPES),
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

    async def _build_evidence_nodes(self, application_id, tenant_id, docs) -> dict:
        """One EvidenceNode per income field. Keyed by field_name. Only the
        first (newest, since ordered received_at DESC) doc of each type wins."""
        nodes: dict = {}

        async def add(node: EvidenceNode):
            if node.field_name in nodes:
                return  # newest already recorded
            await self.store.save_evidence_node(node)
            nodes[node.field_name] = node

        for doc in docs:
            fields, doc_id, doc_type, conf = (
                doc["fields"], doc["document_id"], doc["document_type"], doc["confidence"]
            )

            if doc_type in W2_TYPES:
                tax_year = None
                try:
                    tax_year = int(fields.get("tax_year")) if fields.get("tax_year") else None
                except (ValueError, TypeError):
                    tax_year = None
                box1 = None
                for k in ("box1_wages", "wages_tips_compensation", "box_1"):
                    if fields.get(k) is not None:
                        box1 = fields[k]
                        break
                if box1 is not None:
                    await add(EvidenceNode(
                        application_id=application_id, tenant_id=tenant_id,
                        node_type="document_field", evidence_category="income",
                        field_name=f"box1_wages_{doc_type.lower()}",
                        raw_value=str(box1), numeric_value=_to_float(box1),
                        confidence=conf, source_document_id=doc_id,
                        source_document_type=doc_type, extraction_method="textract",
                        tax_year=tax_year,
                    ))

            elif doc_type == "PAYSTUB_CURRENT":
                ytd = fields.get("ytd_gross") or fields.get("year_to_date_gross")
                ytd_val = _to_float(ytd) if ytd is not None else None
                pay_date = fields.get("pay_date") or fields.get("pay_period_end")
                annualized = _annualize_ytd(ytd_val, pay_date) if ytd_val else None
                if annualized is not None:
                    await add(EvidenceNode(
                        application_id=application_id, tenant_id=tenant_id,
                        node_type="document_field", evidence_category="income",
                        field_name="paystub_annualized_income",
                        raw_value=str(ytd), numeric_value=annualized,
                        confidence=conf, source_document_id=doc_id,
                        source_document_type=doc_type, extraction_method="textract",
                        metadata={"ytd_gross": ytd_val, "pay_date": str(pay_date),
                                  "annualization": "ytd * 365 / days_elapsed"},
                    ))

        return nodes

    async def _cross_validate(self, application_id, tenant_id, nodes):
        """W2 box1 (annual) vs paystub annualized YTD. Within 10% -> corroborates,
        else conflicts_with."""
        edges, conflicts = [], []
        w2_node = nodes.get("box1_wages_w2_current")
        ps_node = nodes.get("paystub_annualized_income")
        if not (w2_node and ps_node):
            return edges, conflicts

        w2_val = w2_node.numeric_value or 0
        ps_val = ps_node.numeric_value or 0
        if w2_val <= 0 or ps_val <= 0:
            return edges, conflicts

        diff_pct = abs(w2_val - ps_val) / w2_val
        if diff_pct <= CORROBORATE_THRESHOLD:
            relationship = "corroborates"
            note = (f"W2 ${w2_val:,.0f} vs paystub annualized ${ps_val:,.0f} "
                    f"- {diff_pct:.1%} diff (within 10%)")
        else:
            relationship = "conflicts_with"
            note = (f"W2 ${w2_val:,.0f} vs paystub annualized ${ps_val:,.0f} "
                    f"- {diff_pct:.1%} diff (>10% conflict)")
            conflicts.append((w2_node, ps_node))

        edge = EvidenceEdge(
            application_id=application_id, tenant_id=tenant_id,
            from_node_id=w2_node.id, to_node_id=ps_node.id,
            relationship=relationship, strength=round(max(0.0, 1.0 - diff_pct), 2),
            notes=note,
        )
        await self.store.save_evidence_edge(edge)
        edges.append(edge)
        return edges, conflicts

    def _resolve_qualifying_income(
        self, application_id, tenant_id, nodes, edges, conflicts
    ) -> Optional[FactNode]:
        """Resolve qualifying monthly income.
          1. W2 current box1_wages / 12 (Fannie B3-3.1-01).
          2. Else paystub annualized / 12.
          3. On W2<->paystub conflict: use the lower value, confidence x0.7."""
        w2_node = nodes.get("box1_wages_w2_current")
        ps_node = nodes.get("paystub_annualized_income")
        has_conflict = len(conflicts) > 0
        evidence_ids, conflict_ids = [], []
        qualifying_monthly = method = notes = None
        confidence = 0.0

        if w2_node and w2_node.numeric_value:
            w2_annual = w2_node.numeric_value
            qualifying_monthly = round(w2_annual / 12, 2)
            method = f"box1_wages ${w2_annual:,.0f} / 12 (W2 salaried - Fannie B3-3.1-01)"
            confidence = w2_node.confidence
            evidence_ids.append(w2_node.id)
            if ps_node:
                evidence_ids.append(ps_node.id)

            if has_conflict:
                ps_val = ps_node.numeric_value or 0
                if 0 < ps_val < w2_annual:
                    qualifying_monthly = round(ps_val / 12, 2)
                    method += f" [CONFLICT: using lower paystub ${ps_val:,.0f}]"
                conflict_ids = [n.id for n, _ in conflicts] + [n.id for _, n in conflicts]
                confidence = round(confidence * 0.7, 2)
                notes = ("Income conflict: W2 vs paystub annualized differ >10%. "
                         "Using lower value. Escalate for UW review.")
            else:
                notes = f"W2 and paystub corroborate. Qualifying ${qualifying_monthly:,.2f}/mo."

        elif ps_node and ps_node.numeric_value:
            qualifying_monthly = round(ps_node.numeric_value / 12, 2)
            method = "paystub annualized / 12 (no W2 available)"
            confidence = round(ps_node.confidence * 0.85, 2)
            evidence_ids.append(ps_node.id)
            notes = "W2 not available. Using paystub annualized. Request W2 for full verification."

        if qualifying_monthly is None:
            return None

        return FactNode(
            application_id=application_id, tenant_id=tenant_id,
            fact_type="qualifying_income", fact_value=qualifying_monthly,
            confidence=confidence, resolution_method=method,
            evidence_ids=evidence_ids, conflicts_found=has_conflict,
            conflict_ids=conflict_ids, resolution_notes=notes or "",
            agency_treatment={"fannie": "box1_wages/12", "fha": "box1_wages/12",
                              "va": "box1_wages/12"},
        )


__all__ = ["IncomeFactResolver"]
