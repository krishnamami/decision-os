from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core.audit import (
    AccessRecord,
    AdverseActionNotice,
    AuditRecord,
    CheckStatus,
    generate_notice,
    is_adverse_action,
)
from core.audit.export import export_csv, export_jsonl
from core.audit.pii_log import PIIAccessEntry
from core.connectors import ConnectorError
from core.normalizer.models import (
    BaseEvent,
    DecisionOutcome,
    NormalizationError,
    normalize_event,
)
from core.trace import (
    AgentLearning,
    DecisionOutcomeCorrelation,
    DecisionTrace,
    HumanReview,
    OutcomeRecord,
    OutcomeType,
    correlate,
    derive_similarity_tags,
)

from .deps import Platform


# ─────────────────────────────────────────────────────────────────────
# Dependency stub.
#
# create_app() below stashes the live Platform on app.state.platform and
# overrides this dependency. Routes only see the Platform — never
# concrete backends.
# ─────────────────────────────────────────────────────────────────────


def get_platform(request: Request) -> Platform:
    platform = getattr(request.app.state, "platform", None)
    if platform is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Platform not initialized; create_app() must wire one",
        )
    return platform


router = APIRouter()


# ─────────────────────────────────────────────────────────────────────
# Request / response models
# ─────────────────────────────────────────────────────────────────────


class IngestEventRequest(BaseModel):
    """Inbound canonical-event envelope. Body MUST set event_type;
    everything else is forwarded to normalize_event() as-is."""

    event: dict[str, Any]


class IngestEventResponse(BaseModel):
    event_id: UUID
    event_type: str
    application_id: Optional[str] = None
    customer_id: Optional[str] = None
    received_at: datetime
    hydrated_keys: list[str] = Field(default_factory=list)


class DecisionRecordResponse(BaseModel):
    application_id: str
    decision_id: str
    outcome: DecisionOutcome
    confidence: float
    payload: dict[str, Any] = Field(default_factory=dict)
    written_at: datetime
    written_by: str
    record_id: UUID


class OverrideRequest(BaseModel):
    trace_id: UUID
    reviewer_id: str
    reviewer_role: str
    new_outcome: DecisionOutcome
    override_reason: str
    override_reason_code: Optional[str] = None


class OverrideResponse(BaseModel):
    trace: DecisionTrace
    learning: AgentLearning


# ─────────────────────────────────────────────────────────────────────
# POST /events — generic canonical-event ingest.
# ─────────────────────────────────────────────────────────────────────


@router.post(
    "/events",
    response_model=IngestEventResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_event(
    body: IngestEventRequest,
    platform: Platform = Depends(get_platform),
) -> IngestEventResponse:
    try:
        event = normalize_event(body.event)
    except NormalizationError as err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(err),
        ) from err

    await platform.sink(event)
    # The hydrator already ran inside the sink. Look up the keys it
    # wrote so the caller can verify the side-effect — useful when
    # composing /events posts in tests.
    hydrated = await platform.hydrator.hydrate(event)
    # hydrate() ran twice if we already re-ran it here; the second call
    # is a redundant overwrite by design — sink() may have been
    # configured without a hydrator (tests). Keep the explicit call so
    # callers always get a deterministic hydrated_keys response.

    return IngestEventResponse(
        event_id=event.event_id,
        event_type=event.event_type.value,
        application_id=event.application_id,
        customer_id=event.customer_id,
        received_at=event.received_at,
        hydrated_keys=hydrated,
    )


# ─────────────────────────────────────────────────────────────────────
# POST /connectors/webhook/{source} — push-connector entry.
# ─────────────────────────────────────────────────────────────────────


