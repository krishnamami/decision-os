"""Fair-lending analysis report — quarterly cadence per PRD §23.7.

Compares approval rates across applicant_segment values. Surfaces any
segment whose approval rate diverges materially from the overall
rate. Per ECOA / FHA, the ~80% rule (any group's selection rate < 80%
of the highest group's selection rate) is a disparate-impact threshold;
this report exposes that ratio so legal can review before adverse
action notices land.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Iterable

from core.audit.schema import AuditRecord

from .base import Report, filter_by_window


# 80% rule from EEOC, mirrored by HUD/CFPB for lending. A selection
# rate that is less than 80% of the highest rate suggests disparate
# impact on its face.
FOUR_FIFTHS_RATIO = 0.80


def _approval_rate(approvals: int, total: int) -> float:
    return approvals / total if total else 0.0


def generate_fair_lending_report(
    records: Iterable[AuditRecord],
    window_start: datetime,
    window_end: datetime,
) -> Report:
    in_window = filter_by_window(
        records, window_start, window_end,
        decision_types=("underwriting_decision",),
    )

    seg_total: Counter[str] = Counter()
    seg_approvals: Counter[str] = Counter()

    for r in in_window:
        seg = r.applicant_segment or "unknown"
        seg_total[seg] += 1
        if r.decision_output.value == "allow":
            seg_approvals[seg] += 1

    overall_total = sum(seg_total.values())
    overall_approvals = sum(seg_approvals.values())
    overall_rate = _approval_rate(overall_approvals, overall_total)

    rows: list[dict] = []
    rates: dict[str, float] = {}
    for seg, total in seg_total.items():
        approvals = seg_approvals.get(seg, 0)
        rate = _approval_rate(approvals, total)
        rates[seg] = rate
        rows.append({
            "applicant_segment": seg,
            "total":             total,
            "approvals":         approvals,
            "approval_rate":     rate,
            "delta_vs_overall":  rate - overall_rate,
        })

    rows.sort(key=lambda x: x["approval_rate"], reverse=True)

    # 4/5 disparate-impact ratio. Best segment vs each other; if any
    # ratio < 0.80 flag for legal review.
    if rates:
        best = max(rates.values())
    else:
        best = 0.0

    flags: list[dict] = []
    for seg, rate in rates.items():
        if best == 0:
            continue
        ratio = rate / best
        if ratio < FOUR_FIFTHS_RATIO:
            flags.append({
                "segment": seg,
                "approval_rate": rate,
                "best_rate": best,
                "ratio": ratio,
                "rule": "EEOC 4/5 disparate impact threshold",
            })

    return Report(
        name="fair_lending",
        cadence="quarterly",
        window_start=window_start,
        window_end=window_end,
        record_count=len(in_window),
        summary={
            "overall_total":      overall_total,
            "overall_approvals":  overall_approvals,
            "overall_rate":       overall_rate,
            "segment_count":      len(rates),
        },
        rows=rows,
        flags=flags,
    )
