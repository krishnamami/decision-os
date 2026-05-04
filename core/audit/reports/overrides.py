"""Override and rollback report — weekly cadence per PRD §23.7.

Counts decisions that took a human review path. Real reason-code +
reviewer-role detail lives on the DecisionTrace.HumanReview, not on
the AuditRecord (the audit blob carries human_reviewed: bool only).
A Postgres migration can extend audit_records with a JSONB
human_review_summary column to surface this without re-joining the
trace; flagged here as a TIER 4 follow-up.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Iterable

from core.audit.schema import AuditRecord

from .base import Report, filter_by_window


def generate_overrides_report(
    records: Iterable[AuditRecord],
    window_start: datetime,
    window_end: datetime,
) -> Report:
    in_window = filter_by_window(records, window_start, window_end)

    by_decision: Counter[str] = Counter()
    reviewed_count = 0
    rows: list[dict] = []

    for r in in_window:
        if r.human_reviewed:
            reviewed_count += 1
            by_decision[r.decision_type] += 1
            rows.append({
                "audit_id":         str(r.audit_id),
                "decision_id":      str(r.decision_id),
                "application_id":   r.application_id,
                "decision_type":    r.decision_type,
                "owner":            r.owner,
                "ai_outcome":       r.decision_output.value,
                "applicant_segment": r.applicant_segment,
                "compliance_status": r.compliance_status.value,
                "ethics_status":    r.ethics_status.value,
                "fairness_status":  r.fairness_status.value,
                "overall_status":   r.overall_status.value,
                "timestamp":        r.timestamp.isoformat(),
            })

    rows.sort(key=lambda x: x["timestamp"])

    return Report(
        name="overrides_rollback",
        cadence="weekly",
        window_start=window_start,
        window_end=window_end,
        record_count=len(in_window),
        summary={
            "reviewed_count":         reviewed_count,
            "by_decision_type":       dict(by_decision),
            "review_rate":            reviewed_count / len(in_window) if in_window else 0.0,
        },
        rows=rows,
    )