@router.post(
    "/connectors/webhook/{source}",
    response_model=IngestEventResponse,
    status_code=status.HTTP_201_CREATED,
)
async def connector_webhook(
    source: str,
    body: dict[str, Any],
    platform: Platform = Depends(get_platform),
) -> IngestEventResponse:
    """Webhook entry for sources that push to us.

    Body is the raw source-specific payload. The connector registered
    for {source} parses it via parse_raw() then funnels it through the
    same EventSink as POST /events. If no connector is registered for
    source, the body is treated as a canonical event and normalized
    directly — same path as POST /events but URL'd by source for
    operability.
    """

    connector = platform.connectors.get(source)
    if connector is None:
        # Fall back to direct normalize_event so a source with no
        # registered adapter can still POST canonical events.
        try:
            event = normalize_event(body)
        except NormalizationError as err:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"no connector registered for source {source!r} and body is "
                    f"not a canonical event: {err}"
                ),
            ) from err
        await platform.sink(event)
    else:
        try:
            event = await connector.emit(body)
        except (ConnectorError, NormalizationError) as err:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(err),
            ) from err

    hydrated = await platform.hydrator.hydrate(event)
    return IngestEventResponse(
        event_id=event.event_id,
        event_type=event.event_type.value,
        application_id=event.application_id,
        customer_id=event.customer_id,
        received_at=event.received_at,
        hydrated_keys=hydrated,
    )


# ─────────────────────────────────────────────────────────────────────
# GET /decisions/{application_id}/{decision_id} — read DecisionRecord.
# ─────────────────────────────────────────────────────────────────────


@router.get(
    "/decisions/{application_id}/{decision_id}",
    response_model=DecisionRecordResponse,
)
async def get_decision_record(
    application_id: str = Path(...),
    decision_id: str = Path(...),
    platform: Platform = Depends(get_platform),
) -> DecisionRecordResponse:
    if decision_id not in platform.spec.decision_index:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown decision_id {decision_id!r}",
        )

    record = await platform.store.get(
        "decision", f"{application_id}:{decision_id}", decision_id
    )
    if record is None or record.superseded_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"no decision record for application {application_id!r} / "
                f"decision {decision_id!r}"
            ),
        )

    value = record.value if isinstance(record.value, dict) else {}
    return DecisionRecordResponse(
        application_id=application_id,
        decision_id=decision_id,
        outcome=DecisionOutcome(value.get("outcome", "escalate")),
        confidence=float(value.get("confidence", 0.0)),
        payload=value.get("payload") or {},
        written_at=record.lineage.written_at,
        written_by=record.lineage.written_by,
        record_id=record.id,
    )


# ─────────────────────────────────────────────────────────────────────
# GET /trace/{trace_id} — read DecisionTrace.
# ─────────────────────────────────────────────────────────────────────


@router.get("/trace/{trace_id}", response_model=DecisionTrace)
async def get_trace(
    trace_id: UUID,
    platform: Platform = Depends(get_platform),
) -> DecisionTrace:
    trace = await platform.trace_writer.get(trace_id)
    if trace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"trace {trace_id} not found",
        )
    return trace


@router.get(
    "/applications/{application_id}/traces",
    response_model=list[DecisionTrace],
)
async def list_traces_for_application(
    application_id: str,
    platform: Platform = Depends(get_platform),
) -> list[DecisionTrace]:
    return await platform.trace_writer.list_for_application(application_id)


# ─────────────────────────────────────────────────────────────────────
# POST /override — capture human override, drive reflection.
# ─────────────────────────────────────────────────────────────────────


@router.post(
    "/override",
    response_model=OverrideResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_override(
    body: OverrideRequest,
    platform: Platform = Depends(get_platform),
) -> OverrideResponse:
    trace = await platform.trace_writer.get(body.trace_id)
    if trace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"trace {body.trace_id} not found",
        )

    overridden = body.new_outcome != trace.outcome
    review = HumanReview(
        reviewer_id=body.reviewer_id,
        reviewer_role=body.reviewer_role,
        original_ai_decision=trace.outcome,
        final_outcome=body.new_outcome,
        overridden=overridden,
        override_reason=body.override_reason,
        override_reason_code=body.override_reason_code,
    )

    if not overridden:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "new_outcome matches the trace's AI outcome; that is a "
                "human approval, not an override — POST a different "
                "new_outcome to capture a real override"
            ),
        )

    updated = await platform.trace_writer.attach_human_review(body.trace_id, review)
    if updated is None:
        # Should not happen: we already verified the trace exists.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="trace disappeared between read and review attach",
        )

    learning = await platform.reflection.capture(
        updated,
        review,
        similarity_tags=derive_similarity_tags(updated),
    )

    return OverrideResponse(trace=updated, learning=learning)


