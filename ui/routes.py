from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Path, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from api.deps import Platform
from api.routes import get_platform
from core.normalizer.models import DecisionOutcome
from core.trace import HumanReview, derive_similarity_tags

from .views import (
    application_detail,
    audit_record_detail,
    decision_detail,
    document_detail_view,
    list_applications,
    list_audit_flags,
    list_audit_for_application,
    list_documents_for_application,
    list_pending_claims,
    list_persona_workbenches,
    list_policies,
    list_workbenches,
    persona_workbench_view,
    policy_version_detail,
    queue_view,
    templates,
    workbench_view,
)


router = APIRouter(tags=["ui"])


@router.get("/", response_class=HTMLResponse)
async def home(request: Request, platform: Platform = Depends(get_platform)):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "applications": list_applications(platform),
            "domain": platform.spec.domain,
            "version": platform.spec.version,
            "agent_count": len(platform.agents),
        },
    )


@router.get("/ui/applications/{application_id}", response_class=HTMLResponse)
async def application_view(
    application_id: str,
    request: Request,
    platform: Platform = Depends(get_platform),
):
    detail = application_detail(platform, application_id)
    if detail is None or not detail.get("waves"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown application {application_id!r}",
        )
    return templates.TemplateResponse(
        "application.html",
        {"request": request, **detail},
    )


@router.get(
    "/ui/applications/{application_id}/decisions/{decision_id}",
    response_class=HTMLResponse,
)
async def decision_view(
    application_id: str,
    decision_id: str,
    request: Request,
    platform: Platform = Depends(get_platform),
):
    detail = decision_detail(platform, application_id, decision_id)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown decision_id {decision_id!r}",
        )
    return templates.TemplateResponse(
        "decision.html",
        {"request": request, **detail},
    )


@router.get("/ui/queue", response_class=HTMLResponse)
async def queue_view_route(
    request: Request,
    platform: Platform = Depends(get_platform),
):
    return templates.TemplateResponse(
        "queue.html",
        {"request": request, **queue_view(platform)},
    )


# ─────────────────────────────────────────────────────────────────────
# Policy inspection — index + detail
# ─────────────────────────────────────────────────────────────────────


@router.get("/ui/policies", response_class=HTMLResponse)
async def policy_index_route(
    request: Request,
    platform: Platform = Depends(get_platform),
):
    return templates.TemplateResponse(
        "policy_index.html",
        {"request": request, **list_policies(platform)},
    )


@router.get(
    "/ui/policies/{policy_version_id:path}",
    response_class=HTMLResponse,
)
async def policy_detail_route(
    policy_version_id: str,
    request: Request,
    platform: Platform = Depends(get_platform),
):
    detail = policy_version_detail(platform, policy_version_id)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown policy_version {policy_version_id!r}",
        )
    return templates.TemplateResponse(
        "policy_detail.html",
        {"request": request, **detail},
    )


# ─────────────────────────────────────────────────────────────────────
# Document inspection — per-app list + single-doc detail
# ─────────────────────────────────────────────────────────────────────


@router.get(
    "/ui/applications/{application_id}/documents",
    response_class=HTMLResponse,
)
async def documents_index_route(
    application_id: str,
    request: Request,
    platform: Platform = Depends(get_platform),
):
    return templates.TemplateResponse(
        "documents_index.html",
        {
            "request": request,
            **list_documents_for_application(platform, application_id),
        },
    )


@router.get("/ui/documents/{document_id}", response_class=HTMLResponse)
async def document_detail_route(
    document_id: str,
    request: Request,
    platform: Platform = Depends(get_platform),
):
    detail = document_detail_view(platform, document_id)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown document {document_id!r}",
        )
    return templates.TemplateResponse(
        "document_detail.html",
        {"request": request, **detail},
    )


# ─────────────────────────────────────────────────────────────────────
# Pending claims queue + verify/reject
# ─────────────────────────────────────────────────────────────────────


