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
    decision_detail,
    list_applications,
    queue_view,
    templates,
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
        {
            "request": request,
            "items": queue_view(platform),
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


__all__ = ["router"]
