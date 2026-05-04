from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Protocol
from uuid import UUID, uuid4

from .schema import (
    AccessRecord,
    AuditRecord,
    CheckStatus,
    ConsentStatus,
    DataClassification,
    EncryptionStatus,
    FairnessFlag,
    PolicyApplied,
)
from core.normalizer.models import DecisionMode, DecisionOutcome


SCHEMA_SQL_PATH = Path(__file__).resolve().parent / "schema.sql"


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


# ─────────────────────────────────────────────────────────────────────
# Postgres backend
#
# Mirrors the InMemory contract over a real database. The schema is
# managed via core/audit/schema.sql (PRD §23.6); init_schema applies it
# idempotently. Tests do NOT exercise this class — they run on
# InMemoryAuditStore — but the smoke runners can swap it in with one
# line once the cloud step starts (PRD STRATEGIC: TIER 1 real-backend
# verification).
# ─────────────────────────────────────────────────────────────────────


try:  # pragma: no cover — exercised at runtime, not in unit tests
    import asyncpg  # type: ignore
except ImportError:  # pragma: no cover
    asyncpg = None  # type: ignore


def _row_to_record(row: Any) -> AuditRecord:
    def _maybe_load(value: Any) -> Any:
        if isinstance(value, str):
            return json.loads(value)
        return value

    return AuditRecord(
        audit_id=row["audit_id"],
        decision_id=row["decision_id"],
        application_id=row["application_id"],
        decision_type=row["decision_type"],
        timestamp=row["timestamp"],
        supersedes_audit_id=row["supersedes_audit_id"],
        event_input=_maybe_load(row["event_input"]) or {},
        context_used=_maybe_load(row["context_used"]) or {},
        ontology_mapping=_maybe_load(row["ontology_mapping"]) or {},
        policy_applied=[
            PolicyApplied(**p) for p in (_maybe_load(row["policy_applied"]) or [])
        ],
        decision_output=DecisionOutcome(row["decision_output"]),
        confidence=row["confidence"],
        owner=row["owner"],
        mode=DecisionMode(row["mode"]),
        execution_result=_maybe_load(row["execution_result"]) or {},
        outcome=row["outcome"],
        regulation_tags=list(row["regulation_tags"] or []),
        consent_status=ConsentStatus(row["consent_status"]),
        data_sources_used=list(row["data_sources_used"] or []),
        disclosure_sent=row["disclosure_sent"],
        disclosure_timestamp=row["disclosure_timestamp"],
        retention_policy=row["retention_policy"],
        compliance_status=CheckStatus(row["compliance_status"]),
        accessed_by=[
            AccessRecord(**a) for a in (_maybe_load(row["accessed_by"]) or [])
        ],
        permissions_used=list(row["permissions_used"] or []),
        data_classification=DataClassification(row["data_classification"]),
        pii_fields_accessed=list(row["pii_fields_accessed"] or []),
        encryption_status=EncryptionStatus(row["encryption_status"]),
        access_anomaly=row["access_anomaly"],
        access_anomaly_reason=row["access_anomaly_reason"],
        security_status=CheckStatus(row["security_status"]),
        applicant_segment=row["applicant_segment"],
        protected_attrs_used=list(row["protected_attrs_used"] or []),
        protected_attrs_excluded=list(row["protected_attrs_excluded"] or []),
        fairness_flags=[
            FairnessFlag(**f) for f in (_maybe_load(row["fairness_flags"]) or [])
        ],
        bias_score=row["bias_score"],
        disparate_impact_flag=row["disparate_impact_flag"],
        human_reviewed=row["human_reviewed"],
        ethics_status=CheckStatus(row["ethics_status"]),
        fairness_status=CheckStatus(row["fairness_status"]),
        overall_status=CheckStatus(row["overall_status"]),
    )


