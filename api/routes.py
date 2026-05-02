from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from pydantic import BaseModel, Field

from core.connectors import ConnectorError
from core.normalizer.models import (
    BaseEvent,
    DecisionOutcome,
    NormalizationError,
    normalize_event,
)
from core.trace import (
    AgentLearning,
    DecisionTrace,
    HumanReview,
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


__all__ = ["router", "get_platform"]
