from __future__ import annotations

from typing import Optional, Protocol
from uuid import UUID

from .schema import AccessRecord, AuditRecord, CheckStatus


class AuditStore(Protocol):
    """Append-only persistence for AuditRecords. PRD §23.6 + §23.9.

    Implementations must enforce:
      - audit_records is append-only — write rejects a duplicate
        audit_id and never modifies an existing row. Corrections come
        in as new rows with supersedes_audit_id pointing at the
        previous record.
      - audit_access_log captures every read of an audit record (the
        record itself, not the underlying decision) so we can audit
        the audit. PRD §23.9 pii_access_always_logged extends this to
        the broader pipeline.
      - audit_flags stores active warn / fail records until cleared
        by compliance.
    """

    async def write(self, record: AuditRecord) -> UUID: ...
    async def get(self, audit_id: UUID) -> Optional[AuditRecord]: ...
    async def list_for_application(self, application_id: str) -> list[AuditRecord]: ...
    async def list_flags(self) -> list[AuditRecord]: ...
    async def log_access(self, audit_id: UUID, entry: AccessRecord) -> None: ...
    async def access_log(self, audit_id: UUID) -> list[AccessRecord]: ...


class InMemoryAuditStore:
    """Reference implementation. Postgres swap implements the same
    contract; the in-memory version exists to exercise the invariants
    in tests and to keep the smoke scripts self-contained."""

    def __init__(self) -> None:
        self._records: dict[UUID, AuditRecord] = {}
        self._access: dict[UUID, list[AccessRecord]] = {}

    async def write(self, record: AuditRecord) -> UUID:
        if record.audit_id in self._records:
            raise ValueError(
                f"audit_id {record.audit_id} already written; "
                f"audit_records is append-only (PRD §23.9)"
            )
        self._records[record.audit_id] = record
        return record.audit_id

    async def get(self, audit_id: UUID) -> Optional[AuditRecord]:
        return self._records.get(audit_id)

    async def list_for_application(self, application_id: str) -> list[AuditRecord]:
        return [
            r for r in self._records.values()
            if r.application_id == application_id
        ]

    async def list_flags(self) -> list[AuditRecord]:
        return [
            r for r in self._records.values()
            if r.overall_status in (CheckStatus.WARN, CheckStatus.FAIL)
        ]

    async def log_access(self, audit_id: UUID, entry: AccessRecord) -> None:
        if audit_id not in self._records:
            raise KeyError(f"audit_id {audit_id} not found")
        self._access.setdefault(audit_id, []).append(entry)

    async def access_log(self, audit_id: UUID) -> list[AccessRecord]:
        return list(self._access.get(audit_id, ()))

    def __len__(self) -> int:
        return len(self._records)
