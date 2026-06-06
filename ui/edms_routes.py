"""Persona-centric workbench — reads from EDMS PostgreSQL.

Each of the 11 lending personas is a real role in a mortgage shop
(credit underwriter, fraud analyst, closer, ...). Each one has a
queue, a review screen, a completed log, and per-persona analytics.

Sibling to the legacy in-memory ``ui/routes.py`` — neither side
touches the other. DATABASE_URL is read from .env at import time.

Tables / views read:
  vw_pipeline_status                — application rollup
  vw_<decision_id>_context          — per-decision projection
  decision_outputs                  — proposed + finalized decisions
  decision_timeline                 — append-only state transitions
  entity_states                     — applicant + loan summary

Mutations:
  decision_outputs                  — human_action + reviewer + outcome
  decision_timeline                 — one row per human_approve /
                                      human_override
"""

from __future__ import annotations

import csv
import io
import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from ui.explanations import (
    DECISION_LABELS,
    ROUTING_ACTIONS,
    action_label,
    build_signals,
    canonical_underwriting_state,
    explain,
    halts_pipeline,
    resolve_vocab,
    vocab_badge,
)


# Load DATABASE_URL from .env if present. Mirrors core/cron/runner.py
# so the app picks it up under uvicorn, python -m, and TestClient.
try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv()
except ImportError:  # pragma: no cover — listed in requirements.txt
    pass


DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()


# ─────────────────────────────────────────────────────────────────────
# PERSONA_CONFIG — the 11 lending roles. Order is presentation order
# inside each stage group; STAGES below pins which group each persona
# belongs to (Pre-underwriting → Underwriting → Decision → Post-decision).
# ─────────────────────────────────────────────────────────────────────


PERSONA_CONFIG: dict[str, dict[str, Any]] = {
    "credit_underwriter": {
        "decision_id": "credit_assessment",
        "title": "Credit Underwriter",
        "view": "vw_credit_assessment_context",
        "description": "Reviews credit reports and determines creditworthiness",
        "key_fields": [
            "credit_score", "credit_band", "active_bankruptcy",
            "foreclosure_last_36_months", "thin_file",
            "no_derogatory_last_24_months", "derogatory_marks",
            "open_tradelines", "credit_utilization",
        ],
        "summary_fields": ["credit_score", "credit_band"],
        "mode": "recommend",
        "icon": "ti-shield",
        "abbr": "CU",
        "color": "blue",
    },
    "income_underwriter": {
        "decision_id": "income_verification",
        "title": "Income Underwriter",
        "view": "vw_income_verification_context",
        "description": "Verifies stated income against documentation",
        "key_fields": [
            "stated_income", "verified_income", "income_discrepancy_pct",
            "employment_type", "payroll_verified", "income_confidence_score",
            "income_stability", "income_trending", "multiple_income_sources",
        ],
        "summary_fields": ["verified_income", "income_discrepancy_pct"],
        "mode": "recommend",
        "icon": "ti-coin",
        "abbr": "IU",
        "color": "emerald",
    },
    "employment_specialist": {
        "decision_id": "employment_reconciliation",
        "title": "Employment Specialist",
        "view": "vw_employment_reconciliation_context",
        "description": "Reconciles employment history across multiple sources",
        "key_fields": [
            "reconciliation_status", "continuity_coverage_pct", "max_gap_days",
            "employer_name_match_confidence", "stated_vs_verified_drift_pct",
            "employer_name", "stated_employer", "period_start", "period_end",
            "gross_amount",
        ],
        "summary_fields": ["reconciliation_status", "continuity_coverage_pct"],
        "mode": "recommend",
        "icon": "ti-briefcase",
        "abbr": "ES",
        "color": "teal",
    },
    "fraud_analyst": {
        "decision_id": "fraud_screening",
        "title": "Fraud Analyst",
        "view": "vw_fraud_screening_context",
        "description": "Screens for identity fraud, synthetic identity, and watchlist matches",
        "key_fields": [
            "fraud_score", "identity_match_confidence",
            "document_authenticity_score", "watchlist_match",
            "synthetic_identity_flag",
        ],
        "summary_fields": ["fraud_score", "identity_match_confidence"],
        "mode": "human_approval",
        "icon": "ti-alert-triangle",
        "abbr": "FA",
        "color": "rose",
    },
    "compliance_officer": {
        "decision_id": "compliance_check",
        "title": "Compliance Officer",
        "view": "vw_compliance_check_context",
        "description": "Validates HMDA, fair lending, and regulatory requirements",
        "key_fields": [
            "all_hmda_fields_complete", "no_fair_lending_flags",
            "state_rules_passed", "fair_lending_violation",
            "missing_required_disclosures", "regulatory_ambiguity",
            "mixed_jurisdiction",
        ],
        "summary_fields": ["all_hmda_fields_complete", "state_rules_passed"],
        "mode": "human_approval",
        "icon": "ti-clipboard-check",
        "abbr": "CO",
        "color": "indigo",
    },
    "collateral_analyst": {
        "decision_id": "ltv_assessment",
        "title": "Collateral Analyst",
        "view": "vw_ltv_assessment_context",
        "description": "Reviews property valuation, LTV ratio, and appraisal",
        "key_fields": [
            "ltv", "appraised_value", "purchase_price", "down_payment",
            "appraisal_disputed", "lien_dispute", "credit_band",
        ],
        "summary_fields": ["ltv", "appraised_value"],
        "mode": "auto_execute",
        "icon": "ti-home",
        "abbr": "CA",
        "color": "amber",
    },
    "product_specialist": {
        "decision_id": "product_eligibility",
        "title": "Product Specialist",
        "view": "vw_product_eligibility_context",
        "description": "Determines eligible loan products based on DTI, LTV, and credit",
        "key_fields": [
            "dti_ratio", "ltv_ratio", "credit_band", "credit_score",
            "loan_type", "loan_amount", "loan_purpose",
        ],
        "summary_fields": ["loan_type", "credit_band"],
        "mode": "recommend",
        "icon": "ti-package",
        "abbr": "PS",
        "color": "cyan",
    },
    "pricing_analyst": {
        "decision_id": "rate_pricing",
        "title": "Pricing Analyst",
        "view": "vw_rate_pricing_context",
        "description": "Sets interest rate and LLPA adjustments",
        "key_fields": [
            "credit_score", "dti_ratio", "ltv_ratio", "interest_rate",
            "loan_type", "llpa_adjustment", "rate_within_normal_band",
            "concurrent_rate_lock_conflict", "loan_program",
        ],
        "summary_fields": ["interest_rate", "llpa_adjustment"],
        "mode": "recommend",
        "icon": "ti-trending-up",
        "abbr": "PA",
        "color": "violet",
    },
    "senior_underwriter": {
        "decision_id": "underwriting_decision",
        "title": "Senior Underwriter",
        "view": "vw_underwriting_decision_context",
        "description": "Final underwriting decision — approve, conditional, or deny",
        "key_fields": [
            "mid_credit_score", "ltv", "dti_back", "dti_front",
            "piti_monthly", "qualifying_monthly", "loan_amount",
            "interest_rate", "appraised_value", "completeness_pct",
            "status",
        ],
        "summary_fields": ["mid_credit_score", "ltv", "dti_back"],
        "mode": "human_approval",
        "icon": "ti-user-check",
        "abbr": "SU",
        "color": "purple",
    },
    "closer": {
        "decision_id": "closing_readiness",
        "title": "Closer",
        "view": "vw_closing_readiness_context",
        "description": "Final closing checklist — title, CD timing, conditions, insurance",
        "key_fields": [
            "all_conditions_cleared", "cd_timing_compliant", "title_clear",
            "title_defect", "lien_dispute", "insurance_gap",
            "insurance_binder", "closing_disclosure_sent_at",
            "days_until_rate_lock_expiry",
        ],
        "summary_fields": ["title_clear", "cd_timing_compliant"],
        "mode": "human_approval",
        "icon": "ti-check-circle",
        "abbr": "CL",
        "color": "orange",
    },
    "post_closer": {
        "decision_id": "approval_routing",
        "title": "Post-Closer",
        "view": "vw_approval_routing_context",
        "description": "Routes finalized decisions — approvals and declines (notice delivery, investor assignment)",
        "key_fields": ["applicant_id", "status", "completeness_pct"],
        "summary_fields": ["status"],
        "mode": "auto_execute",
        "icon": "ti-send",
        "abbr": "PC",
        "color": "slate",
    },
}


# Display order on the home page — workflow stage groups.
STAGES: list[dict[str, Any]] = [
    {
        "name": "Pre-underwriting",
        "slug": "pre_underwriting",
        "personas": [
            "credit_underwriter",
            "fraud_analyst",
            "compliance_officer",
            "employment_specialist",
        ],
    },
    {
        "name": "Underwriting",
        "slug": "underwriting",
        "personas": [
            "income_underwriter",
            "collateral_analyst",
            "product_specialist",
            "pricing_analyst",
        ],
    },
    {
        "name": "Decision",
        "slug": "decision",
        "personas": ["senior_underwriter"],
    },
    {
        "name": "Post-decision",
        "slug": "post_decision",
        "personas": ["closer", "post_closer"],
    },
]


DECISION_TO_SLUG: dict[str, str] = {
    cfg["decision_id"]: slug for slug, cfg in PERSONA_CONFIG.items()
}


# Upstream graph mirrors core/cron/runner.py WAVE_CONFIG so the review
# detail can show "this decision depends on …".
UPSTREAM: dict[str, list[str]] = {
    "credit_assessment":         [],
    "fraud_screening":           [],
    "compliance_check":          [],
    "employment_reconciliation": [],
    "income_verification":       ["employment_reconciliation"],
    "dti_calculation":           ["income_verification"],
    "ltv_assessment":            ["credit_assessment"],
    "product_eligibility":       ["dti_calculation", "ltv_assessment"],
    "rate_pricing":              ["credit_assessment", "dti_calculation", "ltv_assessment"],
    "underwriting_decision":     [
        "income_verification", "credit_assessment", "fraud_screening",
        "dti_calculation", "ltv_assessment", "product_eligibility",
    ],
    "approval_routing":          ["underwriting_decision"],
    "closing_readiness":         ["underwriting_decision", "compliance_check"],
}


WAVE_FOR_DECISION: dict[str, int] = {
    "credit_assessment": 1, "fraud_screening": 1, "compliance_check": 1,
    "employment_reconciliation": 1,
    "income_verification": 2, "dti_calculation": 2, "ltv_assessment": 2,
    "product_eligibility": 3, "rate_pricing": 3,
    "underwriting_decision": 4,
    "approval_routing": 5, "closing_readiness": 5,
}