# ─────────────────────────────────────────────────────────────────────
# POST /applications/{application_id}/run — convenience for E2E tests.
#
# Not in the original STEP 7 list, but trivial to add and lets seed
# events drive the DAG end-to-end without standing up a separate
# scheduler. Fires the AtomicTool through the DAGExecutor for an
# application that has already had its events ingested.
# ─────────────────────────────────────────────────────────────────────


class RunResponse(BaseModel):
    application_id: str
    completed: list[str]
    skipped: list[str]
    failed: list[str]
    halted: bool
    halt_reason: Optional[str] = None
    outcomes: dict[str, DecisionOutcome] = Field(default_factory=dict)


@router.post("/applications/{application_id}/run", response_model=RunResponse)
async def run_application(
    application_id: str,
    platform: Platform = Depends(get_platform),
) -> RunResponse:
    if not platform.agents:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "no decision agents registered; register personas via "
                "Platform.register_agent() before running the DAG"
            ),
        )

    executor = platform.executor()
    result = await executor.run_application(application_id, platform.entity_resolver)
    return RunResponse(
        application_id=application_id,
        completed=result.completed_decisions,
        skipped=result.skipped_decisions,
        failed=result.failed_decisions,
        halted=result.halted,
        halt_reason=result.halt_reason,
        outcomes=result.outcomes,
    )


# ─────────────────────────────────────────────────────────────────────
# GET /audit/{audit_id}                — read one AuditRecord
# GET /audit/application/{app_id}      — list AuditRecords for an application
# GET /audit/flags                     — open warn/fail records (compliance)
# POST /audit/{audit_id}/access        — explicit access-log write
#
# Reading an AuditRecord auto-logs an access entry (PRD §23.9
# pii_access_always_logged). The InMemory store records `system` as the
# user; production swaps in the API auth context (TIER 3).
# ─────────────────────────────────────────────────────────────────────


class AccessLogRequest(BaseModel):
    user_id: str
    role: str
    action: str = "read"
    ip_hash: Optional[str] = None


@router.get("/audit/flags", response_model=list[AuditRecord])
async def list_audit_flags(
    platform: Platform = Depends(get_platform),
) -> list[AuditRecord]:
    return await platform.audit_store.list_flags()


@router.get("/audit/pii-log/recent", response_model=list[PIIAccessEntry])
async def list_recent_pii_accesses(
    limit: int = 100,
    platform: Platform = Depends(get_platform),
) -> list[PIIAccessEntry]:
    return await platform.pii_access_log.list_recent(limit=limit)


@router.get(
    "/audit/pii-log/application/{application_id}",
    response_model=list[PIIAccessEntry],
)
async def list_pii_accesses_for_application(
    application_id: str,
    platform: Platform = Depends(get_platform),
) -> list[PIIAccessEntry]:
    return await platform.pii_access_log.list_for_application(application_id)


# ─────────────────────────────────────────────────────────────────────
# Audit log export — PRD §19 TIER 4. Streams CSV / JSONL of every
# audit_record matching the filter. Examiners ingest the CSV; we keep
# JSONL on the same path for re-ingestable downstream tooling.
# ─────────────────────────────────────────────────────────────────────


def _parse_status_filter(only: Optional[str]) -> Optional[list[CheckStatus]]:
    if not only:
        return None
    out: list[CheckStatus] = []
    for token in (t.strip() for t in only.split(",") if t.strip()):
        try:
            out.append(CheckStatus(token))
        except ValueError as err:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"unknown status {token!r} in `only`; expected "
                    f"comma-separated subset of pass/warn/fail"
                ),
            ) from err
    return out


