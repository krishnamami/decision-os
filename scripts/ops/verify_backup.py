"""HA-D — backup + point-in-time-recovery verification.

Checks that the things Accord must be able to restore are actually being backed up:
  1. RDS automated snapshot exists and is < 24h old.
  2. S3 document bucket has versioning enabled.
  3. A recent tenant_rules export exists in S3 (the rules-activation backup).

Mirrors the platform's graceful-no-AWS posture (RA-P0-A / IN-A / IN-C): when AWS is
unconfigured, each check returns ``"skipped"`` with an honest reason rather than failing
— so this runs locally without pretending a backup exists. Read-only: it never creates
or deletes a snapshot; it only inspects.

Usage:
    python scripts/ops/verify_backup.py
    python scripts/ops/verify_backup.py --db-instance accord-prod --bucket accord-docs

Returns (and prints as JSON): {backup_status, last_backup_age_hours, checks, gaps[]}.
Exit code 0 if backup_status == "healthy", else 1 (CI / cron friendly).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aws_clients():
    """Build (rds, s3) clients only if AWS credentials are actually available.
    Returns (None, None) when unconfigured — the local-dev / CI path."""
    try:
        import boto3
        session = boto3.Session()
        if session.get_credentials() is None:
            return None, None
        return session.client("rds"), session.client("s3")
    except Exception:  # boto3 missing / config error
        return None, None


def check_rds_snapshot(rds, db_instance: str, max_age_hours: float = 24.0) -> dict:
    """Latest automated/manual snapshot for the instance, and its age."""
    if rds is None:
        return {"check": "rds_snapshot", "status": "skipped",
                "reason": "AWS not configured — cannot verify RDS snapshots locally"}
    try:
        resp = rds.describe_db_snapshots(DBInstanceIdentifier=db_instance, MaxRecords=100)
        snaps = [s for s in resp.get("DBSnapshots", []) if s.get("SnapshotCreateTime")]
        if not snaps:
            return {"check": "rds_snapshot", "status": "fail", "db_instance": db_instance,
                    "reason": "no snapshots found for instance"}
        latest = max(snaps, key=lambda s: s["SnapshotCreateTime"])
        created = latest["SnapshotCreateTime"]
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_h = round((_now() - created).total_seconds() / 3600, 1)
        ok = age_h <= max_age_hours
        return {"check": "rds_snapshot", "status": "pass" if ok else "fail",
                "db_instance": db_instance, "latest_snapshot": latest.get("DBSnapshotIdentifier"),
                "age_hours": age_h, "max_age_hours": max_age_hours,
                "reason": None if ok else f"latest snapshot is {age_h}h old (> {max_age_hours}h)"}
    except Exception as exc:  # noqa: BLE001
        return {"check": "rds_snapshot", "status": "error", "reason": str(exc)[:200]}


def check_s3_versioning(s3, bucket: str) -> dict:
    """Object versioning must be enabled so a deleted/overwritten doc is recoverable."""
    if s3 is None:
        return {"check": "s3_versioning", "status": "skipped",
                "reason": "AWS not configured — cannot verify S3 versioning locally"}
    try:
        resp = s3.get_bucket_versioning(Bucket=bucket)
        enabled = resp.get("Status") == "Enabled"
        return {"check": "s3_versioning", "status": "pass" if enabled else "fail",
                "bucket": bucket, "versioning": resp.get("Status", "Disabled"),
                "reason": None if enabled else "bucket versioning is not Enabled"}
    except Exception as exc:  # noqa: BLE001
        return {"check": "s3_versioning", "status": "error", "bucket": bucket,
                "reason": str(exc)[:200]}


def check_rules_export(s3, bucket: str, max_age_hours: float = 168.0) -> dict:
    """A recent tenant_rules export under exports/rules/ (written on version activation)."""
    if s3 is None:
        return {"check": "rules_export", "status": "skipped",
                "reason": "AWS not configured — cannot verify rules export locally"}
    try:
        resp = s3.list_objects_v2(Bucket=bucket, Prefix="exports/rules/", MaxKeys=1000)
        objs = resp.get("Contents", [])
        if not objs:
            return {"check": "rules_export", "status": "fail", "bucket": bucket,
                    "reason": "no tenant_rules export found under exports/rules/"}
        latest = max(objs, key=lambda o: o["LastModified"])
        lm = latest["LastModified"]
        if lm.tzinfo is None:
            lm = lm.replace(tzinfo=timezone.utc)
        age_h = round((_now() - lm).total_seconds() / 3600, 1)
        ok = age_h <= max_age_hours
        return {"check": "rules_export", "status": "pass" if ok else "warn",
                "bucket": bucket, "latest_export": latest.get("Key"), "age_hours": age_h,
                "reason": None if ok else f"latest rules export is {age_h}h old (> {max_age_hours}h)"}
    except Exception as exc:  # noqa: BLE001
        return {"check": "rules_export", "status": "error", "reason": str(exc)[:200]}


def verify_backup(db_instance: str, bucket: str) -> dict:
    """Run all three checks and roll up an overall backup_status + gaps[]."""
    rds, s3 = _aws_clients()
    checks = [
        check_rds_snapshot(rds, db_instance),
        check_s3_versioning(s3, bucket),
        check_rules_export(s3, bucket),
    ]
    gaps = [c["reason"] for c in checks if c["status"] in ("fail", "error") and c.get("reason")]
    skipped = [c["check"] for c in checks if c["status"] == "skipped"]

    if any(c["status"] in ("fail", "error") for c in checks):
        overall = "unhealthy"
    elif skipped:
        overall = "unknown"   # AWS unconfigured — cannot assert backups exist
    else:
        overall = "healthy"

    snap = next((c for c in checks if c["check"] == "rds_snapshot"), {})
    return {
        "backup_status": overall,
        "last_backup_age_hours": snap.get("age_hours"),
        "checks": checks,
        "gaps": gaps,
        "skipped_checks": skipped,
        "as_of": _now().isoformat(),
        "note": ("AWS unconfigured -> checks skipped, status 'unknown' (honest: cannot "
                 "verify a backup that this environment cannot see)." if skipped else
                 "All backup checks ran against live AWS."),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify RDS + S3 backups (HA-D).")
    ap.add_argument("--db-instance", default=os.environ.get("RDS_INSTANCE_ID", "accord-prod"))
    ap.add_argument("--bucket", default=os.environ.get("S3_BUCKET", "accord-docs"))
    args = ap.parse_args()
    report = verify_backup(args.db_instance, args.bucket)
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["backup_status"] == "healthy" else 1


if __name__ == "__main__":
    sys.exit(main())
