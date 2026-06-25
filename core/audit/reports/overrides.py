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


async def generate_exception_register(
    conn, tenant_id: str, start_date: str = None, end_date: str = None,
) -> dict:
    """EX-C — exception register from loan_exceptions, for ECOA consistent-treatment
    review (12 CFR 202.9 / Fannie B3-2-02). Async DB read (the table is populated by
    the exception_writer backfill). Demographic data is NEVER collected or used in
    exception decisions (mirrors HMDA RA-7C)."""
    import json
    rows = await conn.fetch(
        """SELECT le.id, le.application_id, le.exception_type, le.blocked_signal,
                  le.breach_pct, le.below_agency_floor, le.status, le.granted,
                  le.denial_reason, le.requested_at, le.reviewed_at, le.requested_by,
                  le.reviewed_by, le.threshold_source, le.compensating_factors
           FROM loan_exceptions le
           WHERE le.tenant_id = $1
             AND ($2::date IS NULL OR le.requested_at >= $2::date)
             AND ($3::date IS NULL OR le.requested_at <= $3::date)
           ORDER BY le.requested_at DESC""",
        tenant_id, start_date, end_date,
    )

    total = len(rows)
    granted = sum(1 for r in rows if r["granted"] is True)
    denied = sum(1 for r in rows if r["granted"] is False)
    pending = sum(1 for r in rows if r["status"] in ("requested", "under_review"))

    by_type: dict = {}
    for r in rows:
        t = r["exception_type"]
        b = by_type.setdefault(t, {"total": 0, "granted": 0, "denied": 0})
        b["total"] += 1
        if r["granted"] is True:
            b["granted"] += 1
        elif r["granted"] is False:
            b["denied"] += 1

    def _ser(r):
        d = dict(r)
        for k in ("requested_at", "reviewed_at"):
            if d.get(k) is not None and hasattr(d[k], "isoformat"):
                d[k] = d[k].isoformat()
        cf = d.get("compensating_factors")
        if isinstance(cf, str):
            try:
                d["compensating_factors"] = json.loads(cf)
            except Exception:
                pass
        d["id"] = str(d["id"])
        return d

    return {
        "tenant_id": tenant_id,
        "period": {"start": start_date, "end": end_date},
        "summary": {
            "total": total, "granted": granted, "denied": denied, "pending": pending,
            "grant_rate": round(granted / total * 100, 1) if total else 0,
        },
        "by_type": by_type,
        "exceptions": [_ser(r) for r in rows],
        "cfpb_note": ("Exception register for ECOA consistent-treatment review. "
                      "Demographic data not collected or used in exception decisions."),
        "citation": "12 CFR 202.9, Fannie B3-2-02",
        "data_source": "loan_exceptions + compensating_factors tables",
        "missing_inputs": [],
    }
