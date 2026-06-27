# PERF-B — Database Query Optimization

> Implemented: `scripts/perf/index_audit.py` (`IndexAuditor`). Read-only by default;
> `--create` runs `CREATE INDEX CONCURRENTLY`. Verified against live RDS 2026-06-27.

---

## 1. Current Index Coverage (verified)

The hot tables are **already heavily indexed** — 42 indexes across the 5 hot tables:

| Table | Rows | Notable indexes |
|---|---|---|
| `decision_outputs` | ~142k | `(application_id, decision_id, version, tenant_id)` unique · `(tenant_id)` · `(application_id)` · `(decision_id, outcome)` · pending-human partial · bundle |
| `entity_states` | ~8.9k | PK `(application_id)` · `(tenant_id)` · score/dti/ltv/status/completeness |
| `fact_nodes` | 77 | `(application_id, tenant_id)` · `(application_id, tenant_id, fact_type)` partial |
| `document_index` | ~263k | `(tenant_id)` · `(document_type, status)` · GIN on `extracted_fields` · many doc-type partials |
| `persona_bundles` | ~7.2k | current/history/version uniques |

**Spec correction:** the prompt's suggested `decision_outputs (tenant_id, persona_id)`
references a column that does not exist — the persona key is **`decision_id`**. The
auditor recommends `(tenant_id, decision_id)` instead. And `fact_nodes (application_id,
tenant_id)` is **already present** (`idx_fact_nodes_app`) — the auditor detects this and
does not re-recommend it.

## 2. EXPLAIN ANALYZE — Top 3 Hot Views

| View | Actual execution | Uses index? |
|---|---|---|
| `vw_compliance_check_context` | **2.55 ms** | ✅ |
| `vw_credit_assessment_context` | **3.18 ms** | ✅ |
| `vw_income_verification_context` | **2.65 ms** | ✅ |

> The single most important finding: **in-DB query execution is ~3 ms and every hot view
> already uses an index scan.** The 140–560 ms wall-clock latency observed in PERF-A is
> **network round-trip to the remote RDS**, not query planning. Indexes are not the
> bottleneck; co-locating ECS + RDS in-VPC (HA-A) is the real win.

## 3. Recommended Indexes (genuine gaps only)

The auditor flags 4 composite indexes not covered by an existing ordered-prefix index.
All are **low-risk additive** (no behavior change) and **marginal** given the RTT-bound
reality — recommended for when query volume grows, not urgent today:

```sql
-- per-tenant per-persona scans (decision_id IS the persona key; no persona_id column)
CREATE INDEX CONCURRENTLY idx_decision_outputs_tenant_id_decision_id
  ON decision_outputs (tenant_id, decision_id);

-- per-tenant per-application lookup
CREATE INDEX CONCURRENTLY idx_decision_outputs_tenant_id_application_id
  ON decision_outputs (tenant_id, application_id);

-- tenant-scoped join key (PK is application_id alone)
CREATE INDEX CONCURRENTLY idx_entity_states_tenant_id_application_id
  ON entity_states (tenant_id, application_id);

-- LAR / extraction scans by tenant + doc type
CREATE INDEX CONCURRENTLY idx_document_index_tenant_id_document_type
  ON document_index (tenant_id, document_type);
```

`CONCURRENTLY` avoids a table lock. Run via `python scripts/perf/index_audit.py --create`
(dry-run is the default — it prints the DDL without executing).

## 4. Partition Strategy (future scale, documented not implemented)

| Tables | Strategy | Trigger |
|---|---|---|
| `decision_trace`, `decision_audit_log` | RANGE partition by month on `(tenant_id, created_at)` | when a table exceeds **~10M rows** |

Current row counts (decision_outputs ~142k, document_index ~263k) are **far below** the
trigger, so partitioning is not implemented. When triggered, monthly partitions make
retention pruning (HA-D / DOC-D) cheap — old partitions drop wholesale at the retention
boundary instead of a row-by-row `DELETE`.

---

*PERF-B · `scripts/perf/index_audit.py` — index coverage audit + EXPLAIN ANALYZE +
gap DDL + partition strategy.*
