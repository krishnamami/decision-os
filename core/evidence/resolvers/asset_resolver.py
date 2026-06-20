"""Asset Fact Resolver — EV-B2.

  document_index (bank statements)
    -> EvidenceNode per balance field
      -> FactNode: verified_assets (sum of balances)
      -> FactNode: funds_to_close (reserves check, when PITI known)

Asset analysis answers: sufficient? seasoned? sourced?
Large-deposit rule (Fannie B3-4.3-04): a deposit > 50% of monthly qualifying
income must be sourced/documented. A deposit already flagged as documented
does NOT need sourcing — so both amount and documented-status matter.

Gift-fund verification (letter + donor + transfer proof) is out of scope (AV-E).
"""
from __future__ import annotations

import json
from typing import Optional

from ..models import EvidenceNode, FactNode
from ..store import EvidenceStore

LARGE_DEPOSIT_PCT = 0.50       # deposit > 50% of qualifying monthly => source it
DEFAULT_DEPOSIT_THRESHOLD = 5000.0  # used when qualifying income is unknown
MIN_RESERVES_MONTHS = 2.0

_BALANCE_KEYS = ("ending_balance", "account_balance", "balance",
                 "closing_balance", "available_balance")
_DEPOSIT_KEYS = ("large_deposit_amount", "large_deposit",
                 "unusual_deposit", "deposit_over_threshold")