def _downstream_decisions(decision_id: str) -> list[str]:
    """All decisions that transitively depend on ``decision_id`` by
    walking the UPSTREAM edges forward (B is downstream of A when A is in
    UPSTREAM[B], directly or via a chain). Used by the revert flow to mark
    decisions that ran on now-reopened input as stale."""
    result: set[str] = set()
    frontier = [decision_id]
    while frontier:
        cur = frontier.pop()
        for dec, upstreams in UPSTREAM.items():
            if cur in upstreams and dec not in result:
                result.add(dec)
                frontier.append(dec)
    return sorted(result)


router = APIRouter(tags=["edms-workbench"])
templates = Jinja2Templates(directory="ui/edms_templates")


# ─────────────────────────────────────────────────────────────────────
# Lazy resources
# ─────────────────────────────────────────────────────────────────────


_pool: Optional[Any] = None
_edms_store: Optional[Any] = None
_decision_store: Optional[Any] = None


async def _get_pool() -> Any:
    global _pool
    if _pool is None:
        import asyncpg  # type: ignore

        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
        await _ensure_stale_column(_pool)
    return _pool


async def _ensure_stale_column(pool: Any) -> None:
    """Idempotent migration — adds decision_outputs.stale so the revert
    flow can flag downstream decisions as outdated. Runs once, the first
    time the pool is created."""
    async with pool.acquire() as conn:
        await conn.execute(
            "ALTER TABLE decision_outputs "
            "ADD COLUMN IF NOT EXISTS stale BOOLEAN DEFAULT false"
        )


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
    # Sidebar metrics need DATABASE_URL; when it's empty we render the
    # error page with an empty sidebar shell (no PG call).
    sidebar = [
        {
            "slug": slug,
            "title": cfg["title"],
            "icon": cfg["icon"],
            "abbr": cfg.get("abbr", slug[:2].upper()),
            "color": cfg["color"],
            "decision_id": cfg["decision_id"],
            "active": False,
            "in_queue": 0,
        }
        for slug, cfg in PERSONA_CONFIG.items()
    ]
    return templates.TemplateResponse(
        "not_configured.html",
        {
            "request": request,
            "personas_sidebar": sidebar,
            "stages": STAGES,
            "active_persona": None,
        },
        status_code=503,
    )


def _persona_or_none(slug: str) -> Optional[dict[str, Any]]:
    cfg = PERSONA_CONFIG.get(slug)
    if cfg is None:
        return None
    return {**cfg, "slug": slug}


# ─────────────────────────────────────────────────────────────────────
# Jinja filters / globals
# ─────────────────────────────────────────────────────────────────────


