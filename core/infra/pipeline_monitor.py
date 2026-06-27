"""IN-C — pipeline observability: watermark staleness + DLQ depth + CloudWatch sink.

Makes the "15-minute mystery" (a silently stalled pipeline — usually the degraded-RDS
hang CI-B bounded) VISIBLE: a watermark (last time the pipeline produced a decision)
whose age crosses a threshold flags stale/stalled, the DLQ depth surfaces stuck
failures, and a CloudWatch metric sink emits the numbers (graceful no-op without AWS,
the S3/IN-A pattern). Complements core/audit/alerts.py's AlertSink.

Pure evaluation (evaluate_watermark / assess_pipeline_health) is DB-free + unit-
tested; the fetch helpers + the metric sink hold the I/O. Read-only,
decision-path-inert -> 16/16 by construction.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Ops thresholds (NOT lending values): pipeline-idle tolerance. The 900s "stalled"
# band is the 15-minute mystery alarm. Overridable per call.
DEFAULT_STALE_SEC = 300       # 5 min — idle, watch
DEFAULT_STALLED_SEC = 900     # 15 min — likely stuck, alarm


def _parse_iso(v) -> Optional[datetime]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def evaluate_watermark(last_processed, now=None,
                       stale_sec: int = DEFAULT_STALE_SEC,
                       stalled_sec: int = DEFAULT_STALLED_SEC) -> dict:
    """Pure: classify pipeline freshness from the last-processed timestamp.
    healthy < stale_sec <= stale < stalled_sec <= stalled. RULE 11."""
    now_dt = _parse_iso(now) or datetime.now(timezone.utc)
    last_dt = _parse_iso(last_processed)
    if last_dt is None:
        return {"status": "unknown", "age_seconds": None, "last_processed": None,
                "thresholds": {"stale_sec": stale_sec, "stalled_sec": stalled_sec},
                "data_source": "decision_outputs.created_at (MAX)",
                "missing_inputs": ["no last-processed timestamp — pipeline has produced "
                                   "no decisions for this tenant (or watermark unavailable)"]}
    age = round((now_dt - last_dt).total_seconds(), 1)
    if age >= stalled_sec:
        status, note = "stalled", (f"No decision produced in {age:.0f}s (>= {stalled_sec}s) — "
                                   "likely a stalled consumer or a stuck RDS call; investigate.")
    elif age >= stale_sec:
        status, note = "stale", f"No decision in {age:.0f}s (>= {stale_sec}s) — pipeline idle; watch."
    else:
        status, note = "healthy", None
    return {"status": status, "age_seconds": age, "last_processed": last_dt.isoformat(),
            "thresholds": {"stale_sec": stale_sec, "stalled_sec": stalled_sec},
            "note": note, "data_source": "decision_outputs.created_at (MAX)", "missing_inputs": []}


def assess_pipeline_health(watermark: dict, dlq_depth: Optional[int] = None,
                           poll_stats: Optional[dict] = None) -> dict:
    """Pure: combine watermark + DLQ depth into an overall pipeline-health report."""
    wm_status = (watermark or {}).get("status", "unknown")
    findings = []
    if wm_status == "stalled":
        findings.append("watermark stalled — pipeline not producing decisions")
    elif wm_status == "stale":
        findings.append("watermark stale — pipeline idle")
    if dlq_depth:
        findings.append(f"{dlq_depth} message(s) in the DLQ — failed events need inspection")

    if wm_status == "stalled":
        overall = "stalled"
    elif findings:
        overall = "degraded"
    elif wm_status == "unknown":
        overall = "unknown"
    else:
        overall = "healthy"

    action = {
        "stalled": "Page on-call: restart/inspect the consumer; check RDS connectivity.",
        "degraded": "Review the DLQ and watermark age; drain the DLQ after fixing root cause.",
        "unknown": "No recent decisions — confirm the consumer is configured + running.",
        "healthy": "No action.",
    }[overall]

    missing = list((watermark or {}).get("missing_inputs", []))
    if dlq_depth is None:
        missing.append("DLQ depth unavailable (SQS unconfigured) — DLQ health not assessed")
    return {
        "overall_status": overall, "watermark": watermark,
        "dlq_depth": dlq_depth, "poll_stats": poll_stats, "findings": findings,
        "recommended_action": action,
        "note": ("Observability only — read-only, decision-path-inert. A 'stalled' "
                 "watermark is the 15-minute-mystery alarm (often the degraded-RDS hang)."),
        "data_source": "decision_outputs.created_at + SQS DLQ depth",
        "missing_inputs": missing,
    }


class CloudWatchMetricSink:
    """Emit pipeline metrics to CloudWatch via an injectable client. Graceful no-op
    when AWS is unconfigured (the S3/IN-A pattern)."""

    def __init__(self, client=None, namespace: str = "Accord/Pipeline"):
        self._client = client
        self._namespace = namespace

    @property
    def _cw(self):
        if self._client is not None:
            return self._client
        try:
            import boto3
            return boto3.client("cloudwatch")
        except Exception:
            return None

    def emit(self, metrics: dict, dimensions: Optional[dict] = None) -> dict:
        """metrics: {name: value}. Returns {emitted, count}. No-op without AWS."""
        cw = self._cw
        if cw is None or not metrics:
            return {"emitted": False, "count": 0,
                    "note": "CloudWatch unconfigured — metrics not emitted (no-op)."}
        dims = [{"Name": k, "Value": str(v)} for k, v in (dimensions or {}).items()]
        data = [{"MetricName": str(n), "Value": float(v), "Dimensions": dims}
                for n, v in metrics.items() if v is not None]
        try:
            cw.put_metric_data(Namespace=self._namespace, MetricData=data)
            return {"emitted": True, "count": len(data), "namespace": self._namespace}
        except Exception as e:  # noqa: BLE001
            logger.warning("[CloudWatch] put_metric_data failed: %s", e)
            return {"emitted": False, "count": 0, "error": str(e)}


async def fetch_pipeline_watermark(conn, tenant_id: str):
    """Last time the pipeline produced a decision for this tenant (the watermark)."""
    return await conn.fetchval(
        "SELECT MAX(created_at) FROM decision_outputs WHERE tenant_id=$1", tenant_id)


def fetch_dlq_depth(sqs_client, dlq_url: str) -> Optional[int]:
    """ApproximateNumberOfMessages on the DLQ; None when SQS/DLQ unconfigured."""
    if not sqs_client or not dlq_url:
        return None
    try:
        resp = sqs_client.get_queue_attributes(
            QueueUrl=dlq_url, AttributeNames=["ApproximateNumberOfMessages"])
        return int(resp.get("Attributes", {}).get("ApproximateNumberOfMessages", 0))
    except Exception as e:  # noqa: BLE001
        logger.warning("[SQS] DLQ depth fetch failed: %s", e)
        return None


__all__ = ["evaluate_watermark", "assess_pipeline_health", "CloudWatchMetricSink",
           "fetch_pipeline_watermark", "fetch_dlq_depth",
           "DEFAULT_STALE_SEC", "DEFAULT_STALLED_SEC"]