class PostgresAuditStore:
    """asyncpg-backed AuditStore. Honours the same append-only +
    no-delete contract as InMemoryAuditStore. Production swap is one
    line in api/deps.build_default_platform()."""

    def __init__(self, pool: Any):
        if pool is None:
            raise ValueError("asyncpg pool is required")
        self._pool = pool

    @classmethod
    async def connect(
        cls, dsn: str, *, min_size: int = 1, max_size: int = 10
    ) -> "PostgresAuditStore":
        if asyncpg is None:
            raise ImportError(
                "asyncpg is not installed; `pip install asyncpg` "
                "or use InMemoryAuditStore for tests"
            )
        pool = await asyncpg.create_pool(
            dsn,
            min_size=min_size,
            max_size=max_size,
            init=cls._init_connection,
        )
        return cls(pool)

    @staticmethod
    async def _init_connection(conn: Any) -> None:
        await conn.set_type_codec(
            "jsonb",
            encoder=lambda v: v if isinstance(v, str) else json.dumps(v, default=str),
            decoder=json.loads,
            schema="pg_catalog",
        )

    async def aclose(self) -> None:
        await self._pool.close()

    async def init_schema(self) -> None:
        sql = SCHEMA_SQL_PATH.read_text(encoding="utf-8")
        async with self._pool.acquire() as conn:
            await conn.execute(sql)

    # ── Writes ───────────────────────────────────────────────────────

    async def write(self, record: AuditRecord) -> UUID:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                exists = await conn.fetchval(
                    "SELECT 1 FROM audit_records WHERE audit_id = $1",
                    record.audit_id,
                )
                if exists:
                    raise ValueError(
                        f"audit_id {record.audit_id} already written; "
                        f"audit_records is append-only (PRD §23.9)"
                    )
                await conn.execute(
                    """
                    INSERT INTO audit_records (
                        audit_id, decision_id, application_id, decision_type,
                        timestamp, supersedes_audit_id,
                        event_input, context_used, ontology_mapping,
                        policy_applied, decision_output, confidence, owner,
                        mode, execution_result, outcome,
                        regulation_tags, consent_status, data_sources_used,
                        disclosure_sent, disclosure_timestamp, retention_policy,
                        compliance_status,
                        accessed_by, permissions_used, data_classification,
                        pii_fields_accessed, encryption_status, access_anomaly,
                        access_anomaly_reason, security_status,
                        applicant_segment, protected_attrs_used,
                        protected_attrs_excluded, fairness_flags, bias_score,
                        disparate_impact_flag, human_reviewed, ethics_status,
                        fairness_status, overall_status
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6,
                        $7, $8, $9, $10, $11, $12, $13, $14, $15, $16,
                        $17, $18, $19, $20, $21, $22, $23,
                        $24, $25, $26, $27, $28, $29, $30, $31,
                        $32, $33, $34, $35, $36, $37, $38, $39, $40, $41
                    )
                    """,
                    record.audit_id,
                    record.decision_id,
                    record.application_id,
                    record.decision_type,
                    record.timestamp,
                    record.supersedes_audit_id,
                    record.event_input,
                    record.context_used,
                    record.ontology_mapping,
                    [p.model_dump() for p in record.policy_applied],
                    record.decision_output.value,
                    record.confidence,
                    record.owner,
                    record.mode.value,
                    record.execution_result,
                    record.outcome,
                    record.regulation_tags,
                    record.consent_status.value,
                    record.data_sources_used,
                    record.disclosure_sent,
                    record.disclosure_timestamp,
                    record.retention_policy,
                    record.compliance_status.value,
                    [a.model_dump() for a in record.accessed_by],
                    record.permissions_used,
                    record.data_classification.value,
                    record.pii_fields_accessed,
                    record.encryption_status.value,
                    record.access_anomaly,
                    record.access_anomaly_reason,
                    record.security_status.value,
                    record.applicant_segment,
                    record.protected_attrs_used,
                    record.protected_attrs_excluded,
                    [f.model_dump() for f in record.fairness_flags],
                    record.bias_score,
                    record.disparate_impact_flag,
                    record.human_reviewed,
                    record.ethics_status.value,
                    record.fairness_status.value,
                    record.overall_status.value,
                )
                # Mirror flags into audit_flags so compliance can clear
                # them independently of the immutable record body.
                if record.overall_status in (CheckStatus.WARN, CheckStatus.FAIL):
                    for check, status in (
                        ("compliance", record.compliance_status),
                        ("security",   record.security_status),
                        ("ethics",     record.ethics_status),
                        ("fairness",   record.fairness_status),
                    ):
                        if status in (CheckStatus.WARN, CheckStatus.FAIL):
                            await conn.execute(
                                """
                                INSERT INTO audit_flags
                                  (id, audit_id, severity, check_name, description)
                                VALUES ($1, $2, $3, $4, $5)
                                """,
                                uuid4(),
                                record.audit_id,
                                status.value,
                                check,
                                f"{check} {status.value} on {record.decision_type}",
                            )
        return record.audit_id

    # ── Reads ────────────────────────────────────────────────────────

    async def get(self, audit_id: UUID) -> Optional[AuditRecord]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM audit_records WHERE audit_id = $1",
                audit_id,
            )
        if row is None:
            return None
        await self._log_implicit_access(audit_id, action="read")
        return _row_to_record(row)

    async def list_for_application(self, application_id: str) -> list[AuditRecord]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM audit_records
                WHERE application_id = $1
                ORDER BY timestamp ASC
                """,
                application_id,
            )
        return [_row_to_record(r) for r in rows]

    async def list_flags(self) -> list[AuditRecord]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM audit_records
                WHERE overall_status IN ('warn', 'fail')
                ORDER BY timestamp DESC
                """
            )
        return [_row_to_record(r) for r in rows]

    async def log_access(self, audit_id: UUID, entry: AccessRecord) -> None:
        async with self._pool.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT 1 FROM audit_records WHERE audit_id = $1",
                audit_id,
            )
            if not exists:
                raise KeyError(f"audit_id {audit_id} not found")
            await conn.execute(
                """
                INSERT INTO audit_access_log
                  (id, audit_id, user_id, role, action, timestamp, ip_hash)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                uuid4(),
                audit_id,
                entry.user_id,
                entry.role,
                entry.action,
                entry.timestamp,
                entry.ip_hash,
            )

    async def access_log(self, audit_id: UUID) -> list[AccessRecord]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT user_id, role, action, timestamp, ip_hash
                FROM audit_access_log
                WHERE audit_id = $1
                ORDER BY timestamp ASC
                """,
                audit_id,
            )
        return [
            AccessRecord(
                user_id=r["user_id"],
                role=r["role"],
                action=r["action"],
                timestamp=r["timestamp"],
                ip_hash=r["ip_hash"],
            )
            for r in rows
        ]

    async def _log_implicit_access(self, audit_id: UUID, *, action: str) -> None:
        # System-level read trace. Production layers a real user_id /
        # role on top via the API authentication middleware (TIER 3).
        try:
            await self.log_access(
                audit_id,
                AccessRecord(
                    user_id="system",
                    role="system",
                    action=action,
                    timestamp=datetime.utcnow(),
                ),
            )
        except KeyError:
            pass
