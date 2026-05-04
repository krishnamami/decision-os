"""Audit log export — PRD §19 TIER 4 deliverable.

Render an iterable of AuditRecords as CSV or JSONL for regulator
submission. The store + traces are already append-only; this module
just shapes them into the row format examiners expect.

Two formats:
  CSV  — flat header + row per audit record. Lists collapse to
         semicolon-joined strings; jsonb fields render as JSON.
  JSONL — one record per line. Preserves nested shapes for tooling
          that wants to re-ingest the data.

Filtering supports decision-type allow-list, date window, and
overall_status. Both formats stream — no full materialization in
memory — so a year of audit history is exportable without OOM."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Iterable, Iterator, Optional

from .schema import AuditRecord, CheckStatus


# Column order frozen for examiners — adding new fields appends to
# the right; never reorder existing columns.
CSV_COLUMNS: tuple[str, ...] = (
    "audit_id",
    "decision_id",
    "application_id",
    "decision_type",
    "timestamp",
    "decision_output",
    "confidence",
    "owner",
    "mode",
    "outcome",
    "overall_status",
    "compliance_status",
    "security_status",
    "ethics_status",
    "fairness_status",
    "regulation_tags",
    "consent_status",
    "data_sources_used",
    "disclosure_sent",
    "data_classification",
    "encryption_status",
    "pii_fields_accessed",
    "permissions_used",
    "access_anomaly",
    "access_anomaly_reason",
    "applicant_segment",
    "protected_attrs_used",
    "protected_attrs_excluded",
    "bias_score",
    "disparate_impact_flag",
    "human_reviewed",
    "policy_version_ids",
    "fairness_flag_count",
    "supersedes_audit_id",
)


def _filter(
    records: Iterable[AuditRecord],
    *,
    window_start: Optional[datetime],
    window_end: Optional[datetime],
    decision_types: Optional[Iterable[str]],
    status_filter: Optional[Iterable[CheckStatus]],
) -> Iterator[AuditRecord]:
    allowed_types = set(decision_types) if decision_types else None
    allowed_status = set(status_filter) if status_filter else None
    for r in records:
        if window_start is not None and r.timestamp < window_start:
            continue
        if window_end is not None and r.timestamp > window_end:
            continue
        if allowed_types is not None and r.decision_type not in allowed_types:
            continue
        if allowed_status is not None and r.overall_status not in allowed_status:
            continue
        yield r


def _row_dict(record: AuditRecord) -> dict[str, str]:
    return {
        "audit_id":              str(record.audit_id),
        "decision_id":           str(record.decision_id),
        "application_id":        record.application_id,
        "decision_type":         record.decision_type,
        "timestamp":             record.timestamp.isoformat(),
        "decision_output":       record.decision_output.value,
        "confidence":            f"{record.confidence:.4f}",
        "owner":                 record.owner,
        "mode":                  record.mode.value,
        "outcome":               record.outcome or "",
        "overall_status":        record.overall_status.value,
        "compliance_status":     record.compliance_status.value,
        "security_status":       record.security_status.value,
        "ethics_status":         record.ethics_status.value,
        "fairness_status":       record.fairness_status.value,
        "regulation_tags":       ";".join(record.regulation_tags or ()),
        "consent_status":        record.consent_status.value,
        "data_sources_used":     ";".join(record.data_sources_used or ()),
        "disclosure_sent":       "true" if record.disclosure_sent else "false",
        "data_classification":   record.data_classification.value,
        "encryption_status":     record.encryption_status.value,
        "pii_fields_accessed":   ";".join(record.pii_fields_accessed or ()),
        "permissions_used":      ";".join(record.permissions_used or ()),
        "access_anomaly":        "true" if record.access_anomaly else "false",
        "access_anomaly_reason": record.access_anomaly_reason or "",
        "applicant_segment":     record.applicant_segment or "",
        "protected_attrs_used":  ";".join(record.protected_attrs_used or ()),
        "protected_attrs_excluded": ";".join(record.protected_attrs_excluded or ()),
        "bias_score":            "" if record.bias_score is None else f"{record.bias_score:.4f}",
        "disparate_impact_flag": "true" if record.disparate_impact_flag else "false",
        "human_reviewed":        "true" if record.human_reviewed else "false",
        "policy_version_ids":    ";".join(p.policy_id for p in (record.policy_applied or ())),
        "fairness_flag_count":   str(len(record.fairness_flags or ())),
        "supersedes_audit_id":   str(record.supersedes_audit_id) if record.supersedes_audit_id else "",
    }


def export_csv(
    records: Iterable[AuditRecord],
    *,
    window_start: Optional[datetime] = None,
    window_end: Optional[datetime] = None,
    decision_types: Optional[Iterable[str]] = None,
    status_filter: Optional[Iterable[CheckStatus]] = None,
) -> Iterator[str]:
    """Yield CSV chunks (header line first, then one line per record).
    Streamable through FastAPI StreamingResponse without buffering."""

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(CSV_COLUMNS), extrasaction="ignore")
    writer.writeheader()
    yield buf.getvalue()
    buf.seek(0)
    buf.truncate(0)

    for record in _filter(
        records,
        window_start=window_start,
        window_end=window_end,
        decision_types=decision_types,
        status_filter=status_filter,
    ):
        writer.writerow(_row_dict(record))
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)


def export_jsonl(
    records: Iterable[AuditRecord],
    *,
    window_start: Optional[datetime] = None,
    window_end: Optional[datetime] = None,
    decision_types: Optional[Iterable[str]] = None,
    status_filter: Optional[Iterable[CheckStatus]] = None,
) -> Iterator[str]:
    """Yield one JSON object per line. Preserves nested structure
    (jsonb columns + sub-models) for re-ingestable downstream tooling."""

    for record in _filter(
        records,
        window_start=window_start,
        window_end=window_end,
        decision_types=decision_types,
        status_filter=status_filter,
    ):
        # model_dump(mode="json") produces JSON-safe primitives.
        line = json.dumps(record.model_dump(mode="json"), default=str)
        yield line + "\n"


__all__ = [
    "CSV_COLUMNS",
    "export_csv",
    "export_jsonl",
]