def _humanize_age(dt: Any) -> str:
    if dt is None:
        return "—"
    if not isinstance(dt, datetime):
        return str(dt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    secs = int((datetime.now(timezone.utc) - dt).total_seconds())
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
    return f"{hours // 24}d ago"


def _outcome_color(outcome: Any) -> str:
    return {
        "allow": "emerald",
        "recommend": "amber",
        "escalate": "orange",
        "block": "rose",
        "approved": "emerald",
        "overridden": "violet",
        "auto_verified": "emerald",
        "partial": "amber",
        "conflict": "rose",
        "missing": "slate",
    }.get(str(outcome or "").lower(), "slate")


def _credit_color(score: Any) -> str:
    try:
        s = int(score)
    except (TypeError, ValueError):
        return "slate"
    if s >= 700:
        return "emerald"
    if s >= 620:
        return "amber"
    return "rose"


def _fmt_value(val: Any) -> str:
    if val is None or val == "":
        return "—"
    if isinstance(val, bool):
        return "yes" if val else "no"
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
        f = float(val)
        return f"{f * 100:.1f}%" if f <= 1.0 else f"{f:.1f}%"
    except (TypeError, ValueError):
        return str(val)


def _fmt_field(key: str, val: Any) -> str:
    """Pick a formatter based on field-name heuristics."""
    if isinstance(val, bool) or val is None or val == "":
        return _fmt_value(val)
    k = key.lower()
    if any(t in k for t in ("amount", "income", "payment", "value", "price")):
        try:
            return _fmt_money(val)
        except Exception:
            return _fmt_value(val)
    if any(t in k for t in ("rate", "ltv", "dti", "ratio", "pct", "coverage", "confidence", "drift", "utilization")):
        return _fmt_pct(val)
    return _fmt_value(val)


def _fmt_seconds(val: Any) -> str:
    if val is None:
        return "—"
    try:
        s = float(val)
    except (TypeError, ValueError):
        return str(val)
    if s < 60:
        return f"{s:.1f}s"
    if s < 3600:
        return f"{s / 60:.1f}m"
    return f"{s / 3600:.1f}h"


templates.env.filters["humanize_age"] = _humanize_age
templates.env.filters["outcome_color"] = _outcome_color
templates.env.filters["credit_color"] = _credit_color
templates.env.filters["fmt_value"] = _fmt_value
templates.env.filters["fmt_money"] = _fmt_money
templates.env.filters["fmt_pct"] = _fmt_pct
templates.env.filters["fmt_field"] = _fmt_field
templates.env.filters["fmt_seconds"] = _fmt_seconds
templates.env.filters["action_verb"] = action_label
# Persona-kind-aware badge for list rows / pills — routing personas show
# "Auto-execute" (neutral), never "ALLOW" (green).
templates.env.globals["badge_for"] = vocab_badge


# ─────────────────────────────────────────────────────────────────────
# Per-request base context — drives the sidebar + footer
# ─────────────────────────────────────────────────────────────────────


async def _sidebar_queue_counts() -> dict[str, int]:
    """One grouped query that returns in-queue count per decision_id.

    Cheap enough to run on every request (single grouped scan against
    the latest version of each decision_outputs row)."""
    if not DATABASE_URL:
        return {}
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT decision_id, COUNT(*) AS n
            FROM decision_outputs
            WHERE mode IN ('human_approval', 'recommend')
              AND human_action IS NULL
              AND version = (
                  SELECT MAX(version) FROM decision_outputs d2
                  WHERE d2.application_id = decision_outputs.application_id
                    AND d2.decision_id = decision_outputs.decision_id
              )
            GROUP BY decision_id
            """
        )
    by_decision = {r["decision_id"]: int(r["n"] or 0) for r in rows}
    if not by_decision:
        return {}
    # entity_states-only personas (auto_execute with no decisions yet):
    # count un-decided apps as their "queue" so the sidebar reflects the
    # work waiting for that role.
    async with pool.acquire() as conn:
        total_apps = await conn.fetchval(
            "SELECT COUNT(*) FROM entity_states"
        )
        decided_per_decision = await conn.fetch(
            """
            SELECT decision_id, COUNT(*) AS n
            FROM decision_outputs
            WHERE version = (
                SELECT MAX(version) FROM decision_outputs d2
                WHERE d2.application_id = decision_outputs.application_id
                  AND d2.decision_id = decision_outputs.decision_id
            )
            GROUP BY decision_id
            """
        )
    decided = {r["decision_id"]: int(r["n"] or 0) for r in decided_per_decision}
    total_apps = int(total_apps or 0)
    out: dict[str, int] = {}
    for slug, cfg in PERSONA_CONFIG.items():
        d = cfg["decision_id"]
        if cfg["mode"] == "auto_execute":
            out[d] = max(0, total_apps - decided.get(d, 0))
        else:
            out[d] = by_decision.get(d, 0)
    return out


async def _base_ctx(active_persona_slug: Optional[str]) -> dict[str, Any]:
    queue_counts = await _sidebar_queue_counts() if DATABASE_URL else {}
    sidebar = []
    for slug, cfg in PERSONA_CONFIG.items():
        sidebar.append(
            {
                "slug": slug,
                "title": cfg["title"],
                "icon": cfg["icon"],
                "abbr": cfg.get("abbr", slug[:2].upper()),
                "color": cfg["color"],
                "decision_id": cfg["decision_id"],
                "active": slug == active_persona_slug,
                "in_queue": queue_counts.get(cfg["decision_id"], 0),
            }
        )
    return {
        "personas_sidebar": sidebar,
        "stages": STAGES,
        "active_persona": active_persona_slug,
    }


async def _total_decisions() -> int:
    if not DATABASE_URL:
        return 0
    pool = await _get_pool()
    async with pool.acquire() as conn:
        n = await conn.fetchval("SELECT COUNT(*) FROM decision_outputs")
    return int(n or 0)


# ─────────────────────────────────────────────────────────────────────
# Home / sidebar metrics — one query per persona, executed in parallel
# would be fine but the spec asks for 4 metrics; we batch by walking
# PERSONA_CONFIG and issuing per-persona aggregates against the latest-
# version subset.
# ─────────────────────────────────────────────────────────────────────


async def _persona_metrics() -> dict[str, dict[str, Any]]:
    """Return dict slug → {in_queue, completed, auto_pct, avg_review_sec}."""
    pool = await _get_pool()
    metrics: dict[str, dict[str, Any]] = {}
    async with pool.acquire() as conn:
        total_apps = await conn.fetchval(
            "SELECT COUNT(*) FROM entity_states"
        ) or 0
        rows = await conn.fetch(
            """
            WITH latest AS (
                SELECT * FROM decision_outputs
                WHERE version = (
                    SELECT MAX(version) FROM decision_outputs d2
                    WHERE d2.application_id = decision_outputs.application_id
                      AND d2.decision_id = decision_outputs.decision_id
                )
            )
            SELECT decision_id,
                   COUNT(*) AS total,
                   COUNT(*) FILTER (
                       WHERE mode IN ('human_approval', 'recommend')
                         AND human_action IS NULL
                   ) AS pending_review,
                   COUNT(*) FILTER (
                       WHERE mode = 'auto_execute'
                          OR human_action IS NOT NULL
                   ) AS done,
                   COUNT(*) FILTER (WHERE mode = 'auto_execute') AS auto,
                   AVG(
                       CASE WHEN acted_at IS NOT NULL AND decided_at IS NOT NULL
                            THEN EXTRACT(EPOCH FROM (acted_at - decided_at))
                       END
                   ) AS avg_review_sec
            FROM latest
            GROUP BY decision_id
            """
        )
    by_decision = {r["decision_id"]: dict(r) for r in rows}
    for slug, cfg in PERSONA_CONFIG.items():
        d = cfg["decision_id"]
        row = by_decision.get(d, {})
        done = int(row.get("done") or 0)
        auto = int(row.get("auto") or 0)
        pending = int(row.get("pending_review") or 0)
        # auto_execute personas: in-queue = apps without a decision row yet.
        if cfg["mode"] == "auto_execute":
            decided = int(row.get("total") or 0)
            in_queue = max(0, int(total_apps) - decided)
        else:
            in_queue = pending
        metrics[slug] = {
            "in_queue": in_queue,
            "completed": done,
            "auto_count": auto,
            "auto_pct": round(auto * 100 / done, 1) if done else 0.0,
            "avg_review_sec": float(row.get("avg_review_sec") or 0),
        }
    return metrics


# ─────────────────────────────────────────────────────────────────────
# 1) HOME PAGE — all 11 personas
# ─────────────────────────────────────────────────────────────────────


@router.get("/workbench", response_class=HTMLResponse)
async def home(request: Request):
    if not DATABASE_URL:
        return _not_configured(request)
    metrics = await _persona_metrics()
    cards_by_stage = []
    for stage in STAGES:
        cards = []
        for slug in stage["personas"]:
            cfg = PERSONA_CONFIG[slug]
            m = metrics.get(slug, {})
            cards.append(
                {
                    "slug": slug,
                    "title": cfg["title"],
                    "icon": cfg["icon"],
                    "color": cfg["color"],
                    "description": cfg["description"],
                    "mode": cfg["mode"],
                    "decision_id": cfg["decision_id"],
                    "in_queue": m.get("in_queue", 0),
                    "completed": m.get("completed", 0),
                    "auto_pct": m.get("auto_pct", 0.0),
                    "avg_review_sec": m.get("avg_review_sec", 0),
                }
            )
        cards_by_stage.append({"stage": stage, "cards": cards})
    return templates.TemplateResponse(
        "persona_home.html",
        {
            "request": request,
            **(await _base_ctx(None)),
            "active_nav": "home",
            "stages_with_cards": cards_by_stage,
            "total_decisions": await _total_decisions(),
        },
    )


# ─────────────────────────────────────────────────────────────────────
# Literal-prefix routes — registered BEFORE /workbench/{persona_slug}
# so the slug catcher does not swallow them.
# ─────────────────────────────────────────────────────────────────────


# ── 7) PIPELINE DASHBOARD ────────────────────────────────────────────


@router.get("/workbench/pipeline", response_class=HTMLResponse)
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
    return templates.TemplateResponse(
        "pipeline_dashboard.html",
        {
            "request": request,
            **(await _base_ctx(None)),
            "active_nav": "pipeline",
            "applications": [dict(a) for a in apps],
            "total_decisions": await _total_decisions(),
        },
    )


# ── 8) APPLICATION PIPELINE — one app's journey ──────────────────────


@router.get(
    "/workbench/pipeline/{application_id}", response_class=HTMLResponse
)
async def pipeline_app(request: Request, application_id: str):
    if not DATABASE_URL:
        return _not_configured(request)
    pool = await _get_pool()
    async with pool.acquire() as conn:
        decisions = await conn.fetch(
            """
            SELECT decision_id, wave, outcome, mode, confidence,
                   decided_at, human_action, human_reviewer,
                   risk_level, boundary_matched, boundary_rule
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
            "SELECT * FROM entity_states WHERE application_id = $1 LIMIT 1",
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
        slug = DECISION_TO_SLUG.get(dd["decision_id"])
        if slug:
            cfg = PERSONA_CONFIG[slug]
            dd["persona_slug"] = slug
            dd["persona_title"] = cfg["title"]
            dd["persona_color"] = cfg["color"]
        else:
            dd["persona_slug"] = None
            dd["persona_title"] = dd["decision_id"]
            dd["persona_color"] = "slate"
        by_wave.setdefault(int(dd["wave"] or 0), []).append(dd)
    waves = [{"wave": w, "decisions": by_wave[w]} for w in sorted(by_wave)]

    return templates.TemplateResponse(
        "pipeline_app.html",
        {
            "request": request,
            **(await _base_ctx(None)),
            "active_nav": "pipeline",
            "application_id": application_id,
            "entity": _entity_summary(entity),
            "waves": waves,
            "timeline": [dict(t) for t in timeline],
            "total_decisions": await _total_decisions(),
        },
    )


# ── 9) AUDIT DASHBOARD ───────────────────────────────────────────────


@router.get("/workbench/audit", response_class=HTMLResponse)
async def audit_dashboard(request: Request):
    if not DATABASE_URL:
        return _not_configured(request)
    pool = await _get_pool()
    async with pool.acquire() as conn:
        totals = await conn.fetchrow(
            """
            WITH latest AS (
                SELECT * FROM decision_outputs
                WHERE version = (
                    SELECT MAX(version) FROM decision_outputs d2
                    WHERE d2.application_id = decision_outputs.application_id
                      AND d2.decision_id = decision_outputs.decision_id
                )
            )
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE outcome = 'block') AS blocks,
                   COUNT(*) FILTER (WHERE outcome = 'escalate') AS escalations,
                   COUNT(*) FILTER (WHERE human_action = 'overridden') AS overrides,
                   COUNT(*) FILTER (
                       WHERE mode = 'auto_execute'
                          OR human_action IS NOT NULL
                   ) AS cleared,
                   COUNT(*) FILTER (WHERE mode = 'auto_execute') AS auto
            FROM latest
            """
        )
        override_by_persona = await conn.fetch(
            """
            SELECT decision_id,
                   COUNT(*) FILTER (
                       WHERE human_action = 'overridden'
                   ) AS overrides,
                   COUNT(*) FILTER (
                       WHERE human_action IS NOT NULL
                   ) AS reviewed
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
        blocked_apps = await conn.fetch(
            """
            SELECT application_id, decision_id, boundary_rule,
                   confidence, decided_at
            FROM decision_outputs
            WHERE outcome = 'block'
              AND version = (
                  SELECT MAX(version) FROM decision_outputs d2
                  WHERE d2.application_id = decision_outputs.application_id
                    AND d2.decision_id = decision_outputs.decision_id
              )
            ORDER BY decided_at DESC
            LIMIT 100
            """
        )
        fraud_blocks = await conn.fetchval(
            """
            SELECT COUNT(DISTINCT application_id) FROM decision_outputs
            WHERE decision_id = 'fraud_screening' AND outcome = 'block'
            """
        )
        compliance_blocks = await conn.fetchval(
            """
            SELECT COUNT(DISTINCT application_id) FROM decision_outputs
            WHERE decision_id = 'compliance_check' AND outcome = 'block'
            """
        )

    totals_d = dict(totals) if totals else {}
    overrides_table = []
    for r in override_by_persona:
        d = r["decision_id"]
        slug = DECISION_TO_SLUG.get(d)
        cfg = PERSONA_CONFIG.get(slug) if slug else None
        reviewed = int(r["reviewed"] or 0)
        overrides = int(r["overrides"] or 0)
        overrides_table.append(
            {
                "decision_id": d,
                "persona_title": cfg["title"] if cfg else d,
                "persona_slug": slug,
                "persona_color": cfg["color"] if cfg else "slate",
                "overrides": overrides,
                "reviewed": reviewed,
                "rate": round(overrides * 100 / reviewed, 1) if reviewed else 0.0,
            }
        )
    blocks_list = []
    for b in blocked_apps:
        bd = dict(b)
        slug = DECISION_TO_SLUG.get(bd["decision_id"])
        cfg = PERSONA_CONFIG.get(slug) if slug else None
        bd["persona_title"] = cfg["title"] if cfg else bd["decision_id"]
        bd["persona_slug"] = slug
        blocks_list.append(bd)

    return templates.TemplateResponse(
        "audit_dashboard.html",
        {
            "request": request,
            **(await _base_ctx(None)),
            "active_nav": "audit",
            "totals": totals_d,
            "overrides_table": overrides_table,
            "blocks": blocks_list,
            "fraud_blocks": int(fraud_blocks or 0),
            "compliance_blocks": int(compliance_blocks or 0),
            "total_decisions": await _total_decisions(),
        },
    )


# ── 10) AUDIT TRAIL — one application ────────────────────────────────


@router.get(
    "/workbench/audit/{application_id}", response_class=HTMLResponse
)
async def audit_app(request: Request, application_id: str):
    if not DATABASE_URL:
        return _not_configured(request)
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT decision_id, mode, outcome, confidence, risk_level,
                   human_action, human_reviewer, human_override_reason,
                   boundary_matched, boundary_rule, decided_at, acted_at,
                   sla_seconds, actual_seconds, version
            FROM decision_outputs
            WHERE application_id = $1
              AND version = (
                  SELECT MAX(version) FROM decision_outputs d2
                  WHERE d2.application_id = decision_outputs.application_id
                    AND d2.decision_id = decision_outputs.decision_id
              )
            ORDER BY decided_at
            """,
            application_id,
        )
        timeline = await conn.fetch(
            """
            SELECT decision_id, wave, from_state, to_state, trigger,
                   transition_at, pipeline_position,
                   time_in_prev_state_seconds,
                   cumulative_elapsed_seconds
            FROM decision_timeline
            WHERE application_id = $1
            ORDER BY transition_at
            """,
            application_id,
        )
        elapsed = await conn.fetchval(
            """
            SELECT EXTRACT(EPOCH FROM (
                MAX(transition_at) - MIN(transition_at)
            ))
            FROM decision_timeline
            WHERE application_id = $1
            """,
            application_id,
        )
    decisions = []
    for r in rows:
        d = dict(r)
        slug = DECISION_TO_SLUG.get(d["decision_id"])
        cfg = PERSONA_CONFIG.get(slug) if slug else None
        d["persona_slug"] = slug
        d["persona_title"] = cfg["title"] if cfg else d["decision_id"]
        decisions.append(d)
    return templates.TemplateResponse(
        "audit_app.html",
        {
            "request": request,
            **(await _base_ctx(None)),
            "active_nav": "audit",
            "application_id": application_id,
            "decisions": decisions,
            "timeline": [dict(t) for t in timeline],
            "total_pipeline_seconds": float(elapsed or 0),
            "total_decisions": await _total_decisions(),
        },
    )


# ── 11) GOVERNANCE ───────────────────────────────────────────────────


@router.get("/workbench/governance", response_class=HTMLResponse)
async def governance(request: Request):
    if not DATABASE_URL:
        return _not_configured(request)
    pool = await _get_pool()
    async with pool.acquire() as conn:
        outcome_grid = await conn.fetch(
            """
            SELECT decision_id, outcome, COUNT(*) AS n
            FROM decision_outputs
            WHERE version = (
                SELECT MAX(version) FROM decision_outputs d2
                WHERE d2.application_id = decision_outputs.application_id
                  AND d2.decision_id = decision_outputs.decision_id
            )
            GROUP BY decision_id, outcome
            """
        )
        overrides_by_reviewer = await conn.fetch(
            """
            SELECT human_reviewer,
                   COUNT(*) AS n,
                   COUNT(DISTINCT decision_id) AS distinct_personas
            FROM decision_outputs
            WHERE human_action = 'overridden'
            GROUP BY human_reviewer
            ORDER BY n DESC
            LIMIT 20
            """
        )
        overrides_by_reason = await conn.fetch(
            """
            SELECT COALESCE(human_override_reason, '(no reason given)')
                       AS reason,
                   COUNT(*) AS n
            FROM decision_outputs
            WHERE human_action = 'overridden'
            GROUP BY reason
            ORDER BY n DESC
            LIMIT 20
            """
        )
        sla_rows = await conn.fetch(
            """
            SELECT decision_id,
                   COUNT(*) AS total,
                   COUNT(*) FILTER (
                       WHERE actual_seconds <= sla_seconds
                   ) AS within_sla,
                   AVG(actual_seconds) AS avg_sec,
                   AVG(sla_seconds) AS avg_sla
            FROM decision_outputs
            WHERE actual_seconds IS NOT NULL AND sla_seconds IS NOT NULL
            GROUP BY decision_id
            ORDER BY decision_id
            """
        )

    grid: dict[str, dict[str, int]] = {}
    for r in outcome_grid:
        grid.setdefault(r["decision_id"], {})[r["outcome"]] = r["n"]
    rows_pretty = []
    for d in sorted(grid):
        slug = DECISION_TO_SLUG.get(d)
        cfg = PERSONA_CONFIG.get(slug) if slug else None
        cells = grid[d]
        rows_pretty.append(
            {
                "decision_id": d,
                "persona_title": cfg["title"] if cfg else d,
                "persona_slug": slug,
                "persona_color": cfg["color"] if cfg else "slate",
                "allow": cells.get("allow", 0),
                "recommend": cells.get("recommend", 0),
                "escalate": cells.get("escalate", 0),
                "block": cells.get("block", 0),
                "total": sum(cells.values()),
            }
        )

    sla_pretty = []
    for r in sla_rows:
        d = r["decision_id"]
        slug = DECISION_TO_SLUG.get(d)
        cfg = PERSONA_CONFIG.get(slug) if slug else None
        total = int(r["total"] or 0)
        within = int(r["within_sla"] or 0)
        sla_pretty.append(
            {
                "decision_id": d,
                "persona_title": cfg["title"] if cfg else d,
                "persona_color": cfg["color"] if cfg else "slate",
                "total": total,
                "within_sla": within,
                "sla_pct": round(within * 100 / total, 1) if total else 0.0,
                "avg_sec": float(r["avg_sec"] or 0),
                "avg_sla": float(r["avg_sla"] or 0),
            }
        )

    return templates.TemplateResponse(
        "governance.html",
        {
            "request": request,
            **(await _base_ctx(None)),
            "active_nav": "governance",
            "outcome_grid": rows_pretty,
            "overrides_by_reviewer": [dict(r) for r in overrides_by_reviewer],
            "overrides_by_reason": [dict(r) for r in overrides_by_reason],
            "sla": sla_pretty,
            "total_decisions": await _total_decisions(),
        },
    )


# ── Governance CSV export ────────────────────────────────────────────


@router.get("/workbench/governance/export.csv")
async def governance_export():
    if not DATABASE_URL:
        return RedirectResponse("/workbench", status_code=303)
    pool = await _get_pool()

    async def _stream():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([
            "application_id", "decision_id", "wave", "outcome", "mode",
            "risk_level", "boundary_matched", "confidence", "human_action",
            "human_reviewer", "human_override_reason", "decided_at",
            "acted_at", "sla_seconds", "actual_seconds", "version",
        ])
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)
        async with pool.acquire() as conn:
            async with conn.transaction():
                async for r in conn.cursor(
                    """
                    SELECT application_id, decision_id, wave, outcome, mode,
                           risk_level, boundary_matched, confidence,
                           human_action, human_reviewer,
                           human_override_reason, decided_at, acted_at,
                           sla_seconds, actual_seconds, version
                    FROM decision_outputs
                    ORDER BY decided_at
                    """
                ):
                    w.writerow([
                        r["application_id"], r["decision_id"], r["wave"],
                        r["outcome"], r["mode"], r["risk_level"],
                        r["boundary_matched"], r["confidence"],
                        r["human_action"], r["human_reviewer"],
                        r["human_override_reason"],
                        r["decided_at"].isoformat() if r["decided_at"] else "",
                        r["acted_at"].isoformat() if r["acted_at"] else "",
                        r["sla_seconds"], r["actual_seconds"], r["version"],
                    ])
                    yield buf.getvalue()
                    buf.seek(0)
                    buf.truncate(0)

    return StreamingResponse(
        _stream(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=decisions.csv"},
    )


# ─────────────────────────────────────────────────────────────────────
# 2) PERSONA WORKBENCH — 4 tabs
# ─────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────
# Per-persona KPI cards + tab labels.
#
# Every persona has 4 KPI cards and 3 tabs that match their actual
# lending job. Credit underwriters care about Approved / Flagged /
# Blocked counts; compliance officers care about Pending review and
# Avg review time; pricing analysts care about Normal band / Exception
# pricing / Usury blocked. The shape per entry:
#
#   "kind":  "auto" | "human"           — drives tab semantics
#   "cards": [ { label, query, color } × 4 ]
#   "tabs":  [ (slug, label) × 3 ]
#
# All query kinds are computed in _compute_kpi_card below against the
# current date range (with pending_human as the only unfiltered card).
# ─────────────────────────────────────────────────────────────────────


# Every human-review persona (mode 'recommend' or 'human_approval')
# shares ONE card set and tab layout — the human-review workflow is the
# same regardless of which role is reviewing. The 4 cards map 1:1 onto
# the lifecycle of a decision a human acts on:
#
#   Pending review → un-acted (human_action IS NULL); these need attention
#   Approved       → human accepted the AI proposal as-is
#   Overridden     → human changed the outcome
#   Blocked        → current outcome is 'block' (hard stop)
#
# RECOMMEND / ESCALATE proposals that nobody has reviewed yet live under
# "Pending review", not a separate "Flagged" card — once a human acts they
# move to Approved or Overridden.
HUMAN_REVIEW_CARDS: list[dict[str, Any]] = [
    {"label": "Pending review", "query": "pending_human",       "color": "orange"},
    {"label": "Approved",       "query": "count_human_approved", "color": "green"},
    {"label": "Overridden",     "query": "count_overridden",     "color": "violet"},
    {"label": "Blocked",        "query": "count_block",          "color": "red"},
]
HUMAN_REVIEW_TABS: list[tuple[str, str]] = [
    ("pending", "Pending review"),
    ("reviewed", "Reviewed"),
    ("analytics", "Analytics"),
]


def _human_kpis() -> dict[str, Any]:
    """Fresh copy of the shared human-review KPI config so per-persona
    edits never alias the module-level card list."""
    return {
        "kind": "human",
        "cards": [dict(c) for c in HUMAN_REVIEW_CARDS],
        "tabs": list(HUMAN_REVIEW_TABS),
    }


PERSONA_KPIS: dict[str, dict[str, Any]] = {
    # ── Human-review personas (mode recommend / human_approval) ──────
    # All 9 use kind='human' so their Pending review queue links to
    # /review/ (Approve / Override / Revert), NOT the read-only
    # /completed/ page. Cross-referenced against the modes in
    # PERSONA_CONFIG and core/cron/runner.py DECISION_CONFIG.
    "credit_underwriter":    _human_kpis(),   # recommend
    "income_underwriter":    _human_kpis(),   # recommend
    "employment_specialist": _human_kpis(),   # recommend
    "fraud_analyst":         _human_kpis(),   # human_approval
    "compliance_officer":    _human_kpis(),   # human_approval
    "product_specialist":    _human_kpis(),   # recommend
    "pricing_analyst":       _human_kpis(),   # recommend
    "senior_underwriter":    _human_kpis(),   # human_approval
    "closer":                _human_kpis(),   # human_approval
    # ── Auto personas (mode auto_execute) — finalized by the system, ──
    # no human queue. Only these two have workbench pages.
    "collateral_analyst": {
        "kind": "auto",
        "cards": [
            {"label": "Total assessed",    "query": "total",                     "color": "default"},
            {"label": "LTV ≤ 80%",         "query": "count_allow",               "color": "green"},
            {"label": "LTV 80-95%",        "query": "count_recommend",           "color": "amber"},
            {"label": "LTV > 97%",         "query": "count_block",               "color": "red"},
        ],
        "tabs": [("all", "All decisions"), ("by_outcome", "By outcome"), ("analytics", "Analytics")],
    },
    "post_closer": {
        "kind": "auto",
        "cards": [
            {"label": "Total routed",      "query": "total",                     "color": "default"},
            {"label": "Approved sent",     "query": "count_allow",               "color": "green"},
            {"label": "Conditional sent", "query": "count_recommend",            "color": "amber"},
            {"label": "Avg routing time",  "query": "avg_processing_time",       "color": "default"},
        ],
        "tabs": [("all", "All decisions"), ("by_outcome", "By outcome"), ("analytics", "Analytics")],
    },
}


# Tailwind color → number-class map for the 5 KPI palette values.
_KPI_COLOR_CLASS: dict[str, str] = {
    "default": "text-slate-900",
    "green":   "text-emerald-700",
    "amber":   "text-amber-700",
    "orange":  "text-orange-600",
    "violet":  "text-violet-700",
    "red":     "text-rose-700",
}


async def _compute_kpi_card(
    conn: Any,
    decision_id: str,
    query_kind: str,
    date_clause: str,
    date_args: list[Any],
) -> dict[str, Any]:
    """Run the SQL for one card kind and return:

        { "value": int|float|None, "display": str }

    Caller wraps this with the card's label + color before handing to
    the template. ``date_clause`` is the same ``AND decided_at …``
    fragment the rest of the route builds; ``date_args`` are bound
    after the leading ``$1 = decision_id``."""
    # Strip ``dout.`` aliasing — the route builds the clause for the
    # tab-specific queries that join entity_states; the KPI helpers
    # query an unaliased ``decision_outputs``.
    date_clause = date_clause.replace("dout.", "")
    latest_clause = (
        " AND version = ("
        "    SELECT MAX(version) FROM decision_outputs d2"
        "    WHERE d2.application_id = decision_outputs.application_id"
        "      AND d2.decision_id = decision_outputs.decision_id"
        ")"
    )
    base = (
        "FROM decision_outputs WHERE decision_id = $1"
        + latest_clause + date_clause
    )

    async def _scalar(sql: str) -> Any:
        return await conn.fetchval(sql, decision_id, *date_args)

    if query_kind == "total":
        n = await _scalar(f"SELECT COUNT(*) {base}")
        return {"value": int(n or 0), "display": f"{int(n or 0):,}"}
    if query_kind == "count_allow":
        n = await _scalar(f"SELECT COUNT(*) {base} AND outcome = 'allow'")
        return {"value": int(n or 0), "display": f"{int(n or 0):,}"}
    if query_kind == "count_recommend":
        n = await _scalar(f"SELECT COUNT(*) {base} AND outcome = 'recommend'")
        return {"value": int(n or 0), "display": f"{int(n or 0):,}"}
    if query_kind == "count_escalate":
        n = await _scalar(f"SELECT COUNT(*) {base} AND outcome = 'escalate'")
        return {"value": int(n or 0), "display": f"{int(n or 0):,}"}
    if query_kind == "count_block":
        n = await _scalar(f"SELECT COUNT(*) {base} AND outcome = 'block'")
        return {"value": int(n or 0), "display": f"{int(n or 0):,}"}
    if query_kind == "count_recommend_escalate":
        n = await _scalar(
            f"SELECT COUNT(*) {base} AND outcome IN ('recommend', 'escalate')"
        )
        return {"value": int(n or 0), "display": f"{int(n or 0):,}"}
    if query_kind == "pending_human":
        # NOTE: pending is the only card that stays unfiltered by date —
        # it reflects work waiting right now, not historical throughput.
        # We rebuild the args list without the date clause for this one.
        sql = (
            "SELECT COUNT(*) FROM decision_outputs WHERE decision_id = $1"
            " AND human_action IS NULL"
            " AND mode IN ('human_approval', 'recommend')"
            + latest_clause
        )
        n = await conn.fetchval(sql, decision_id)
        return {"value": int(n or 0), "display": f"{int(n or 0):,}"}
    if query_kind == "count_approved":
        n = await _scalar(
            f"SELECT COUNT(*) {base} AND human_action IS NOT NULL"
        )
        return {"value": int(n or 0), "display": f"{int(n or 0):,}"}
    if query_kind == "count_human_approved":
        # Reviewer accepted the AI proposal as-is (human_action='approved').
        # Distinct from count_approved, which counts ANY human action.
        n = await _scalar(
            f"SELECT COUNT(*) {base} AND human_action = 'approved'"
        )
        return {"value": int(n or 0), "display": f"{int(n or 0):,}"}
    if query_kind == "count_overridden":
        n = await _scalar(
            f"SELECT COUNT(*) {base} AND human_action = 'overridden'"
        )
        return {"value": int(n or 0), "display": f"{int(n or 0):,}"}
    if query_kind == "count_allow_approved":
        n = await _scalar(
            f"SELECT COUNT(*) {base}"
            " AND outcome = 'allow'"
            " AND (mode = 'auto_execute' OR human_action IS NOT NULL)"
        )
        return {"value": int(n or 0), "display": f"{int(n or 0):,}"}
    if query_kind == "override_rate":
        reviewed = await _scalar(
            f"SELECT COUNT(*) {base} AND human_action IS NOT NULL"
        ) or 0
        overridden = await _scalar(
            f"SELECT COUNT(*) {base} AND human_action = 'overridden'"
        ) or 0
        pct = round(int(overridden) * 100 / int(reviewed), 1) if reviewed else 0.0
        return {"value": pct, "display": f"{pct}%"}
    if query_kind == "count_escalate_pct":
        total = await _scalar(f"SELECT COUNT(*) {base}") or 0
        esc = await _scalar(
            f"SELECT COUNT(*) {base} AND outcome = 'escalate'"
        ) or 0
        pct = round(int(esc) * 100 / int(total), 1) if total else 0.0
        return {"value": pct, "display": f"{pct}%"}
    if query_kind == "avg_review_time":
        sec = await _scalar(
            f"SELECT AVG(EXTRACT(EPOCH FROM (acted_at - decided_at))) {base}"
            " AND human_action IS NOT NULL AND acted_at IS NOT NULL"
        )
        if sec is None or float(sec) <= 0:
            return {"value": None, "display": "—"}
        s = float(sec)
        if s < 3600:
            return {"value": s, "display": f"{s / 60:.1f}m"}
        return {"value": s, "display": f"{s / 3600:.1f}h"}
    if query_kind == "avg_review_time_days":
        sec = await _scalar(
            f"SELECT AVG(EXTRACT(EPOCH FROM (acted_at - decided_at))) {base}"
            " AND human_action IS NOT NULL AND acted_at IS NOT NULL"
        )
        if sec is None or float(sec) <= 0:
            return {"value": None, "display": "—"}
        days = float(sec) / 86400.0
        return {"value": days, "display": f"{days:.1f} days"}
    if query_kind == "avg_processing_time":
        sec = await _scalar(f"SELECT AVG(actual_seconds) {base}")
        if sec is None or float(sec) < 0:
            return {"value": None, "display": "—"}
        return {"value": float(sec), "display": f"{float(sec):.1f}s"}
    # Unknown kind — render an em-dash so the card still shows up.
    return {"value": None, "display": "—"}


async def _by_outcome_groups(
    conn: Any,
    decision_id: str,
    date_clause: str,
    date_args: list[Any],
) -> list[dict[str, Any]]:
    """Group decisions by outcome, return sample applications per group.

    Powers the "By outcome" tab for auto_execute personas. Up to 8
    sample app ids per outcome so the page doesn't balloon."""
    date_clause = date_clause.replace("dout.", "")
    latest_clause = (
        " AND version = ("
        "    SELECT MAX(version) FROM decision_outputs d2"
        "    WHERE d2.application_id = decision_outputs.application_id"
        "      AND d2.decision_id = decision_outputs.decision_id"
        ")"
    )
    counts_sql = (
        "SELECT outcome, COUNT(*) AS n FROM decision_outputs"
        " WHERE decision_id = $1" + latest_clause + date_clause +
        " GROUP BY outcome"
    )
    samples_sql = (
        "WITH ranked AS ("
        "  SELECT application_id, outcome, confidence, decided_at,"
        "         ROW_NUMBER() OVER (PARTITION BY outcome ORDER BY decided_at DESC) AS rn"
        "  FROM decision_outputs"
        "  WHERE decision_id = $1" + latest_clause + date_clause +
        ")"
        " SELECT application_id, outcome, confidence, decided_at"
        " FROM ranked WHERE rn <= 8"
    )
    counts = await conn.fetch(counts_sql, decision_id, *date_args)
    samples = await conn.fetch(samples_sql, decision_id, *date_args)
    by_outcome: dict[str, list[dict[str, Any]]] = {}
    for s in samples:
        by_outcome.setdefault(s["outcome"], []).append(dict(s))
    return [
        {
            "outcome": r["outcome"],
            "count": int(r["n"] or 0),
            "samples": by_outcome.get(r["outcome"], []),
        }
        for r in sorted(counts, key=lambda r: -int(r["n"] or 0))
    ]


def _normalize_tab(tab: str, kind: str) -> str:
    """Map legacy tab slugs (queue / completed / auto) onto the new
    persona-kind-aware names (pending / reviewed / all / by_outcome /
    analytics). Unknown slugs fall through to the first tab for the
    persona kind."""
    legacy = {
        ("queue", "human"):      "pending",
        ("queue", "auto"):       "all",
        ("completed", "human"):  "reviewed",
        ("completed", "auto"):   "all",
        ("auto", "auto"):        "all",
        ("auto", "human"):       "pending",
    }
    if tab in ("pending", "reviewed", "all", "by_outcome", "analytics"):
        return tab
    if (tab, kind) in legacy:
        return legacy[(tab, kind)]
    return "pending" if kind == "human" else "all"


# ─────────────────────────────────────────────────────────────────────
# Date range filter — drives every persona workbench query.
#
# Sidebar queue badges, the In-Queue KPI card, and home-page metrics
# stay UNFILTERED (they reflect work waiting right now); everything
# else on the persona workbench page narrows to the selected window.
# ─────────────────────────────────────────────────────────────────────


RANGE_KEYS: tuple[str, ...] = (
    "today", "this_week", "this_month", "this_quarter",
    "this_year", "all_time", "custom",
)
RANGE_LABELS: dict[str, str] = {
    "today":        "today",
    "this_week":    "this week",
    "this_month":   "this month",
    "this_quarter": "this quarter",
    "this_year":    "this year",
    "all_time":     "all time",
    "custom":       "custom range",
}


def _date_range(
    range_key: str,
    from_str: Optional[str],
    to_str: Optional[str],
) -> tuple[Optional[datetime], Optional[datetime], str, Optional[str], Optional[str]]:
    """Resolve (start, end, normalized_key, from_str, to_str).

    Returns tz-aware UTC datetimes. ``start`` is inclusive, ``end`` is
    exclusive (matches ``decided_at >= start AND decided_at < end``).
    For ``all_time`` both bounds are None."""
    from datetime import date as _date, timedelta as _td

    if range_key not in RANGE_KEYS:
        range_key = "this_month"

    now = datetime.now(timezone.utc)
    today = now.date()

    def _at(d: _date) -> datetime:
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)

    if range_key == "today":
        start, end = _at(today), _at(today + _td(days=1))
    elif range_key == "this_week":
        monday = today - _td(days=today.weekday())
        start, end = _at(monday), _at(monday + _td(days=7))
    elif range_key == "this_month":
        first = today.replace(day=1)
        if first.month == 12:
            next_first = first.replace(year=first.year + 1, month=1)
        else:
            next_first = first.replace(month=first.month + 1)
        start, end = _at(first), _at(next_first)
    elif range_key == "this_quarter":
        q_start_month = ((today.month - 1) // 3) * 3 + 1
        q_start = today.replace(month=q_start_month, day=1)
        end_month = q_start_month + 3
        if end_month > 12:
            q_end = q_start.replace(year=q_start.year + 1, month=end_month - 12)
        else:
            q_end = q_start.replace(month=end_month)
        start, end = _at(q_start), _at(q_end)
    elif range_key == "this_year":
        start = _at(today.replace(month=1, day=1))
        end = _at(today.replace(year=today.year + 1, month=1, day=1))
    elif range_key == "all_time":
        return (None, None, "all_time", None, None)
    else:
        # custom: parse from/to strings; either may be missing
        f = None
        t = None
        try:
            if from_str:
                fd = datetime.strptime(from_str, "%Y-%m-%d").date()
                f = _at(fd)
            if to_str:
                td = datetime.strptime(to_str, "%Y-%m-%d").date()
                # Inclusive end-of-day → exclusive next-day midnight.
                t = _at(td + _td(days=1))
        except ValueError:
            # bad date string → fall through to this_month default
            return _date_range("this_month", None, None)
        return (f, t, "custom", from_str, to_str)

    return (start, end, range_key, None, None)


@router.get("/workbench/{persona_slug}", response_class=HTMLResponse)
async def persona_workbench(
    request: Request,
    persona_slug: str,
    tab: str = Query("queue"),
    range: str = Query("this_month"),  # noqa: A002 — query param name
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
):
    if not DATABASE_URL:
        return _not_configured(request)
    persona = _persona_or_none(persona_slug)
    if persona is None:
        return await _persona_404(request, persona_slug)

    decision_id = persona["decision_id"]
    mode = persona["mode"]
    pool = await _get_pool()

    start, end, range_key, date_from_str, date_to_str = _date_range(
        range, date_from, date_to
    )
    # decided_at filter fragment + extra args (always positioned after
    # the leading $1 = decision_id). Building the string is the
    # cleanest way to keep the bind-arg count consistent across the
    # 4 tabs without per-tab branches.
    date_clause = ""
    date_args: list[Any] = []
    if start is not None:
        date_args.append(start)
        date_clause += f" AND dout.decided_at >= ${len(date_args) + 1}"
    if end is not None:
        date_args.append(end)
        date_clause += f" AND dout.decided_at < ${len(date_args) + 1}"
    # Variant without the `dout.` alias for queries that read
    # decision_outputs without aliasing.
    date_clause_plain = date_clause.replace("dout.", "")

    # Persona-specific KPI config + 3-tab system. Fall back to a
    # generic auto-style layout if a persona isn't in PERSONA_KPIS
    # (defensive — keeps the page rendering during config edits).
    kpi_cfg = PERSONA_KPIS.get(persona_slug) or {
        "kind": "human" if mode != "auto_execute" else "auto",
        "cards": [
            {"label": "Total",        "query": "total",         "color": "default"},
            {"label": "Allow",        "query": "count_allow",   "color": "green"},
            {"label": "Recommend",    "query": "count_recommend", "color": "amber"},
            {"label": "Block",        "query": "count_block",   "color": "red"},
        ],
        "tabs": [
            ("pending" if mode != "auto_execute" else "all",
             "Pending review" if mode != "auto_execute" else "All decisions"),
            ("reviewed" if mode != "auto_execute" else "by_outcome",
             "Reviewed" if mode != "auto_execute" else "By outcome"),
            ("analytics", "Analytics"),
        ],
    }
    persona_kind = kpi_cfg["kind"]
    tab = _normalize_tab(tab, persona_kind)
    payload: dict[str, Any] = {}
    summary_fields = persona["summary_fields"]

    # ── KPI strip — render the 4 cards from the persona's config ──
    kpi_cards: list[dict[str, Any]] = []
    async with pool.acquire() as conn:
        for card in kpi_cfg["cards"]:
            data = await _compute_kpi_card(
                conn, decision_id, card["query"], date_clause, date_args
            )
            # When pending_human is 0, flip the color to green so the
            # operator sees the queue is clear at a glance (the spec).
            color = card["color"]
            if card["query"] == "pending_human" and (data["value"] or 0) == 0:
                color = "green"
                data = {**data, "display": "✓ 0"}
            kpi_cards.append(
                {
                    "label": card["label"],
                    "display": data["display"],
                    "value": data["value"],
                    "color_class": _KPI_COLOR_CLASS.get(color, "text-slate-900"),
                    "color": color,
                    "query": card["query"],
                }
            )

    if tab == "pending":
        # Human personas: queue of un-acted decisions, oldest first
        # (FIFO). Date filter applied to decided_at.
        sql = f"""
            SELECT dout.application_id, dout.outcome,
                   dout.confidence, dout.decided_at,
                   dout.boundary_rule, dout.stale,
                   es.mid_credit_score, es.ltv, es.dti_back,
                   es.loan_amount, es.status
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
              ){date_clause}
            ORDER BY dout.decided_at ASC
            LIMIT 200
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, decision_id, *date_args)
        payload = {"queue_rows": [dict(r) for r in rows]}

    elif tab == "reviewed":
        # Human personas: rows where a reviewer has acted (approved
        # or overridden), most recent first.
        sql = f"""
            SELECT dout.application_id, dout.outcome, dout.mode,
                   dout.confidence, dout.decided_at, dout.acted_at,
                   dout.human_action, dout.human_reviewer,
                   dout.human_override_reason,
                   dout.boundary_rule, dout.reasoning, dout.stale,
                   (
                       SELECT t.from_state FROM decision_timeline t
                       WHERE t.application_id = dout.application_id
                         AND t.decision_id = dout.decision_id
                         AND t.trigger IN ('human_approve', 'human_override')
                       ORDER BY t.transition_at ASC
                       LIMIT 1
                   ) AS proposed_outcome,
                   es.mid_credit_score, es.ltv, es.dti_back, es.loan_amount
            FROM decision_outputs dout
            LEFT JOIN entity_states es
                   ON es.application_id = dout.application_id
                  AND es.tenant_id = dout.tenant_id
            WHERE dout.decision_id = $1
              AND dout.human_action IS NOT NULL
              AND dout.version = (
                  SELECT MAX(version) FROM decision_outputs d2
                  WHERE d2.application_id = dout.application_id
                    AND d2.decision_id = dout.decision_id
              ){date_clause}
            ORDER BY dout.acted_at DESC NULLS LAST
            LIMIT 200
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, decision_id, *date_args)
        completed_rows = []
        for r in rows:
            d = dict(r)
            d["reasoning"] = _maybe_json(d.get("reasoning"))
            completed_rows.append(d)
        payload = {"completed_rows": completed_rows}

    elif tab == "all":
        # Auto personas: every decision this persona has produced,
        # most recent first.
        sql = f"""
            SELECT dout.application_id, dout.outcome, dout.mode,
                   dout.confidence, dout.decided_at, dout.acted_at,
                   dout.human_action, dout.human_reviewer,
                   dout.human_override_reason,
                   dout.boundary_rule, dout.reasoning,
                   es.mid_credit_score, es.ltv, es.dti_back, es.loan_amount
            FROM decision_outputs dout
            LEFT JOIN entity_states es
                   ON es.application_id = dout.application_id
                  AND es.tenant_id = dout.tenant_id
            WHERE dout.decision_id = $1
              AND dout.version = (
                  SELECT MAX(version) FROM decision_outputs d2
                  WHERE d2.application_id = dout.application_id
                    AND d2.decision_id = dout.decision_id
              ){date_clause}
            ORDER BY dout.decided_at DESC
            LIMIT 200
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, decision_id, *date_args)
        completed_rows = []
        for r in rows:
            d = dict(r)
            d["reasoning"] = _maybe_json(d.get("reasoning"))
            completed_rows.append(d)
        payload = {"completed_rows": completed_rows}

    elif tab == "by_outcome":
        # Auto personas: grouped view — count + sample apps per outcome.
        async with pool.acquire() as conn:
            groups = await _by_outcome_groups(
                conn, decision_id, date_clause, date_args
            )
        payload = {"by_outcome_groups": groups}

    elif tab == "analytics":
        outcome_sql = f"""
            SELECT outcome, COUNT(*) AS n FROM decision_outputs dout
            WHERE decision_id = $1
              AND version = (
                  SELECT MAX(version) FROM decision_outputs d2
                  WHERE d2.application_id = dout.application_id
                    AND d2.decision_id = dout.decision_id
              ){date_clause}
            GROUP BY outcome
        """
        agg_sql = f"""
            SELECT COUNT(*) AS total,
                   AVG(confidence) AS avg_conf,
                   AVG(actual_seconds) AS avg_sec,
                   COUNT(*) FILTER (WHERE mode = 'auto_execute') AS auto,
                   COUNT(*) FILTER (
                       WHERE human_action = 'overridden'
                   ) AS overrides,
                   COUNT(*) FILTER (
                       WHERE human_action IS NOT NULL
                   ) AS reviewed
            FROM decision_outputs dout
            WHERE decision_id = $1
              AND version = (
                  SELECT MAX(version) FROM decision_outputs d2
                  WHERE d2.application_id = dout.application_id
                    AND d2.decision_id = dout.decision_id
              ){date_clause}
        """
        rules_sql = f"""
            SELECT COALESCE(boundary_rule, '(no rule)') AS rule,
                   COUNT(*) AS n
            FROM decision_outputs dout
            WHERE decision_id = $1
              AND version = (
                  SELECT MAX(version) FROM decision_outputs d2
                  WHERE d2.application_id = dout.application_id
                    AND d2.decision_id = dout.decision_id
              ){date_clause}
            GROUP BY rule
            ORDER BY n DESC
            LIMIT 5
        """
        review_sql = f"""
            SELECT AVG(EXTRACT(EPOCH FROM (acted_at - decided_at)))
            FROM decision_outputs dout
            WHERE decision_id = $1
              AND human_action IS NOT NULL
              AND acted_at IS NOT NULL{date_clause}
        """
        async with pool.acquire() as conn:
            outcome_dist = await conn.fetch(outcome_sql, decision_id, *date_args)
            agg = await conn.fetchrow(agg_sql, decision_id, *date_args)
            top_rules = await conn.fetch(rules_sql, decision_id, *date_args)
            avg_review = await conn.fetchval(
                review_sql, decision_id, *date_args
            )
        total = int(agg["total"] or 0) if agg else 0
        reviewed = int(agg["reviewed"] or 0) if agg else 0
        overrides = int(agg["overrides"] or 0) if agg else 0
        auto = int(agg["auto"] or 0) if agg else 0
        outcome_counts = {r["outcome"]: r["n"] for r in outcome_dist}
        payload = {
            "analytics": {
                "total": total,
                "outcomes": outcome_counts,
                "auto_pct": round(auto * 100 / total, 1) if total else 0.0,
                "avg_confidence": float(agg["avg_conf"] or 0) if agg else 0.0,
                "avg_processing_sec": float(agg["avg_sec"] or 0) if agg else 0.0,
                "avg_review_sec": float(avg_review or 0),
                "override_rate": (
                    round(overrides * 100 / reviewed, 1) if reviewed else 0.0
                ),
                "top_rules": [
                    {"rule": r["rule"], "n": r["n"]} for r in top_rules
                ],
            }
        }

    # Pre-baked query suffix the template uses on tab links so the
    # selected range survives a tab switch.
    qs_parts = [f"range={range_key}"]
    if range_key == "custom":
        if date_from_str:
            qs_parts.append(f"from={date_from_str}")
        if date_to_str:
            qs_parts.append(f"to={date_to_str}")
    range_query_suffix = "&" + "&".join(qs_parts)

    return templates.TemplateResponse(
        "persona_workbench.html",
        {
            "request": request,
            **(await _base_ctx(persona_slug)),
            "persona": persona,
            "tab": tab,
            "kpi_cards": kpi_cards,
            "tabs_config": kpi_cfg["tabs"],
            "persona_kind": persona_kind,
            "summary_fields": summary_fields,
            "total_decisions": await _total_decisions(),
            "range_key": range_key,
            "range_label": RANGE_LABELS[range_key],
            "range_options": [
                (k, RANGE_LABELS[k].capitalize()) for k in RANGE_KEYS
            ],
            "date_from_str": date_from_str,
            "date_to_str": date_to_str,
            "range_query_suffix": range_query_suffix,
            **payload,
        },
    )


async def _persona_in_queue_count(decision_id: str, mode: str) -> int:
    """Current pending count for the In-Queue KPI card.

    For human personas: decision_outputs WHERE human_action IS NULL.
    For auto_execute: apps in entity_states without a decision row."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        if mode == "auto_execute":
            decided = await conn.fetchval(
                """
                SELECT COUNT(*) FROM decision_outputs
                WHERE decision_id = $1
                  AND version = (
                      SELECT MAX(version) FROM decision_outputs d2
                      WHERE d2.application_id = decision_outputs.application_id
                        AND d2.decision_id = decision_outputs.decision_id
                  )
                """,
                decision_id,
            )
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM entity_states"
            )
            return max(0, int(total or 0) - int(decided or 0))
        n = await conn.fetchval(
            """
            SELECT COUNT(*) FROM decision_outputs
            WHERE decision_id = $1
              AND mode IN ('human_approval', 'recommend')
              AND human_action IS NULL
              AND version = (
                  SELECT MAX(version) FROM decision_outputs d2
                  WHERE d2.application_id = decision_outputs.application_id
                    AND d2.decision_id = decision_outputs.decision_id
              )
            """,
            decision_id,
        )
    return int(n or 0)


