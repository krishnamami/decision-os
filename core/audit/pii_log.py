"""Store-level PII access log — PRD §23.9 pii_access_always_logged.

Every read of a PII field anywhere in the pipeline writes here. The
ContextStore layer instruments LendingContextStore.get() so the log is
populated automatically — callers don't opt in per decision.

The security report aggregates from this log to produce the daily PII
access roll-up (PRD §23.7 Security access report).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# Canonical PII field names. Same set as security_checker.PII_FIELDS
# but redeclared here to avoid a hard dependency between the store and
# the checker module — both reference this constant. Keep them in sync.
PII_FIELDS: frozenset[str] = frozenset(
    {
        "ssn",
        "tax_id",
        "dob",
        "date_of_birth",
        "address_full",
        "bank_account",
        "routing_number",
        "drivers_license",
        # Lending-domain extensions — names + DOB qualify even when the
        # other fields aren't present.
        "first_name",
        "last_name",
    }
)


class PIIAccessEntry(BaseModel):
    """One row in the PII access log. Append-only; never deleted."""

    id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    entity_type: str
    entity_id: str
    application_id: Optional[str] = None
    pii_fields: list[str] = Field(default_factory=list)
    caller: Optional[str] = None
    action: str = "read"


class PIIAccessLog(Protocol):
    """Append-only log for PII reads."""

    async def record(self, entry: PIIAccessEntry) -> None: ...
    async def list_for_application(
        self, application_id: str
    ) -> list[PIIAccessEntry]: ...
    async def list_recent(self, limit: int = 100) -> list[PIIAccessEntry]: ...


class InMemoryPIIAccessLog:
    """Reference implementation. Postgres swap stores rows in
    audit_access_log with a NULL audit_id (system-wide access) — the
    schema already permits it."""

    def __init__(self) -> None:
        self._entries: list[PIIAccessEntry] = []

    async def record(self, entry: PIIAccessEntry) -> None:
        self._entries.append(entry)

    async def list_for_application(
        self, application_id: str
    ) -> list[PIIAccessEntry]:
        return [e for e in self._entries if e.application_id == application_id]

    async def list_recent(self, limit: int = 100) -> list[PIIAccessEntry]:
        return list(reversed(self._entries[-limit:]))

    def __len__(self) -> int:
        return len(self._entries)


def detect_pii_fields(value: dict | None) -> list[str]:
    """Return PII field names found in the entity's value blob."""

    if not isinstance(value, dict):
        return []
    return sorted(k for k in value.keys() if k in PII_FIELDS)


__all__ = [
    "InMemoryPIIAccessLog",
    "PII_FIELDS",
    "PIIAccessEntry",
    "PIIAccessLog",
    "detect_pii_fields",
]
