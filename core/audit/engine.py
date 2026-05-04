from __future__ import annotations

import asyncio
from typing import Any, Optional

from core.trace.trace_schema import DecisionTrace

from .alerts import AlertSink, AuditAlert
from .compliance_checker import ComplianceChecker
from .ethics_checker import EthicsChecker
from .fairness_checker import FairnessChecker
from .schema import (
    AccessRecord,
    AuditRecord,
    CheckResult,
    CheckStatus,
    ConsentStatus,
    DataClassification,
    EncryptionStatus,
    FairnessFlag,
    PolicyApplied,
)
from .security_checker import SecurityChecker


# Worst-of aggregation: FAIL > WARN > PASS.
_STATUS_RANK = {CheckStatus.PASS: 0, CheckStatus.WARN: 1, CheckStatus.FAIL: 2}


def _worst(a: CheckStatus, b: CheckStatus) -> CheckStatus:
    return a if _STATUS_RANK[a] >= _STATUS_RANK[b] else b


class AuditEngine:
    """Runs the four audit checks in parallel and assembles an
    AuditRecord. PRD §23.

    Engine.evaluate() is the single entry point; the
    audit_record_required_before_writeback hard rule is enforced by
    the caller (atomic_tool / dag_executor) gating writeback on the
    presence of an AuditRecord."""

    def __init__(
        self,
        compliance: Optional[ComplianceChecker] = None,
        security: Optional[SecurityChecker] = None,
        ethics: Optional[EthicsChecker] = None,
        fairness: Optional[FairnessChecker] = None,
        alert_sink: Optional[AlertSink] = None,
    ):
        self._compliance = compliance or ComplianceChecker()
        self._security = security or SecurityChecker()
        self._ethics = ethics or EthicsChecker()
        self._fairness = fairness or FairnessChecker()
        # Optional sink for PRD §23.9 audit_fail_alerts_compliance_immediately.
        # When set, every record with overall_status=FAIL fires synchronously
        # through the sink before evaluate() returns. WARN does not alert.
        self._alert_sink = alert_sink

    async def evaluate(
        self,
        trace: DecisionTrace,
        *,
        event_input: Optional[dict[str, Any]] = None,
        context_used: Optional[dict[str, Any]] = None,
        ontology_mapping: Optional[dict[str, Any]] = None,
        execution_result: Optional[dict[str, Any]] = None,
        regulation_tags: Optional[list[str]] = None,
        data_sources_used: Optional[list[str]] = None,
        consent_status: ConsentStatus = ConsentStatus.OBTAINED,
        disclosure_sent: bool = False,
        retention_policy: Optional[str] = None,
        accessed_by: Optional[list[AccessRecord]] = None,
        permissions_used: Optional[list[str]] = None,
        pii_fields_accessed: Optional[list[str]] = None,
        data_classification: DataClassification = DataClassification.CONFIDENTIAL,
        encryption_status: EncryptionStatus = EncryptionStatus.BOTH,
        access_anomaly: bool = False,
        access_anomaly_reason: Optional[str] = None,
        applicant_segment: Optional[str] = None,
        protected_attrs_used: Optional[list[str]] = None,
        protected_attrs_excluded: Optional[list[str]] = None,
        bias_score: Optional[float] = None,
        disparate_impact_flag: bool = False,
        fairness_flags: Optional[list[FairnessFlag]] = None,
    ) -> AuditRecord:
        """Build the AuditRecord skeleton from inputs, run the four
        checkers concurrently, merge their results, and aggregate
        overall_status. The returned record is ready to write to the
        AuditStore — the engine itself does not persist."""

        record = AuditRecord(
            decision_id=trace.trace_id,
            application_id=trace.application_id,
            decision_type=trace.decision_id,
            event_input=event_input or {},
            context_used=context_used or {},
            ontology_mapping=ontology_mapping or {},
            policy_applied=self._policies_from_trace(trace),
            decision_output=trace.outcome,
            confidence=trace.confidence,
            owner=trace.persona,
            mode=trace.mode,
            execution_result=execution_result or {},
            regulation_tags=list(regulation_tags or []),
            consent_status=consent_status,
            data_sources_used=list(data_sources_used or []),
            disclosure_sent=disclosure_sent,
            retention_policy=retention_policy,
            accessed_by=list(accessed_by or []),
            permissions_used=list(permissions_used or []),
            pii_fields_accessed=list(pii_fields_accessed or []),
            data_classification=data_classification,
            encryption_status=encryption_status,
            access_anomaly=access_anomaly,
            access_anomaly_reason=access_anomaly_reason,
            applicant_segment=applicant_segment,
            protected_attrs_used=list(protected_attrs_used or []),
            protected_attrs_excluded=list(protected_attrs_excluded or []),
            bias_score=bias_score,
            disparate_impact_flag=disparate_impact_flag,
            fairness_flags=list(fairness_flags or []),
            human_reviewed=trace.human_review is not None,
        )

        # Run the four checkers concurrently. Each is synchronous
        # internally but wrapping in to_thread keeps the engine I/O-
        # bound friendly when checkers grow into Postgres lookups
        # (segment baselines, prior PII access counts, etc.).
        compliance_t = asyncio.to_thread(self._compliance.check, record)
        security_t = asyncio.to_thread(self._security.check, record)
        ethics_t = asyncio.to_thread(self._ethics.check, record)
        fairness_t = asyncio.to_thread(self._fairness.check, record)
        compliance_r, security_r, ethics_r, fairness_r = await asyncio.gather(
            compliance_t, security_t, ethics_t, fairness_t
        )

        record.compliance_status = compliance_r.status
        record.security_status = security_r.status
        record.ethics_status = ethics_r.status
        record.fairness_status = fairness_r.status
        record.overall_status = self._aggregate(
            compliance_r.status,
            security_r.status,
            ethics_r.status,
            fairness_r.status,
        )

        # PRD §23.9 audit_fail_alerts_compliance_immediately. FAIL fires
        # synchronously — no buffering, no batching. WARN flows through
        # the standard /ui/audit/flags queue. Sink errors don't propagate
        # because alerting must never block the audit gate itself.
        if (
            self._alert_sink is not None
            and record.overall_status == CheckStatus.FAIL
        ):
            try:
                await self._alert_sink.fire(AuditAlert(record))
            except Exception:
                pass

        return record

    @staticmethod
    def _policies_from_trace(trace: DecisionTrace) -> list[PolicyApplied]:
        applied: list[PolicyApplied] = []
        if trace.policy_version_id:
            applied.append(
                PolicyApplied(
                    policy_id=trace.policy_version_id,
                    clause=trace.policy_matched_clause,
                    result=(trace.policy_decision_outcome or trace.outcome).value,
                    reason="; ".join(trace.policy_reasons) or None,
                )
            )
        return applied

    @staticmethod
    def _aggregate(*statuses: CheckStatus) -> CheckStatus:
        worst = CheckStatus.PASS
        for s in statuses:
            worst = _worst(worst, s)
        return worst
