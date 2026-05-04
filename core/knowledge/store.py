from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from core.context_store.base import Lineage
from core.context_store.lending import LendingContextStore


# ─────────────────────────────────────────────────────────────────────
# KnowledgeStore — read+write facade over LendingContextStore for the
# two doc-related ObjectTypes (Document, Claim).
#
# Pattern mirrors core/policy_engine/store.PolicyStore — same Type-2
# supersession, lineage, point-in-time reads come for free. Documents
# and Claims live under SHARED scope (decision_id=None). Per-decision
# permission filtering happens at the Retriever, gated by the
# document_types matrix in domains/lending/knowledge_base.json.
#
# Status semantics:
#   Document.status: unverified → ocr_extracted → human_corrected →
#                    verified | rejected
#   Claim.status:    pending    → verified | rejected | superseded
# Re-uploads of a Document supersede via the standard ContextRecord
# chain (entity_id stays the same; new write bumps version). Re-extracted
# claims get a new claim_id when extraction reruns; the prior is marked
# `superseded` via Claim.status.
# ─────────────────────────────────────────────────────────────────────


DOCUMENT_ENTITY_TYPE = "Document"
CLAIM_ENTITY_TYPE = "Claim"


class DocumentRecord(BaseModel):
    """Typed view over a stored Document value blob."""

    document_id: str
    application_id: str
    applicant_id: Optional[str] = None
    doc_type: str
    status: str = "unverified"
    source_url: Optional[str] = None
    source_system: Optional[str] = None
    uploaded_at: Optional[datetime] = None
    uploaded_by: Optional[str] = None
    verified_at: Optional[datetime] = None
    verified_by: Optional[str] = None
    ocr_confidence: Optional[float] = None
    page_count: Optional[int] = None
    mime_type: Optional[str] = None


class ClaimRecord(BaseModel):
    """Typed view over a stored Claim value blob."""

    claim_id: str
    document_id: str
    application_id: str
    applicant_id: Optional[str] = None
    field_name: str
    field_value: Any = None
    source_page: Optional[int] = None
    source_bbox: Optional[dict[str, Any]] = None
    extraction_method: str = "manual"
    extraction_confidence: float = 1.0
    status: str = "pending"
    verified_at: Optional[datetime] = None
    verified_by: Optional[str] = None
    extracted_at: Optional[datetime] = None
    extracted_by: str = "system"

    @property
    def is_verified(self) -> bool:
        return self.status == "verified"


