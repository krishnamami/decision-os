from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from .store import ClaimRecord, DocumentRecord, KnowledgeStore


# ─────────────────────────────────────────────────────────────────────
# Retriever — single contract every knowledge backend implements.
#
# v1 ships MetadataRetriever (SQL/dict match) — solves per-loan doc
# retrieval which is metadata-bounded by nature. Vectors are NOT in v1.
# Cross-corpus retrievers (PgVectorRetriever, QdrantRetriever) drop in
# without changing call sites — Context Agent reads through this
# Protocol regardless of backend. See PRD STREAM E v0 vs v1 split.
#
# Design decisions (locked):
#   - retrieve() returns *verified-by-default* claims so a decision
#     agent never accidentally consumes pending data. Pass
#     verified_only=False to inspect the unverified pool (used by the
#     verification UI / human-queue worker, not by decision agents).
#   - Per-decision filtering happens HERE via the doc_type matrix in
#     knowledge_base.json — not on the ObjectType. Coarse-grained
#     decisions_that_read_it on Document/Claim is wide-open; fine
#     grained "income_verification reads claims from W-2 / pay_stub /
#     1040 / bank_stmt" lives in the matrix. Lets us update the matrix
#     without redeploying ontology types.
# ─────────────────────────────────────────────────────────────────────


class RetrievalResult(BaseModel):
    """What the Retriever returns. Carries:
      - claims_by_field: name → value (the simple shape decision agents
        read; only verified claims by default)
      - claim_records: full Claim records with provenance (status, page,
        verified_by, etc.) — the trace consumes these
      - documents: source documents these claims came from
      - retrieval_metadata: backend stats (source, latency, k-retrieved)"""

    decision_id: str
    application_id: str
    claims_by_field: dict[str, Any] = Field(default_factory=dict)
    claim_records: list[ClaimRecord] = Field(default_factory=list)
    documents: list[DocumentRecord] = Field(default_factory=list)
    retrieval_metadata: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class Retriever(Protocol):
    async def retrieve(
        self,
        decision_id: str,
        application_id: str,
        *,
        verified_only: bool = True,
        at: Optional[datetime] = None,
    ) -> RetrievalResult: ...


# ─────────────────────────────────────────────────────────────────────
# MetadataRetriever — SQL/dict-match backend.
# ─────────────────────────────────────────────────────────────────────