async def _persona_kpi_window(
    decision_id: str,
    start: Optional[datetime],
    end: Optional[datetime],
) -> dict[str, Any]:
    """Date-bounded KPI numbers: completed count, auto-decided %, avg
    human-review time. ``In Queue`` is computed separately and stays
    unfiltered."""
    pool = await _get_pool()
    date_clause = ""
    date_args: list[Any] = []
    if start is not None:
        date_args.append(start)
        date_clause += f" AND dout.decided_at >= ${len(date_args) + 1}"
    if end is not None:
        date_args.append(end)
        date_clause += f" AND dout.decided_at < ${len(date_args) + 1}"

    sql = f"""
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE mode = 'auto_execute') AS auto,
               AVG(
                   CASE WHEN acted_at IS NOT NULL AND decided_at IS NOT NULL
                        THEN EXTRACT(EPOCH FROM (acted_at - decided_at))
                   END
               ) AS avg_review_sec
        FROM decision_outputs dout
        WHERE decision_id = $1
          AND version = (
              SELECT MAX(version) FROM decision_outputs d2
              WHERE d2.application_id = dout.application_id
                AND d2.decision_id = dout.decision_id
          ){date_clause}
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, decision_id, *date_args)

    total = int(row["total"] or 0) if row else 0
    auto = int(row["auto"] or 0) if row else 0
    return {
        "completed": total,
        "auto_pct": round(auto * 100 / total, 1) if total else 0.0,
        "avg_review_sec": (
            float(row["avg_review_sec"]) if row and row["avg_review_sec"] is not None
            else 0.0
        ),
    }


# ─────────────────────────────────────────────────────────────────────
# 3) REVIEW DETAIL
# ─────────────────────────────────────────────────────────────────────


@router.get(
    "/workbench/{persona_slug}/review/{application_id}",
    response_class=HTMLResponse,
)
async def review_detail(
    request: Request, persona_slug: str, application_id: str
):
    if not DATABASE_URL:
        return _not_configured(request)
    persona = _persona_or_none(persona_slug)
    if persona is None:
        return await _persona_404(request, persona_slug)
    return await _render_review(
        request, persona, application_id, readonly=False
    )


@router.get(
    "/workbench/{persona_slug}/completed/{application_id}",
    response_class=HTMLResponse,
)
async def completed_detail(
    request: Request, persona_slug: str, application_id: str
):
    if not DATABASE_URL:
        return _not_configured(request)
    persona = _persona_or_none(persona_slug)
    if persona is None:
        return await _persona_404(request, persona_slug)
    return await _render_review(
        request, persona, application_id, readonly=True
    )


async def _render_review(
    request: Request,
    persona: dict[str, Any],
    application_id: str,
    readonly: bool,
) -> HTMLResponse:
    decision_id = persona["decision_id"]
    pool = await _get_pool()
    edms = _get_edms()

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
            "SELECT * FROM entity_states WHERE application_id = $1 LIMIT 1",
            application_id,
        )
        doc_rows = await conn.fetch(
            """
            SELECT document_type, document_category, status, confidence_score
            FROM document_index
            WHERE application_id = $1 AND COALESCE(is_current, true)
            ORDER BY document_category, document_type
            """,
            application_id,
        )
        upstreams = UPSTREAM.get(decision_id, [])
        upstream_rows: list[dict[str, Any]] = []
        if upstreams:
            urows = await conn.fetch(
                """
                SELECT decision_id, outcome, confidence, decided_at,
                       human_action
                FROM decision_outputs
                WHERE application_id = $1
                  AND decision_id = ANY($2)
                  AND version = (
                      SELECT MAX(version) FROM decision_outputs d2
                      WHERE d2.application_id = decision_outputs.application_id
                        AND d2.decision_id = decision_outputs.decision_id
                  )
                """,
                application_id,
                upstreams,
            )
            for r in urows:
                d = dict(r)
                slug = DECISION_TO_SLUG.get(d["decision_id"])
                cfg = PERSONA_CONFIG.get(slug) if slug else None
                d["persona_slug"] = slug
                d["persona_title"] = cfg["title"] if cfg else d["decision_id"]
                d["persona_color"] = cfg["color"] if cfg else "slate"
                upstream_rows.append(d)

        # Queue navigation (only meaningful in non-readonly mode).
        nav_ids: list[str] = []
        if not readonly and persona["mode"] != "auto_execute":
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
            nav_ids = [r["application_id"] for r in nav_rows]

        # If this decision was flagged stale by an upstream revert, pull
        # the most recent revert event for the application so the banner
        # can name who reopened it and when.
        revert_info: Optional[dict[str, Any]] = None
        if decision is not None and decision.get("stale"):
            rev = await conn.fetchrow(
                """
                SELECT decision_id, transition_at, waiting_on
                FROM decision_timeline
                WHERE application_id = $1 AND trigger = 'human_revert'
                ORDER BY transition_at DESC
                LIMIT 1
                """,
                application_id,
            )
            if rev is not None:
                meta = _maybe_json(rev["waiting_on"])
                meta = meta if isinstance(meta, dict) else {}
                slug = DECISION_TO_SLUG.get(rev["decision_id"])
                cfg = PERSONA_CONFIG.get(slug) if slug else None
                revert_info = {
                    "date": rev["transition_at"],
                    "reverter": meta.get("reverted_by"),
                    "reason": meta.get("reason"),
                    "decision_id": rev["decision_id"],
                    "persona_title": cfg["title"] if cfg else rev["decision_id"],
                }

    # Persona context via EDMS view.
    try:
        snap = await edms.snapshot(
            application_id=application_id,
            decision_id=decision_id,
            upstream_decision_ids=None,
        )
        ctx_objects = snap.context
    except Exception as exc:  # noqa: BLE001
        ctx_objects = {"_error": {"detail": {"message": str(exc)}}}

    # Flatten: build a dict of all known field-name → value (first match
    # across object buckets wins). Used to display persona key_fields.
    flat_ctx: dict[str, Any] = {}
    raw_groups: list[dict[str, Any]] = []
    for object_type, by_id in (ctx_objects or {}).items():
        if not isinstance(by_id, dict):
            continue
        for entity_id, fields in by_id.items():
            if not isinstance(fields, dict):
                continue
            raw_groups.append(
                {
                    "object_type": object_type,
                    "entity_id": entity_id,
                    "fields": [
                        {"key": k, "value": v} for k, v in fields.items()
                    ],
                }
            )
            for k, v in fields.items():
                flat_ctx.setdefault(k, v)

    entity_dict = dict(entity) if entity else {}
    key_field_rows = []
    for field in persona["key_fields"]:
        val = flat_ctx.get(field)
        if val is None:
            val = entity_dict.get(field)
        key_field_rows.append({"key": field, "value": val})

    decision_dict: Optional[dict[str, Any]] = None
    if decision is not None:
        decision_dict = dict(decision)
        for k in ("context_snapshot", "reasoning", "upstream_decisions"):
            decision_dict[k] = _maybe_json(decision_dict.get(k))

    # The review template gates the Approve/Override forms on can_act:
    # an outcome exists, it hasn't been human-reviewed yet, and the mode
    # is one a human acts on. auto_execute / already-reviewed rows fall
    # through to the "Decision is final" banner instead.
    can_act = (
        not readonly
        and decision_dict is not None
        and decision_dict.get("mode") in ("human_approval", "recommend")
        and decision_dict.get("human_action") is None
    )

    # ── Story-driven review copy ─────────────────────────────────────
    # Merge the richest available context: entity summary < live view
    # fields < the decision's frozen context_snapshot (what the AI
    # actually evaluated wins). Drives the "Why" paragraph + signals.
    merged_ctx: dict[str, Any] = {}
    merged_ctx.update(entity_dict)
    merged_ctx.update(flat_ctx)
    snap = decision_dict.get("context_snapshot") if decision_dict else None
    if isinstance(snap, dict):
        merged_ctx.update(snap)

    outcome = decision_dict.get("outcome") if decision_dict else None
    boundary_rule = decision_dict.get("boundary_rule") if decision_dict else None
    signals = build_signals(decision_id, merged_ctx, boundary_rule)

    # Render from the CANONICAL underwriting state, not the raw engine
    # outcome, so Senior UW and the router never disagree (block↔decline).
    if decision_id == "underwriting_decision":
        effective_outcome = canonical_underwriting_state(outcome, merged_ctx)
    else:
        effective_outcome = outcome

    vocab = resolve_vocab(decision_id, effective_outcome)
    labels = {**DECISION_LABELS.get(decision_id, {}), "kind": vocab["kind"], "vocab": vocab}
    if vocab["kind"] == "routing":
        rt = str(merged_ctx.get("routing_target") or "")
        labels["routing"] = {
            "underwriting_state": canonical_underwriting_state(outcome, merged_ctx),
            "routing_action": ROUTING_ACTIONS.get(rt, f"executing the {rt or 'routing'} step"),
        }
    explanation = (
        explain(effective_outcome, boundary_rule, signals, labels)
        if decision_dict is not None
        else None
    )
    ungated_signals = [s for s in signals if s["ungated"]]
    outcome_badge = vocab_badge(decision_id, effective_outcome)
    action_label_text = vocab["action_label"]

    # Downstream-of-hard-block flag: a fraud/compliance hard block should
    # have suspended this persona. Surface it so a reviewer isn't misled.
    halted_by_upstream = next(
        (
            {"persona": u.get("persona_title") or u.get("decision_id"),
             "decision_id": u.get("decision_id")}
            for u in upstream_rows
            if halts_pipeline(u.get("decision_id"), u.get("outcome"), None)
        ),
        None,
    )

    # Documents on file — grouped by category, deduped by type.
    docs_by_cat: dict[str, dict[str, dict[str, Any]]] = {}
    for d in doc_rows:
        cat = (d["document_category"] or "other").replace("_", " ")
        docs_by_cat.setdefault(cat, {})[d["document_type"]] = {
            "type": (d["document_type"] or "").replace("_", " ").title(),
            "status": d["status"],
            "confidence": d["confidence_score"],
        }
    documents = [
        {"category": cat.title(), "docs": list(items.values())}
        for cat, items in sorted(docs_by_cat.items())
    ]
    document_count = sum(len(g["docs"]) for g in documents)

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

    template = "completed_detail.html" if readonly else "review_detail.html"
    return templates.TemplateResponse(
        template,
        {
            "request": request,
            **(await _base_ctx(persona["slug"])),
            "persona": persona,
            "application_id": application_id,
            "decision": decision_dict,
            "can_act": can_act,
            "revert_info": revert_info,
            "explanation": explanation,
            "signals": signals,
            "ungated_signals": ungated_signals,
            "outcome_badge": outcome_badge,
            "action_label_text": action_label_text,
            "halted_by_upstream": halted_by_upstream,
            "documents": documents,
            "document_count": document_count,
            "entity": _entity_summary(entity),
            "key_field_rows": key_field_rows,
            "raw_context_groups": raw_groups,
            "upstreams": upstream_rows,
            "prev_id": prev_id,
            "next_id": next_id,
            "queue_position": queue_position,
            "queue_total": len(nav_ids),
            "total_decisions": await _total_decisions(),
        },
    )


# ─────────────────────────────────────────────────────────────────────
# 4) + 5) POST approve / override
# ─────────────────────────────────────────────────────────────────────


@router.post(
    "/workbench/{persona_slug}/review/{application_id}/approve"
)
async def review_approve(
    persona_slug: str,
    application_id: str,
    reviewer: str = Form(""),
):
    if not DATABASE_URL:
        return RedirectResponse("/workbench", status_code=303)
    persona = _persona_or_none(persona_slug)
    if persona is None:
        return RedirectResponse("/workbench", status_code=303)
    next_app = await _record_review(
        application_id=application_id,
        decision_id=persona["decision_id"],
        new_outcome=None,
        reviewer=reviewer or "anonymous",
        override_reason=None,
        trigger="human_approve",
        action="approved",
    )
    if next_app:
        return RedirectResponse(
            f"/workbench/{persona_slug}/review/{next_app}", status_code=303
        )
    return RedirectResponse(
        f"/workbench/{persona_slug}?tab=queue", status_code=303
    )


@router.post(
    "/workbench/{persona_slug}/review/{application_id}/override"
)
async def review_override(
    persona_slug: str,
    application_id: str,
    new_outcome: str = Form(...),
    reviewer: str = Form(""),
    reason: str = Form(""),
):
    if not DATABASE_URL:
        return RedirectResponse("/workbench", status_code=303)
    persona = _persona_or_none(persona_slug)
    if persona is None:
        return RedirectResponse("/workbench", status_code=303)
    next_app = await _record_review(
        application_id=application_id,
        decision_id=persona["decision_id"],
        new_outcome=new_outcome,
        reviewer=reviewer or "anonymous",
        override_reason=reason or None,
        trigger="human_override",
        action="overridden",
    )
    if next_app:
        return RedirectResponse(
            f"/workbench/{persona_slug}/review/{next_app}", status_code=303
        )
    return RedirectResponse(
        f"/workbench/{persona_slug}?tab=queue", status_code=303
    )


@router.post(
    "/workbench/{persona_slug}/review/{application_id}/revert"
)
async def review_revert(
    persona_slug: str,
    application_id: str,
    reviewer: str = Form(""),
    reason: str = Form(""),
    notes: str = Form(""),
):
    """Re-open a previously approved/overridden decision: a supervisor
    action. Pushes a fresh un-acted version back into the pending queue
    and marks downstream decisions stale."""
    if not DATABASE_URL:
        return RedirectResponse("/workbench", status_code=303)
    persona = _persona_or_none(persona_slug)
    if persona is None:
        return RedirectResponse("/workbench", status_code=303)
    await _record_revert(
        application_id=application_id,
        decision_id=persona["decision_id"],
        reviewer=reviewer or "anonymous",
        reason=reason or None,
        notes=notes or None,
    )
    return RedirectResponse(
        f"/workbench/{persona_slug}?tab=pending", status_code=303
    )


@router.post(
    "/workbench/{persona_slug}/review/{application_id}/request-info"
)
async def review_request_info(
    persona_slug: str,
    application_id: str,
    reviewer: str = Form(""),
    note: str = Form(""),
):
    """Log a 'need more information' request. Leaves the decision in the
    pending queue (human_action stays NULL) — the reviewer is waiting on
    something — and appends a timeline entry recording what was asked."""
    if not DATABASE_URL:
        return RedirectResponse("/workbench", status_code=303)
    persona = _persona_or_none(persona_slug)
    if persona is None:
        return RedirectResponse("/workbench", status_code=303)
    pool = await _get_pool()
    now = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        current = await conn.fetchrow(
            """
            SELECT outcome, wave, tenant_id FROM decision_outputs
            WHERE application_id = $1 AND decision_id = $2
              AND version = (
                  SELECT MAX(version) FROM decision_outputs d2
                  WHERE d2.application_id = decision_outputs.application_id
                    AND d2.decision_id = decision_outputs.decision_id
              )
            LIMIT 1
            """,
            application_id,
            persona["decision_id"],
        )
        if current is not None:
            meta = json.dumps(
                {"requested_by": reviewer or "anonymous", "note": note or None}
            )
            await conn.execute(
                """
                INSERT INTO decision_timeline (
                    application_id, decision_id, wave, from_state,
                    to_state, trigger, transition_at, waiting_on, tenant_id
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9)
                """,
                application_id,
                persona["decision_id"],
                current["wave"],
                current["outcome"],
                current["outcome"],
                "human_request_info",
                now,
                meta,
                current["tenant_id"],
            )
    return RedirectResponse(
        f"/workbench/{persona_slug}/review/{application_id}", status_code=303
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


async def _record_revert(
    *,
    application_id: str,
    decision_id: str,
    reviewer: str,
    reason: Optional[str],
    notes: Optional[str],
) -> bool:
    """Re-open a finalized decision. Writes a new un-acted version (with
    the AI's original outcome restored), appends a ``human_revert``
    timeline row carrying who/why, and flags every downstream decision
    on the application as stale. Returns False if there's nothing to
    revert."""
    pool = await _get_pool()
    now = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        async with conn.transaction():
            current = await conn.fetchrow(
                """
                SELECT id, outcome, wave, version, tenant_id
                FROM decision_outputs
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
            if current is None or current["version"] is None:
                return False

            # Original AI proposal = the from_state of the FIRST human
            # action on this decision (before any human touched it). Fall
            # back to the current outcome if there's no human history.
            ai_outcome = await conn.fetchval(
                """
                SELECT from_state FROM decision_timeline
                WHERE application_id = $1 AND decision_id = $2
                  AND trigger IN ('human_approve', 'human_override')
                ORDER BY transition_at ASC
                LIMIT 1
                """,
                application_id,
                decision_id,
            ) or current["outcome"]

            new_version = int(current["version"]) + 1
            # Copy the current row forward, restoring the AI outcome and
            # clearing the human-action fields so it lands back in the
            # pending queue as a fresh version.
            await conn.execute(
                """
                INSERT INTO decision_outputs (
                    application_id, decision_id, wave, outcome, mode,
                    risk_level, boundary_matched, boundary_rule,
                    context_snapshot, reasoning, confidence,
                    upstream_decisions, human_action, human_override_reason,
                    human_reviewer, decided_at, acted_at, sla_seconds,
                    actual_seconds, version, tenant_id, stale
                )
                SELECT application_id, decision_id, wave, $1::varchar, mode,
                       risk_level, boundary_matched, boundary_rule,
                       context_snapshot, reasoning, confidence,
                       upstream_decisions, NULL::varchar, NULL::text,
                       NULL::varchar, decided_at, NULL::timestamptz, sla_seconds,
                       actual_seconds, $2::integer, tenant_id, false
                FROM decision_outputs WHERE id = $3
                """,
                ai_outcome,
                new_version,
                current["id"],
            )

            # Timeline row — state is unchanged (just reopened); the
            # who/why/notes ride along in waiting_on.
            meta = json.dumps(
                {"reverted_by": reviewer, "reason": reason, "notes": notes}
            )
            await conn.execute(
                """
                INSERT INTO decision_timeline (
                    application_id, decision_id, wave, from_state,
                    to_state, trigger, transition_at, waiting_on, tenant_id
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9)
                """,
                application_id,
                decision_id,
                current["wave"],
                current["outcome"],
                current["outcome"],
                "human_revert",
                now,
                meta,
                current["tenant_id"],
            )

            # Mark downstream decisions (those that ran on this input)
            # stale so reviewers know to re-run the pipeline.
            downstream = _downstream_decisions(decision_id)
            if downstream:
                await conn.execute(
                    """
                    UPDATE decision_outputs SET stale = true
                    WHERE application_id = $1
                      AND decision_id = ANY($2)
                      AND version = (
                          SELECT MAX(version) FROM decision_outputs d2
                          WHERE d2.application_id = decision_outputs.application_id
                            AND d2.decision_id = decision_outputs.decision_id
                      )
                    """,
                    application_id,
                    downstream,
                )
    return True


# ─────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────


async def _persona_404(request: Request, slug: str) -> HTMLResponse:
    return templates.TemplateResponse(
        "persona_404.html",
        {
            "request": request,
            **(await _base_ctx(None)),
            "bad_slug": slug,
        },
        status_code=404,
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
    summary = {k: d.get(k) for k in keep}
    # A back/front DTI of exactly 0 means "not computed" in entity_states,
    # not a borrower with zero debt — surface it as missing ("—") rather
    # than a misleading 0.0%.
    for f in ("dti_back", "dti_front"):
        if summary.get(f) == 0:
            summary[f] = None
    return summary


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


__all__ = ["router", "DATABASE_URL", "PERSONA_CONFIG", "STAGES"]
