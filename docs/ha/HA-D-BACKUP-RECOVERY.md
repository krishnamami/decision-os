# HA-D — Backup + Point-in-Time Recovery

> Spec + verification script (`scripts/ops/verify_backup.py`). The script is
> graceful-no-AWS: it returns `unknown` (not a false `healthy`) when AWS is
> unconfigured, so it never pretends a backup exists.

---

## 1. What Needs Backing Up

| Asset | Backup mechanism | Frequency |
|---|---|---|
| **RDS** (entity_states, decision_outputs, catalogue, tenant_rules, audit) | Automated daily snapshot (7-day retention, HA-A) + **manual snapshot before every major deploy** | Daily + pre-deploy |
| **S3 documents** | Bucket **versioning enabled** + 90-day lifecycle to Glacier | Continuous (per-object) |
| **tenant_rules** | Export to S3 (`exports/rules/`) on **every version activation** — extends `scripts/rules_cron.py` | Per activation |
| **Catalogue** | Source of truth is `scripts/compliance/seed_*.py` in git — re-seedable from code | Git history |
| **Decision history** | `decision_outputs` is read-only/append; covered by the RDS snapshot above | Daily |

The catalogue does not need a data backup — it is **reconstructible from the seed
scripts in version control** (RULE 8: catalogue-before-code). tenant_rules is the
lender-specific overlay state and IS backed up explicitly on activation.

## 2. Recovery Objectives

| Objective | Target | Mechanism |
|---|---|---|
| **RTO** (time to restore service) | **30 min** | Multi-AZ automatic failover (HA-A) |
| | **2 hours** | PITR restore (full instance rebuild) |
| **RPO** (max data loss) | **5 min** | Multi-AZ synchronous standby (zero-loss on failover) |
| | **1 hour** | Backup/PITR granularity (worst case, full-region loss) |

Multi-AZ failover (RTO 30 min / RPO 5 min) covers the common case — an AZ or instance
failure. PITR (RTO 2 h / RPO 1 h) is the disaster path — accidental deletion, corruption,
or restoring to a point before a bad change.

## 3. Recovery Procedures (summary; see HA-F runbooks for steps)

- **AZ/instance failure** → automatic Multi-AZ failover, no action (HA-A §6).
- **Bad data change** → PITR restore to a timestamp before the change, into a new
  instance, validate, then cut `DATABASE_URL` over.
- **Bad rule change** → restore the `tenant_rules` version (no DB restore needed —
  `rules_cron.py` emergency-revert; see HA-F RDB-004/005).

## 4. Verification — `scripts/ops/verify_backup.py`

Run on a schedule (daily cron / CI) to assert backups are actually happening:

```bash
python scripts/ops/verify_backup.py --db-instance accord-prod --bucket accord-docs
```

Checks:
1. **RDS snapshot exists and is < 24h old** (`describe_db_snapshots`).
2. **S3 bucket versioning is Enabled** (`get_bucket_versioning`).
3. **A tenant_rules export exists** under `exports/rules/` and is < 7 days old.

Returns:
```json
{
  "backup_status": "healthy" | "unhealthy" | "unknown",
  "last_backup_age_hours": 6.2,
  "checks": [ ... per-check pass/fail/skipped ... ],
  "gaps": [ "latest snapshot is 30h old (> 24h)" ],
  "skipped_checks": []
}
```

Exit code `0` only when `backup_status == "healthy"` (cron/CI-friendly). When AWS is
unconfigured every check is `skipped` and the status is **`unknown`** — deliberately not
`healthy`, because the environment cannot see (and must not claim) a backup.

---

*HA-D · backup/PITR spec + `scripts/ops/verify_backup.py` (RTO 30min/2h · RPO 5min/1h).*
