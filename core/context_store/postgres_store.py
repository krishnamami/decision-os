from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from uuid import UUID, uuid4

from .base import ContextRecord, Lineage, Snapshot


# ─────────────────────────────────────────────────────────────────────
# Durable store implementations of the lending._DurableProtocol shape.
#
# Two backends:
#   - PostgresDurableStore: real Postgres via asyncpg — production path.
#   - InMemoryDurableStore: list-backed, asyncio.Lock-guarded — same
#                           append-only semantics, used in tests and
#                           single-process dev so unit tests don't need
#                           a running database.
#
# Both honour the same invariants:
#   - append-only: insert_record never UPDATEs an existing row's value
#     or lineage; supersession sets superseded_at + superseded_by on
#     the prior active row and writes a new versioned row.
#   - tombstone() inserts a tombstone row (tombstoned_at NOT NULL) and
#     supersedes the active row in the same transaction. Tombstone rows
#     are themselves marked superseded so they are never returned as
#     "active" by get_latest / get_at_time.
#   - lineage is required on every write; enforced by ContextStore base.
# ─────────────────────────────────────────────────────────────────────


SCHEMA_SQL_PATH = Path(__file__).resolve().parent / "schema.sql"


# ─────────────────────────────────────────────────────────────────────
# Postgres backend
# ─────────────────────────────────────────────────────────────────────

try:  # pragma: no cover — exercised at runtime, not in unit tests
    import asyncpg  # type: ignore
except ImportError:  # pragma: no cover
    asyncpg = None  # type: ignore


def _row_to_record(row: Any) -> ContextRecord:
    lineage_blob = row["lineage"]
    if isinstance(lineage_blob, str):
        lineage_blob = json.loads(lineage_blob)
    value_blob = row["value"]
    if isinstance(value_blob, str):
        value_blob = json.loads(value_blob)
    return ContextRecord(
        id=row["id"],
        entity_type=row["entity_type"],
        entity_id=row["entity_id"],
        decision_id=row["decision_id"],
        version=row["version"],
        value=value_blob,
        lineage=Lineage.model_validate(lineage_blob),
        superseded_at=row["superseded_at"],
        superseded_by=row["superseded_by"],
    )


