"""Accord — Admin/Manager pipeline dashboard aggregates.

Three read-only, admin/manager-gated endpoints for the DashboardPage:
  GET /api/accord/dashboard/summary           6 KPI cards
  GET /api/accord/dashboard/team-performance  per-teammate throughput
  GET /api/accord/dashboard/attention         top loans needing attention

Tenant-scoped (tenant from JWT). Every metric is computed in its own guarded
block so a missing column / empty table degrades that metric to 0 / null rather
than failing the whole dashboard. Reuses the proven vw_loan_conditions_aggregate
(same view the workbench uses) + entity_states + loan_assignments + users +
decision_outputs.

HONEST FLAGS (no real source today — surfaced as placeholders, see DashboardPage):
  * deltas vs yesterday — no daily-snapshot table exists -> returned null.
  * capacity_pct — no capacity model -> heuristic = active / CAPACITY_TARGET.
  * channel / loan_purpose filters — not columns on entity_states.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from api.accord.auth import get_current_user
from api.accord.pipeline import _get_pool, _require_db, _f

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/accord/dashboard", tags=["accord-dashboard"])

ACTIVE_STATUSES = ("in_progress", "processing", "review", "intake", "open")
CAPACITY_TARGET = 15  # heuristic max active files / underwriter (no real model yet)


def _require_manager(user: dict) -> None:
    if user.get("role") not in ("admin", "manager", "super_admin"):
        raise HTTPException(403, "Admin or manager access required")


async def _scalar(conn, sql: str, *args, default: Any = 0) -> Any:
    """Run a COUNT/scalar query; return default on any error (defensive)."""
    try:
        v = await conn.fetchval(sql, *args)
        return v if v is not None else default
    except Exception as exc:  # noqa: BLE001
        logger.warning("[dashboard] scalar failed: %s", str(exc)[:160])
        return default


@router.get("/summary")
async def summary(user: dict = Depends(get_current_user)) -> dict:
    """6 KPI cards. Each metric guarded independently."""
    _require_manager(user)
    _require_db()
    tid = user["tenant_id"]
    pool = await _get_pool()
    async with pool.acquire() as conn:
        active_files = await _scalar(
            conn,
            f"SELECT COUNT(*) FROM entity_states WHERE tenant_id=$1 "
            f"AND status = ANY($2::text[])",
            tid, list(ACTIVE_STATUSES))

        # Condition-derived metrics from the proven aggregate view.
        needs_attention = await _scalar(
            conn,
            "SELECT COUNT(*) FROM vw_loan_conditions_aggregate "
            "WHERE tenant_id=$1 AND (blocking_conditions > 0 OR overdue_conditions > 0)",
            tid)
        ready_to_decide = await _scalar(
            conn,
            "SELECT COUNT(*) FROM vw_loan_conditions_aggregate "
            "WHERE tenant_id=$1 AND total_conditions > 0 AND open_conditions = 0",
            tid)
        sla_breaches = await _scalar(
            conn,
            "SELECT COUNT(*) FROM vw_loan_conditions_aggregate "
            "WHERE tenant_id=$1 AND overdue_conditions > 0",
            tid)
        pending_customer = await _scalar(
            conn,
            "SELECT COUNT(DISTINCT application_id) FROM loan_condition_instances "
            "WHERE tenant_id=$1 AND assignee='borrower' AND status='open'",
            tid)

        # Avg decision time: days from the loan's first decision to its
        # underwriting decision. Guarded (decided_at may be null on some rows).
        avg_decision_days = await _scalar(
            conn,
            """
            WITH uw AS (
                SELECT DISTINCT ON (application_id) application_id, decided_at
                FROM decision_outputs
                WHERE tenant_id=$1 AND decision_id='underwriting_decision' AND decided_at IS NOT NULL
                ORDER BY application_id, version DESC
            ),
            firstd AS (
                SELECT application_id, MIN(decided_at) AS started
                FROM decision_outputs WHERE tenant_id=$1 AND decided_at IS NOT NULL
                GROUP BY application_id
            )
            SELECT ROUND(AVG(EXTRACT(EPOCH FROM (uw.decided_at - firstd.started)) / 86400.0)::numeric, 1)
            FROM uw JOIN firstd USING (application_id)
            WHERE uw.decided_at >= firstd.started
            """,
            tid, default=None)

        # Real status distribution (drives the "Files by Status" funnel — the
        # idealized 7-stage funnel isn't modelled in the data, so we show the
        # actual statuses instead of faking stages).
        by_status = []
        try:
            srows = await conn.fetch(
                "SELECT status, COUNT(*) AS n FROM entity_states WHERE tenant_id=$1 "
                "GROUP BY status ORDER BY n DESC", tid)
            by_status = [{"status": r["status"], "count": int(r["n"])} for r in srows]
        except Exception as exc:  # noqa: BLE001
            logger.warning("[dashboard] by_status failed: %s", str(exc)[:160])

        # Aging buckets from active assignments' assigned_at (real).
        aging = []
        try:
            arow = await conn.fetchrow(
                """
                SELECT
                  COUNT(*) FILTER (WHERE d <= 3)            AS b0_3,
                  COUNT(*) FILTER (WHERE d > 3 AND d <= 7)  AS b4_7,
                  COUNT(*) FILTER (WHERE d > 7 AND d <= 15) AS b8_15,
                  COUNT(*) FILTER (WHERE d > 15 AND d <= 30) AS b16_30,
                  COUNT(*) FILTER (WHERE d > 30)            AS b30
                FROM (
                  SELECT EXTRACT(EPOCH FROM (NOW() - assigned_at))/86400.0 AS d
                  FROM loan_assignments WHERE tenant_id=$1 AND status='active' AND assigned_at IS NOT NULL
                ) q
                """, tid)
            if arow:
                aging = [
                    {"bucket": "0-3 days", "count": int(arow["b0_3"] or 0)},
                    {"bucket": "4-7 days", "count": int(arow["b4_7"] or 0)},
                    {"bucket": "8-15 days", "count": int(arow["b8_15"] or 0)},
                    {"bucket": "16-30 days", "count": int(arow["b16_30"] or 0)},
                    {"bucket": "30+ days", "count": int(arow["b30"] or 0)},
                ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("[dashboard] aging failed: %s", str(exc)[:160])

    return {
        "active_files": int(active_files or 0),
        "needs_attention": int(needs_attention or 0),
        "pending_customer": int(pending_customer or 0),
        "ready_to_decide": int(ready_to_decide or 0),
        "sla_breaches": int(sla_breaches or 0),
        "avg_decision_days": _f(avg_decision_days),
        "by_status": by_status,
        "aging": aging,
        # No daily-snapshot table -> deltas are not computable. Surfaced null so
        # the UI hides the ↑/↓ rather than fabricating a trend.
        "deltas": None,
        "deltas_available": False,
    }


@router.get("/team-performance")
async def team_performance(user: dict = Depends(get_current_user)) -> dict:
    """Per-teammate throughput + condition rollups for active assignments."""
    _require_manager(user)
    _require_db()
    tid = user["tenant_id"]
    pool = await _get_pool()
    members: list[dict] = []
    async with pool.acquire() as conn:
        try:
            rows = await conn.fetch(
                """
                SELECT u.user_id, u.name, u.role,
                       COUNT(la.application_id) FILTER (WHERE la.status='active') AS active,
                       COUNT(la.application_id) FILTER (WHERE la.status IN ('decided','funded')) AS decided,
                       COUNT(la.application_id) FILTER (
                           WHERE la.status='active'
                           AND (agg.blocking_conditions > 0 OR agg.overdue_conditions > 0)) AS needs_attention,
                       COUNT(la.application_id) FILTER (
                           WHERE la.status='active' AND agg.overdue_conditions > 0) AS sla_breaches,
                       COUNT(la.application_id) FILTER (
                           WHERE la.status='active'
                           AND agg.total_conditions > 0 AND agg.open_conditions = 0) AS ready_to_decide,
                       AVG(EXTRACT(EPOCH FROM (NOW() - la.assigned_at)) / 86400.0)
                           FILTER (WHERE la.status='active') AS avg_days
                FROM users u
                LEFT JOIN loan_assignments la
                       ON la.assigned_to = u.user_id AND la.tenant_id = $1
                LEFT JOIN vw_loan_conditions_aggregate agg
                       ON agg.application_id = la.application_id AND agg.tenant_id = $1
                WHERE u.tenant_id = $1
                  AND u.role IN ('processor','underwriter','senior_uw','closer')
                GROUP BY u.user_id, u.name, u.role
                ORDER BY u.name
                """,
                tid)
            for r in rows:
                active = int(r["active"] or 0)
                # pending_customer per member needs a borrower-assignee join we
                # don't have per-assignment cheaply; approximate as needs_attention
                # minus ready, never negative. Flagged heuristic.
                members.append({
                    "user_id": str(r["user_id"]),
                    "name": r["name"],
                    "role": r["role"],
                    "avatar_initials": _initials(r["name"]),
                    "active": active,
                    "needs_attention": int(r["needs_attention"] or 0),
                    "pending": 0,  # placeholder — no per-assignment borrower-doc source
                    "ready_to_decide": int(r["ready_to_decide"] or 0),
                    "decided": int(r["decided"] or 0),
                    "avg_decision_days": round(float(r["avg_days"]), 1) if r["avg_days"] is not None else None,
                    "avg_decision_delta": None,  # no snapshot history
                    "sla_breaches": int(r["sla_breaches"] or 0),
                    "capacity_pct": min(100, round(active * 100 / CAPACITY_TARGET)) if active else 0,
                })
        except Exception as exc:  # noqa: BLE001
            logger.warning("[dashboard] team-performance failed: %s", str(exc)[:200])
            members = []
    return {"members": members, "capacity_target": CAPACITY_TARGET, "capacity_is_heuristic": True}


@router.get("/attention")
async def attention(user: dict = Depends(get_current_user),
                    limit: int = Query(12, ge=1, le=50)) -> dict:
    """Top loans needing attention (blocking or overdue conditions first)."""
    _require_manager(user)
    _require_db()
    tid = user["tenant_id"]
    pool = await _get_pool()
    out: list[dict] = []
    total = 0
    async with pool.acquire() as conn:
        try:
            total = int(await _scalar(
                conn,
                "SELECT COUNT(*) FROM vw_loan_conditions_aggregate "
                "WHERE tenant_id=$1 AND (blocking_conditions > 0 OR overdue_conditions > 0)", tid))
            rows = await conn.fetch(
                """
                SELECT agg.application_id,
                       agg.blocking_conditions, agg.overdue_conditions, agg.open_conditions,
                       es.loan_amount,
                       ap.full_name AS borrower,
                       la.assigned_to,
                       u.name AS assigned_name,
                       la.assigned_at,
                       (SELECT condition_text FROM loan_condition_instances lci
                         WHERE lci.application_id = agg.application_id AND lci.tenant_id = $1
                           AND lci.status NOT IN ('approved','waived')
                         ORDER BY lci.blocks_closing DESC, lci.due_date ASC NULLS LAST LIMIT 1) AS issue
                FROM vw_loan_conditions_aggregate agg
                LEFT JOIN entity_states es ON es.application_id = agg.application_id AND es.tenant_id = $1
                LEFT JOIN applications app ON app.application_id = agg.application_id
                LEFT JOIN applicants ap ON ap.applicant_id = app.applicant_id
                LEFT JOIN loan_assignments la ON la.application_id = agg.application_id
                       AND la.tenant_id = $1 AND la.status='active'
                LEFT JOIN users u ON u.user_id = la.assigned_to
                WHERE agg.tenant_id = $1 AND (agg.blocking_conditions > 0 OR agg.overdue_conditions > 0)
                ORDER BY agg.overdue_conditions DESC, agg.blocking_conditions DESC
                LIMIT $2
                """,
                tid, limit)
            for r in rows:
                overdue = int(r["overdue_conditions"] or 0)
                blocking = int(r["blocking_conditions"] or 0)
                sla = "Breach" if overdue > 0 else ("At Risk" if blocking > 0 else "Due Soon")
                days_in_queue = None
                if r["assigned_at"] is not None:
                    try:
                        from datetime import datetime, timezone
                        aa = r["assigned_at"]
                        aa = aa if aa.tzinfo else aa.replace(tzinfo=timezone.utc)
                        days_in_queue = round((datetime.now(timezone.utc) - aa).total_seconds() / 86400.0, 1)
                    except Exception:  # noqa: BLE001
                        days_in_queue = None
                out.append({
                    "application_id": r["application_id"],
                    "borrower": r["borrower"],
                    "loan_amount": _f(r["loan_amount"]),
                    "loan_purpose": None,  # not a column on entity_states
                    "issue": r["issue"],
                    "sla_status": sla,
                    "days_in_queue": days_in_queue,
                    "assigned_to": r["assigned_name"],
                    "assigned_initials": _initials(r["assigned_name"]),
                })
        except Exception as exc:  # noqa: BLE001
            logger.warning("[dashboard] attention failed: %s", str(exc)[:200])
            out, total = [], 0
    return {"files": out, "total": total}


def _initials(name: Any) -> str:
    s = str(name or "").strip()
    if not s:
        return "?"
    parts = s.split()
    return ((parts[0][0] if parts else "") + (parts[-1][0] if len(parts) > 1 else "")).upper() or "?"


__all__ = ["router"]