@router.get("/ui/claims/pending", response_class=HTMLResponse)
async def claims_pending_route(
    request: Request,
    platform: Platform = Depends(get_platform),
):
    return templates.TemplateResponse(
        "claims_pending.html",
        {"request": request, **list_pending_claims(platform)},
    )


@router.post("/ui/claims/{claim_id}/verify", response_class=HTMLResponse)
async def claim_verify_route(
    claim_id: str,
    request: Request,
    platform: Platform = Depends(get_platform),
    reviewer_id: str = Form(...),
    reviewer_role: str = Form(...),
):
    knowledge_store = getattr(platform, "knowledge_store", None)
    if knowledge_store is None:
        raise HTTPException(status_code=503, detail="knowledge store unavailable")
    updated = await knowledge_store.verify_claim(
        claim_id, reviewer_id=reviewer_id, reviewer_role=reviewer_role
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=f"claim {claim_id} not found")
    # Redirect back to the pending queue.
    return RedirectResponse(
        url="/ui/claims/pending",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/ui/claims/{claim_id}/reject", response_class=HTMLResponse)
async def claim_reject_route(
    claim_id: str,
    request: Request,
    platform: Platform = Depends(get_platform),
    reviewer_id: str = Form(...),
    reviewer_role: str = Form(...),
    reason: Optional[str] = Form(None),
):
    knowledge_store = getattr(platform, "knowledge_store", None)
    if knowledge_store is None:
        raise HTTPException(status_code=503, detail="knowledge store unavailable")
    updated = await knowledge_store.reject_claim(
        claim_id,
        reviewer_id=reviewer_id,
        reviewer_role=reviewer_role,
        reason=reason,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=f"claim {claim_id} not found")
    return RedirectResponse(
        url="/ui/claims/pending",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ─────────────────────────────────────────────────────────────────────
# Workbench — operator-centric view per owner_team
# ─────────────────────────────────────────────────────────────────────


@router.get("/ui/workbench", response_class=HTMLResponse)
async def workbench_index(
    request: Request,
    platform: Platform = Depends(get_platform),
):
    return templates.TemplateResponse(
        "workbench_index.html",
        {
            "request": request,
            "workbenches": list_workbenches(platform),
        },
    )


@router.get("/ui/workbench/{owner_team}", response_class=HTMLResponse)
async def workbench(
    owner_team: str,
    request: Request,
    application_id: Optional[str] = None,
    platform: Platform = Depends(get_platform),
):
    detail = workbench_view(platform, owner_team, application_id)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown owner_team {owner_team!r}",
        )
    return templates.TemplateResponse(
        "workbench.html",
        {"request": request, **detail},
    )


# ─────────────────────────────────────────────────────────────────────
# Persona workbench — one route per persona, plus 3 action endpoints
# (Approve / Decline / Request evidence). Each action returns the
# refreshed _persona_detail partial via HTMX.
# ─────────────────────────────────────────────────────────────────────


@router.get("/ui/personas", response_class=HTMLResponse)
async def personas_index(
    request: Request,
    platform: Platform = Depends(get_platform),
):
    return templates.TemplateResponse(
        "persona_index.html",
        {
            "request": request,
            "personas": list_persona_workbenches(platform),
        },
    )


@router.get("/ui/personas/{decision_id}", response_class=HTMLResponse)
async def persona_workbench(
    decision_id: str,
    request: Request,
    application_id: Optional[str] = None,
    time_range: str = "quarter",
    tab: str = "workbench",
    platform: Platform = Depends(get_platform),
):
    detail = persona_workbench_view(
        platform,
        decision_id,
        application_id=application_id or None,
        time_range=time_range,
        tab=tab,
    )
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown decision_id {decision_id!r}",
        )
    return templates.TemplateResponse(
        "persona_workbench.html",
        {"request": request, **detail},
    )


