"""Accord — infrastructure management endpoints (SQS consumer status / manual poll).

Read-only status + an admin-triggered single poll. Decision-path-inert (the consumer
only triggers the existing pipeline). No-op + honest status when AWS is unconfigured.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.accord.auth import get_current_user, get_tenant_id
from api.accord.pipeline import _get_pool, _require_db

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


@router.get("/pipeline-health")
async def pipeline_health(tenant_id: str = Depends(get_tenant_id),
                          user: dict = Depends(get_current_user)) -> dict:
    """Pipeline observability (IN-C): watermark staleness (last decision produced) +
    DLQ depth -> overall health. A 'stalled' watermark is the 15-minute-mystery alarm.
    Read-only; emits CloudWatch metrics best-effort (no-op without AWS). Admin/compliance."""
    if user.get("role") not in ("admin", "compliance", "super_admin"):
        raise HTTPException(403, "Admin or compliance access required")
    _require_db()
    from core.infra.pipeline_monitor import (
        CloudWatchMetricSink, assess_pipeline_health, evaluate_watermark,
        fetch_dlq_depth, fetch_pipeline_watermark)
    from core.infra.sqs_consumer import SQSConsumer
    pool = await _get_pool()
    async with pool.acquire() as conn:
        last_processed = await fetch_pipeline_watermark(conn, tenant_id)
    consumer = SQSConsumer()
    dlq_depth = fetch_dlq_depth(consumer._sqs if consumer.is_configured() else None,
                                consumer._dlq_url)
    watermark = evaluate_watermark(last_processed)
    report = assess_pipeline_health(watermark, dlq_depth=dlq_depth)
    # best-effort metric emission (no-op without AWS)
    report["metrics_emitted"] = CloudWatchMetricSink().emit(
        {"WatermarkAgeSeconds": watermark.get("age_seconds"), "DLQDepth": dlq_depth},
        dimensions={"tenant_id": tenant_id})
    return report


__all__ = ["router"]
