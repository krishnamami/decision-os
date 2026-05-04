from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Optional

from pydantic import BaseModel, Field

from core.audit.schema import AuditRecord


class Report(BaseModel):
    """Structured output for every audit report. Same shape across all
    six generators so a downstream renderer (CSV, JSON, regulator
    submission) doesn't branch on report type."""

    name: str
    cadence: str  # daily / weekly / monthly / quarterly / on_demand
    window_start: datetime
    window_end: datetime
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    record_count: int
    summary: dict[str, Any] = Field(default_factory=dict)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    flags: list[dict[str, Any]] = Field(default_factory=list)


def filter_by_window(
    records: Iterable[AuditRecord],
    window_start: datetime,
    window_end: datetime,
    *,
    decision_types: Optional[Iterable[str]] = None,
) -> list[AuditRecord]:
    """Cheap reusable filter — by timestamp window and optionally
    decision_type. Reports call this first so the rest of the
    aggregation works on a focused set."""

    allowed = set(decision_types) if decision_types else None
    out: list[AuditRecord] = []
    for r in records:
        if r.timestamp < window_start or r.timestamp > window_end:
            continue
        if allowed is not None and r.decision_type not in allowed:
            continue
        out.append(r)
    return out
