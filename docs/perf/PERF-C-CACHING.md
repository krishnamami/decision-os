# PERF-C — Evidence-Graph Query Caching

> Implemented: `core/infra/cache.py` (`EvidenceCache`). In-memory TTL cache, no Redis
> dependency. **Standalone** — built + unit-ready, NOT wired into the live decision path
> (the wiring point is documented below). Decision-path-inert → 16/16 by construction.

---

## 1. What's Cached

The output of `ContextEnricher.evidence_facts(application_id, tenant_id, decision_id)` —
the RA-3B `evidence_*` / `ev_*` keys read from current `fact_nodes`. This is the same
data for a given application until its documents change.

**Cache key:** `(tenant_id, application_id, document_index_updated_at)`.

## 2. Invalidation Strategy

Two layers, primary + safety net:

1. **Document-timestamp keying (primary).** `document_index_updated_at` is part of the
   key. When a document is (re)ingested, `updated_at` advances → the key changes → the
   old entry is never read again (and is lazily evicted on its TTL). This means the cache
   is **automatically correct**: a changed document can never serve stale evidence.
2. **TTL (secondary safety net).** Default **300 s** — nothing lives forever even if a
   timestamp somehow doesn't advance.
3. **Explicit `invalidate(tenant_id, app_id)`** — removes all entries for an application
   (call on document upload for immediate eviction).

## 3. Expected Hit Rate + Latency Improvement

- **Meridian (and any stable tenant): high hit rate.** Documents are seeded fixtures and
  never change, so after the first load every `evidence_facts` call for an application is
  a hit — `document_index_updated_at` is constant.
- **Latency improvement:** an evidence load is one round-trip to the remote RDS
  (~140–560 ms observed, PERF-A). A cache hit is an **in-memory dict lookup (~microseconds)**
  — effectively removing that round-trip for repeat reads of the same application within
  the TTL. For workbench / replay / audit flows that re-read the same applications, this
  is the single largest available latency win short of in-VPC co-location.

## 4. Properties

- **In-memory dict, no Redis** — zero new infra dependency.
- **Thread-safe** under the asyncio single-event-loop model (a lock guards mutation).
- **Lazy eviction** on read (expired entries removed when next accessed).
- **RULE 11:** `get()` returns a `cache_hit` flag; `stats()` carries `data_source` +
  `missing_inputs` so any response built from cached evidence declares its provenance.

## 5. Wiring Point (documented, not wired)

`evidence_facts()` is called by the runner inside `_process_one`
(`core/cron/runner.py:340-362`) — the **live meridian 16/16 decision path**. Wrapping it
would risk the eval, so the cache ships standalone. To wire it (a future, gated slice):

```python
# inside ContextEnricher.evidence_facts(), before the fact_nodes query:
from core.infra.cache import get_evidence_cache
cache = get_evidence_cache()
doc_ts = await self._conn.fetchval(
    "SELECT MAX(updated_at) FROM document_index WHERE application_id=$1 AND tenant_id=$2",
    application_id, tenant_id)
cached, hit = cache.get(tenant_id, application_id, doc_ts)
if hit:
    return {**cached, "cache_hit": True}
result = await self._compute_evidence_facts(...)   # the existing body
cache.set(tenant_id, application_id, doc_ts, result)
return {**result, "cache_hit": False}
```

The `SELECT MAX(updated_at)` is itself a round-trip, so wiring is only a net win when the
key-fetch is cheaper than the full evidence query (it is — one indexed scalar vs the full
join), or when the timestamp is already in hand from the calling context. Validate
against a green 16/16 before enabling.

## 6. Redis Upgrade Path

`EvidenceCache`'s `get`/`set`/`invalidate` interface mirrors a Redis client. Swapping the
in-memory dict for Redis (shared across ECS tasks) is a backend change behind the same
interface — callers are untouched. Use Redis once there is more than one API task
(HA-B scale-out) so the cache is shared rather than per-task.

---

*PERF-C · `core/infra/cache.py` — TTL evidence cache (300s + doc-timestamp invalidation),
standalone with a documented wiring point.*