def _persona_detail_response(
    request: Request,
    platform: Platform,
    decision_id: str,
    application_id: str,
    *,
    flash: Optional[dict[str, str]] = None,
):
    """Render the right-column partial for HTMX swaps. Used by all three
    action endpoints so the rest of the page stays put."""

    detail = persona_workbench_view(
        platform, decision_id, application_id=application_id
    )
    if detail is None or detail.get("focused") is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="persona detail not available",
        )
    if flash is not None:
        detail["focused"]["flash"] = flash
    return templates.TemplateResponse(
        "_persona_detail.html",
        {"request": request, **detail},
    )


@router.post(
    "/ui/personas/{decision_id}/applications/{application_id}/ack",
    response_class=HTMLResponse,
)
async def persona_ack(
    decision_id: str,
    application_id: str,
    request: Request,
    platform: Platform = Depends(get_platform),
    trace_id: UUID = Form(...),
    reviewer_id: str = Form(...),
    reviewer_role: str = Form(...),
):
    """Positive ack — operator confirms the AI's outcome. Records a
    HumanReview with overridden=False and final_outcome == AI's
    original. No AgentLearning is captured (reflection refuses
    non-overrides — by design)."""

    trace = await platform.trace_writer.get(trace_id)
    if trace is None or trace.application_id != application_id or trace.decision_id != decision_id:
        raise HTTPException(status_code=404, detail="trace not found")

    review = HumanReview(
        reviewer_id=reviewer_id,
        reviewer_role=reviewer_role,
        original_ai_decision=trace.outcome,
        final_outcome=trace.outcome,
        overridden=False,
        notes="approved from persona workbench",
    )
    await platform.trace_writer.attach_human_review(trace_id, review)

    # Dequeue the corresponding queue item if one exists. Idempotent —
    # missing item returns None, no error.
    item = await platform.human_queue.find_open(
        application_id=application_id, decision_id=decision_id
    )
    if item is not None:
        await platform.human_queue.resolve(
            item.id,
            resolution="approve",
            reviewer_id=reviewer_id,
            reviewer_role=reviewer_role,
        )

    return _persona_detail_response(
        request, platform, decision_id, application_id,
        flash={
            "tone": "success",
            "message": (
                f"Approved · AI's {trace.outcome.value} outcome confirmed by "
                f"{reviewer_role}."
            ),
        },
    )


@router.post(
    "/ui/personas/{decision_id}/applications/{application_id}/decline",
    response_class=HTMLResponse,
)
async def persona_decline(
    decision_id: str,
    application_id: str,
    request: Request,
    platform: Platform = Depends(get_platform),
    trace_id: UUID = Form(...),
    reviewer_id: str = Form(...),
    reviewer_role: str = Form(...),
):
    """Decline — override the AI's outcome to BLOCK. Runs the full
    reflection capture so the persona learns from the decline."""

    trace = await platform.trace_writer.get(trace_id)
    if trace is None or trace.application_id != application_id or trace.decision_id != decision_id:
        raise HTTPException(status_code=404, detail="trace not found")

    if trace.outcome == DecisionOutcome.BLOCK:
        return _persona_detail_response(
            request, platform, decision_id, application_id,
            flash={
                "tone": "error",
                "message": "AI already produced a block outcome — nothing to decline.",
            },
        )

    review = HumanReview(
        reviewer_id=reviewer_id,
        reviewer_role=reviewer_role,
        original_ai_decision=trace.outcome,
        final_outcome=DecisionOutcome.BLOCK,
        overridden=True,
        override_reason=f"Declined from {reviewer_role} workbench",
        override_reason_code="manual_decline",
    )
    updated = await platform.trace_writer.attach_human_review(trace_id, review)
    await platform.reflection.capture(
        updated, review, similarity_tags=derive_similarity_tags(updated)
    )

    # Dequeue. Same idempotent pattern as ack.
    item = await platform.human_queue.find_open(
        application_id=application_id, decision_id=decision_id
    )
    if item is not None:
        await platform.human_queue.resolve(
            item.id,
            resolution="decline",
            reviewer_id=reviewer_id,
            reviewer_role=reviewer_role,
        )

    return _persona_detail_response(
        request, platform, decision_id, application_id,
        flash={
            "tone": "error",
            "message": (
                f"Declined · AI proposed {trace.outcome.value}; final outcome "
                f"set to block. Reflection captured for next similar event."
            ),
        },
    )


