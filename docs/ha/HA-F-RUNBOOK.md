# HA-F — Runbook + Incident Response

> Operational runbook referencing HA-A through HA-E and the real platform components.
> Endpoint paths are the live ones (`/api/accord/...`). Keep this current as the system
> changes.

---

## Incident Severity Tiers

| Tier | Definition | Response |
|---|---|---|
| **SEV-1** | All decisions failing · RDS down · data-loss risk | **Page on-call immediately · 5-min response SLA** |
| **SEV-2** | Pipeline stalled · DLQ backing up · partial degradation | Alert on-call · **30-min response SLA** |
| **SEV-3** | Performance degraded · non-critical errors | Ticket · next business day |

---

## RDB-001 — RDS Connection Failure  *(SEV-1)*

**Symptoms:** `decision_outputs` writes failing; `GET /api/accord/health/deep` →
`db_latency_ms: null`, `status: degraded`.

1. Check RDS Multi-AZ failover status (AWS Console → RDS → `accord-prod` → Events).
2. Confirm `DATABASE_URL` points at the **cluster/writer endpoint**, not an instance
   address (HA-A §3) — an instance address does not survive failover.
3. Test connectivity:
   `python -c "import asyncio,asyncpg,os; asyncio.run(asyncpg.connect(os.environ['DATABASE_URL']))"`
4. If a failover is in progress: **wait up to 2 min** for automatic standby promotion
   (HA-A §5). The runner's pool-reset + one-shot retry (`runner.py:258-290`) re-runs
   in-flight rows automatically.
5. If manual promotion is required:
   `aws rds reboot-db-instance --db-instance-identifier accord-prod --force-failover`
6. Verify recovery: `GET /api/accord/health/deep` → `db_latency_ms < 100`, `status: ok`.

---

## RDB-002 — Pipeline Stalled (Watermark > 15 min)  *(SEV-2)*

**Symptoms:** `GET /api/accord/infra/pipeline-health` → `overall_status: stalled`
(WatermarkAgeSeconds > 900 — the IN-C "15-minute mystery" alarm).

1. Check SQS queue depth: `GET /api/accord/infra/sqs-status` (or AWS Console).
2. Check task health: `GET /api/accord/health` across tasks (all returning ok?).
3. Check RDS connectivity: `GET /api/accord/health/deep`.
4. Check the DLQ: `GET /api/accord/infra/pipeline-health` → `dlq_depth`.
5. If tasks are healthy but stalled, force new tasks:
   `aws ecs update-service --cluster accord --service accord-api --force-new-deployment`
6. Drain the DLQ: inspect messages, fix root cause, replay (un-acked messages
   redeliver automatically; poison messages sit in the DLQ).

> Note: the most common historical cause was an **unbounded await on a degraded RDS
> link** — now bounded by `asyncio.wait_for(SCENARIO_TIMEOUT)` (CI-B, Known Gap g). A
> stuck decision becomes a TIMEOUT and the run continues.

---

## RDB-003 — Claude API Unavailable  *(SEV-2/3)*

**Symptoms:** Vision extraction failing; document classification degraded.

1. The `claude_api` circuit breaker (HA-C) auto-OPENs after 5 failures in 60s.
2. Verify the degraded path is active: extraction falls back to **pdfplumber/regex**
   (RA-EX-F) — decisions continue; only Vision accuracy is temporarily reduced.
3. Check Anthropic status: https://status.anthropic.com
4. Monitor the circuit: look for `[circuit:claude_api] tripped OPEN` in logs; the
   breaker's `snapshot()` is embedded in affected responses (RULE 11).
5. On recovery the circuit moves OPEN → HALF_OPEN (30s cooldown) → CLOSED on the first
   successful trial call — **no manual intervention** if degradation is acceptable.

---

## RDB-004 — Wrong Decision Output  *(SEV-1 if systemic)*

**Symptoms:** Loans incorrectly approved/blocked · 16/16 eval fails · user report ·
`PersonaFailures > 0` alarm.

1. Identify affected loans:
   `SELECT application_id, outcome FROM decision_outputs WHERE outcome != <expected>`
2. Reproduce via replay (CI-B): `replay_decision(conn, application_id, tenant_id, version_id)`
   (`core/intelligence/decision_replay.py`).
3. Check what changed: `git log --oneline -10` (recent catalogue/rule/code changes?).
4. Check overlay versions:
   `SELECT version, status FROM tenant_rules WHERE tenant_id=$1 ORDER BY version DESC`
5. If a **catalogue/overlay change** is the cause: emergency-revert via
   `scripts/rules_cron.py` (unratified emergency changes auto-revert within 24h).
6. If a **code change** is the cause: `git revert <sha>` + redeploy.
7. Re-run the affected tenant:
   `PersonaRunner(DATABASE_URL).run_all_waves(tenant_id="<tenant>")`
   (note: `run_all_waves` takes `batch_size` + `tenant_id` — there is no per-application
   argument; decisions are idempotent per `application_id, decision_id`).
8. File an incident report: `affected_apps[]`, root cause, remediation, re-eval result.

---

## RDB-005 — Fair Lending Alert  *(SEV-1 — Legal involved)*

**Symptoms:** CM-D flags disparate impact · QA-A proxy-swap CI failure · CM-G elevated
overlay risk.

1. **DO NOT continue deploying overlay changes.** Freeze the overlay pipeline.
2. Run CM-F overlay attribution: `GET /api/accord/audit/hmda/overlay-disparity`
   (which overlay drives the gap?).
3. Run the CF-B privileged self-test: `GET /api/accord/audit/fair-lending/self-test`
   (conduct + document as **privileged** ECOA 12 CFR 202.15 material).
4. Notify the **Fair Lending Officer + Legal immediately** (per DOC-C governance).
5. If an overlay is the root cause: revert to the prior `tenant_rules` version
   (version rollback, same mechanism as RDB-004 step 5).
6. Preserve all findings as privileged self-test material.
7. Follow remediation per `docs/FAIR_LENDING_POLICY.md` (DOC-C).

> Reminder: QA-A asserts byte-identical outcomes across 8 proxy pairs on every deploy —
> a CI failure here means a proxy may have leaked into the decision path. Treat as SEV-1.

---

## Contact / Escalation

| Level | Owner | Triggers |
|---|---|---|
| **L1** | On-call engineer (PagerDuty) | SQS stall, RDS down, watermark stalled |
| **L2** | Engineering lead | wrong decisions, data integrity |
| **L3** | Legal / Compliance / Fair Lending Officer | fair-lending alert, data breach, regulatory |
| **L4** | CEO / Board | systemic failure, regulatory action |

---

*HA-F · incident runbook (RDB-001..005) + SEV-1/2/3 tiers + escalation. References
HA-A (RDS), HA-B (health/deep, ECS), HA-C (circuit breaker), HA-D (recovery), HA-E
(alarms).*