class MetadataRetriever:
    """Per-loan retrieval via metadata + the doc_type matrix.

    Does NOT use embeddings. Solves the "what's on THIS loan?" query
    cleanly because per-loan doc retrieval is metadata-bounded by
    nature. For cross-corpus / fuzzy queries (agency guidelines, fraud
    analogues, persona learning recall) plug in a vector retriever
    behind the same Protocol — that's STREAM E2 territory.

    The doc_type → decisions matrix is loaded from
    domains/<domain>/knowledge_base.json#document_types at construction.
    Caller can override or pass a pre-parsed dict for tests.
    """

    def __init__(
        self,
        store: KnowledgeStore,
        *,
        doc_type_matrix: Optional[dict[str, Any]] = None,
        knowledge_base_path: Optional[Path] = None,
    ):
        self._store = store
        if doc_type_matrix is not None:
            self._matrix = dict(doc_type_matrix)
        else:
            self._matrix = _load_doc_type_matrix(knowledge_base_path)

    # ── Public Retriever surface ──────────────────────────────────────

    async def retrieve(
        self,
        decision_id: str,
        application_id: str,
        *,
        verified_only: bool = True,
        at: Optional[datetime] = None,
    ) -> RetrievalResult:
        # `at` is passed through for future PolicyStore-style point-in-time
        # reads. Today's KnowledgeStore.list_* returns live state; the
        # _ReadOnlyAtTimeShim already pins durable reads to `at` during
        # replay so the result is naturally point-in-time when the
        # underlying store is wrapped. Explicit `at` filtering on top
        # of that shim is a TODO — STREAM E2 (multi-version claims).

        relevant_doc_types = self._doc_types_for_decision(decision_id)
        if not relevant_doc_types:
            # This decision doesn't consume docs at all (e.g. lead_scoring).
            return RetrievalResult(
                decision_id=decision_id,
                application_id=application_id,
                retrieval_metadata={
                    "source": "metadata",
                    "doc_types_consulted": 0,
                    "claims_returned": 0,
                },
            )

        # Pull docs and claims for this application; filter by doc_type
        # in Python. TODO postgres: a single
        # `SELECT * FROM claims WHERE application_id=$1
        #   AND document_id IN (SELECT id FROM documents WHERE doc_type = ANY($2))
        #   AND status='verified'`.
        all_docs = await self._store.list_documents(application_id)
        relevant_docs: list[DocumentRecord] = [
            d for d in all_docs if d.doc_type in relevant_doc_types
        ]
        relevant_doc_ids = {d.document_id for d in relevant_docs}

        all_claims = await self._store.list_claims(application_id)
        relevant_claims: list[ClaimRecord] = [
            c for c in all_claims
            if c.document_id in relevant_doc_ids
            and (not verified_only or c.is_verified)
        ]

        # Collapse to {field_name → value}. When multiple claims for the
        # same field exist (e.g. two W-2s in different years), the most
        # recently extracted wins — same "latest fact" semantics as
        # `latest_object` on entity rolls.
        claims_by_field: dict[str, Any] = {}
        latest_at: dict[str, datetime] = {}
        for c in relevant_claims:
            ts = c.extracted_at or datetime.min
            prev = latest_at.get(c.field_name)
            if prev is None or ts > prev:
                claims_by_field[c.field_name] = c.field_value
                latest_at[c.field_name] = ts

        return RetrievalResult(
            decision_id=decision_id,
            application_id=application_id,
            claims_by_field=claims_by_field,
            claim_records=relevant_claims,
            documents=relevant_docs,
            retrieval_metadata={
                "source": "metadata",
                "doc_types_consulted": len(relevant_doc_types),
                "documents_matched": len(relevant_docs),
                "claims_returned": len(relevant_claims),
                "verified_only": verified_only,
            },
        )

    # ── Internals ────────────────────────────────────────────────────

    def _doc_types_for_decision(self, decision_id: str) -> set[str]:
        """Reverse the doc_type matrix to: which doc_types feed this
        decision? Computed each call — cheap, dict-walk; cache later if
        a profile shows it matters."""
        out: set[str] = set()
        for doc_type, entry in self._matrix.items():
            if not isinstance(entry, dict):
                continue
            feeds = entry.get("feeds_decisions") or []
            if decision_id in feeds:
                out.add(doc_type)
        return out


# ─────────────────────────────────────────────────────────────────────
# Knowledge-base loader
# ─────────────────────────────────────────────────────────────────────


_DEFAULT_KB_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "domains" / "lending" / "knowledge_base.json"
)


def _load_doc_type_matrix(
    path: Optional[Path] = None,
) -> dict[str, Any]:
    p = path or _DEFAULT_KB_PATH
    if not p.exists():
        return {}
    try:
        with p.open("r", encoding="utf-8") as fh:
            kb = json.load(fh)
    except Exception:
        return {}
    matrix = kb.get("document_types") or {}
    # Strip the leading "_description" meta-row if present.
    return {
        k: v for k, v in matrix.items()
        if isinstance(v, dict) and not k.startswith("_")
    }


# ─────────────────────────────────────────────────────────────────────
# Future retrievers (STREAM E2) — stubbed as comments only.
#
# class PgVectorRetriever:
#     """Vector search via pgvector. Same Retriever Protocol.
#     Earns its cost on cross-corpus / fuzzy queries — agency
#     guidelines, fraud analogues, persona learning recall. NOT for
#     per-loan doc retrieval (metadata wins there)."""
#     ...
#
# class QdrantRetriever:
#     """For 100M+ vector workloads at Rocket-class scale —
#     fraud analogue search, property comp search."""
#     ...
#
# class HybridRetriever:
#     """Composes MetadataRetriever + vector retrievers and routes by
#     workload. Most lenders want this — metadata for per-loan, vector
#     for cross-corpus."""
#     ...
# ─────────────────────────────────────────────────────────────────────


__all__ = [
    "MetadataRetriever",
    "RetrievalResult",
    "Retriever",
]
