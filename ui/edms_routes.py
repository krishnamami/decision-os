"""Human review workbench — reads from EDMS PostgreSQL.

Sibling to ``ui/routes.py``. The existing UI reads from the in-memory
Platform (durable store + trace writer + human queue). These routes
read from EDMS's PG schema:

  vw_pipeline_status            — dashboard rollup
  decision_outputs              — per-decision result + review state
  decision_timeline             — append-only state-transition log
  vw_<decision_id>_context      — per-decision context projection
  entity_states                 — applicant summary fields

Writes (approve / override) land in ``decision_outputs.human_*`` columns
and an append-only ``decision_timeline`` row with trigger
``human_approve`` or ``human_override``.

DATABASE_URL is read from the process env at import time. If it is
empty the router still mounts but every route returns a friendly
"DATABASE_URL not configured" page, so local dev without PG can still
boot the app.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates


# Mirror core/cron/runner.py: load .env so DATABASE_URL is picked up
# whether the app is launched via `uvicorn`, `python -m`, or a test
# harness that doesn't export the variable manually.
try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv()
except ImportError:  # pragma: no cover — listed in requirements.txt
    pass


DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()


router = APIRouter(tags=["edms-workbench"])
templates = Jinja2Templates(directory="ui/edms_templates")


# ─────────────────────────────────────────────────────────────────────
# Wave + persona metadata. Mirrors core/cron/runner.py WAVE_CONFIG +
# DECISION_DEFAULTS so the dashboard / review screens can label each
# decision without a YAML parse. Keep in sync if a decision is added
# or its wave changes.
# ─────────────────────────────────────────────────────────────────────


WAVE_FOR_DECISION: dict[str, int] = {
    "credit_assessment": 1,
    "fraud_screening": 1,
    "compliance_check": 1,
    "employment_reconciliation": 1,
    "income_verification": 2,
    "dti_calculation": 2,
    "ltv_assessment": 2,
    "product_eligibility": 3,
    "rate_pricing": 3,
    "underwriting_decision": 4,
    "approval_routing": 5,
    "closing_readiness": 5,
}

DECISION_LABELS: dict[str, str] = {
    "credit_assessment": "Credit Assessment",
    "fraud_screening": "Fraud Screening",
    "compliance_check": "Compliance Check",
    "employment_reconciliation": "Employment Reconciliation",
    "income_verification": "Income Verification",
    "dti_calculation": "DTI Calculation",
    "ltv_assessment": "LTV Assessment",
    "product_eligibility": "Product Eligibility",
    "rate_pricing": "Rate Pricing",
    "underwriting_decision": "Underwriting Decision",
    "approval_routing": "Approval Routing",
    "closing_readiness": "Closing Readiness",
}

RISK_BY_DECISION: dict[str, str] = {
    "credit_assessment": "medium",
    "fraud_screening": "high",
    "compliance_check": "high",
    "employment_reconciliation": "medium",
    "income_verification": "medium",
    "dti_calculation": "low",
    "ltv_assessment": "low",
    "product_eligibility": "medium",
    "rate_pricing": "medium",
    "underwriting_decision": "high",
    "approval_routing": "low",
    "closing_readiness": "high",
}


# ─────────────────────────────────────────────────────────────────────
# Lazy resources — pool + EDMS store + decision store. Constructed on
# first request so module import is cheap.
# ─────────────────────────────────────────────────────────────────────


_pool: Optional[Any] = None
_edms_store: Optional[Any] = None
_decision_store: Optional[Any] = None


async def _get_pool() -> Any:
    global _pool
    if _pool is None:
        import asyncpg  # type: ignore

        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    return _pool


def _get_edms() -> Any:
    global _edms_store
    if _edms_store is None:
        from core.edms_store import EdmsContextStore

        _edms_store = EdmsContextStore(DATABASE_URL)
    return _edms_store


def _get_decision_store() -> Any:
    global _decision_store
    if _decision_store is None:
        from core.decision_store import DecisionStore

        _decision_store = DecisionStore(DATABASE_URL)
    return _decision_store


def _not_configured(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "not_configured.html", {"request": request}, status_code=503
    )


# ─────────────────────────────────────────────────────────────────────
# Jinja filters
# ─────────────────────────────────────────────────────────────────────


def _humanize_age(dt: Any) -> str:
    if dt is None:
        return "—"
    if not isinstance(dt, datetime):
        return str(dt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    secs = int(delta.total_seconds())
    if secs < 0:
        return "just now"
    if secs < 60:
        return f"{secs}s ago"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m ago"
    hours = mins // 60
    if hours < 48:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


def _outcome_color(outcome: Optional[str]) -> str:
    return {
        "allow": "emerald",
        "recommend": "amber",
        "escalate": "orange",
        "block": "rose",
        "approved": "emerald",
        "overridden": "violet",
        "pending": "slate",
    }.get((outcome or "").lower(), "slate")


def _fmt_value(val: Any) -> str:
    if val is None or val == "":
        return "—"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, float):
        return f"{val:.3f}".rstrip("0").rstrip(".") or "0"
    return str(val)


def _fmt_money(val: Any) -> str:
    if val is None:
        return "—"
    try:
        return f"${float(val):,.0f}"
    except (TypeError, ValueError):
        return str(val)


def _fmt_pct(val: Any) -> str:
    if val is None:
        return "—"
    try:
        return f"{float(val) * 100:.1f}%" if float(val) <= 1 else f"{float(val):.1f}%"
    except (TypeError, ValueError):
        return str(val)


def _signal_color(key: str) -> str:
    """Crude positive/negative classification used by the context panel."""
    risky = (
        "block", "violation", "bankruptcy", "foreclosure", "dispute",
        "watchlist", "synthetic", "thin_file", "defect", "gap",
        "discrepancy", "drift", "missing", "fail",
    )
    safe = (
        "verified", "complete", "clear", "passed", "approved",
        "auto_verified", "match",
    )
    k = key.lower()
    if any(r in k for r in risky):
        return "rose"
    if any(s in k for s in safe):
        return "emerald"
    return "slate"


templates.env.filters["humanize_age"] = _humanize_age
templates.env.filters["outcome_color"] = _outcome_color
templates.env.filters["fmt_value"] = _fmt_value
templates.env.filters["fmt_money"] = _fmt_money
templates.env.filters["fmt_pct"] = _fmt_pct
templates.env.filters["signal_color"] = _signal_color
templates.env.globals["WAVE_FOR_DECISION"] = WAVE_FOR_DECISION
templates.env.globals["DECISION_LABELS"] = DECISION_LABELS


# ─────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────


@router.get("/workbench", response_class=HTMLResponse)
async def pipeline_dashboard(request: Request):
    if not DATABASE_URL:
        return _not_configured(request)
    pool = await _get_pool()
    async with pool.acquire() as conn:
        apps = await conn.fetch(
            """
            SELECT application_id, decisions_complete, decisions_total,
                   pipeline_pct, current_wave, has_block,
                   pending_human_review, escalate_count,
                   pipeline_started, last_decision_at,
                   pipeline_elapsed_seconds
            FROM vw_pipeline_status
            ORDER BY pipeline_pct DESC, last_decision_at DESC NULLS LAST
            LIMIT 100
            """
        )
        totals = await conn.fetchrow(
            """
            SELECT
                COUNT(*) AS total_apps,
                COUNT(*) FILTER (
                    WHERE decisions_complete = decisions_total
                      AND decisions_total > 0
                ) AS complete_apps,
                COUNT(*) FILTER (WHERE has_block) AS blocked_apps,
                COUNT(*) FILTER (
                    WHERE pending_human_review > 0
                ) AS pending_apps
            FROM vw_pipeline_status
            """
        )
        queue_total = await conn.fetchval(
            """
            SELECT COUNT(*) FROM decision_outputs
            WHERE mode IN ('human_approval', 'recommend')
              AND human_action IS NULL
              AND version = (
                  SELECT MAX(version) FROM decision_outputs d2
                  WHERE d2.application_id = decision_outputs.application_id
                    AND d2.decision_id = decision_outputs.decision_id
              )
            """
        )
    return templates.TemplateResponse(
        "pipeline_dashboard.html",
        {
            "request": request,
            "applications": [dict(a) for a in apps],
            "totals": dict(totals) if totals else {},
            "queue_total": queue_total or 0,
        },
    )


@router.get("/workbench/queue", response_class=HTMLResponse)
async def review_queue(request: Request):
    if not DATABASE_URL:
        return _not_configured(request)
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT decision_id,
                   COUNT(*) AS pending,
                   MIN(decided_at) AS oldest,
                   COUNT(*) FILTER (WHERE mode = 'human_approval') AS hum,
                   COUNT(*) FILTER (WHERE mode = 'recommend') AS rec
            FROM decision_outputs
            WHERE mode IN ('human_approval', 'recommend')
              AND human_action IS NULL
              AND version = (
                  SELECT MAX(version) FROM decision_outputs d2
                  WHERE d2.application_id = decision_outputs.application_id
                    AND d2.decision_id = decision_outputs.decision_id
              )
            GROUP BY decision_id
            ORDER BY MIN(decided_at) ASC
            """
        )
    personas = []
    for r in rows:
        d = r["decision_id"]
        personas.append(
            {
                "decision_id": d,
                "label": DECISION_LABELS.get(d, d),
                "wave": WAVE_FOR_DECISION.get(d, 0),
                "risk": RISK_BY_DECISION.get(d, "medium"),
                "pending": r["pending"],
                "oldest": r["oldest"],
                "human_approval": r["hum"],
                "recommend": r["rec"],
            }
        )
    by_wave: dict[int, list] = {}
    for p in personas:
        by_wave.setdefault(p["wave"], []).append(p)
    waves = [{"wave": w, "personas": by_wave[w]} for w in sorted(by_wave)]
    return templates.TemplateResponse(
        "review_queue.html",
        {
            "request": request,
            "waves": waves,
            "total_pending": sum(p["pending"] for p in personas),
        },
    )


