"""
Decision Trace API — TR-C

GET   /api/accord/trace/{application_id}          full decision trace
GET   /api/accord/trace/{application_id}/summary  human-readable workbench summary
GET   /api/accord/trace/{application_id}/export   regulator / repurchase JSON export
GET   /api/accord/trace/{application_id}/audit    audit log (who did what when)
POST  /api/accord/trace/{application_id}/review    UW attaches review notes

Conventions match the rest of the Accord API: tenant from the JWT
(get_tenant_id), DB via _require_db()/_get_pool(), router under /api/accord
(registered in api/accord/__init__.py) — not the spec's request.app.state.pool /
query-param tenant. Reads decision_trace (TR-A/TR-B), loan_condition_instances,
fraud_signals, decision_audit_log.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.accord.auth import get_tenant_id
from api.accord.pipeline import _get_pool, _require_db

router = APIRouter(prefix="/api/accord/trace", tags=["accord-trace"])


class ReviewRequest(BaseModel):
    reviewer: str
    review_notes: str
    outcome_confirmed: bool = True


OUTCOME_DISPLAY = {
    "approve": "✅ Approve",
    "approve_with_conditions": "✅ Approve with Conditions",
    "escalate": "⚠️ Escalate to UW",
    "block": "🚫 Block",
    "refer": "↗️ Refer",
    "incomplete": "⏳ Incomplete",
}


def _safe(v: Any) -> Any:
    """JSON-safe: datetime->iso, Decimal->float, jsonb str->parsed."""
    if isinstance(v, Decimal):
        return float(v)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


def _row(r: Any) -> dict:
    return {k: _safe(v) for k, v in dict(r).items()}


def _jsonb(v: Any) -> Any:
    if isinstance(v, (dict, list)) or v is None:
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (ValueError, TypeError):
            return v
    return v


async def _latest_trace(conn, application_id: str, tenant_id: str):
    return await conn.fetchrow(
        """
        SELECT * FROM decision_trace
        WHERE application_id = $1 AND tenant_id = $2
        AND superseded_by IS NULL
        ORDER BY created_at DESC LIMIT 1
        """,
        application_id,
        tenant_id,
    )


@router.get("/{application_id}")
async def get_trace(
    application_id: str,
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Full decision trace."""
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await _latest_trace(conn, application_id, tenant_id)
        if not row:
            raise HTTPException(
                status_code=404, detail=f"No trace for {application_id}"
            )
        out = _row(row)
        # Expand jsonb columns into objects.
        for k in (
            "input_snapshot", "persona_traces", "policy_trace",
            "evidence_trace", "conditions_snapshot",
        ):
            if k in out:
                out[k] = _jsonb(out[k])
        return out


@router.get("/{application_id}/summary")
async def get_trace_summary(
    application_id: str,
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Human-readable summary for the workbench."""
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                dt.application_id, dt.final_outcome, dt.outcome_reason,
                dt.confidence_score, dt.loan_amount, dt.ltv, dt.dti,
                dt.credit_score, dt.loan_type, dt.decided_at,
                dt.reviewed_by, dt.reviewed_at,
                jsonb_array_length(dt.conditions_snapshot) AS condition_count,
                (SELECT COUNT(*) FROM decision_audit_log dal
                   WHERE dal.application_id = dt.application_id
                   AND dal.tenant_id = dt.tenant_id) AS audit_event_count,
                (SELECT COUNT(*) FROM fraud_signals fs
                   WHERE fs.application_id = dt.application_id
                   AND fs.tenant_id = dt.tenant_id
                   AND fs.resolved = false) AS fraud_signal_count
            FROM decision_trace dt
            WHERE dt.application_id = $1 AND dt.tenant_id = $2
            AND dt.superseded_by IS NULL
            ORDER BY dt.created_at DESC LIMIT 1
            """,
            application_id,
            tenant_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="No trace found")
        r = dict(row)
        outcome = r["final_outcome"] or "unknown"
        return {
            "application_id": application_id,
            "outcome": outcome,
            "outcome_display": OUTCOME_DISPLAY.get(outcome, outcome),
            "outcome_reason": r["outcome_reason"],
            "decided_at": _safe(r["decided_at"]),
            "reviewed_by": r["reviewed_by"],
            "reviewed_at": _safe(r["reviewed_at"]),
            "loan_snapshot": {
                "loan_amount": _safe(r["loan_amount"]),
                "ltv": _safe(r["ltv"]),
                "dti": _safe(r["dti"]),
                "credit_score": r["credit_score"],
                "loan_type": r["loan_type"],
            },
            "condition_count": r["condition_count"],
            "fraud_signal_count": r["fraud_signal_count"],
            "audit_event_count": r["audit_event_count"],
            "confidence_score": _safe(r["confidence_score"]),
        }


