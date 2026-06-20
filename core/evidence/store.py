"""EvidenceStore — persist and retrieve evidence nodes, edges, and facts."""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from typing import List, Optional
from uuid import UUID

from .models import EvidenceEdge, EvidenceNode, FactNode


def _as_date(val):
    """Coerce an ISO string to a date for the DATE column (asyncpg rejects
    a bare str). Pass through date/None unchanged."""
    if val is None or isinstance(val, date):
        return val
    if isinstance(val, datetime):
        return val.date()
    return date.fromisoformat(str(val))


def _as_uuids(vals) -> List[UUID]:
    """Coerce a list of UUID/str into UUID objects for a uuid[] column."""
    return [v if isinstance(v, UUID) else uuid.UUID(str(v)) for v in (vals or [])]


class EvidenceStore:
    def __init__(self, conn):
        self.conn = conn

    async def save_evidence_node(self, node: EvidenceNode) -> UUID:
        await self.conn.execute(
            """
            INSERT INTO evidence_nodes (
                id, application_id, tenant_id, node_type, evidence_category,
                field_name, raw_value, numeric_value, confidence,
                source_document_id, source_document_type, extraction_method,
                tax_year, as_of_date, metadata
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
            ON CONFLICT DO NOTHING
            """,
            node.id, node.application_id, node.tenant_id, node.node_type,
            node.evidence_category, node.field_name, node.raw_value,
            node.numeric_value, node.confidence, node.source_document_id,
            node.source_document_type, node.extraction_method, node.tax_year,
            _as_date(node.as_of_date), json.dumps(node.metadata),
        )
        return node.id

    async def save_evidence_edge(self, edge: EvidenceEdge) -> UUID:
        await self.conn.execute(
            """
            INSERT INTO evidence_edges (
                id, application_id, tenant_id, from_node_id, to_node_id,
                relationship, strength, notes
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
            ON CONFLICT DO NOTHING
            """,
            edge.id, edge.application_id, edge.tenant_id, edge.from_node_id,
            edge.to_node_id, edge.relationship, edge.strength, edge.notes,
        )
        return edge.id

    async def save_fact_node(self, fact: FactNode) -> UUID:
        """Insert a fact, superseding any current fact of the same type for
        this (application, tenant). Keeps an immutable history while the
        partial unique index enforces exactly one current row per fact_type.

        Supersede-then-insert runs in one transaction: the UPDATE moves the
        prior fact out of the partial unique index, and the deferrable
        superseded_by FK is validated at commit (when the new row exists)."""
        async with self.conn.transaction():
            await self.conn.execute(
                """
                UPDATE fact_nodes
                SET superseded_by = $1
                WHERE application_id = $2 AND tenant_id = $3 AND fact_type = $4
                  AND superseded_by IS NULL AND id != $1
                """,
                fact.id, fact.application_id, fact.tenant_id, fact.fact_type,
            )
            await self.conn.execute(
                """
                INSERT INTO fact_nodes (
                    id, application_id, tenant_id, fact_type, fact_value, fact_text,
                    confidence, resolution_method, evidence_ids, conflicts_found,
                    conflict_ids, resolution_notes, agency_treatment
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
                ON CONFLICT DO NOTHING
                """,
                fact.id, fact.application_id, fact.tenant_id, fact.fact_type,
                fact.fact_value, fact.fact_text, fact.confidence,
                fact.resolution_method, _as_uuids(fact.evidence_ids),
                fact.conflicts_found, _as_uuids(fact.conflict_ids),
                fact.resolution_notes, json.dumps(fact.agency_treatment),
            )
        return fact.id

    async def get_facts_for_application(
        self, application_id: str, tenant_id: str, fact_type: Optional[str] = None,
    ) -> List[dict]:
        """Current (non-superseded) facts for an application."""
        query = (
            "SELECT * FROM fact_nodes "
            "WHERE application_id = $1 AND tenant_id = $2 AND superseded_by IS NULL"
        )
        params: list = [application_id, tenant_id]
        if fact_type:
            query += " AND fact_type = $3"
            params.append(fact_type)
        query += " ORDER BY computed_at DESC"
        rows = await self.conn.fetch(query, *params)
        return [dict(r) for r in rows]

    async def get_evidence_for_application(
        self, application_id: str, tenant_id: str,
        evidence_category: Optional[str] = None,
    ) -> List[dict]:
        """All evidence nodes for an application, optionally by category."""
        query = (
            "SELECT * FROM evidence_nodes "
            "WHERE application_id = $1 AND tenant_id = $2"
        )
        params: list = [application_id, tenant_id]
        if evidence_category:
            query += " AND evidence_category = $3"
            params.append(evidence_category)
        query += " ORDER BY created_at"
        rows = await self.conn.fetch(query, *params)
        return [dict(r) for r in rows]


__all__ = ["EvidenceStore"]
