# HA-E — Observability: Metrics, Logs, Alerts

> Builds on IN-C (`core/infra/pipeline_monitor.py` + `core/audit/alerts.py`). Adds
> decision-level metrics via `emit_decision_metrics()`. Graceful no-AWS throughout.

---

## 1. Metrics

Emitted through `CloudWatchMetricSink` (IN-C — injectable client, no-op without AWS).

| Metric | Namespace | Source | Status |
|---|---|---|---|
| `WatermarkAgeSeconds` | `Accord/Pipeline` | `evaluate_watermark` | **exists (IN-C)** |
| `DLQDepth` | `Accord/Pipeline` | `fetch_dlq_depth` | **exists (IN-C)** |
| `DecisionLatencyMs` | `Accord/Decisions` | `emit_decision_metrics` | **NEW (HA-E)** |
| `PersonaFailures` | `Accord/Decisions` | `emit_decision_metrics` | **NEW (HA-E)** |
| `ConnectionPoolSize` | `Accord/DB` | `emit_decision_metrics` | **NEW (HA-E)** |

```python
from core.infra.pipeline_monitor import emit_decision_metrics

emit_decision_metrics(
    outcome="recommend", latency_ms=842.0, persona_count=14,
    tenant_id="meridian", persona_failures=0, connection_pool_size=5,
)
# -> {"metrics_emitted": False (no AWS locally), "namespace": ["Accord/Decisions","Accord/DB"],
#     "dimensions": {"tenant_id":"meridian","outcome":"recommend"}, "metrics": {...}}
```

Dimensions: `tenant_id` + `outcome` on decision metrics; `tenant_id` on DB metrics.
Best-effort and non-blocking — safe to call from the decision path without risk of
raising or stalling a decision (the IN-C pattern). **Wiring the call into the runner's
per-decision path is the next decision-path-safe slice;** the function ships unit-ready.

## 2. Alarms

| Alarm | Condition | Severity | Action |
|---|---|---|---|
| Pipeline stalled | `WatermarkAgeSeconds > 900` | **Page** | HA-F RDB-002 |
| DLQ backing up | `DLQDepth > 10` | **Alert** | drain DLQ, fix root cause |
| Slow decisions | `DecisionLatencyMs > 5000` | **Warning** | investigate DB/persona latency |
| Persona failures | `PersonaFailures > 0` | **Page** | HA-F RDB-004 (critical) |

The 900s watermark threshold is the IN-C "15-minute mystery" alarm (`DEFAULT_STALLED_SEC`).

## 3. Structured Logs (JSON)

Every decision and every error logs a single structured line for ingestion (CloudWatch
Logs Insights / OpenSearch):

```json
// per decision
{"event": "decision", "tenant_id": "meridian", "application_id": "APP-001",
 "outcome": "recommend", "latency_ms": 842, "personas_run": 14}

// per error
{"event": "error", "level": "error", "service": "runner",
 "error_type": "ConnectionError", "trace_id": "..."}
```

## 4. Dashboard Layout (described, not built)

| Row | Widgets |
|---|---|
| 1 — Pipeline health | WatermarkAgeSeconds · DLQDepth · decisions/min |
| 2 — Decision outcomes | recommend / block / escalate rates (by tenant) |
| 3 — Latency | DecisionLatencyMs p50 / p95 / p99 |
| 4 — Errors + alerts | PersonaFailures · error rate · active alarms |

---

*HA-E · observability spec + `emit_decision_metrics()` (DecisionLatencyMs /
PersonaFailures / ConnectionPoolSize) on top of the IN-C CloudWatch sink.*