@router.get("/workbench/queue/{decision_id}", response_class=HTMLResponse)
async def persona_queue(request: Request, decision_id: str):
    if not DATABASE_URL:
        return _not_configured(request)
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT dout.application_id, dout.outcome, dout.confidence,
                   dout.decided_at, dout.mode,
                   es.mid_credit_score, es.ltv, es.dti_back,
                   es.status, es.loan_amount
            FROM decision_outputs dout
            LEFT JOIN entity_states es
                   ON es.application_id = dout.application_id
                  AND es.tenant_id = dout.tenant_id
            WHERE dout.decision_id = $1
              AND dout.mode IN ('human_approval', 'recommend')
              AND dout.human_action IS NULL
              AND dout.version = (
                  SELECT MAX(version) FROM decision_outputs d2
                  WHERE d2.application_id = dout.application_id
                    AND d2.decision_id = dout.decision_id
              )
            ORDER BY dout.decided_at ASC
            LIMIT 200
            """,
            decision_id,
        )
    return templates.TemplateResponse(
        "persona_queue.html",
        {
            "request": request,
            "decision_id": decision_id,
            "decision_label": DECISION_LABELS.get(decision_id, decision_id),
            "wave": WAVE_FOR_DECISION.get(decision_id, 0),
            "risk": RISK_BY_DECISION.get(decision_id, "medium"),
            "applications": [dict(r) for r in rows],
        },
    )


@router.get(
    "/workbench/review/{application_id}/{decision_id}",
    response_class=HTMLResponse,
)
async def review_detail(
    request: Request, application_id: str, decision_id: str
):
    if not DATABASE_URL:
        return _not_configured(request)
    edms = _get_edms()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        decision = await conn.fetchrow(
            """
            SELECT * FROM decision_outputs
            WHERE application_id = $1 AND decision_id = $2
              AND version = (
                  SELECT MAX(version) FROM decision_outputs d2
                  WHERE d2.application_id = decision_outputs.application_id
                    AND d2.decision_id = decision_outputs.decision_id
              )
            LIMIT 1
            """,
            application_id,
            decision_id,
        )
        entity = await conn.fetchrow(
            """
            SELECT application_id, mid_credit_score, ltv, dti_back,
                   dti_front, status, loan_amount, interest_rate,
                   appraised_value, purchase_price, completeness_pct,
                   combined_monthly_income
            FROM entity_states WHERE application_id = $1 LIMIT 1
            """,
            application_id,
        )
        nav_rows = await conn.fetch(
            """
            SELECT application_id FROM decision_outputs
            WHERE decision_id = $1
              AND mode IN ('human_approval', 'recommend')
              AND human_action IS NULL
              AND version = (
                  SELECT MAX(version) FROM decision_outputs d2
                  WHERE d2.application_id = decision_outputs.application_id
                    AND d2.decision_id = decision_outputs.decision_id
              )
            ORDER BY decided_at ASC
            """,
            decision_id,
        )

    try:
        snap = await edms.snapshot(
            application_id=application_id,
            decision_id=decision_id,
            upstream_decision_ids=None,
        )
        context_objects = snap.context
    except Exception as exc:  # noqa: BLE001 — surface the failure inline
        context_objects = {"_error": {"detail": {"message": str(exc)}}}

    context_groups: list[dict[str, Any]] = []
    for object_type, by_id in (context_objects or {}).items():
        if not isinstance(by_id, dict):
            continue
        for entity_id, fields in by_id.items():
            if not isinstance(fields, dict):
                continue
            context_groups.append(
                {
                    "object_type": object_type,
                    "entity_id": entity_id,
                    "fields": [
                        {"key": k, "value": v} for k, v in fields.items()
                    ],
                }
            )

    decision_dict: Optional[dict[str, Any]] = None
    if decision is not None:
        decision_dict = dict(decision)
        for k in ("context_snapshot", "reasoning", "upstream_decisions"):
            decision_dict[k] = _maybe_json(decision_dict.get(k))

    nav_ids = [r["application_id"] for r in nav_rows]
    prev_id: Optional[str] = None
    next_id: Optional[str] = None
    queue_position: Optional[int] = None
    if application_id in nav_ids:
        idx = nav_ids.index(application_id)
        queue_position = idx + 1
        if idx > 0:
            prev_id = nav_ids[idx - 1]
        if idx + 1 < len(nav_ids):
            next_id = nav_ids[idx + 1]
    elif nav_ids:
        next_id = nav_ids[0]

    return templates.TemplateResponse(
        "review_detail.html",
        {
            "request": request,
            "application_id": application_id,
            "decision_id": decision_id,
            "decision_label": DECISION_LABELS.get(decision_id, decision_id),
            "wave": WAVE_FOR_DECISION.get(decision_id, 0),
            "risk": RISK_BY_DECISION.get(decision_id, "medium"),
            "decision": decision_dict,
            "entity": dict(entity) if entity else None,
            "context_groups": context_groups,
            "prev_id": prev_id,
            "next_id": next_id,
            "queue_position": queue_position,
            "queue_total": len(nav_ids),
        },
    )


@router.post("/workbench/review/{application_id}/{decision_id}/approve")
async def review_approve(
    application_id: str,
    decision_id: str,
    reviewer: str = Form(""),
):
    if not DATABASE_URL:
        return RedirectResponse("/workbench", status_code=303)
    next_app = await _record_review(
        application_id=application_id,
        decision_id=decision_id,
        new_outcome=None,
        reviewer=reviewer or "anonymous",
        override_reason=None,
        trigger="human_approve",
        action="approved",
    )
    if next_app:
        return RedirectResponse(
            f"/workbench/review/{next_app}/{decision_id}", status_code=303
        )
    return RedirectResponse(
        f"/workbench/queue/{decision_id}", status_code=303
    )


@router.post("/workbench/review/{application_id}/{decision_id}/override")
async def review_override(
    application_id: str,
    decision_id: str,
    new_outcome: str = Form(...),
    reviewer: str = Form(""),
    override_reason: str = Form(""),
):
    if not DATABASE_URL:
        return RedirectResponse("/workbench", status_code=303)
    next_app = await _record_review(
        application_id=application_id,
        decision_id=decision_id,
        new_outcome=new_outcome,
        reviewer=reviewer or "anonymous",
        override_reason=override_reason or None,
        trigger="human_override",
        action="overridden",
    )
    if next_app:
        return RedirectResponse(
            f"/workbench/review/{next_app}/{decision_id}", status_code=303
        )
    return RedirectResponse(
        f"/workbench/queue/{decision_id}", status_code=303
    )


async def _record_review(
    *,
    application_id: str,
    decision_id: str,
    new_outcome: Optional[str],
    reviewer: str,
    override_reason: Optional[str],
    trigger: str,
    action: str,
) -> Optional[str]:
    """Update the decision row + append a timeline entry, return the
    application_id of the next pending review (or None)."""
    pool = await _get_pool()
    now = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        async with conn.transaction():
            current = await conn.fetchrow(
                """
                SELECT id, outcome, wave, tenant_id FROM decision_outputs
                WHERE application_id = $1 AND decision_id = $2
                  AND version = (
                      SELECT MAX(version) FROM decision_outputs d2
                      WHERE d2.application_id = decision_outputs.application_id
                        AND d2.decision_id = decision_outputs.decision_id
                  )
                LIMIT 1
                """,
                application_id,
                decision_id,
            )
            if current is None:
                return None
            final_outcome = new_outcome if new_outcome else current["outcome"]
            await conn.execute(
                """
                UPDATE decision_outputs
                   SET human_action = $1,
                       human_reviewer = $2,
                       human_override_reason = $3,
                       outcome = $4,
                       acted_at = $5
                 WHERE id = $6
                """,
                action,
                reviewer,
                override_reason,
                final_outcome,
                now,
                current["id"],
            )
            await conn.execute(
                """
                INSERT INTO decision_timeline (
                    application_id, decision_id, wave, from_state,
                    to_state, trigger, transition_at, tenant_id
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                application_id,
                decision_id,
                current["wave"],
                current["outcome"],
                final_outcome,
                trigger,
                now,
                current["tenant_id"],
            )
            next_app = await conn.fetchval(
                """
                SELECT application_id FROM decision_outputs
                WHERE decision_id = $1
                  AND application_id != $2
                  AND mode IN ('human_approval', 'recommend')
                  AND human_action IS NULL
                  AND version = (
                      SELECT MAX(version) FROM decision_outputs d2
                      WHERE d2.application_id = decision_outputs.application_id
                        AND d2.decision_id = decision_outputs.decision_id
                  )
                ORDER BY decided_at ASC
                LIMIT 1
                """,
                decision_id,
                application_id,
            )
    return next_app


