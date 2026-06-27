"""PERF-C — TTL cache for evidence-graph queries.

A small in-memory TTL cache for ``ContextEnricher.evidence_facts()`` results, keyed by
``(tenant_id, application_id, document_index_updated_at)``. The doc-timestamp in the key
is the PRIMARY invalidation mechanism: when a document changes, ``updated_at`` advances,
the key changes, and the stale entry is never read again. The TTL (default 300s) is a
secondary safety net so nothing lives forever.

In-memory only (dict) — NO Redis dependency. Single-event-loop / asyncio assumption: a
lock guards mutation so it is safe under cooperative concurrency. The interface mirrors
a Redis client (get/set/invalidate) so a Redis backend can be swapped in later without
touching callers.

RULE 11: ``get()`` returns a ``cache_hit`` flag and ``stats()`` carries
``data_source`` + ``missing_inputs`` so any response built from cached evidence can
declare its provenance.

WIRING STATUS — STANDALONE (not wired into the live decision path). ``evidence_facts()``
is called by the runner inside ``_process_one`` (runner.py:340-362); wrapping it would
touch the meridian 16/16 path. So this ships built + unit-ready, with the exact wiring
point documented in ``docs/perf/PERF-C-CACHING.md``. Decision-path-inert by construction.
"""
from __future__ import annotations

import threading
import time as _time
from typing import Any, Callable, Optional

DEFAULT_TTL_SECONDS = 300   # 5-minute safety-net TTL (invalidation is the real mechanism)


class EvidenceCache:
    """TTL cache for evidence_facts() output, invalidated on document change."""

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS,
                 now_fn: Optional[Callable[[], float]] = None):
        self._store: dict[str, tuple[Any, float]] = {}   # key -> (value, expires_at)
        self._ttl = ttl_seconds
        self._now = now_fn or _time.monotonic
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def _key(self, tenant_id: str, app_id: str, doc_updated_at: Any) -> str:
        # doc_updated_at advancing is what invalidates the entry (its value is in the key).
        return f"{tenant_id}:{app_id}:{doc_updated_at}"

    def get(self, tenant_id: str, app_id: str, doc_updated_at: Any) -> tuple[Any, bool]:
        """Returns (value, cache_hit). (None, False) on miss or expiry."""
        key = self._key(tenant_id, app_id, doc_updated_at)
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None, False
            value, expires_at = entry
            if self._now() >= expires_at:
                del self._store[key]            # lazy eviction on read
                self._misses += 1
                return None, False
            self._hits += 1
            return value, True

    def set(self, tenant_id: str, app_id: str, doc_updated_at: Any, value: Any) -> None:
        key = self._key(tenant_id, app_id, doc_updated_at)
        with self._lock:
            self._store[key] = (value, self._now() + self._ttl)

    def invalidate(self, tenant_id: str, app_id: str) -> int:
        """Remove ALL entries for an application (document changed). Returns count removed."""
        prefix = f"{tenant_id}:{app_id}:"
        with self._lock:
            doomed = [k for k in self._store if k.startswith(prefix)]
            for k in doomed:
                del self._store[k]
            return len(doomed)

    def stats(self) -> dict:
        """Hit/miss/size + RULE 11 provenance."""
        with self._lock:
            total = self._hits + self._misses
            return {
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / total, 4) if total else None,
                "size": len(self._store),
                "ttl_seconds": self._ttl,
                "backend": "in_memory_dict",
                "data_source": "EvidenceCache (in-memory; key = tenant:app:doc_updated_at)",
                "missing_inputs": ([] if total else
                                   ["no cache traffic yet — hit_rate unavailable"]),
            }

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


# Process-wide singleton (callers share one cache).
_EVIDENCE_CACHE: Optional[EvidenceCache] = None


def get_evidence_cache(ttl_seconds: int = DEFAULT_TTL_SECONDS) -> EvidenceCache:
    global _EVIDENCE_CACHE
    if _EVIDENCE_CACHE is None:
        _EVIDENCE_CACHE = EvidenceCache(ttl_seconds=ttl_seconds)
    return _EVIDENCE_CACHE


__all__ = ["EvidenceCache", "get_evidence_cache", "DEFAULT_TTL_SECONDS"]