class PostgresDurableStore:
    """Append-only versioned record store on Postgres."""

    def __init__(self, pool: Any):
        if pool is None:
            raise ValueError("asyncpg pool is required")
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str, *, min_size: int = 1, max_size: int = 10) -> "PostgresDurableStore":
        if asyncpg is None:
            raise ImportError(
                "asyncpg is not installed; `pip install asyncpg` "
                "or use InMemoryDurableStore for tests"
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
        # JSONB codec — let asyncpg accept Python dicts/lists directly and
        # decode JSONB back into Python objects without a manual loads().
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

    async def insert_record(self, record: ContextRecord) -> ContextRecord:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                prev = await conn.fetchrow(
                    """
                    SELECT id, version FROM context_records
                    WHERE entity_type = $1 AND entity_id = $2
                      AND decision_id IS NOT DISTINCT FROM $3
                      AND superseded_at IS NULL
                      AND tombstoned_at IS NULL
                    ORDER BY version DESC LIMIT 1
                    """,
                    record.entity_type,
                    record.entity_id,
                    record.decision_id,
                )

                if prev is not None:
                    new_version = prev["version"] + 1
                    record = record.model_copy(update={"version": new_version})
                    await conn.execute(
                        """
                        UPDATE context_records
                        SET superseded_at = now(), superseded_by = $1
                        WHERE id = $2
                        """,
                        record.id,
                        prev["id"],
                    )
                else:
                    record = record.model_copy(update={"version": 1})

                await conn.execute(
                    """
                    INSERT INTO context_records (
                        id, entity_type, entity_id, decision_id,
                        version, value, lineage,
                        superseded_at, superseded_by, tombstoned_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, NULL, NULL, NULL)
                    """,
                    record.id,
                    record.entity_type,
                    record.entity_id,
                    record.decision_id,
                    record.version,
                    record.value,
                    record.lineage.model_dump(mode="json"),
                )
        return record

    async def tombstone(
        self,
        entity_type: str,
        entity_id: str,
        decision_id: Optional[str],
        lineage: Lineage,
    ) -> int:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                prev = await conn.fetchrow(
                    """
                    SELECT id, version FROM context_records
                    WHERE entity_type = $1 AND entity_id = $2
                      AND decision_id IS NOT DISTINCT FROM $3
                      AND superseded_at IS NULL
                      AND tombstoned_at IS NULL
                    ORDER BY version DESC LIMIT 1
                    """,
                    entity_type,
                    entity_id,
                    decision_id,
                )
                if prev is None:
                    return 0

                tomb_id = uuid4()
                # Tombstone is itself superseded at insert time so it's
                # never returned as the active row.
                await conn.execute(
                    """
                    UPDATE context_records
                    SET superseded_at = now(), superseded_by = $1
                    WHERE id = $2
                    """,
                    tomb_id,
                    prev["id"],
                )
                await conn.execute(
                    """
                    INSERT INTO context_records (
                        id, entity_type, entity_id, decision_id,
                        version, value, lineage,
                        superseded_at, superseded_by, tombstoned_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, now(), NULL, now())
                    """,
                    tomb_id,
                    entity_type,
                    entity_id,
                    decision_id,
                    prev["version"] + 1,
                    {},
                    lineage.model_dump(mode="json"),
                )
        return 1

    async def insert_snapshot(self, snapshot: Snapshot) -> Snapshot:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO context_snapshots (
                    id, application_id, decision_id, snapshot_at,
                    context, record_ids, upstream_decision_ids
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                snapshot.id,
                snapshot.application_id,
                snapshot.decision_id,
                snapshot.snapshot_at,
                snapshot.context,
                list(snapshot.record_ids),
                list(snapshot.upstream_decision_ids),
            )
        return snapshot

    # ── Reads ────────────────────────────────────────────────────────

    async def get_latest(
        self,
        entity_type: str,
        entity_id: str,
        decision_id: Optional[str],
    ) -> Optional[ContextRecord]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM context_records
                WHERE entity_type = $1 AND entity_id = $2
                  AND decision_id IS NOT DISTINCT FROM $3
                  AND superseded_at IS NULL
                  AND tombstoned_at IS NULL
                ORDER BY version DESC LIMIT 1
                """,
                entity_type,
                entity_id,
                decision_id,
            )
        return _row_to_record(row) if row is not None else None

    async def get_at_time(
        self,
        entity_type: str,
        entity_id: str,
        decision_id: Optional[str],
        at: datetime,
    ) -> Optional[ContextRecord]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM context_records
                WHERE entity_type = $1 AND entity_id = $2
                  AND decision_id IS NOT DISTINCT FROM $3
                  AND created_at <= $4
                  AND (superseded_at IS NULL OR superseded_at > $4)
                  AND tombstoned_at IS NULL
                ORDER BY version DESC LIMIT 1
                """,
                entity_type,
                entity_id,
                decision_id,
                at,
            )
        return _row_to_record(row) if row is not None else None

    async def history(
        self,
        entity_type: str,
        entity_id: str,
        decision_id: Optional[str],
        limit: int,
    ) -> list[ContextRecord]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM context_records
                WHERE entity_type = $1 AND entity_id = $2
                  AND decision_id IS NOT DISTINCT FROM $3
                ORDER BY version DESC
                LIMIT $4
                """,
                entity_type,
                entity_id,
                decision_id,
                limit,
            )
        return [_row_to_record(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────
# In-memory durable store — tests, dev
# ─────────────────────────────────────────────────────────────────────


class InMemoryDurableStore:
    """Same append-only contract as PostgresDurableStore, backed by a list.

    Useful for unit tests so test runs don't require a live database.
    Round-trips through Pydantic JSON the same way the Postgres path
    will, so model drift surfaces in the tests without requiring a DB."""

    def __init__(self) -> None:
        self._records: list[ContextRecord] = []
        self._snapshots: list[Snapshot] = []
        self._tombstones: set[UUID] = set()
        self._lock = asyncio.Lock()

    def _scope_match(
        self,
        rec: ContextRecord,
        entity_type: str,
        entity_id: str,
        decision_id: Optional[str],
    ) -> bool:
        return (
            rec.entity_type == entity_type
            and rec.entity_id == entity_id
            and rec.decision_id == decision_id
        )

    async def insert_record(self, record: ContextRecord) -> ContextRecord:
        async with self._lock:
            prev = self._latest_unlocked(record.entity_type, record.entity_id, record.decision_id)
            if prev is not None:
                new_version = prev.version + 1
                record = record.model_copy(update={"version": new_version})
                idx = self._records.index(prev)
                self._records[idx] = prev.model_copy(update={
                    "superseded_at": datetime.utcnow(),
                    "superseded_by": record.id,
                })
            else:
                record = record.model_copy(update={"version": 1})
            # Round-trip through JSON so failures here mirror the Postgres path.
            stored = ContextRecord.model_validate_json(record.model_dump_json())
            self._records.append(stored)
            return stored

    async def tombstone(
        self,
        entity_type: str,
        entity_id: str,
        decision_id: Optional[str],
        lineage: Lineage,
    ) -> int:
        async with self._lock:
            prev = self._latest_unlocked(entity_type, entity_id, decision_id)
            if prev is None:
                return 0
            tomb_id = uuid4()
            now = datetime.utcnow()
            # Tombstone is itself superseded at insert so it never appears
            # active — a single predicate (superseded_at IS NULL) suffices
            # for both writes and tombstones.
            tombstone = ContextRecord(
                id=tomb_id,
                entity_type=entity_type,
                entity_id=entity_id,
                decision_id=decision_id,
                version=prev.version + 1,
                value={},
                lineage=lineage,
                superseded_at=now,
            )
            idx = self._records.index(prev)
            self._records[idx] = prev.model_copy(update={
                "superseded_at": now,
                "superseded_by": tomb_id,
            })
            self._records.append(tombstone)
            self._tombstones.add(tomb_id)
            return 1

    async def insert_snapshot(self, snapshot: Snapshot) -> Snapshot:
        async with self._lock:
            stored = Snapshot.model_validate_json(snapshot.model_dump_json())
            self._snapshots.append(stored)
            return stored

    async def get_latest(
        self,
        entity_type: str,
        entity_id: str,
        decision_id: Optional[str],
    ) -> Optional[ContextRecord]:
        async with self._lock:
            return self._latest_unlocked(entity_type, entity_id, decision_id)

    def _latest_unlocked(
        self,
        entity_type: str,
        entity_id: str,
        decision_id: Optional[str],
    ) -> Optional[ContextRecord]:
        candidates = [
            r for r in self._records
            if self._scope_match(r, entity_type, entity_id, decision_id)
            and r.superseded_at is None
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda r: r.version)

    async def get_at_time(
        self,
        entity_type: str,
        entity_id: str,
        decision_id: Optional[str],
        at: datetime,
    ) -> Optional[ContextRecord]:
        async with self._lock:
            candidates = [
                r for r in self._records
                if self._scope_match(r, entity_type, entity_id, decision_id)
                and r.id not in self._tombstones
                and r.lineage.written_at <= at
                and (r.superseded_at is None or r.superseded_at > at)
            ]
            if not candidates:
                return None
            return max(candidates, key=lambda r: r.version)

    async def history(
        self,
        entity_type: str,
        entity_id: str,
        decision_id: Optional[str],
        limit: int,
    ) -> list[ContextRecord]:
        async with self._lock:
            rows = [
                r for r in self._records
                if self._scope_match(r, entity_type, entity_id, decision_id)
            ]
        rows.sort(key=lambda r: r.version, reverse=True)
        return rows[:limit]

    async def aclose(self) -> None:
        async with self._lock:
            self._records.clear()
            self._snapshots.clear()
            self._tombstones.clear()
