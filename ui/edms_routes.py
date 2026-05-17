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
        "description": "Routes approved loans — notification, delivery, investor assignment",
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


@router.get("/workbench/{persona_slug}", response_class=HTMLResponse)
async def persona_workbench(
    request: Request,
    persona_slug: str,
    tab: str = Query("queue"),
):
    if not DATABASE_URL:
        return _not_configured(request)
    persona = _persona_or_none(persona_slug)
    if persona is None:
        return await _persona_404(request, persona_slug)

    decision_id = persona["decision_id"]
    mode = persona["mode"]
    pool = await _get_pool()

    # ── KPI strip (always rendered) ──
    metrics_all = await _persona_metrics()
    kpi = metrics_all.get(persona_slug, {})

    tab = tab if tab in ("queue", "completed", "auto", "analytics") else "queue"
    payload: dict[str, Any] = {}

    summary_fields = persona["summary_fields"]

    if tab == "queue":
        if mode == "auto_execute":
            # Apps not yet decided.
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    f"""
                    SELECT es.application_id,
                           es.mid_credit_score, es.ltv, es.dti_back,
                           es.loan_amount, es.status
                    FROM entity_states es
                    WHERE es.application_id NOT IN (
                        SELECT application_id FROM decision_outputs
                        WHERE decision_id = $1
                    )
                    ORDER BY es.application_id
                    LIMIT 200
                    """,
                    decision_id,
                )
            queue_rows = [
                {
                    "application_id": r["application_id"],
                    "mid_credit_score": r["mid_credit_score"],
                    "ltv": r["ltv"],
                    "dti_back": r["dti_back"],
                    "loan_amount": r["loan_amount"],
                    "status": r["status"],
                    "outcome": None,
                    "confidence": None,
                    "decided_at": None,
                }
                for r in rows
            ]
        else:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT dout.application_id, dout.outcome,
                           dout.confidence, dout.decided_at,
                           dout.boundary_rule,
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
                      )
                    ORDER BY dout.decided_at ASC
                    LIMIT 200
                    """,
                    decision_id,
                )
            queue_rows = [dict(r) for r in rows]
        payload = {"queue_rows": queue_rows}

    elif tab in ("completed", "auto"):
        only_auto = tab == "auto"
        async with pool.acquire() as conn:
            if only_auto:
                rows = await conn.fetch(
                    """
                    SELECT dout.application_id, dout.outcome, dout.mode,
                           dout.confidence, dout.decided_at, dout.acted_at,
                           dout.human_action, dout.human_reviewer,
                           dout.boundary_rule, dout.reasoning,
                           es.mid_credit_score, es.ltv, es.dti_back
                    FROM decision_outputs dout
                    LEFT JOIN entity_states es
                           ON es.application_id = dout.application_id
                          AND es.tenant_id = dout.tenant_id
                    WHERE dout.decision_id = $1
                      AND dout.mode = 'auto_execute'
                      AND dout.version = (
                          SELECT MAX(version) FROM decision_outputs d2
                          WHERE d2.application_id = dout.application_id
                            AND d2.decision_id = dout.decision_id
                      )
                    ORDER BY dout.decided_at DESC
                    LIMIT 200
                    """,
                    decision_id,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT dout.application_id, dout.outcome, dout.mode,
                           dout.confidence, dout.decided_at, dout.acted_at,
                           dout.human_action, dout.human_reviewer,
                           dout.human_override_reason,
                           dout.boundary_rule, dout.reasoning,
                           es.mid_credit_score, es.ltv, es.dti_back
                    FROM decision_outputs dout
                    LEFT JOIN entity_states es
                           ON es.application_id = dout.application_id
                          AND es.tenant_id = dout.tenant_id
                    WHERE dout.decision_id = $1
                      AND (
                          dout.mode = 'auto_execute'
                          OR dout.human_action IS NOT NULL
                      )
                      AND dout.version = (
                          SELECT MAX(version) FROM decision_outputs d2
                          WHERE d2.application_id = dout.application_id
                            AND d2.decision_id = dout.decision_id
                      )
                    ORDER BY dout.decided_at DESC
                    LIMIT 200
                    """,
                    decision_id,
                )
        completed_rows = []
        for r in rows:
            d = dict(r)
            d["reasoning"] = _maybe_json(d.get("reasoning"))
            completed_rows.append(d)
        payload = {"completed_rows": completed_rows}

    elif tab == "analytics":
        async with pool.acquire() as conn:
            outcome_dist = await conn.fetch(
                """
                SELECT outcome, COUNT(*) AS n FROM decision_outputs
                WHERE decision_id = $1
                  AND version = (
                      SELECT MAX(version) FROM decision_outputs d2
                      WHERE d2.application_id = decision_outputs.application_id
                        AND d2.decision_id = decision_outputs.decision_id
                  )
                GROUP BY outcome
                """,
                decision_id,
            )
            agg = await conn.fetchrow(
                """
                SELECT COUNT(*) AS total,
                       AVG(confidence) AS avg_conf,
                       AVG(actual_seconds) AS avg_sec,
                       COUNT(*) FILTER (
                           WHERE mode = 'auto_execute'
                       ) AS auto,
                       COUNT(*) FILTER (
                           WHERE human_action = 'overridden'
                       ) AS overrides,
                       COUNT(*) FILTER (
                           WHERE human_action IS NOT NULL
                       ) AS reviewed
                FROM decision_outputs
                WHERE decision_id = $1
                  AND version = (
                      SELECT MAX(version) FROM decision_outputs d2
                      WHERE d2.application_id = decision_outputs.application_id
                        AND d2.decision_id = decision_outputs.decision_id
                  )
                """,
                decision_id,
            )
            top_rules = await conn.fetch(
                """
                SELECT COALESCE(boundary_rule, '(no rule)') AS rule,
                       COUNT(*) AS n
                FROM decision_outputs
                WHERE decision_id = $1
                  AND version = (
                      SELECT MAX(version) FROM decision_outputs d2
                      WHERE d2.application_id = decision_outputs.application_id
                        AND d2.decision_id = decision_outputs.decision_id
                  )
                GROUP BY rule
                ORDER BY n DESC
                LIMIT 5
                """,
                decision_id,
            )
            avg_review = await conn.fetchval(
                """
                SELECT AVG(EXTRACT(EPOCH FROM (acted_at - decided_at)))
                FROM decision_outputs
                WHERE decision_id = $1
                  AND human_action IS NOT NULL
                  AND acted_at IS NOT NULL
                """,
                decision_id,
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

    return templates.TemplateResponse(
        "persona_workbench.html",
        {
            "request": request,
            **(await _base_ctx(persona_slug)),
            "persona": persona,
            "tab": tab,
            "kpi": kpi,
            "summary_fields": summary_fields,
            "total_decisions": await _total_decisions(),
            **payload,
        },
    )


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
    return {k: d.get(k) for k in keep}


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