@router.get("/{application_id}/export")
async def export_trace(
    application_id: str,
    format: str = "json",
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Full trace export for regulator / repurchase defense."""
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        trace = await _latest_trace(conn, application_id, tenant_id)
        if not trace:
            raise HTTPException(status_code=404, detail="No trace found")

        audit = await conn.fetch(
            """
            SELECT action, actor, actor_role, details, created_at
            FROM decision_audit_log
            WHERE application_id = $1 AND tenant_id = $2
            ORDER BY created_at ASC
            """,
            application_id, tenant_id,
        )
        conditions = await conn.fetch(
            """
            SELECT condition_code, category, status, prior_to,
                   blocks_closing, assignee, condition_text
            FROM loan_condition_instances
            WHERE application_id = $1 AND tenant_id = $2
            ORDER BY blocks_closing DESC, condition_code
            """,
            application_id, tenant_id,
        )
        fraud = await conn.fetch(
            """
            SELECT signal_type, severity, description, auto_block,
                   variance_pct, resolved
            FROM fraud_signals
            WHERE application_id = $1 AND tenant_id = $2
            """,
            application_id, tenant_id,
        )

        t = dict(trace)
        return {
            "export_metadata": {
                "application_id": application_id,
                "tenant_id": tenant_id,
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "export_version": "1.0",
                "purpose": "regulatory_audit",
                "format": format,
            },
            "decision": {
                "trace_id": str(t["id"]),
                "final_outcome": t["final_outcome"],
                "outcome_reason": t["outcome_reason"],
                "decided_at": _safe(t["decided_at"]),
                "decided_by": t["decided_by"],
                "reviewed_by": t["reviewed_by"],
                "confidence": _safe(t["confidence_score"]) or 0.0,
                "loan_snapshot": {
                    "loan_amount": _safe(t["loan_amount"]),
                    "ltv": _safe(t["ltv"]),
                    "dti": _safe(t["dti"]),
                    "credit_score": t["credit_score"],
                    "loan_type": t["loan_type"],
                },
            },
            "input_snapshot": _jsonb(t["input_snapshot"]),
            "evidence_chain": _jsonb(t["evidence_trace"]),
            "policy_applied": _jsonb(t["policy_trace"]),
            "persona_outputs": _jsonb(t["persona_traces"]),
            "conditions": [_row(c) for c in conditions],
            "fraud_signals": [_row(f) for f in fraud],
            "audit_log": [
                {
                    "action": a["action"],
                    "actor": a["actor"],
                    "role": a["actor_role"],
                    "details": _jsonb(a["details"]),
                    "timestamp": _safe(a["created_at"]),
                }
                for a in audit
            ],
        }


@router.get("/{application_id}/audit")
async def get_audit_log(
    application_id: str,
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Audit log for a loan."""
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT action, actor, actor_role, details, created_at
            FROM decision_audit_log
            WHERE application_id = $1 AND tenant_id = $2
            ORDER BY created_at ASC
            """,
            application_id, tenant_id,
        )
        return {
            "application_id": application_id,
            "events": [
                {
                    "action": r["action"],
                    "actor": r["actor"],
                    "role": r["actor_role"],
                    "details": _jsonb(r["details"]),
                    "timestamp": _safe(r["created_at"]),
                }
                for r in rows
            ],
            "total": len(rows),
        }


@router.post("/{application_id}/review")
async def attach_review(
    application_id: str,
    body: ReviewRequest,
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """UW attaches review notes to the trace + records an audit entry."""
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        trace_row = await _latest_trace(conn, application_id, tenant_id)
        if not trace_row:
            raise HTTPException(status_code=404, detail="No trace found")
        async with conn.transaction():
            await conn.execute(
                """
                UPDATE decision_trace
                SET reviewed_by = $1, reviewed_at = NOW(),
                    review_notes = $2, is_final = $3
                WHERE id = $4
                """,
                body.reviewer, body.review_notes,
                body.outcome_confirmed, trace_row["id"],
            )
            await conn.execute(
                """
                INSERT INTO decision_audit_log (
                    application_id, tenant_id, trace_id,
                    action, actor, actor_role, details
                ) VALUES ($1,$2,$3,$4,$5,$6,$7)
                """,
                application_id, tenant_id, trace_row["id"],
                "decision_reviewed", body.reviewer, "underwriter",
                json.dumps({
                    "notes": body.review_notes,
                    "confirmed": body.outcome_confirmed,
                }),
            )
        return {
            "status": "reviewed",
            "reviewer": body.reviewer,
            "confirmed": body.outcome_confirmed,
        }