@router.get("/workbench/app/{application_id}", response_class=HTMLResponse)
async def app_detail(request: Request, application_id: str):
    if not DATABASE_URL:
        return _not_configured(request)
    pool = await _get_pool()
    async with pool.acquire() as conn:
        decisions = await conn.fetch(
            """
            SELECT decision_id, wave, outcome, mode, confidence,
                   decided_at, human_action, human_reviewer,
                   human_override_reason, risk_level, boundary_matched,
                   boundary_rule, actual_seconds, sla_seconds
            FROM decision_outputs
            WHERE application_id = $1
              AND version = (
                  SELECT MAX(version) FROM decision_outputs d2
                  WHERE d2.application_id = decision_outputs.application_id
                    AND d2.decision_id = decision_outputs.decision_id
              )
            ORDER BY wave, decided_at
            """,
            application_id,
        )
        entity = await conn.fetchrow(
            """
            SELECT * FROM entity_states WHERE application_id = $1 LIMIT 1
            """,
            application_id,
        )
        timeline = await conn.fetch(
            """
            SELECT decision_id, wave, from_state, to_state, trigger,
                   transition_at, pipeline_position,
                   time_in_prev_state_seconds
            FROM decision_timeline
            WHERE application_id = $1
            ORDER BY transition_at
            """,
            application_id,
        )

    by_wave: dict[int, list] = {}
    for d in decisions:
        dd = dict(d)
        dd["label"] = DECISION_LABELS.get(dd["decision_id"], dd["decision_id"])
        by_wave.setdefault(int(dd["wave"] or 0), []).append(dd)
    waves = [{"wave": w, "decisions": by_wave[w]} for w in sorted(by_wave)]

    return templates.TemplateResponse(
        "app_detail.html",
        {
            "request": request,
            "application_id": application_id,
            "entity": _entity_summary(entity),
            "waves": waves,
            "timeline": [dict(t) for t in timeline],
            "total_decisions": len(decisions),
        },
    )


