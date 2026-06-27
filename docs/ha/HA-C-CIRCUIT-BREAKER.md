# HA-C — Circuit Breaker + Graceful Degradation

> Implemented: `core/infra/circuit_breaker.py` (pure Python, injectable clock).
> Decision-path-inert — wraps external I/O only; no persona imports it.

---

## 1. Why

Accord's core decision path is **synchronous and dependency-free** (RULE 5/6). The only
external calls are at the edges: Claude Vision (document extraction), S3 (object
storage), and SQS (event ingestion). Each ALREADY has a graceful-no-AWS fallback. The
circuit breaker makes that fallback **fast and automatic**: instead of every request
waiting on (and timing out against) a dead dependency, the circuit trips OPEN and calls
short-circuit immediately to the degraded path.

## 2. States + Thresholds

```
            5 failures / 60s
   CLOSED ───────────────────────▶ OPEN
     ▲                               │ 30s cooldown
     │ trial succeeds                ▼
     └──────────────────────── HALF_OPEN
            trial fails ──▶ OPEN
```

| State | Behavior |
|---|---|
| **CLOSED** | Normal. Calls pass through; failures counted in a rolling 60s window. |
| **OPEN** | Tripped after **5 failures in 60s**. Calls raise `CircuitOpenError` immediately (no dependency wait). |
| **HALF_OPEN** | After a **30s cooldown**, one trial call is allowed. Success → CLOSED; failure → OPEN. |

All three thresholds are constructor args (`failure_threshold`, `window_sec`,
`cooldown_sec`); the clock is injectable (`now_fn`) for deterministic tests.

## 3. Where It Applies + the Degradation Path

| Breaker | Dependency | When OPEN, degrade to |
|---|---|---|
| `claude_api` | Claude Vision extraction | **rule-based path** — pdfplumber + regex (RA-EX-F) already extract without Claude |
| `s3_upload` | S3 object storage | **queue locally / skip the put** — `s3_client` already no-ops without AWS (RA-P0-A); extraction unaffected |
| `sqs_send` | SQS event ingestion | **synchronous inline processing** — the pipeline already runs without SQS (IN-A) |

Every degraded path is an existing, tested code path. OPEN is therefore **safe by
construction** — the platform keeps making decisions; only the optional enhancement
(Vision accuracy, async durability) is temporarily skipped.

## 4. Usage

```python
from core.infra.circuit_breaker import get_breaker, CircuitOpenError, degradation_for

breaker = get_breaker("claude_api")          # process-wide, created on first use
try:
    fields = breaker.call(claude_vision_extract, document_bytes)
    extraction_method = "vision"
except CircuitOpenError:
    fields = regex_extract(document_text)    # documented degraded path
    extraction_method = "regex_fallback"

# RULE 11 — embed circuit provenance in the response
result = {
    "fields": fields,
    "extraction_method": extraction_method,
    "circuit": breaker.snapshot(),           # {state, failure_count, retry_after_sec, ...}
}
```

`breaker.snapshot()` is the RULE 11 provenance hook: any response that used a guarded
external call carries the circuit state (state + failure_count + retry_after_sec + the
degradation applied), the same way resolver outputs carry `data_source` /
`missing_inputs`.

## 5. Properties

- **Pure Python, no external deps** — importable anywhere, no AWS.
- **Thread-safe** — a simple lock (these calls are I/O-bound, not a hot path).
- **Injectable clock** — `now_fn` makes OPEN→HALF_OPEN transitions deterministic in
  tests (no sleeps, no wall-clock flakiness).
- **Wiring is a follow-up.** The breaker is built and unit-ready; wrapping the actual
  Claude/S3/SQS call sites with it is the next, decision-path-safe slice.

---

*HA-C · `core/infra/circuit_breaker.py` — CLOSED/OPEN/HALF_OPEN with documented
graceful degradation per dependency.*
