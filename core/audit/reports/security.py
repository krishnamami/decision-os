"""Security access report — daily cadence per PRD §23.7.

Roll-up of PII access patterns + anomaly flags across audit_records.
Real production also pulls audit_access_log entries (who viewed which
record) — that lookup needs the AuditStore handle, so the generator
takes an optional access_log_loader callable.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Awaitable, Callable, Iterable, Optional
from uuid import UUID

from core.audit.schema import AccessRecord, AuditRecord

from .base import Report, filter_by_window


AccessLogLoader = Callable[[UUID], Awaitable[list[AccessRecord]]]


def generate_security_report(
    records: Iterable[AuditRecord],
    window_start: datetime,
    window_end: datetime,
) -> Report:
    in_window = filter_by_window(records, window_start, window_end)

    pii_counter: Counter[str] = Counter()
    permission_counter: Counter[str] = Counter()
    anomaly_count = 0
    by_classification: Counter[str] = Counter()
    rows: list[dict] = []
    flags: list[dict] = []

    for r in in_window:
        for f in r.pii_fields_accessed:
            pii_counter[f] += 1
        for p in r.permissions_used:
            permission_counter[p] += 1
        by_classification[r.data_classification.value] += 1
        if r.access_anomaly:
            anomaly_count += 1
            flags.append({
                "audit_id": str(r.audit_id),
                "decision_type": r.decision_type,
                "reason": r.access_anomaly_reason or "anomaly flagged upstream",
            })
        if r.security_status.value == "fail":
            flags.append({
                "audit_id": str(r.audit_id),
                "decision_type": r.decision_type,
                "reason": "security check fail",
            })

        rows.append({
            "audit_id":            str(r.audit_id),
            "decision_type":       r.decision_type,
            "application_id":      r.application_id,
            "data_classification": r.data_classification.value,
            "encryption_status":   r.encryption_status.value,
            "pii_fields_accessed": list(r.pii_fields_accessed),
            "permissions_used":    list(r.permissions_used),
            "access_anomaly":      r.access_anomaly,
            "security_status":     r.security_status.value,
            "timestamp":           r.timestamp.isoformat(),
        })

    return Report(
        name="security_access",
        cadence="daily",
        window_start=window_start,
        window_end=window_end,
        record_count=len(in_window),
        summary={
            "pii_field_counts":     dict(pii_counter),
            "permission_counts":    dict(permission_counter),
            "by_data_classification": dict(by_classification),
            "anomaly_count":        anomaly_count,
        },
        rows=rows,
        flags=flags,
    )
