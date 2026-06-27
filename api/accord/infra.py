"""Accord — infrastructure management endpoints (SQS consumer status / manual poll).

Read-only status + an admin-triggered single poll. Decision-path-inert (the consumer
only triggers the existing pipeline). No-op + honest status when AWS is unconfigured.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.accord.auth import get_current_user

router = APIRouter(prefix="/api/accord/infra", tags=["accord-infra"])


@router.get("/sqs-status")
async def sqs_status(user: dict = Depends(get_current_user)) -> dict:
    """SQS consumer configuration status (no secrets). Admin/super_admin."""
    if user.get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin access required")
    from core.infra.sqs_consumer import SQSConsumer
    return SQSConsumer().status()


@router.post("/sqs-poll")
async def sqs_poll(user: dict = Depends(get_current_user)) -> dict:
    """Trigger a single SQS poll manually (useful without a running consumer).
    Returns not_configured when AWS/queue unset. Admin/super_admin."""
    if user.get("role") not in ("admin", "super_admin"):
        raise HTTPException(403, "Admin access required")
    from core.infra.sqs_consumer import SQSConsumer
    return await SQSConsumer().poll_once()


__all__ = ["router"]