def _entity_summary(row: Any) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    d = dict(row)
    keep = (
        "application_id", "status", "mid_credit_score", "ltv", "dti_back",
        "dti_front", "loan_amount", "interest_rate", "appraised_value",
        "purchase_price", "combined_monthly_income", "completeness_pct",
        "total_liquid_assets", "qualifying_monthly", "piti_monthly",
    )
    return {k: d.get(k) for k in keep}


@router.get("/workbench/analytics", response_class=HTMLResponse)
async def analytics(request: Request):
    if not DATABASE_URL:
        return _not_configured(request)
    pool = await _get_pool()
    async with pool.acquire() as conn:
        outcome_dist = await conn.fetch(
            """
            SELECT decision_id, outcome, COUNT(*) AS n
            FROM decision_outputs
            WHERE version = (
                SELECT MAX(version) FROM decision_outputs d2
                WHERE d2.application_id = decision_outputs.application_id
                  AND d2.decision_id = decision_outputs.decision_id
            )
            GROUP BY decision_id, outcome
            ORDER BY decision_id, outcome
            """
        )
        avg_time = await conn.fetch(
            """
            SELECT decision_id, AVG(actual_seconds) AS avg_sec,
                   COUNT(*) AS n
            FROM decision_outputs
            WHERE version = (
                SELECT MAX(version) FROM decision_outputs d2
                WHERE d2.application_id = decision_outputs.application_id
                  AND d2.decision_id = decision_outputs.decision_id
            )
            GROUP BY decision_id
            ORDER BY decision_id
            """
        )
        bottlenecks = await conn.fetch(
            """
            SELECT decision_id, COUNT(*) AS pending,
                   MIN(decided_at) AS oldest
            FROM decision_outputs
            WHERE mode IN ('human_approval', 'recommend')
              AND human_action IS NULL
              AND version = (
                  SELECT MAX(version) FROM decision_outputs d2
                  WHERE d2.application_id = decision_outputs.application_id
                    AND d2.decision_id = decision_outputs.decision_id
              )
            GROUP BY decision_id
            ORDER BY pending DESC
            """
        )
        totals = await conn.fetchrow(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE mode = 'auto_execute') AS auto,
                COUNT(*) FILTER (WHERE human_action IS NOT NULL) AS reviewed,
                COUNT(*) FILTER (WHERE outcome = 'block') AS blocked,
                COUNT(*) FILTER (
                    WHERE human_action = 'overridden'
                ) AS overridden,
                COUNT(*) FILTER (
                    WHERE mode IN ('human_approval', 'recommend')
                ) AS reviewable
            FROM decision_outputs
            WHERE version = (
                SELECT MAX(version) FROM decision_outputs d2
                WHERE d2.application_id = decision_outputs.application_id
                  AND d2.decision_id = decision_outputs.decision_id
            )
            """
        )
        wave_velocity = await conn.fetch(
            """
            SELECT wave,
                   AVG(time_in_prev_state_seconds) AS avg_sec,
                   COUNT(*) AS n
            FROM decision_timeline
            WHERE wave IS NOT NULL
            GROUP BY wave ORDER BY wave
            """
        )

    by_decision: dict[str, dict[str, int]] = {}
    for r in outcome_dist:
        by_decision.setdefault(r["decision_id"], {})[r["outcome"]] = r["n"]
    outcome_rows = []
    for d in sorted(by_decision):
        row = by_decision[d]
        outcome_rows.append(
            {
                "decision_id": d,
                "label": DECISION_LABELS.get(d, d),
                "allow": row.get("allow", 0),
                "recommend": row.get("recommend", 0),
                "escalate": row.get("escalate", 0),
                "block": row.get("block", 0),
                "total": sum(row.values()),
            }
        )

    totals_d = dict(totals) if totals else {}
    total = totals_d.get("total") or 0

    def _pct(n: Any) -> float:
        return round((n or 0) * 100 / total, 1) if total else 0.0

    reviewable = totals_d.get("reviewable") or 0
    kpis = {
        "total": total,
        "auto_pct": _pct(totals_d.get("auto")),
        "reviewed_pct": _pct(totals_d.get("reviewed")),
        "blocked_pct": _pct(totals_d.get("blocked")),
        "override_rate": (
            round(
                (totals_d.get("overridden") or 0) * 100 / reviewable, 1
            )
            if reviewable
            else 0.0
        ),
    }

    return templates.TemplateResponse(
        "analytics.html",
        {
            "request": request,
            "kpis": kpis,
            "outcomes": outcome_rows,
            "avg_time": [
                {
                    "decision_id": r["decision_id"],
                    "label": DECISION_LABELS.get(
                        r["decision_id"], r["decision_id"]
                    ),
                    "avg_sec": round(float(r["avg_sec"] or 0), 3),
                    "n": r["n"],
                }
                for r in avg_time
            ],
            "bottlenecks": [
                {
                    "decision_id": r["decision_id"],
                    "label": DECISION_LABELS.get(
                        r["decision_id"], r["decision_id"]
                    ),
                    "pending": r["pending"],
                    "oldest": r["oldest"],
                }
                for r in bottlenecks
            ],
            "wave_velocity": [
                {
                    "wave": r["wave"],
                    "avg_sec": round(float(r["avg_sec"] or 0), 1),
                    "n": r["n"],
                }
                for r in wave_velocity
            ],
        },
    )


def _maybe_json(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, (bytes, bytearray)):
        val = val.decode("utf-8", errors="replace")
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (ValueError, json.JSONDecodeError):
            return val
    return val


__all__ = ["router", "DATABASE_URL"]
