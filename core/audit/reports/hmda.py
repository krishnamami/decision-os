"""HMDA compliance report — monthly cadence per PRD §23.7.

Aggregates underwriting decisions in the window by geography (where
known) + decision outcome rates. Real HMDA LAR fields (loan amount,
purpose, race, ethnicity, sex, etc.) require joining with the
Application + Applicant entities — flagged as a follow-up here. v0
gives the structural shape regulators expect to consume.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Iterable

from core.audit.schema import AuditRecord

from .base import Report, filter_by_window


HMDA_DECISIONS = ("underwriting_decision", "approval_routing", "closing_readiness")


def generate_hmda_report(
    records: Iterable[AuditRecord],
    window_start: datetime,
    window_end: datetime,
) -> Report:
    in_window = filter_by_window(
        records, window_start, window_end, decision_types=HMDA_DECISIONS
    )

    by_outcome: Counter[str] = Counter()
    by_decision_type: Counter[str] = Counter()
    by_state: Counter[str] = Counter()
    rows: list[dict] = []

    for r in in_window:
        outcome = r.decision_output.value
        by_outcome[outcome] += 1
        by_decision_type[r.decision_type] += 1

        # Best-effort state lookup. The audit record carries
        # ontology_mapping (object types) and context_used; the actual
        # property_state lives on the Application entity, not the
        # audit record itself. v0 reports leave state blank and let
        # TIER 4 wire the join.
        state = (
            r.execution_result.get("property_state")
            or r.context_used.get("property_state")
        )
        if state:
            by_state[state] += 1

        rows.append({
            "audit_id":         str(r.audit_id),
            "application_id":   r.application_id,
            "decision_type":    r.decision_type,
            "outcome":          outcome,
            "confidence":       r.confidence,
            "regulation_tags":  list(r.regulation_tags),
            "consent_status":   r.consent_status.value,
            "disclosure_sent":  r.disclosure_sent,
            "property_state":   state,
            "applicant_segment": r.applicant_segment,
            "compliance_status": r.compliance_status.value,
            "overall_status":   r.overall_status.value,
            "timestamp":        r.timestamp.isoformat(),
        })

    flags = [
        {"audit_id": str(r.audit_id), "reason": "compliance status not pass",
         "compliance_status": r.compliance_status.value}
        for r in in_window if r.compliance_status.value != "pass"
    ]

    return Report(
        name="hmda_compliance",
        cadence="monthly",
        window_start=window_start,
        window_end=window_end,
        record_count=len(in_window),
        summary={
            "by_outcome":       dict(by_outcome),
            "by_decision_type": dict(by_decision_type),
            "by_state":         dict(by_state),
        },
        rows=rows,
        flags=flags,
    )