def _parse_iso(s: Optional[str], field: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field} must be ISO-8601 (got {s!r})",
        ) from err


async def _gather_records(platform: Platform) -> list[AuditRecord]:
    # InMemoryAuditStore exposes _records dict; production swap will
    # add a list_all() method or a paged iterator. For TIER 4 export
    # against InMemory the dict is fine.
    records_attr = getattr(platform.audit_store, "_records", None)
    if isinstance(records_attr, dict):
        return list(records_attr.values())
    # Fallback: walk every application_id we know about. Unused in v0
    # but keeps the contract honest if the store doesn't expose _records.
    out: list[AuditRecord] = []
    return out


@router.get("/audit/export.csv")
async def export_audit_csv(
    decision_type: Optional[str] = None,
    only: Optional[str] = None,
    after: Optional[str] = None,
    before: Optional[str] = None,
    platform: Platform = Depends(get_platform),
) -> StreamingResponse:
    """Stream every audit record as CSV. Filters:
      decision_type=lead_scoring,credit_assessment,...   (comma list)
      only=warn,fail                                     (status filter)
      after=2026-01-01T00:00:00                          (ISO-8601)
      before=2026-12-31T23:59:59                         (ISO-8601)
    """

    records = await _gather_records(platform)
    types = (
        [t.strip() for t in decision_type.split(",") if t.strip()]
        if decision_type else None
    )
    chunks = export_csv(
        records,
        window_start=_parse_iso(after, "after"),
        window_end=_parse_iso(before, "before"),
        decision_types=types,
        status_filter=_parse_status_filter(only),
    )
    return StreamingResponse(
        chunks,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="audit_records.csv"'},
    )


@router.get("/audit/export.jsonl")
async def export_audit_jsonl(
    decision_type: Optional[str] = None,
    only: Optional[str] = None,
    after: Optional[str] = None,
    before: Optional[str] = None,
    platform: Platform = Depends(get_platform),
) -> StreamingResponse:
    """Same filters as /audit/export.csv but emits JSONL (one record
    per line) preserving nested structure for re-ingestable tooling."""

    records = await _gather_records(platform)
    types = (
        [t.strip() for t in decision_type.split(",") if t.strip()]
        if decision_type else None
    )
    chunks = export_jsonl(
        records,
        window_start=_parse_iso(after, "after"),
        window_end=_parse_iso(before, "before"),
        decision_types=types,
        status_filter=_parse_status_filter(only),
    )
    return StreamingResponse(
        chunks,
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="audit_records.jsonl"'},
    )


@router.get(
    "/audit/application/{application_id}",
    response_model=list[AuditRecord],
)
async def list_audit_records_for_application(
    application_id: str,
    platform: Platform = Depends(get_platform),
) -> list[AuditRecord]:
    return await platform.audit_store.list_for_application(application_id)


@router.get("/audit/{audit_id}", response_model=AuditRecord)
async def get_audit_record(
    audit_id: UUID,
    platform: Platform = Depends(get_platform),
) -> AuditRecord:
    record = await platform.audit_store.get(audit_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"audit record {audit_id} not found",
        )
    await platform.audit_store.log_access(
        audit_id,
        AccessRecord(user_id="system", role="system", action="read"),
    )
    return record