class KnowledgeStore:
    """Read+write facade over LendingContextStore for Document / Claim.

    Public surface:
      put_document(doc, *, written_by)             -> DocumentRecord
      put_claim(claim, *, written_by)              -> ClaimRecord
      verify_claim(claim_id, reviewer_id, role)    -> ClaimRecord | None
      reject_claim(claim_id, reviewer_id, role,
                   reason)                          -> ClaimRecord | None
      get_document(doc_id)                         -> DocumentRecord | None
      get_claim(claim_id)                          -> ClaimRecord | None
      list_documents(application_id, doc_type=None,
                     status=None)                  -> list[DocumentRecord]
      list_claims(application_id, field_name=None,
                  status=None, document_id=None)   -> list[ClaimRecord]
    """

    def __init__(self, store: LendingContextStore):
        self._store = store

    # ── Writes ───────────────────────────────────────────────────────

    async def put_document(
        self, document: DocumentRecord, *, written_by: str = "system"
    ) -> DocumentRecord:
        existing = await self._store.get(
            DOCUMENT_ENTITY_TYPE, document.document_id, None
        )
        new_value = document.model_dump(mode="json")
        if existing is not None and isinstance(existing.value, dict):
            if existing.value == new_value:
                return DocumentRecord.model_validate(existing.value)
        lineage = Lineage(
            decision_id=None,
            agent=written_by,
            written_by=written_by,
            confidence=1.0,
            notes="document upsert",
        )
        await self._store.set(
            DOCUMENT_ENTITY_TYPE, document.document_id, new_value, lineage
        )
        return document

    async def put_claim(
        self, claim: ClaimRecord, *, written_by: str = "system"
    ) -> ClaimRecord:
        existing = await self._store.get(
            CLAIM_ENTITY_TYPE, claim.claim_id, None
        )
        new_value = claim.model_dump(mode="json")
        if existing is not None and isinstance(existing.value, dict):
            if existing.value == new_value:
                return ClaimRecord.model_validate(existing.value)
        lineage = Lineage(
            decision_id=None,
            agent=written_by,
            written_by=written_by,
            confidence=claim.extraction_confidence,
            notes="claim upsert",
        )
        await self._store.set(
            CLAIM_ENTITY_TYPE, claim.claim_id, new_value, lineage
        )
        return claim

    async def verify_claim(
        self,
        claim_id: str,
        *,
        reviewer_id: str,
        reviewer_role: str,
    ) -> Optional[ClaimRecord]:
        existing = await self.get_claim(claim_id)
        if existing is None:
            return None
        updated = existing.model_copy(update={
            "status": "verified",
            "verified_at": datetime.utcnow(),
            "verified_by": f"{reviewer_role}:{reviewer_id}",
        })
        return await self.put_claim(updated, written_by=f"verify:{reviewer_id}")

    async def reject_claim(
        self,
        claim_id: str,
        *,
        reviewer_id: str,
        reviewer_role: str,
        reason: Optional[str] = None,
    ) -> Optional[ClaimRecord]:
        existing = await self.get_claim(claim_id)
        if existing is None:
            return None
        updated = existing.model_copy(update={
            "status": "rejected",
            "verified_at": datetime.utcnow(),
            "verified_by": f"{reviewer_role}:{reviewer_id}",
        })
        # Reason is captured on the lineage notes so the audit chain
        # carries the human's stated reason.
        lineage = Lineage(
            decision_id=None,
            agent=f"reject:{reviewer_id}",
            written_by=f"reject:{reviewer_id}",
            confidence=1.0,
            notes=f"claim rejected: {reason or 'no reason'}",
        )
        await self._store.set(
            CLAIM_ENTITY_TYPE,
            claim_id,
            updated.model_dump(mode="json"),
            lineage,
        )
        return updated

    # ── Reads ────────────────────────────────────────────────────────

    async def get_document(self, document_id: str) -> Optional[DocumentRecord]:
        rec = await self._store.get(DOCUMENT_ENTITY_TYPE, document_id, None)
        if rec is None or not isinstance(rec.value, dict):
            return None
        return DocumentRecord.model_validate(rec.value)

    async def get_claim(self, claim_id: str) -> Optional[ClaimRecord]:
        rec = await self._store.get(CLAIM_ENTITY_TYPE, claim_id, None)
        if rec is None or not isinstance(rec.value, dict):
            return None
        return ClaimRecord.model_validate(rec.value)

    async def list_documents(
        self,
        application_id: str,
        *,
        doc_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[DocumentRecord]:
        out: list[DocumentRecord] = []
        for value in self._iter_active_values(DOCUMENT_ENTITY_TYPE):
            try:
                d = DocumentRecord.model_validate(value)
            except Exception:
                continue
            if d.application_id != application_id:
                continue
            if doc_type is not None and d.doc_type != doc_type:
                continue
            if status is not None and d.status != status:
                continue
            out.append(d)
        return out

    async def list_claims(
        self,
        application_id: str,
        *,
        field_name: Optional[str] = None,
        status: Optional[str] = None,
        document_id: Optional[str] = None,
    ) -> list[ClaimRecord]:
        out: list[ClaimRecord] = []
        for value in self._iter_active_values(CLAIM_ENTITY_TYPE):
            try:
                c = ClaimRecord.model_validate(value)
            except Exception:
                continue
            if c.application_id != application_id:
                continue
            if field_name is not None and c.field_name != field_name:
                continue
            if status is not None and c.status != status:
                continue
            if document_id is not None and c.document_id != document_id:
                continue
            out.append(c)
        return out

    # ── Internal: walk active rows. Same pattern as PolicyStore /
    # api.deps._default_resolver. TODO postgres: replace with one SELECT.
    # ─────────────────────────────────────────────────────────────────

    def _iter_active_values(self, entity_type: str) -> list[dict[str, Any]]:
        durable = self._store._durable  # type: ignore[attr-defined]
        records = getattr(durable, "_records", None)
        if not isinstance(records, list):
            return []
        latest_by_id: dict[str, Any] = {}
        for rec in records:
            if rec.entity_type != entity_type:
                continue
            if rec.decision_id is not None:
                continue
            if rec.superseded_at is not None:
                continue
            current = latest_by_id.get(rec.entity_id)
            if current is None or rec.version > current.version:
                latest_by_id[rec.entity_id] = rec
        return [
            r.value for r in latest_by_id.values()
            if isinstance(r.value, dict)
        ]


__all__ = [
    "CLAIM_ENTITY_TYPE",
    "ClaimRecord",
    "DOCUMENT_ENTITY_TYPE",
    "DocumentRecord",
    "KnowledgeStore",
]