@router.post(
    "/ui/personas/{decision_id}/applications/{application_id}/send_back",
    response_class=HTMLResponse,
)
async def persona_send_back(
    decision_id: str,
    application_id: str,
    request: Request,
    platform: Platform = Depends(get_platform),
    trace_id: Optional[UUID] = Form(None),
):
    """Stub for the planned send_back outcome (PRD §13). Records nothing
    today — backend support arrives in TIER 6."""

    return _persona_detail_response(
        request, platform, decision_id, application_id,
        flash={
            "tone": "info",
            "message": (
                "Request evidence — send_back routes to upstream personas. "
                "Backend support is planned in TIER 6 (PRD §13). For now this "
                "is a no-op; use the cross-application override on the full "
                "trace if you need to re-run upstream."
            ),
        },
    )


# ─────────────────────────────────────────────────────────────────────
# Override form submit — HTMX target replaces the override card with
# the post-override view (human_review attached + AgentLearning).
# ─────────────────────────────────────────────────────────────────────


@router.post(
    "/ui/applications/{application_id}/decisions/{decision_id}/override",
    response_class=HTMLResponse,
)
async def submit_override(
    application_id: str,
    decision_id: str,
    request: Request,
    platform: Platform = Depends(get_platform),
    trace_id: UUID = Form(...),
    reviewer_id: str = Form(...),
    reviewer_role: str = Form(...),
    new_outcome: str = Form(...),
    override_reason: str = Form(...),
    override_reason_code: Optional[str] = Form(None),
):
    trace = await platform.trace_writer.get(trace_id)
    if trace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="trace not found"
        )

    try:
        new_outcome_enum = DecisionOutcome(new_outcome)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid outcome {new_outcome!r}",
        )

    overridden = new_outcome_enum != trace.outcome
    if not overridden:
        # Re-render the form with an inline error — same partial,
        # different message. Keeps the user in place.
        detail = decision_detail(platform, application_id, decision_id)
        return templates.TemplateResponse(
            "_override_card.html",
            {
                "request": request,
                **(detail or {}),
                "error": (
                    "new_outcome matches the AI's outcome — pick a different "
                    "outcome to record an override, or skip the form to "
                    "leave the queued decision pending."
                ),
            },
        )

    review = HumanReview(
        reviewer_id=reviewer_id,
        reviewer_role=reviewer_role,
        original_ai_decision=trace.outcome,
        final_outcome=new_outcome_enum,
        overridden=overridden,
        override_reason=override_reason,
        override_reason_code=override_reason_code,
    )
    updated = await platform.trace_writer.attach_human_review(trace_id, review)
    learning = await platform.reflection.capture(
        updated, review, similarity_tags=derive_similarity_tags(updated)
    )

    detail = decision_detail(platform, application_id, decision_id)
    return templates.TemplateResponse(
        "_override_result.html",
        {
            "request": request,
            **(detail or {}),
            "learning": learning,
        },
    )


# ─────────────────────────────────────────────────────────────────────
# Audit — flag queue + per-record drilldown
# ─────────────────────────────────────────────────────────────────────


@router.get("/ui/audit/flags", response_class=HTMLResponse)
async def audit_flags_route(
    request: Request,
    platform: Platform = Depends(get_platform),
):
    return templates.TemplateResponse(
        "audit_flags.html",
        {"request": request, **list_audit_flags(platform)},
    )


@router.get("/ui/audit/{audit_id}", response_class=HTMLResponse)
async def audit_record_route(
    audit_id: str,
    request: Request,
    platform: Platform = Depends(get_platform),
):
    detail = audit_record_detail(platform, audit_id)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown audit_id {audit_id!r}",
        )
    return templates.TemplateResponse(
        "audit_detail.html",
        {"request": request, **detail},
    )


__all__ = ["router"]
