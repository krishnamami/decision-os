"""Audit alert sinks — PRD §23.9 audit_fail_alerts_compliance_immediately.

Any AuditRecord whose overall_status is FAIL fires a real-time alert
to the compliance team. No buffering. No batching. Immediate
notification.

The platform wires one AlertSink into AuditEngine. Production swaps
the InMemory sink for a PagerDuty / email / Slack / OpsGenie sink
that implements the same Protocol. WARN status does NOT fire alerts —
those flow through the standard /ui/audit/flags queue.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Protocol

from .schema import AuditRecord, CheckStatus


logger = logging.getLogger(__name__)


class AuditAlert:
    """Immutable wrapper around an AuditRecord at the moment a sink
    fires. Carries enough context that a sink can render a message
    without re-resolving the record."""

    __slots__ = ("audit_id", "decision_type", "application_id",
                 "overall_status", "fired_at", "failed_checks", "summary")

    def __init__(self, record: AuditRecord):
        self.audit_id       = str(record.audit_id)
        self.decision_type  = record.decision_type
        self.application_id = record.application_id
        self.overall_status = record.overall_status.value
        self.fired_at       = datetime.utcnow()
        self.failed_checks  = [
            name for name, status in (
                ("compliance", record.compliance_status),
                ("security",   record.security_status),
                ("ethics",     record.ethics_status),
                ("fairness",   record.fairness_status),
            ) if status == CheckStatus.FAIL
        ]
        self.summary = (
            f"Audit FAIL: {record.decision_type} on application "
            f"{record.application_id} — failing checks: "
            f"{', '.join(self.failed_checks) or 'aggregate'}"
        )


class AlertSink(Protocol):
    """Notify a downstream channel that an AuditRecord failed.

    Sinks must be tolerant of the same alert firing twice (engine
    retry, replay) — idempotency is the sink's job, not the engine's."""

    async def fire(self, alert: AuditAlert) -> None: ...


class InMemoryAlertSink:
    """Reference sink for tests + the local smoke. Captures every
    alert so test assertions can inspect the sequence; production
    replaces this with PagerDuty / Slack / email."""

    def __init__(self) -> None:
        self.alerts: list[AuditAlert] = []

    async def fire(self, alert: AuditAlert) -> None:
        self.alerts.append(alert)

    def __len__(self) -> int:
        return len(self.alerts)


class LoggingAlertSink:
    """Emits each alert through structlog/stdlib logger at WARNING.
    Useful when running locally without a PagerDuty integration —
    every fail still leaves a visible trace in the operator's log."""

    async def fire(self, alert: AuditAlert) -> None:
        logger.warning(
            "audit_fail_alert",
            extra={
                "audit_id":       alert.audit_id,
                "decision_type":  alert.decision_type,
                "application_id": alert.application_id,
                "failed_checks":  alert.failed_checks,
                "fired_at":       alert.fired_at.isoformat(),
            },
        )


__all__ = [
    "AlertSink",
    "AuditAlert",
    "InMemoryAlertSink",
    "LoggingAlertSink",
]
