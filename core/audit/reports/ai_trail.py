"""AI decision audit trail — weekly cadence per PRD §23.7.

Per-decision listing for every automated decision in the window with
full context: outcome, policy applied, regulation tags, the four
check statuses, and whether a human review attached. This is the
"every decision is a work journal" surface for regulators — not a
roll-up.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Iterable

from core.audit.schema import AuditRecord

from .base import Report, filter_by_window


def generate_ai_trail_report(
    records: Iterable[AuditRecord],
    window_start: datetime,
    window_end: datetime,
) -> Report:
    in_window = filter_by_window(records, window_start, window_end)

    by_status: Counter[str] = Counter()
    by_outcome: Counter[str] = Counter()
    by_decision: Counter[str] = Counter()
    rows: list[dict] = []

    for r in in_window:
        by_status[r.overall_status.value] += 1
        by_outcome[r.decision_output.value] += 1
        by_decision[r.decision_type] += 1

        rows.append({
            "audit_id":         str(r.audit_id),
            "decision_id":      str(r.decision_id),
            "application_id":   r.application_id,
            "decision_type":    r.decision_type,
            "owner":            r.owner,
            "mode":             r.mode.value,
            "outcome":          r.decision_output.value,
            "confidence":       r.confidence,
            "compliance":       r.compliance_status.value,
            "security":         r.security_status.value,
            "ethics":           r.ethics_status.value,
            "fairness":         r.fairness_status.value,
            "overall":          r.overall_status.value,
            "policies_applied": [
                {"policy_id": p.policy_id, "result": p.result}
                for p in r.policy_applied
            ],
            "human_reviewed":   r.human_reviewed,
            "timestamp":        r.timestamp.isoformat(),
        })

    rows.sort(key=lambda x: x["timestamp"])

    return Report(
        name="ai_trail",
        cadence="weekly",
        window_start=window_start,
        window_end=window_end,
        record_count=len(in_window),
        summary={
            "by_overall_status": dict(by_status),
            "by_outcome":        dict(by_outcome),
            "by_decision_type":  dict(by_decision),
            "human_reviewed_count": sum(1 for r in in_window if r.human_reviewed),
        },
        rows=rows,
    )