@router.get(
    "/audit/{audit_id}/adverse-action",
    response_model=AdverseActionNotice,
)
async def get_adverse_action_notice(
    audit_id: UUID,
    platform: Platform = Depends(get_platform),
) -> AdverseActionNotice:
    """Generate the ECOA / FCRA §615 notice for a declined / failed
    audit record. Returns 404 when the record doesn't exist; returns
    409 when the underlying decision is not an adverse action (an
    approved or recommended decision has nothing to send)."""

    record = await platform.audit_store.get(audit_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"audit record {audit_id} not found",
        )
    if not is_adverse_action(record):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"audit record {audit_id} is not an adverse action "
                f"(decision_output={record.decision_output.value!r}, "
                f"overall_status={record.overall_status.value!r}); "
                f"no notice required"
            ),
        )
    trace = await platform.trace_writer.get(record.decision_id)
    if trace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"trace {record.decision_id} not found for audit {audit_id}",
        )
    # Best-effort applicant lookup (system-wide) so the notice
    # carries the applicant's name.
    applicant_value = None
    try:
        ids = await platform.entity_resolver("Applicant", record.application_id)
        if ids:
            ar = await platform.store.get("Applicant", ids[0])
            if ar is not None and isinstance(ar.value, dict):
                applicant_value = ar.value
    except Exception:
        applicant_value = None
    return generate_notice(record, trace, applicant_value=applicant_value)


@router.post(
    "/audit/{audit_id}/access",
    response_model=list[AccessRecord],
    status_code=status.HTTP_201_CREATED,
)
async def post_audit_access(
    audit_id: UUID,
    body: AccessLogRequest,
    platform: Platform = Depends(get_platform),
) -> list[AccessRecord]:
    try:
        await platform.audit_store.log_access(
            audit_id,
            AccessRecord(
                user_id=body.user_id,
                role=body.role,
                action=body.action,
                ip_hash=body.ip_hash,
            ),
        )
    except KeyError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(err) or f"audit record {audit_id} not found",
        ) from err
    return await platform.audit_store.access_log(audit_id)


# ─────────────────────────────────────────────────────────────────────
# Outcome tracker — PRD STEP 12. Post-decision ground-truth feed.
#
# POST /outcomes                             — capture an OutcomeRecord
# GET  /outcomes/application/{id}            — full history for an app
# GET  /outcomes/application/{id}/correlate  — join the underwriting
#                                              decision trace with the
#                                              outcome trajectory
# ─────────────────────────────────────────────────────────────────────


class CaptureOutcomeRequest(BaseModel):
    application_id: str
    outcome_type: OutcomeType
    occurred_at: Optional[datetime] = None
    source: str = "manual"
    reason: Optional[str] = None
    amount: Optional[float] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.post(
    "/outcomes",
    response_model=OutcomeRecord,
    status_code=status.HTTP_201_CREATED,
)
async def capture_outcome(
    body: CaptureOutcomeRequest,
    platform: Platform = Depends(get_platform),
) -> OutcomeRecord:
    record = OutcomeRecord(
        application_id=body.application_id,
        outcome_type=body.outcome_type,
        occurred_at=body.occurred_at,
        source=body.source,
        reason=body.reason,
        amount=body.amount,
        metadata=body.metadata,
    )
    await platform.outcome_tracker.capture(record)
    return record


@router.get(
    "/outcomes/application/{application_id}",
    response_model=list[OutcomeRecord],
)
async def list_outcomes_for_application(
    application_id: str,
    platform: Platform = Depends(get_platform),
) -> list[OutcomeRecord]:
    return await platform.outcome_tracker.list_for_application(application_id)


@router.get(
    "/outcomes/application/{application_id}/correlate",
    response_model=DecisionOutcomeCorrelation,
)
async def correlate_outcomes(
    application_id: str,
    decision_id: str = "underwriting_decision",
    platform: Platform = Depends(get_platform),
) -> DecisionOutcomeCorrelation:
    """Join the named DecisionTrace with the captured outcomes for
    this application. Defaults to underwriting_decision since that's
    the trace most regulators / risk teams correlate against."""

    traces = await platform.trace_writer.list_for_application(application_id)
    trace = next((t for t in traces if t.decision_id == decision_id), None)
    if trace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"no {decision_id!r} trace for application {application_id!r}"
            ),
        )
    outcomes = await platform.outcome_tracker.list_for_application(application_id)
    return correlate(
        application_id,
        decision_id=decision_id,
        decision_outcome=trace.outcome.value,
        decision_confidence=trace.confidence,
        decision_at=trace.started_at,
        outcomes=outcomes,
    )


__all__ = ["router", "get_platform"]