def _to_float(val) -> Optional[float]:
    try:
        return float(str(val).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return None


class AssetFactResolver:
    def __init__(self, conn):
        self.conn = conn
        self.store = EvidenceStore(conn)

    async def resolve(
        self,
        application_id: str,
        tenant_id: str,
        qualifying_monthly: Optional[float] = None,
        piti_monthly: Optional[float] = None,
    ) -> dict:
        docs = await self._load_asset_docs(application_id, tenant_id)
        if not docs:
            return {}

        # Idempotency: drop prior asset evidence (edges cascade) before rebuild.
        await self.conn.execute(
            "DELETE FROM evidence_nodes WHERE application_id=$1 AND tenant_id=$2 "
            "AND evidence_category='asset'",
            application_id, tenant_id,
        )

        # If caller didn't supply qualifying income, reuse the EV-B1 fact so the
        # large-deposit threshold is the real 50%-of-income figure.
        if qualifying_monthly is None:
            qualifying_monthly = await self.conn.fetchval(
                "SELECT fact_value FROM fact_nodes WHERE application_id=$1 "
                "AND tenant_id=$2 AND fact_type='qualifying_income' "
                "AND superseded_by IS NULL",
                application_id, tenant_id,
            )
            qualifying_monthly = float(qualifying_monthly) if qualifying_monthly is not None else None

        nodes = await self._build_evidence_nodes(application_id, tenant_id, docs)
        facts: dict = {}

        asset_fact = self._resolve_verified_assets(
            application_id, tenant_id, nodes, qualifying_monthly
        )
        if asset_fact:
            await self.store.save_fact_node(asset_fact)
            facts["verified_assets"] = asset_fact

        if piti_monthly and asset_fact:
            ftc = self._resolve_funds_to_close(
                application_id, tenant_id, asset_fact, piti_monthly
            )
            if ftc:
                await self.store.save_fact_node(ftc)
                facts["funds_to_close"] = ftc

        return facts

    async def _load_asset_docs(self, application_id, tenant_id) -> list:
        rows = await self.conn.fetch(
            """
            SELECT document_id, document_type, extracted_fields,
                   confidence_score, received_at
            FROM document_index
            WHERE application_id = $1 AND tenant_id = $2
              AND document_type ILIKE '%BANK_STATEMENT%' AND is_current = true
            ORDER BY document_type, received_at DESC
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
                "fields": fields or {},
                "confidence": float(r["confidence_score"] or 0),
            })
        return docs

    async def _build_evidence_nodes(self, application_id, tenant_id, docs) -> list:
        nodes: list = []
        seen_types: set = set()
        for doc in docs:
            fields, doc_id, doc_type, conf = (
                doc["fields"], doc["document_id"], doc["document_type"], doc["confidence"]
            )
            if doc_type in seen_types:  # newest per type only (ordered DESC)
                continue
            balance = next((_to_float(fields[k]) for k in _BALANCE_KEYS
                            if fields.get(k) is not None and _to_float(fields[k]) is not None), None)
            if balance is None:
                continue
            seen_types.add(doc_type)

            large_deposit = next((_to_float(fields[k]) for k in _DEPOSIT_KEYS
                                  if fields.get(k) and _to_float(fields[k])), None)
            deposit_documented = bool(fields.get("large_deposit_documented"))

            node = EvidenceNode(
                application_id=application_id, tenant_id=tenant_id,
                node_type="document_field", evidence_category="asset",
                field_name=f"balance_{doc_type.lower()}",
                raw_value=str(balance), numeric_value=balance, confidence=conf,
                source_document_id=doc_id, source_document_type=doc_type,
                extraction_method="textract",
                metadata={"large_deposit": large_deposit,
                          "large_deposit_documented": deposit_documented,
                          "doc_type": doc_type},
            )
            await self.store.save_evidence_node(node)
            nodes.append(node)
        return nodes

    def _resolve_verified_assets(
        self, application_id, tenant_id, nodes, qualifying_monthly
    ) -> Optional[FactNode]:
        if not nodes:
            return None
        total = sum(n.numeric_value or 0 for n in nodes)
        evidence_ids = [n.id for n in nodes]

        threshold = (qualifying_monthly * LARGE_DEPOSIT_PCT
                     if qualifying_monthly else DEFAULT_DEPOSIT_THRESHOLD)
        # A deposit needs sourcing only if it exceeds the threshold AND is not
        # already documented.
        unsourced = [
            n.metadata.get("large_deposit") for n in nodes
            if n.metadata.get("large_deposit")
            and n.metadata["large_deposit"] > threshold
            and not n.metadata.get("large_deposit_documented")
        ]
        conflicts = len(unsourced) > 0

        notes = [f"Total verified liquid assets: ${total:,.2f}",
                 f"Sources: {len(nodes)} bank statement(s)",
                 f"Large-deposit threshold: ${threshold:,.0f}"]
        if unsourced:
            notes.append(
                f"{len(unsourced)} undocumented large deposit(s) require sourcing: "
                f"${sum(unsourced):,.0f} total (Fannie B3-4.3-04)"
            )

        return FactNode(
            application_id=application_id, tenant_id=tenant_id,
            fact_type="verified_assets", fact_value=round(total, 2),
            confidence=min(n.confidence for n in nodes),
            resolution_method="sum of bank statement balances",
            evidence_ids=evidence_ids, conflicts_found=conflicts,
            resolution_notes="\n".join(notes),
            agency_treatment={
                "large_deposit_threshold": "50% of qualifying monthly (Fannie B3-4.3-04)",
                "seasoning": "60 days required",
            },
        )

    def _resolve_funds_to_close(
        self, application_id, tenant_id, asset_fact, piti_monthly
    ) -> Optional[FactNode]:
        """Reserves-only sufficiency signal (down payment + closing costs +
        prepaids need loan data — full funds-to-close is AV-E)."""
        reserves_needed = piti_monthly * MIN_RESERVES_MONTHS
        available = asset_fact.fact_value or 0
        sufficient = available >= reserves_needed
        notes = (f"Reserves check: ${reserves_needed:,.2f} needed "
                 f"({MIN_RESERVES_MONTHS:.0f} mo PITI), ${available:,.2f} available -> "
                 f"{'sufficient' if sufficient else 'INSUFFICIENT'}")
        return FactNode(
            application_id=application_id, tenant_id=tenant_id,
            fact_type="funds_to_close", fact_value=round(available, 2),
            confidence=asset_fact.confidence, resolution_method="reserves check only",
            evidence_ids=asset_fact.evidence_ids, conflicts_found=not sufficient,
            resolution_notes=notes,
            agency_treatment={"reserves_minimum": "2 months PITI",
                              "full_ftc": "requires AV-E (down + costs + prepaids)"},
        )


__all__ = ["AssetFactResolver"]
