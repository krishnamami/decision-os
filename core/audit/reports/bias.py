"""Bias and fairness report — weekly cadence per PRD §23.7.

Aggregates bias_score + fairness_flags + disparate_impact_flag across
the window. Calls out any record over the action threshold (0.30 per
PRD §23.4) and any segment with sustained warn-level signal.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Iterable

from core.audit.schema import AuditRecord
from core.audit.ethics_checker import (
    BIAS_ACTION_THRESHOLD,
    BIAS_MONITORING_THRESHOLD,
)

from .base import Report, filter_by_window


def generate_bias_report(
    records: Iterable[AuditRecord],
    window_start: datetime,
    window_end: datetime,
) -> Report:
    in_window = filter_by_window(records, window_start, window_end)

    scores: list[float] = []
    seg_flags: dict[str, Counter[str]] = defaultdict(Counter)
    flag_type_counter: Counter[str] = Counter()
    di_flag_count = 0
    rows: list[dict] = []
    flags: list[dict] = []

    for r in in_window:
        if r.bias_score is not None:
            scores.append(r.bias_score)
            if r.bias_score >= BIAS_ACTION_THRESHOLD:
                flags.append({
                    "audit_id": str(r.audit_id),
                    "decision_type": r.decision_type,
                    "bias_score": r.bias_score,
                    "threshold": BIAS_ACTION_THRESHOLD,
                    "rule": "bias_score >= action threshold",
                })
        if r.disparate_impact_flag:
            di_flag_count += 1

        for f in r.fairness_flags:
            flag_type_counter[f.flag_type] += 1
            if r.applicant_segment:
                seg_flags[r.applicant_segment][f.flag_type] += 1

        rows.append({
            "audit_id":             str(r.audit_id),
            "decision_type":        r.decision_type,
            "applicant_segment":    r.applicant_segment,
            "bias_score":           r.bias_score,
            "ethics_status":        r.ethics_status.value,
            "fairness_status":      r.fairness_status.value,
            "disparate_impact":     r.disparate_impact_flag,
            "fairness_flag_count":  len(r.fairness_flags),
            "fairness_flag_types":  [f.flag_type for f in r.fairness_flags],
            "protected_attrs_used": list(r.protected_attrs_used),
            "timestamp":            r.timestamp.isoformat(),
        })

    summary = {
        "score_count":         len(scores),
        "score_mean":          sum(scores) / len(scores) if scores else None,
        "score_max":           max(scores) if scores else None,
        "monitoring_threshold": BIAS_MONITORING_THRESHOLD,
        "action_threshold":    BIAS_ACTION_THRESHOLD,
        "above_action":        sum(1 for s in scores if s >= BIAS_ACTION_THRESHOLD),
        "above_monitoring":    sum(1 for s in scores if s >= BIAS_MONITORING_THRESHOLD),
        "disparate_impact_count": di_flag_count,
        "fairness_flag_types": dict(flag_type_counter),
        "by_segment": {
            seg: dict(counts) for seg, counts in seg_flags.items()
        },
    }

    return Report(
        name="bias_fairness",
        cadence="weekly",
        window_start=window_start,
        window_end=window_end,
        record_count=len(in_window),
        summary=summary,
        rows=rows,
        flags=flags,
    )
