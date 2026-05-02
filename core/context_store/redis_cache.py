from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from .base import ContextRecord


# ─────────────────────────────────────────────────────────────────────
# Hot cache implementations of the lending._HotProtocol shape.
#
# Two backends:
#   - RedisHotCache:    real Redis via `redis.asyncio` — production path.
#   - InMemoryHotCache: dict-backed, asyncio.Lock-guarded — tests and
#                       single-process dev. Same surface, same TTL semantics.
#
# Records are serialized via ContextRecord.model_dump_json() so datetimes,
# UUIDs, and nested lineage round-trip cleanly. The decoder uses
# model_validate_json() — no custom JSON shape.
# ─────────────────────────────────────────────────────────────────────


_KEY_SEPARATOR = ":"
_SHARED_SCOPE = "_shared"


def _key(prefix: str, entity_type: str, entity_id: str, decision_id: Optional[str]) -> str:
    scope = decision_id or _SHARED_SCOPE
    return f"{prefix}{_KEY_SEPARATOR}{entity_type}{_KEY_SEPARATOR}{entity_id}{_KEY_SEPARATOR}{scope}"


# ─────────────────────────────────────────────────────────────────────
# Redis-backed hot cache
# ─────────────────────────────────────────────────────────────────────

try:  # pragma: no cover — import guard, exercised at runtime not in tests
    import redis.asyncio as _redis_async  # type: ignore
except ImportError:  # pragma: no cover
    _redis_async = None  # type: ignore


class RedisHotCache:
    """Hot cache backed by Redis via the async client.

    A leaky key in one decision must not return bytes from another
    decision — the key is namespaced by ``(entity_type, entity_id,
    decision_id)``. Shared (decision-less) writes use the ``_shared``
    scope so they cannot collide with a real decision id."""

    def __init__(self, client: Any, *, key_prefix: str = "context"):
        if client is None:
            raise ValueError("redis client is required")
        self._client = client
        self._key_prefix = key_prefix

    @classmethod
    def from_url(cls, url: str, *, key_prefix: str = "context", **kwargs: Any) -> "RedisHotCache":
        if _redis_async is None:
            raise ImportError(
                "redis package is not installed; `pip install redis>=5` "
                "or use InMemoryHotCache for tests"
            )
        client = _redis_async.from_url(url, decode_responses=True, **kwargs)
        return cls(client, key_prefix=key_prefix)

    def _make_key(self, entity_type: str, entity_id: str, decision_id: Optional[str]) -> str:
        return _key(self._key_prefix, entity_type, entity_id, decision_id)

    async def get(
        self,
        entity_type: str,
        entity_id: str,
        decision_id: Optional[str],
    ) -> Optional[ContextRecord]:
        raw = await self._client.get(self._make_key(entity_type, entity_id, decision_id))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return ContextRecord.model_validate_json(raw)

    async def set(self, record: ContextRecord, ttl_seconds: int) -> None:
        key = self._make_key(record.entity_type, record.entity_id, record.decision_id)
        payload = record.model_dump_json()
        if ttl_seconds and ttl_seconds > 0:
            await self._client.setex(key, ttl_seconds, payload)
        else:
            await self._client.set(key, payload)

    async def invalidate(
        self,
        entity_type: str,
        entity_id: str,
        decision_id: Optional[str],
    ) -> None:
        await self._client.delete(self._make_key(entity_type, entity_id, decision_id))

    async def aclose(self) -> None:
        close = getattr(self._client, "aclose", None) or getattr(self._client, "close", None)
        if close is None:
            return
        result = close()
        if asyncio.iscoroutine(result):
            await result


# ─────────────────────────────────────────────────────────────────────
# In-memory hot cache — tests and single-process dev
# ─────────────────────────────────────────────────────────────────────


class InMemoryHotCache:
    """Asyncio-safe in-memory hot cache with TTL semantics.

    Behaviorally a stand-in for RedisHotCache. Stored payload is the
    serialized JSON string so round-tripping matches the Redis path
    byte-for-byte — catches model/lineage drift in tests."""

    def __init__(self, *, key_prefix: str = "context"):
        self._key_prefix = key_prefix
        self._store: dict[str, tuple[str, Optional[float]]] = {}
        self._lock = asyncio.Lock()

    def _make_key(self, entity_type: str, entity_id: str, decision_id: Optional[str]) -> str:
        return _key(self._key_prefix, entity_type, entity_id, decision_id)

    async def get(
        self,
        entity_type: str,
        entity_id: str,
        decision_id: Optional[str],
    ) -> Optional[ContextRecord]:
        async with self._lock:
            entry = self._store.get(self._make_key(entity_type, entity_id, decision_id))
            if entry is None:
                return None
            payload, expires_at = entry
            if expires_at is not None and time.monotonic() >= expires_at:
                self._store.pop(self._make_key(entity_type, entity_id, decision_id), None)
                return None
        return ContextRecord.model_validate_json(payload)

    async def set(self, record: ContextRecord, ttl_seconds: int) -> None:
        payload = record.model_dump_json()
        expires_at = time.monotonic() + ttl_seconds if ttl_seconds and ttl_seconds > 0 else None
        async with self._lock:
            self._store[self._make_key(
                record.entity_type, record.entity_id, record.decision_id
            )] = (payload, expires_at)

    async def invalidate(
        self,
        entity_type: str,
        entity_id: str,
        decision_id: Optional[str],
    ) -> None:
        async with self._lock:
            self._store.pop(self._make_key(entity_type, entity_id, decision_id), None)

    async def aclose(self) -> None:
        async with self._lock:
            self._store.clear()
