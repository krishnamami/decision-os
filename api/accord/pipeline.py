"""Accord — pipeline product API (the React frontend's backend).

Read-side endpoints over the EDMS PostgreSQL tables the workbench already
writes (``entity_states``, ``decision_outputs``, ``applications``,
``applicants``, ``document_index``, ``document_relationships``,
``conditions``, ``activity_log``) plus the human-review write actions
(approve / override / revert). Reuses the verified explanation generator
in ``ui.explanations`` so the API and the workbench tell the same story.

DB access mirrors the rest of the repo: a lazy asyncpg pool over
DATABASE_URL from .env.
"""

from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from api.accord.auth import get_current_user, get_tenant_id, require_permission
from core.auth.security import hash_password

try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from ui.explanations import (  # pure logic module — no web/DB deps
    DECISION_LABELS,
    build_signals,
    canonical_underwriting_state,
    explain,
    resolve_vocab,
)

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
# Product-API connection. Defaults to DATABASE_URL (edms_admin, RLS bypassed) so
# this stays INERT until Step 5 sets ACCORD_DATABASE_URL to the non-bypass
# accord_app role. Isolates the RLS flip to /api/accord/* — legacy /workbench +
# core stores keep DATABASE_URL unchanged. Rollback = unset one ECS env var.
ACCORD_DATABASE_URL = os.environ.get("ACCORD_DATABASE_URL", "").strip() or DATABASE_URL
router = APIRouter(prefix="/api/accord", tags=["accord"])


@router.get("/health")
async def health() -> dict:
    """Public liveness probe for the ALB target group — intentionally has no
    auth dependency so the load balancer's unauthenticated health check passes.
    """
    return {"status": "ok"}


# ─────────────────────────────────────────────────────────────────────
# The 12 persona decisions (name + pipeline wave). lead_scoring is a
# pre-application lead qualifier and not part of the loan pipeline.
# ─────────────────────────────────────────────────────────────────────


PERSONAS: dict[str, dict[str, Any]] = {
    "credit_assessment":         {"name": "Credit Underwriter",    "wave": 1},
    "fraud_screening":           {"name": "Fraud Analyst",         "wave": 1},
    "compliance_check":          {"name": "Compliance Officer",    "wave": 1},
    "employment_reconciliation": {"name": "Employment Specialist", "wave": 1},
    "income_verification":       {"name": "Income Underwriter",    "wave": 2},
    "dti_calculation":           {"name": "DTI Analyst",           "wave": 2},
    "ltv_assessment":            {"name": "Collateral Analyst",    "wave": 2},
    "product_eligibility":       {"name": "Product Specialist",    "wave": 3},
    "rate_pricing":              {"name": "Pricing Analyst",       "wave": 3},
    "underwriting_decision":     {"name": "Senior Underwriter",    "wave": 4},
    "approval_routing":          {"name": "Loan Ops Router",       "wave": 5},
    "closing_readiness":         {"name": "Closer",                "wave": 5},
}
PERSONA_ORDER = list(PERSONAS.keys())

# Forward dependency graph (B depends on A) — drives revert staling.
UPSTREAM: dict[str, list[str]] = {
    "credit_assessment": [], "fraud_screening": [], "compliance_check": [],
    "employment_reconciliation": [],
    "income_verification": ["employment_reconciliation"],
    "dti_calculation": ["income_verification"],
    "ltv_assessment": ["credit_assessment"],
    "product_eligibility": ["dti_calculation", "ltv_assessment"],
    "rate_pricing": ["credit_assessment", "dti_calculation", "ltv_assessment"],
    "underwriting_decision": [
        "income_verification", "credit_assessment", "fraud_screening",
        "dti_calculation", "ltv_assessment", "product_eligibility",
    ],
    "approval_routing": ["underwriting_decision"],
    "closing_readiness": ["underwriting_decision", "compliance_check"],
}


def _downstream(decision_id: str) -> list[str]:
    out: set[str] = set()
    frontier = [decision_id]
    while frontier:
        cur = frontier.pop()
        for dec, ups in UPSTREAM.items():
            if cur in ups and dec not in out:
                out.add(dec)
                frontier.append(dec)
    return sorted(out)


# ─────────────────────────────────────────────────────────────────────
# Lazy pool + small helpers
# ─────────────────────────────────────────────────────────────────────


_pool: Optional[Any] = None


async def _get_pool() -> Any:
    global _pool
    if _pool is None:
        import asyncpg  # type: ignore
        from core.db.tenant_pool import TenantPool

        _pool = TenantPool(
            await asyncpg.create_pool(ACCORD_DATABASE_URL, min_size=1, max_size=5))
    return _pool


def _require_db() -> None:
    if not DATABASE_URL:
        raise HTTPException(503, "DATABASE_URL not configured")


@router.post("/pipeline/license-check")
async def license_check(payload: dict, tenant_id: str = Depends(get_tenant_id)) -> dict:
    """State licensing compliance check (P0-I, SAFE Act 12 U.S.C. §5101). Single loan
    {property_state} or bulk {loans:[{application_id, property_state}]}. ADVISORY — a
    standalone gate, NOT blocking middleware and NOT wired into the compliance_check
    persona (deferred). not_applicable when property_state unknown or no licenses set."""
    _require_db()
    from core.compliance.license_checker import LicenseComplianceChecker, fetch_license_data
    pool = await _get_pool()
    async with pool.acquire() as conn:
        licenses = await fetch_license_data(conn, tenant_id)
    checker = LicenseComplianceChecker()
    loans = payload.get("loans") if isinstance(payload, dict) else None
    if loans:
        return checker.check_bulk(loans, licenses, tenant_id)
    return checker.check((payload or {}).get("property_state"), licenses, tenant_id=tenant_id)


@router.get("/products")
async def list_products(tenant_id: str = Depends(get_tenant_id)) -> dict:
    """Read-only catalog of the tenant's loan products with their governing
    authority (Fannie / FHA / VA / …). Includes shared 'default' products."""
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT p.product_id, p.product_name, p.active_indicator, p.rate_type,
                   ga.authority_name AS governing_authority
            FROM product p
            JOIN program pgm ON pgm.program_id = p.program_id
            JOIN governing_authority ga ON ga.governing_authority_id = pgm.governing_authority_id
            WHERE p.tenant_id IN ($1, 'default')
            ORDER BY p.active_indicator DESC, p.product_name
            """,
            tenant_id,
        )
    return {
        "products": [
            {
                "product_id": r["product_id"], "product_name": r["product_name"],
                "active_indicator": bool(r["active_indicator"]), "rate_type": r["rate_type"],
                "governing_authority": r["governing_authority"],
            }
            for r in rows
        ],
        "active_count": sum(1 for r in rows if r["active_indicator"]),
    }


# ─────────────────────────────────────────────────────────────────────
# Tiny in-process TTL cache for portfolio-wide AGGREGATES (KPIs, analytics,
# compliance health). These scan the whole decision table and change
# slowly; per-loan reads are never cached, so an edit shows immediately.
# Writes (approve / override / revert) clear the cache so aggregates stay
# correct. Single event loop → a plain dict is safe (no locks).
# ─────────────────────────────────────────────────────────────────────

AGG_TTL_SECONDS = 60.0
_AGG_CACHE: dict[str, tuple[float, Any]] = {}


async def cached_agg(key: str, producer: Callable[[], Awaitable[Any]], ttl: float = AGG_TTL_SECONDS) -> Any:
    now = time.monotonic()
    hit = _AGG_CACHE.get(key)
    if hit is not None and (now - hit[0]) < ttl:
        return hit[1]
    value = await producer()
    _AGG_CACHE[key] = (now, value)
    return value


def invalidate_agg_cache() -> None:
    _AGG_CACHE.clear()


def _J(v: Any) -> Any:
    if isinstance(v, (bytes, bytearray)):
        v = v.decode("utf-8", "replace")
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (ValueError, json.JSONDecodeError):
            return {}
    return v or {}


def _f(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pct(v: Any) -> Optional[float]:
    f = _f(v)
    if f is None:
        return None
    return round(f * 100, 1) if -1.5 <= f <= 1.5 else round(f, 1)


def _lock_days(loan_terms: dict) -> Optional[int]:
    expiry = ((loan_terms or {}).get("rate_lock") or {}).get("lock_expiry")
    if not expiry:
        return None
    try:
        exp = datetime.fromisoformat(str(expiry)[:10]).date()
    except ValueError:
        return None
    return (exp - datetime.now(timezone.utc).date()).days


# ─────────────────────────────────────────────────────────────────────
# Per-app decision rollup → status / urgency
# ─────────────────────────────────────────────────────────────────────


def _derive_status(flags: dict) -> str:
    if flags.get("fraud_block"):
        return "halted"
    if flags.get("any_block"):
        return "blocked"
    if flags.get("pending_human"):
        return "in_review"
    if (flags.get("n_decisions") or 0) >= len(PERSONAS) and not flags.get("any_block"):
        return "clear_to_close"
    return "in_progress"


def _derive_urgency(flags: dict, lock_days: Optional[int]) -> str:
    if flags.get("fraud_block"):
        return "CRITICAL"
    sla = flags.get("sla_ratio") or 0
    if (lock_days is not None and lock_days < 7) or sla > 0.8:
        return "URGENT"
    if flags.get("pending_adverse"):
        return "REVIEW"
    return "ON TRACK"


async def _flags_producer(tenant_id: str) -> dict[str, dict]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        return await _decision_flags(conn, tenant_id)


async def _decision_flags(conn, tenant_id: str) -> dict[str, dict]:
    """One pass over the latest decision per (app, decision) → per-app
    flags used for status, urgency, and KPIs across the whole tenant."""
    rows = await conn.fetch(
        """
        WITH latest AS (
            SELECT DISTINCT ON (application_id, decision_id)
                   application_id, decision_id, outcome, mode, human_action,
                   sla_seconds, actual_seconds
            FROM decision_outputs
            WHERE tenant_id = $1
            ORDER BY application_id, decision_id, version DESC
        )
        SELECT application_id,
               bool_or(decision_id = 'fraud_screening' AND outcome = 'block') AS fraud_block,
               bool_or(outcome = 'block') AS any_block,
               bool_or(human_action IS NULL AND mode IN ('recommend','human_approval')) AS pending_human,
               bool_or(outcome IN ('escalate','recommend') AND human_action IS NULL) AS pending_adverse,
               count(*) AS n_decisions,
               max(COALESCE(actual_seconds, 0) / NULLIF(sla_seconds, 0)) AS sla_ratio
        FROM latest
        GROUP BY application_id
        """,
        tenant_id,
    )
    return {r["application_id"]: dict(r) for r in rows}


# ─────────────────────────────────────────────────────────────────────
# 1) GET /api/accord/pipeline
# ─────────────────────────────────────────────────────────────────────


@router.get("/pipeline")
async def list_pipeline(
    status: Optional[str] = Query(None),
    type: Optional[str] = Query(None),  # noqa: A002 — public query name
    search: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    _require_db()
    pool = await _get_pool()

    # Portfolio flags + KPIs are cached (the whole-table scan); the list
    # query below is per-request (cheap, filter-dependent).
    flags_by_app = await cached_agg(f"flags:{tenant_id}", lambda: _flags_producer(tenant_id))
    kpis = {"total": 0, "in_review": 0, "blocked": 0, "clear_to_close": 0, "halted": 0}
    for flags in flags_by_app.values():
        kpis["total"] += 1
        st = _derive_status(flags)
        if st in kpis:
            kpis[st] += 1

    async with pool.acquire() as conn:
        where = ["es.tenant_id = $1"]
        params: list[Any] = [tenant_id]
        if type:
            params.append(type)
            where.append(f"a.loan_type = ${len(params)}")
        if search:
            params.append(f"%{search.lower()}%")
            where.append(
                f"(LOWER(COALESCE(ap.full_name, es.application_id)) LIKE ${len(params)}"
                f" OR LOWER(es.application_id) LIKE ${len(params)})"
            )
        rows = await conn.fetch(
            f"""
            SELECT es.application_id,
                   COALESCE(ap.full_name, es.application_id) AS borrower_name,
                   a.loan_type, a.loan_purpose,
                   es.loan_amount, es.mid_credit_score, es.interest_rate,
                   es.ltv, es.dti_back,
                   (es.loan_terms->'rate_lock'->>'lock_expiry') AS lock_expiry
            FROM entity_states es
            LEFT JOIN applications a ON a.application_id = es.application_id
            LEFT JOIN applicants ap ON ap.applicant_id = a.applicant_id
            WHERE {' AND '.join(where)}
            ORDER BY es.last_updated DESC NULLS LAST
            """,
            *params,
        )

        # Build records, attach status/urgency, apply the status filter,
        # then paginate.
        records = []
        for r in rows:
            flags = flags_by_app.get(r["application_id"], {})
            st = _derive_status(flags)
            if status and st != status:
                continue
            lock_days = None
            if r["lock_expiry"]:
                try:
                    lock_days = (datetime.fromisoformat(r["lock_expiry"][:10]).date()
                                 - datetime.now(timezone.utc).date()).days
                except ValueError:
                    lock_days = None
            records.append({
                "application_id": r["application_id"],
                "borrower_name": r["borrower_name"],
                "loan_type": r["loan_type"],
                "loan_purpose": r["loan_purpose"],
                "loan_amount": _f(r["loan_amount"]),
                "credit_score": int(r["mid_credit_score"]) if r["mid_credit_score"] else None,
                "ltv": _pct(r["ltv"]),
                "dti": _pct(r["dti_back"]),
                "interest_rate": _pct(r["interest_rate"]),
                "status": st,
                "urgency": _derive_urgency(flags, lock_days),
                "_flags": flags,
            })

        total = len(records)
        page = records[offset:offset + limit]
        page_ids = [rec["application_id"] for rec in page]

        # Decisions detail for the page only.
        decisions_by_app = await _page_decisions(conn, tenant_id, page_ids)

    applications = []
    for rec in page:
        decs = decisions_by_app.get(rec["application_id"], {})
        rec.pop("_flags", None)
        rec["decisions"] = decs
        rec["blocking_persona"] = _blocking_persona(decs)
        applications.append(rec)

    return {"total": total, "kpis": kpis, "applications": applications}


async def _page_decisions(conn, tenant_id: str, app_ids: list[str]) -> dict[str, dict]:
    if not app_ids:
        return {}
    rows = await conn.fetch(
        """
        SELECT DISTINCT ON (application_id, decision_id)
               application_id, decision_id, outcome, confidence,
               human_action, human_reviewer
        FROM decision_outputs
        WHERE tenant_id = $1 AND application_id = ANY($2)
        ORDER BY application_id, decision_id, version DESC
        """,
        tenant_id, app_ids,
    )
    out: dict[str, dict] = {}
    for r in rows:
        out.setdefault(r["application_id"], {})[r["decision_id"]] = {
            "outcome": r["outcome"],
            "confidence": _f(r["confidence"]),
            "reviewed": r["human_action"] is not None,
            "reviewer": r["human_reviewer"],
        }
    return out


def _blocking_persona(decisions: dict) -> Optional[str]:
    """Lowest-wave decision currently at 'block'."""
    blockers = [d for d, v in decisions.items() if v.get("outcome") == "block"]
    if not blockers:
        return None
    return min(blockers, key=lambda d: PERSONAS.get(d, {}).get("wave", 99))


# ─────────────────────────────────────────────────────────────────────
# 1b) GET /api/accord/pipeline/my-queue  +  /pipeline/team
#
# Role-based landing surfaces. The plain-English AI lines are templated
# per blocking persona + outcome (the bespoke per-loan NLG in the spec is
# approximated from real entity data — income deltas, fraud score, DTI…).
# ─────────────────────────────────────────────────────────────────────

# Which documents/agents each persona consulted — drives "What AI saw".
PERSONA_SOURCES = {
    "income_verification": "W2, IRS transcript, URLA",
    "employment_reconciliation": "W2, paystubs, The Work Number",
    "credit_assessment": "credit report, tradelines, FICO",
    "fraud_screening": "ID verification, watchlist, device signals",
    "compliance_check": "TRID timeline, disclosures, fair-lending checks",
    "dti_calculation": "income, monthly obligations, credit report",
    "ltv_assessment": "appraisal, purchase contract",
    "product_eligibility": "loan-program guidelines, borrower profile",
    "rate_pricing": "rate sheet, lock terms",
    "underwriting_decision": "full file — credit, income, collateral",
    "approval_routing": "final decision, adverse-action rules",
    "closing_readiness": "conditions, title, insurance",
}


def _k(v: Any) -> str:
    try:
        return f"${round(float(v) / 1000)}K"
    except (TypeError, ValueError):
        return "?"


def _queue_ai(blocking_did: Optional[str], decs: dict, borrower: Any, es: dict) -> dict:
    """Three plain-English lines (finding / sources / recommendation) for a
    queue card, derived from the blocking (or pending) decision + entity data."""
    did, outcome = blocking_did, "block"
    if not did:
        pending = [d for d, v in decs.items()
                   if v.get("outcome") in ("escalate", "recommend") and not v.get("reviewed")]
        if not pending:
            return {
                "ai_finding": "All checks passed — no blocks or open flags",
                "ai_data_sources": "All 12 agent reviews complete",
                "ai_recommendation": "Approve — ready to advance to the next stage",
            }
        did = min(pending, key=lambda d: PERSONAS.get(d, {}).get("wave", 99))
        outcome = decs[did].get("outcome", "recommend")

    binfo = borrower if isinstance(borrower, dict) else {}
    inc = binfo.get("income", {}) if isinstance(binfo.get("income"), dict) else {}
    ident = binfo.get("identity", {}) if isinstance(binfo.get("identity"), dict) else {}
    stated, verified = inc.get("stated_income_annual"), inc.get("verified_income_annual")
    dti, score, ltv = es.get("dti_back"), es.get("mid_credit_score"), es.get("ltv")
    name = PERSONAS.get(did, {}).get("name", did.replace("_", " ").title())
    sources = PERSONA_SOURCES.get(did, "application file")
    blocked = outcome == "block"
    verb = "blocked" if blocked else "flagged for review"

    if did in ("income_verification", "employment_reconciliation"):
        if stated and verified and abs(stated - verified) / max(stated, 1) > 0.05:
            finding = f"Income {verb} — verified {_k(verified)} vs stated {_k(stated)}"
            sources = "W2, IRS transcript, URLA — sources disagree on income"
        else:
            finding = f"Income {verb} — employment/income not fully verified"
        rec = ("Request corrected income docs or restructure the loan amount" if blocked
               else "Confirm income with a written VOE before approving")
    elif did == "fraud_screening":
        reason = ("watchlist match" if ident.get("watchlist_match")
                  else f"fraud score {float(ident['fraud_score']):.2f}" if ident.get("fraud_score") is not None
                  else "elevated identity risk")
        finding = f"Fraud {verb} — {reason}"
        rec = ("Escalate to fraud review; file a SAR if confirmed" if blocked
               else "Run a manual identity check before clearing")
    elif did == "credit_assessment":
        finding = f"Credit {verb}" + (f" — mid score {int(score)}" if score else "")
        rec = ("Request a letter of explanation or decline per credit policy" if blocked
               else "Review the credit profile and document the rationale")
    elif did == "dti_calculation":
        finding = f"DTI {verb}" + (f" — back-end DTI {float(dti):.0f}%" if dti else "")
        rec = "Reduce the loan amount or add a co-borrower to bring DTI in range"
    elif did == "compliance_check":
        finding = f"Compliance {verb} — disclosure / TRID timing issue"
        rec = "Re-issue disclosures and confirm TRID timing before proceeding"
    elif did == "ltv_assessment":
        finding = f"Collateral {verb}" + (f" — LTV {float(ltv):.0f}%" if ltv else "")
        rec = "Order a review appraisal or increase the down payment"
    else:
        finding = f"{name} {verb} this file"
        rec = "Review the flagged decision and clear it or request more info"
    return {"ai_finding": finding, "ai_data_sources": sources, "ai_recommendation": rec}


SLA_BY_STAGE = {"verify": 3, "underwrite": 5, "eligibility": 4, "decide": 3, "close": 2}


def _block_category(decs: dict) -> str:
    """Queue-card category from the root blocking decision (lowest wave; a hard
    block beats an escalate at the same wave)."""
    blockers = sorted(
        (PERSONAS.get(d, {}).get("wave", 9), 0 if v.get("outcome") == "block" else 1, d)
        for d, v in decs.items() if v.get("outcome") in ("block", "escalate")
    )
    if not blockers:
        return "clean"
    did = blockers[0][2]
    if did == "fraud_screening":
        return "fraud"
    if did in ("income_verification", "employment_reconciliation"):
        return "income"
    if did == "compliance_check":
        return "compliance"
    return "other"


def _days_since(ts: Any) -> Optional[int]:
    if ts is None:
        return None
    if getattr(ts, "tzinfo", None) is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - ts).days)


def _time_ago(ts: Any) -> str:
    """Server-side relative time (e.g. '2 hours ago'), relative to now()."""
    if ts is None:
        return ""
    if getattr(ts, "tzinfo", None) is None:
        ts = ts.replace(tzinfo=timezone.utc)
    secs = max(0, (datetime.now(timezone.utc) - ts).total_seconds())
    if secs < 60:
        return "just now"
    for unit, size in (("minute", 60), ("hour", 3600), ("day", 86400),
                       ("month", 2592000), ("year", 31536000)):
        nxt = {"minute": 3600, "hour": 86400, "day": 2592000,
               "month": 31536000, "year": float("inf")}[unit]
        if secs < nxt:
            n = int(secs // size)
            return f"{n} {unit}{'s' if n != 1 else ''} ago"
    return "just now"


def _jsonb(v: Any) -> Any:
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return {}
    return v or {}


@router.get("/pipeline/my-queue")
async def my_queue(
    user_id: Optional[str] = Query(None),  # managers/admins may view a teammate
    user: dict = Depends(get_current_user),
) -> dict:
    _require_db()
    tenant_id = user["tenant_id"]
    if user_id and user.get("role") not in ("admin", "manager"):
        raise HTTPException(403, "Only managers can view another user's queue")
    target_uid = user_id or user["user_id"]
    pool = await _get_pool()
    async with pool.acquire() as conn:
        urow = await conn.fetchrow(
            "SELECT name, role FROM users WHERE user_id = $1 AND tenant_id = $2",
            UUID(str(target_uid)), tenant_id,
        )
        if urow is None:
            raise HTTPException(404, "User not found")
        rows = await conn.fetch(
            """
            SELECT la.application_id, la.stage, la.status AS assign_status, la.assigned_at,
                   la.assignment_type,
                   COALESCE(ap.full_name, es.application_id) AS borrower_name,
                   a.loan_type, es.loan_amount, es.loan_status,
                   es.dti_back, es.mid_credit_score, es.ltv, es.borrower,
                   (es.loan_terms->'rate_lock'->>'lock_expiry') AS lock_expiry
            FROM loan_assignments la
            JOIN entity_states es ON es.application_id = la.application_id
            LEFT JOIN applications a ON a.application_id = la.application_id
            LEFT JOIN applicants ap ON ap.applicant_id = a.applicant_id
            WHERE la.assigned_to = $1 AND la.tenant_id = $2
            ORDER BY la.assigned_at DESC
            """,
            UUID(str(target_uid)), tenant_id,
        )
        app_ids = [r["application_id"] for r in rows]
        flags = await _decision_flags(conn, tenant_id)
        decisions = await _page_decisions(conn, tenant_id, app_ids)
        attn_rows = await conn.fetch(
            """
            SELECT ar.request_id, ar.application_id, ar.message, ar.priority, ar.category, ar.source, u.name AS from_name
            FROM attention_requests ar LEFT JOIN users u ON u.user_id = ar.from_user_id
            WHERE ar.to_user_id = $1 AND ar.status = 'open'
            """,
            UUID(str(target_uid)),
        )
        attn = {r["application_id"]: dict(r) for r in attn_rows}
        comm_rows = await conn.fetch(
            """
            SELECT DISTINCT ON (c.application_id) c.application_id, c.items_requested, c.due_date,
                   c.created_at, c.recipient_email, c.responded_at, u.name AS requested_by_name
            FROM communications c LEFT JOIN users u ON u.user_id = c.from_user_id
            WHERE c.tenant_id = $1 AND c.application_id = ANY($2) AND c.direction = 'outbound'
            ORDER BY c.application_id, c.created_at DESC
            """,
            tenant_id, app_ids,
        )
        comms = {r["application_id"]: dict(r) for r in comm_rows}
        responded_apps = {app for app, c in comms.items() if c.get("responded_at")}
        # Loans with a senior-review request (for the ⚑ queue flag).
        sr_rows = await conn.fetch(
            "SELECT DISTINCT application_id FROM loan_actions "
            "WHERE tenant_id = $1 AND action_type = 'senior_review' AND application_id = ANY($2)",
            tenant_id, app_ids,
        )
        sr_apps = {r["application_id"] for r in sr_rows}

        # Internal-review requests TO this user on loans they aren't assigned —
        # surface them so the target still sees the 🔵 in their queue.
        assigned_set = set(app_ids)
        extra_ids = [app for app in attn if app not in assigned_set]
        extra_rows = []
        if extra_ids:
            extra_rows = await conn.fetch(
                "SELECT es.application_id, COALESCE(ap.full_name, es.application_id) AS borrower_name, "
                "a.loan_type, es.loan_amount FROM entity_states es "
                "LEFT JOIN applications a ON a.application_id = es.application_id "
                "LEFT JOIN applicants ap ON ap.applicant_id = a.applicant_id "
                "WHERE es.application_id = ANY($1) AND es.tenant_id = $2",
                extra_ids, tenant_id,
            )
        # Loans THIS user escalated that are now awaiting the senior UW's decision.
        # They were reassigned to the senior (assigned_to != me), so they're absent
        # from the assigned-loans query above — surface them in Pending Response.
        esc_rows = await conn.fetch(
            """
            SELECT la.application_id, la.assigned_at,
                   COALESCE(ap.full_name, es.application_id) AS borrower_name,
                   a.loan_type, es.loan_amount, ut.name AS senior_name
            FROM loan_assignments la
            JOIN entity_states es ON es.application_id = la.application_id
            LEFT JOIN applications a ON a.application_id = la.application_id
            LEFT JOIN applicants ap ON ap.applicant_id = a.applicant_id
            LEFT JOIN users ut ON ut.user_id = la.assigned_to
            WHERE la.assigned_by = $1 AND la.tenant_id = $2
              AND la.status = 'active' AND la.stage = 'decide' AND la.assigned_to <> $1
            ORDER BY la.assigned_at DESC
            """,
            UUID(str(target_uid)), tenant_id,
        )
        # Replies to MY internal requests, resolved in the last 24h — surfaced in
        # the queue's "Recently resolved" section so the requester sees the answer.
        reply_rows = await conn.fetch(
            """
            SELECT ar.request_id, ar.application_id, ar.message, ar.response,
                   ar.completed_at, ut.name AS from_name,
                   COALESCE(ap.full_name, es.application_id) AS borrower_name,
                   a.loan_type, es.loan_amount
            FROM attention_requests ar
            JOIN entity_states es ON es.application_id = ar.application_id
            LEFT JOIN applications a ON a.application_id = ar.application_id
            LEFT JOIN applicants ap ON ap.applicant_id = a.applicant_id
            LEFT JOIN users ut ON ut.user_id = ar.to_user_id
            WHERE ar.from_user_id = $1 AND ar.tenant_id = $2
              AND ar.status = 'resolved' AND ar.response IS NOT NULL
              AND ar.completed_at >= NOW() - INTERVAL '24 hours'
            ORDER BY ar.completed_at DESC
            """,
            UUID(str(target_uid)), tenant_id,
        )

    active, pending, decided = [], [], []
    for r in rows:
        app = r["application_id"]
        decs = decisions.get(app, {})
        blocking = _blocking_persona(decs)
        es = {"dti_back": r["dti_back"], "mid_credit_score": r["mid_credit_score"], "ltv": r["ltv"]}
        lock_days = None
        if r["lock_expiry"]:
            try:
                lock_days = (datetime.fromisoformat(r["lock_expiry"][:10]).date()
                             - datetime.now(timezone.utc).date()).days
            except ValueError:
                lock_days = None
        st = r["assign_status"]
        ai = _queue_ai(blocking, decs, _jsonb(r["borrower"]), es)
        a = attn.get(app)
        if a:
            queue_type = "internal_request"
        elif r["assignment_type"] == "direct_assignment" and st == "active":
            queue_type = "direct_assignment"
        elif app in responded_apps and st == "active":
            queue_type = "returned"
        else:
            queue_type = "action_needed"
        urg = _derive_urgency(flags.get(app, {}), lock_days)
        card = {
            "application_id": app,
            "borrower_name": r["borrower_name"],
            "loan_amount": _f(r["loan_amount"]),
            "loan_type": r["loan_type"],
            "status": st,
            "stage": r["stage"],
            "queue_type": queue_type,
            "category": _block_category(decs),
            "days_in_queue": _days_since(r["assigned_at"]),
            "sla_days": SLA_BY_STAGE.get(r["stage"], 5),
            "rate_lock_days": lock_days,
            "urgency": "urgent" if urg in ("CRITICAL", "URGENT") else "normal",
            "ai_finding": ai["ai_finding"],
            "ai_data_sources": ai["ai_data_sources"],
            "ai_recommendation": ai["ai_recommendation"],
            "attention_request": ({"request_id": str(a["request_id"]), "from": a["from_name"], "message": a["message"], "priority": a["priority"], "category": a.get("category"), "source": a.get("source")} if a else None),
            "senior_review": app in sr_apps,
        }
        if st == "pending_borrower":
            c = comms.get(app)
            if c:
                card["requesting"] = _jsonb(c["items_requested"])
                card["sent"] = c["created_at"].isoformat() if c.get("created_at") else None
                card["due_date"] = c["due_date"].isoformat() if c.get("due_date") else None
                card["recipient_email"] = c.get("recipient_email")
                card["requested_by_name"] = c.get("requested_by_name")
            card["awaiting"] = "borrower"
            pending.append(card)
        elif st in ("decided", "funded"):
            decided.append(card)
        else:
            active.append(card)

    for r in extra_rows:
        app = r["application_id"]
        a = attn[app]
        active.append({
            "application_id": app, "borrower_name": r["borrower_name"], "loan_amount": _f(r["loan_amount"]),
            "loan_type": r["loan_type"], "status": "active", "stage": "", "queue_type": "internal_request",
            "category": "other", "sla_days": 5,
            "days_in_queue": None, "rate_lock_days": None, "urgency": "urgent" if a["priority"] == "urgent" else "normal",
            "ai_finding": "Internal review requested", "ai_data_sources": "", "ai_recommendation": "",
            "attention_request": {"request_id": str(a["request_id"]), "from": a["from_name"], "message": a["message"], "priority": a["priority"], "category": a.get("category"), "source": a.get("source")},
        })

    # Escalated-by-me loans → Pending Response ("Awaiting Senior UW decision").
    for r in esc_rows:
        pending.append({
            "application_id": r["application_id"],
            "borrower_name": r["borrower_name"],
            "loan_amount": _f(r["loan_amount"]),
            "loan_type": r["loan_type"],
            "status": "escalated", "stage": "decide",
            "queue_type": "escalated", "awaiting": "senior",
            "senior_name": r["senior_name"],
            "category": "other", "sla_days": 5,
            "days_in_queue": _days_since(r["assigned_at"]),
            "rate_lock_days": None, "urgency": "normal",
            "ai_finding": "", "ai_data_sources": "", "ai_recommendation": "",
        })

    active.sort(key=lambda c: (0 if c["urgency"] == "urgent" else 1, -(c["days_in_queue"] or 0)))
    recently_resolved = [
        {
            "request_id": str(r["request_id"]), "application_id": r["application_id"],
            "borrower_name": r["borrower_name"], "loan_amount": _f(r["loan_amount"]),
            "loan_type": r["loan_type"], "from": r["from_name"],
            "message": r["message"], "response": r["response"],
            "resolved_at": r["completed_at"].isoformat() if r["completed_at"] else None,
        }
        for r in reply_rows
    ]
    return {
        "user": {"name": urow["name"], "role": urow["role"]},
        "counts": {"active": len(active), "pending": len(pending), "decided": len(decided)},
        "active": active,
        "pending": pending,
        "decided": decided,
        "recently_resolved": recently_resolved,
    }


@router.get("/pipeline/team")
async def team_overview(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in ("admin", "manager"):
        raise HTTPException(403, "Manager access required")
    _require_db()
    tenant_id = user["tenant_id"]
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT u.user_id, u.name, u.role,
                   la.application_id, la.status AS assign_status, la.stage, la.assigned_at,
                   COALESCE(ap.full_name, es.application_id) AS borrower_name,
                   es.loan_amount, es.loan_status
            FROM users u
            LEFT JOIN loan_assignments la ON la.assigned_to = u.user_id AND la.tenant_id = $1
            LEFT JOIN entity_states es ON es.application_id = la.application_id
            LEFT JOIN applications a ON a.application_id = la.application_id
            LEFT JOIN applicants ap ON ap.applicant_id = a.applicant_id
            WHERE u.tenant_id = $1
              AND u.role IN ('processor', 'underwriter', 'senior_uw', 'closer', 'compliance')
            ORDER BY u.name, la.assigned_at DESC
            """,
            tenant_id,
        )
    members: dict = {}
    totals = {"active": 0, "pending": 0, "decided": 0}
    all_days: list[int] = []
    for r in rows:
        m = members.setdefault(str(r["user_id"]), {
            "user_id": str(r["user_id"]), "name": r["name"], "role": r["role"],
            "active": 0, "pending": 0, "decided": 0, "loans": [], "oldest_days": 0, "_days": [],
        })
        if not r["application_id"]:
            continue
        st = r["assign_status"]
        bucket = "active" if st == "active" else ("pending" if st == "pending_borrower" else "decided")
        m[bucket] += 1
        totals[bucket] += 1
        d = _days_since(r["assigned_at"])
        if bucket != "decided" and d is not None:
            m["_days"].append(d)
            all_days.append(d)
        if bucket != "decided" and len(m["loans"]) < 6:
            m["loans"].append({
                "application_id": r["application_id"],
                "borrower_name": r["borrower_name"],
                "loan_amount": _f(r["loan_amount"]),
                "loan_status": r["loan_status"],
                "stage": r["stage"],
                "days_in_queue": d,
            })
    for m in members.values():
        m["oldest_days"] = max(m.pop("_days") or [0])
    totals["avg_days"] = round(sum(all_days) / len(all_days), 1) if all_days else 0
    return {"members": list(members.values()), "totals": totals}


# ─────────────────────────────────────────────────────────────────────
# 1c) Communications, attention requests, notes, notifications
# ─────────────────────────────────────────────────────────────────────


class RequestInfoBody(BaseModel):
    application_id: str
    recipient_email: Optional[str] = None
    items: list[str] = []
    note: Optional[str] = None
    due_date: Optional[str] = None  # ISO date


class AttentionBody(BaseModel):
    application_id: str
    decision_id: Optional[str] = None
    to_user_id: str
    message: str
    priority: str = "normal"


class NoteBody(BaseModel):
    note: str
    note_type: str = "general"


class ReassignBody(BaseModel):
    application_ids: list[str]
    to_user_id: str


@router.post("/pipeline/reassign")
async def reassign(body: ReassignBody, user: dict = Depends(get_current_user)) -> dict:
    """Manager moves loans between teammates."""
    if user.get("role") not in ("admin", "manager"):
        raise HTTPException(403, "Manager access required")
    _require_db()
    tid, to_uid = user["tenant_id"], UUID(str(body.to_user_id))
    pool = await _get_pool()
    n = 0
    async with pool.acquire() as conn:
        to_name = await conn.fetchval("SELECT name FROM users WHERE user_id=$1 AND tenant_id=$2", to_uid, tid)
        if not to_name:
            raise HTTPException(404, "Target user not found")
        for app in body.application_ids:
            await conn.execute(
                "UPDATE loan_assignments SET previous_assignee=assigned_to, assigned_to=$1, assigned_at=NOW() "
                "WHERE application_id=$2 AND tenant_id=$3", to_uid, app, tid,
            )
            await conn.execute("UPDATE entity_states SET assigned_to=$1 WHERE application_id=$2 AND tenant_id=$3", to_uid, app, tid)
            n += 1
        if n:
            await conn.execute(
                "INSERT INTO notifications (tenant_id, user_id, type, title) VALUES ($1,$2,'loan_assigned',$3)",
                tid, to_uid, f"{n} loan{'s' if n != 1 else ''} reassigned to you",
            )
    return {"transferred": n, "to_name": to_name}


class DecideBody(BaseModel):
    application_id: str
    action: str  # approve | deny | escalate | override
    note: Optional[str] = None
    decision_id: Optional[str] = None      # override: which decision to override
    override_reason: Optional[str] = None  # override: exam-trail rationale (>=50)
    override_outcome: Optional[str] = None # override: approve|deny|clear_block|waive_condition
    reasoning: Optional[str] = None        # override/approve/deny rationale
    conditions: Optional[str] = None       # approve: optional conditions
    denial_code: Optional[str] = None      # deny: credit|income|collateral|fraud|other
    denial_reason: Optional[str] = None    # deny: detailed reason
    feedback_message: Optional[str] = None   # request_more_info: senior-UW feedback (>=25)
    feedback_category: Optional[str] = None  # request_more_info: documentation|income|...


@router.post("/pipeline/decide")
async def decide(body: DecideBody, user: dict = Depends(get_current_user)) -> dict:
    """Finalize a loan. approve/deny/override require the override_decision
    permission (read from role_permissions, never hardcoded); escalate hands the
    loan to the tenant's senior UW. TENANT ISOLATION: the loan must belong to the
    caller's tenant (from the JWT) or the call 403s — the body never carries a
    tenant_id. Read-only roles can't decide."""
    if user.get("role") in ("viewer", "compliance"):
        raise HTTPException(403, "Read-only role cannot decide")
    _require_db()
    tid, uid = user["tenant_id"], UUID(str(user["user_id"]))
    app = body.application_id
    perms = user.get("permissions", {}) or {}
    # approve/deny/override are decision authority — gate on the role's
    # override_decision permission (dynamic, from role_permissions).
    if body.action in ("approve", "deny", "override") and not perms.get("override_decision"):
        raise HTTPException(403, "Your role cannot approve, deny, or override decisions")
    pool = await _get_pool()
    async with pool.acquire() as conn:
        # TENANT ISOLATION: the loan must exist under the caller's tenant. A
        # cross-tenant application_id (or unknown loan) is a hard 403 — never a
        # silent no-op. tenant_id always comes from the JWT, never the request.
        owns = await conn.fetchval(
            "SELECT 1 FROM entity_states WHERE application_id=$1 AND tenant_id=$2", app, tid)
        if not owns:
            raise HTTPException(403, "Loan is not in your tenant")

        if body.action == "approve":
            await conn.execute("UPDATE loan_assignments SET status='decided', completed_at=NOW() WHERE application_id=$1 AND tenant_id=$2 AND assigned_to=$3", app, tid, uid)
            await conn.execute("UPDATE entity_states SET loan_status='decided' WHERE application_id=$1 AND tenant_id=$2", app, tid)
            title = "Loan approved — advanced to the next stage"
        elif body.action == "deny":
            await conn.execute("UPDATE loan_assignments SET status='denied', completed_at=NOW() WHERE application_id=$1 AND tenant_id=$2 AND assigned_to=$3", app, tid, uid)
            await conn.execute("UPDATE entity_states SET loan_status='denied' WHERE application_id=$1 AND tenant_id=$2", app, tid)
            title = "Loan denied — adverse-action notice queued"
        elif body.action == "override":
            if not body.decision_id:
                raise HTTPException(422, "decision_id is required to override")
            override_outcome = (body.override_outcome or "").strip()
            if override_outcome not in ("approve", "deny", "clear_block", "waive_condition"):
                raise HTTPException(422, "override_outcome must be approve|deny|clear_block|waive_condition")
            reason = (body.override_reason or body.reasoning or "").strip()
            if len(reason) < 50:
                raise HTTPException(422, "override_reason is required (min 50 characters)")
            reviewer_name = user.get("name") or user.get("email") or str(uid)
            # Current decision — preserve its ORIGINAL outcome for the audit trail.
            cur = await conn.fetchrow(
                "SELECT id, outcome, wave FROM decision_outputs "
                "WHERE application_id=$1 AND tenant_id=$2 AND decision_id=$3 AND superseded_by IS NULL "
                "ORDER BY version DESC LIMIT 1",
                app, tid, body.decision_id)
            if not cur:
                raise HTTPException(404, "Decision not found")
            original_outcome = cur["outcome"]
            # New engine outcome by override type (clear_block/approve/waive all
            # unblock the gate → 'allow'; deny → 'block').
            new_outcome = {"approve": "allow", "clear_block": "allow",
                           "waive_condition": "allow", "deny": "block"}[override_outcome]
            await conn.execute(
                "UPDATE decision_outputs SET human_action='overridden', human_reviewer=$1, "
                "human_override_reason=$2, outcome=$3, acted_at=NOW() WHERE id=$4",
                reviewer_name, reason, new_outcome, cur["id"])
            # Preserve original → new as a queryable transition (drives revert +
            # the audit trail's "Original: BLOCK → New: CLEARED").
            try:
                await conn.execute(
                    "INSERT INTO decision_timeline (application_id, decision_id, wave, "
                    "from_state, to_state, trigger, transition_at, tenant_id) "
                    "VALUES ($1,$2,$3,$4,$5,'human_override',NOW(),$6)",
                    app, body.decision_id, cur["wave"], original_outcome, new_outcome, tid)
            except Exception:  # noqa: BLE001 — timeline is best-effort
                pass
            invalidate_agg_cache()  # a decision outcome changed → portfolio aggregates
            # Waive open blocking conditions when requested.
            waived = 0
            if override_outcome == "waive_condition":
                res = await conn.execute(
                    "UPDATE loan_condition_instances SET status='waived', cleared_at=NOW(), "
                    "notes=CONCAT(COALESCE(notes,''), $3::text), updated_at=NOW() "
                    "WHERE application_id=$1 AND tenant_id=$2 AND status='open' AND blocks_closing=true",
                    app, tid, f"\n[waived by {reviewer_name}]: {reason}")
                waived = int(res.split()[-1]) if res and res.startswith("UPDATE") else 0
            # Final-decision override types mirror the approve/deny loan-state moves.
            if override_outcome == "approve":
                await conn.execute("UPDATE loan_assignments SET status='decided', completed_at=NOW() WHERE application_id=$1 AND tenant_id=$2 AND assigned_to=$3", app, tid, uid)
                await conn.execute("UPDATE entity_states SET loan_status='decided' WHERE application_id=$1 AND tenant_id=$2", app, tid)
            elif override_outcome == "deny":
                await conn.execute("UPDATE loan_assignments SET status='denied', completed_at=NOW() WHERE application_id=$1 AND tenant_id=$2 AND assigned_to=$3", app, tid, uid)
                await conn.execute("UPDATE entity_states SET loan_status='denied' WHERE application_id=$1 AND tenant_id=$2", app, tid)
            # clear_block / waive_condition leave the loan active so a final
            # decision can still be made now that the gate is cleared.
            decision_name = body.decision_id.replace("_", " ").title()
            # Detailed audit entry — the exam-ready override record.
            try:
                await conn.execute(
                    "INSERT INTO activity_log (tenant_id, application_id, actor, action, target, detail) "
                    "VALUES ($1,$2,$3,'override',$4,$5::jsonb)",
                    tid, app, reviewer_name, decision_name,
                    json.dumps({"decision_id": body.decision_id, "decision_name": decision_name,
                                "original_outcome": original_outcome, "new_outcome": new_outcome,
                                "override_outcome": override_outcome, "reason": reason,
                                "conditions_waived": waived}))
            except Exception:  # noqa: BLE001 — best-effort
                pass
            # Notify the original underwriter (whoever escalated it) with specifics.
            orig_uw = await conn.fetchval(
                "SELECT assigned_by FROM loan_assignments WHERE application_id=$1 AND tenant_id=$2 "
                "AND assigned_by IS NOT NULL ORDER BY assigned_at DESC LIMIT 1", app, tid)
            if orig_uw and str(orig_uw) != str(uid):
                _lbl = {"approve": "approved", "deny": "denied",
                        "clear_block": "cleared the block", "waive_condition": "waived the condition"}[override_outcome]
                await conn.execute(
                    "INSERT INTO notifications (tenant_id,user_id,type,title,application_id) VALUES ($1,$2,'override',$3,$4)",
                    tid, orig_uw, f"{reviewer_name} overrode {decision_name} on {app}: {_lbl}. Reason: {reason[:140]}", app)
            title = f"Override recorded: {decision_name} → {override_outcome.replace('_', ' ')}"
        elif body.action == "escalate":
            senior = await conn.fetchval(
                "SELECT user_id FROM users WHERE tenant_id=$1 AND role='senior_uw' AND is_active=true ORDER BY name LIMIT 1", tid,
            )
            if senior:
                # Record assigned_by = the escalating UW, so a later senior decision
                # can notify them back.
                await conn.execute("UPDATE loan_assignments SET previous_assignee=assigned_to, assigned_to=$1, assigned_by=$2, status='active', stage='decide', assigned_at=NOW() WHERE application_id=$3 AND tenant_id=$4", senior, uid, app, tid)
                await conn.execute("UPDATE entity_states SET assigned_to=$1, current_stage='decide' WHERE application_id=$2 AND tenant_id=$3", senior, app, tid)
                await conn.execute("INSERT INTO notifications (tenant_id,user_id,type,title,application_id) VALUES ($1,$2,'escalation',$3,$4)", tid, senior, "Loan escalated to you for senior review", app)
            title = "Escalated to Senior UW"
        elif body.action == "snooze_pending_docs":
            # Wait-for-docs: park the loan in Pending Response until the borrower
            # uploads (the upload flow flips it back to active + notifies). Reuses
            # the pending_borrower mechanism — no new column.
            await conn.execute(
                "UPDATE loan_assignments SET status='pending_borrower' "
                "WHERE application_id=$1 AND tenant_id=$2 AND assigned_to=$3", app, tid, uid)
            await conn.execute(
                "UPDATE entity_states SET loan_status='pending_borrower' WHERE application_id=$1 AND tenant_id=$2", app, tid)
            title = "Loan moved to Pending Response — awaiting borrower documents"
        elif body.action == "return_to_uw":
            # Hand the loan back to the original underwriter (who escalated it).
            arow = await conn.fetchrow(
                "SELECT previous_assignee, assigned_by FROM loan_assignments "
                "WHERE application_id=$1 AND tenant_id=$2 AND assigned_to=$3 "
                "ORDER BY assigned_at DESC LIMIT 1", app, tid, uid)
            target = arow and (arow["previous_assignee"] or arow["assigned_by"])
            if not target:
                raise HTTPException(422, "No original underwriter to return this loan to")
            note = (body.note or body.reasoning
                    or "Please wait for borrower documents before escalating.").strip()
            await conn.execute(
                "UPDATE loan_assignments SET previous_assignee=assigned_to, assigned_to=$1, "
                "assigned_by=$2, status='active', handoff_notes=$3, assigned_at=NOW() "
                "WHERE application_id=$4 AND tenant_id=$5 AND assigned_to=$6",
                target, uid, note, app, tid, uid)
            await conn.execute(
                "UPDATE entity_states SET assigned_to=$1 WHERE application_id=$2 AND tenant_id=$3", target, app, tid)
            await conn.execute(
                "INSERT INTO notifications (tenant_id,user_id,type,title,application_id) "
                "VALUES ($1,$2,'returned_to_uw',$3,$4)", tid, target,
                "Loan returned to you — please wait for borrower documents", app)
            title = "Returned to the underwriter"
        elif body.action == "request_more_info":
            # Senior UW returns the loan to the original underwriter WITH structured
            # feedback (creates an attention_request the UW sees). Distinct from
            # return_to_uw (which only leaves a handoff note).
            if user.get("role") not in ("senior_uw", "admin"):
                raise HTTPException(403, "Only a senior underwriter can send feedback")
            msg = (body.feedback_message or "").strip()
            if len(msg) < 25:
                raise HTTPException(422, "feedback_message is required (min 25 characters)")
            cat = body.feedback_category or "other"
            if cat not in ("documentation", "income", "employment", "property", "compliance", "other"):
                raise HTTPException(422, f"Invalid feedback_category: {cat}")
            arow = await conn.fetchrow(
                "SELECT previous_assignee, assigned_by FROM loan_assignments "
                "WHERE application_id=$1 AND tenant_id=$2 AND assigned_to=$3 "
                "ORDER BY assigned_at DESC LIMIT 1", app, tid, uid)
            target = arow and (arow["previous_assignee"] or arow["assigned_by"])
            if not target:
                raise HTTPException(422, "This loan is not escalated to you")
            await conn.execute(
                "UPDATE loan_assignments SET previous_assignee=assigned_to, assigned_to=$1, "
                "assigned_by=$2, status='active', stage='underwrite', assigned_at=NOW() "
                "WHERE application_id=$3 AND tenant_id=$4 AND assigned_to=$5",
                target, uid, app, tid, uid)
            await conn.execute(
                "UPDATE entity_states SET assigned_to=$1, current_stage='underwrite' WHERE application_id=$2 AND tenant_id=$3",
                target, app, tid)
            await conn.execute(
                "INSERT INTO attention_requests (application_id, tenant_id, from_user_id, to_user_id, "
                "message, priority, status, category, source) "
                "VALUES ($1,$2,$3,$4,$5,'high','open',$6,'senior_uw_feedback')",
                app, tid, uid, target, msg, cat)
            me_name = user.get("name") or "Senior UW"
            await conn.execute(
                "INSERT INTO notifications (tenant_id, user_id, type, title, application_id) "
                "VALUES ($1,$2,'senior_uw_feedback',$3,$4)",
                tid, target, f"{me_name} returned {app} with feedback: {msg[:120]}", app)
            try:
                await conn.execute(
                    "INSERT INTO activity_log (tenant_id, application_id, actor, action, target, detail) "
                    "VALUES ($1,$2,$3,'returned_to_uw',$4,$5::jsonb)",
                    tid, app, me_name, app, json.dumps({"reason": msg, "category": cat}))
            except Exception:  # noqa: BLE001 — audit is best-effort
                pass
            title = "Feedback sent — loan returned to the underwriter"
        elif body.action == "recommend_approval":
            # Clean-file forward path: a UW recommends approval; the loan goes to the
            # senior UW for the decision (reassigned like an escalation, so the senior
            # can actually act on it) with status pending_decision.
            if user.get("role") not in ("underwriter", "processor"):
                raise HTTPException(403, "Only an underwriter can recommend approval")
            blocking = await conn.fetchval(
                "SELECT count(*) FROM loan_condition_instances "
                "WHERE application_id=$1 AND tenant_id=$2 AND status='open' AND blocks_closing=true",
                app, tid)
            if blocking and blocking > 0:
                raise HTTPException(400, "Cannot recommend approval — blocking conditions exist")
            senior = await conn.fetchval(
                "SELECT user_id FROM users WHERE tenant_id=$1 AND role='senior_uw' AND is_active=true ORDER BY name LIMIT 1", tid)
            if not senior:
                raise HTTPException(422, "No senior underwriter available")
            await conn.execute(
                "UPDATE loan_assignments SET previous_assignee=assigned_to, assigned_to=$1, assigned_by=$2, "
                "status='pending_decision', stage='decide', assigned_at=NOW() "
                "WHERE application_id=$3 AND tenant_id=$4 AND assigned_to=$5", senior, uid, app, tid, uid)
            await conn.execute(
                "UPDATE entity_states SET assigned_to=$1, current_stage='decide' WHERE application_id=$2 AND tenant_id=$3",
                senior, app, tid)
            uw_name = user.get("name") or "The underwriter"
            notes = (body.note or "").strip()
            msg = f"{uw_name} reviewed {app} and recommends approval." + (f" Notes: {notes}" if notes else "")
            await conn.execute(
                "INSERT INTO attention_requests (application_id, tenant_id, from_user_id, to_user_id, "
                "message, priority, status, source) VALUES ($1,$2,$3,$4,$5,'normal','open','uw_recommendation')",
                app, tid, uid, senior, msg)
            borrower_name = await conn.fetchval(
                "SELECT COALESCE(ap.full_name, es.application_id) FROM entity_states es "
                "LEFT JOIN applications a ON a.application_id = es.application_id "
                "LEFT JOIN applicants ap ON ap.applicant_id = a.applicant_id "
                "WHERE es.application_id=$1 AND es.tenant_id=$2", app, tid) or app
            await conn.execute(
                "INSERT INTO notifications (tenant_id, user_id, type, title, application_id) "
                "VALUES ($1,$2,'uw_recommendation',$3,$4)",
                tid, senior, f"{uw_name} recommends approval for {borrower_name} ({app})", app)
            try:
                await conn.execute(
                    "INSERT INTO activity_log (tenant_id, application_id, actor, action, target, detail) "
                    "VALUES ($1,$2,$3,'recommend_approval',$4,$5::jsonb)",
                    tid, app, uw_name, app, json.dumps({"notes": notes}))
            except Exception:  # noqa: BLE001 — audit is best-effort
                pass
            title = "Recommendation sent to Senior UW"
        else:
            raise HTTPException(400, f"Unknown action: {body.action}")

        # Audit trail (best-effort) — actor name + action + full reason context.
        # override writes its own richer entry above, so skip the generic one.
        if body.action != "override":
            try:
                detail = {"note": body.note or "", "reasoning": body.reasoning or "",
                          "decision_id": body.decision_id or "", "denial_code": body.denial_code or "",
                          "denial_reason": body.denial_reason or "", "conditions": body.conditions or ""}
                await conn.execute(
                    "INSERT INTO activity_log (tenant_id, application_id, actor, action, target, detail) VALUES ($1,$2,$3,$4,$5,$6::jsonb)",
                    tid, app, user.get("name") or user.get("email", "user"), body.action, app, json.dumps(detail),
                )
            except Exception:  # noqa: BLE001 — best-effort
                pass

        # Notify the actor; and on a senior decision, notify the UW who escalated.
        # (override already notified the original UW with a specific message.)
        await conn.execute("INSERT INTO notifications (tenant_id,user_id,type,title,application_id) VALUES ($1,$2,'decision_made',$3,$4)", tid, uid, title, app)
        if body.action in ("approve", "deny"):
            escalator = await conn.fetchval(
                "SELECT assigned_by FROM loan_assignments WHERE application_id=$1 AND tenant_id=$2 "
                "AND assigned_by IS NOT NULL ORDER BY assigned_at DESC LIMIT 1", app, tid)
            if escalator and str(escalator) != str(uid):
                await conn.execute(
                    "INSERT INTO notifications (tenant_id,user_id,type,title,application_id) VALUES ($1,$2,'decision_made',$3,$4)",
                    tid, escalator, f"Senior UW decision on your escalation: {title}", app)
    return {"ok": True, "title": title}


ALLOWED_ROLES = ["admin", "manager", "processor", "underwriter", "senior_uw", "closer", "compliance", "viewer"]


class InviteBody(BaseModel):
    email: str
    name: str
    role: str = "processor"


class RoleBody(BaseModel):
    role: str


class AssignmentRuleBody(BaseModel):
    rule_name: str
    priority: int = 0
    min_loan_amount: Optional[float] = None
    max_loan_amount: Optional[float] = None
    loan_type: Optional[str] = None
    min_fraud_score: Optional[float] = None
    min_ltv: Optional[float] = None
    assign_to_role: str = "senior_uw"
    assign_to_user_id: Optional[str] = None


class RuleToggleBody(BaseModel):
    is_active: bool


def _rule_view(r) -> dict:
    return {
        "rule_id": str(r["rule_id"]),
        "rule_name": r["rule_name"],
        "priority": r["priority"],
        "min_loan_amount": float(r["min_loan_amount"]) if r["min_loan_amount"] is not None else None,
        "max_loan_amount": float(r["max_loan_amount"]) if r["max_loan_amount"] is not None else None,
        "loan_type": r["loan_type"],
        "min_fraud_score": float(r["min_fraud_score"]) if r["min_fraud_score"] is not None else None,
        "min_ltv": float(r["min_ltv"]) if r["min_ltv"] is not None else None,
        "assign_to_role": r["assign_to_role"],
        "assign_to_user_id": str(r["assign_to_user_id"]) if r["assign_to_user_id"] else None,
        "is_active": r["is_active"],
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
    }


@router.get("/pipeline/assignment-rules")
async def list_assignment_rules(user: dict = Depends(get_current_user)) -> dict:
    """Assignment rules for the tenant — drives the admin Settings UI."""
    _require_admin(user)
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT rule_id, rule_name, priority, min_loan_amount, max_loan_amount, loan_type, "
            "min_fraud_score, min_ltv, assign_to_role, assign_to_user_id, is_active, created_at "
            "FROM assignment_rules WHERE tenant_id=$1 ORDER BY priority DESC, created_at ASC",
            user["tenant_id"])
    return {"rules": [_rule_view(r) for r in rows]}


@router.post("/pipeline/assignment-rules")
async def create_assignment_rule(body: AssignmentRuleBody, user: dict = Depends(get_current_user)) -> dict:
    _require_admin(user)
    _require_db()
    if body.assign_to_role not in ALLOWED_ROLES:
        raise HTTPException(400, f"Invalid assign_to_role: {body.assign_to_role}")
    if not body.rule_name.strip():
        raise HTTPException(422, "rule_name is required")
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rid = await conn.fetchval(
            "INSERT INTO assignment_rules (tenant_id, rule_name, priority, min_loan_amount, "
            "max_loan_amount, loan_type, min_fraud_score, min_ltv, assign_to_role, assign_to_user_id) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING rule_id",
            user["tenant_id"], body.rule_name.strip(), body.priority, body.min_loan_amount,
            body.max_loan_amount, (body.loan_type or None), body.min_fraud_score, body.min_ltv,
            body.assign_to_role, (UUID(body.assign_to_user_id) if body.assign_to_user_id else None))
    return {"rule_id": str(rid), "ok": True}


@router.patch("/pipeline/assignment-rules/{rule_id}")
async def toggle_assignment_rule(rule_id: str, body: RuleToggleBody, user: dict = Depends(get_current_user)) -> dict:
    _require_admin(user)
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        res = await conn.execute(
            "UPDATE assignment_rules SET is_active=$1 WHERE rule_id=$2 AND tenant_id=$3",
            body.is_active, UUID(rule_id), user["tenant_id"])
    if res.endswith("0"):
        raise HTTPException(404, "Rule not found")
    return {"ok": True}


@router.get("/users")
async def list_users(user: dict = Depends(get_current_user)) -> dict:
    """Teammates in the tenant — drives 'assign to' dropdowns + Settings."""
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT user_id, name, email, role, is_active, last_login FROM users WHERE tenant_id = $1 ORDER BY name",
            user["tenant_id"],
        )
    return {"users": [{
        "user_id": str(r["user_id"]), "name": r["name"], "email": r["email"], "role": r["role"],
        "is_active": r["is_active"], "last_login": r["last_login"].isoformat() if r["last_login"] else None,
    } for r in rows]}


def _require_admin(user: dict) -> None:
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")


@router.post("/users/invite")
async def invite_user(
    body: InviteBody,
    user: dict = Depends(get_current_user),
    _perm: dict = Depends(require_permission("manage_users")),
) -> dict:
    _require_admin(user)
    _require_db()
    if body.role not in ALLOWED_ROLES:
        raise HTTPException(400, f"Invalid role: {body.role}")
    tid = user["tenant_id"]
    pool = await _get_pool()
    async with pool.acquire() as conn:
        if await conn.fetchval("SELECT 1 FROM users WHERE email = $1", body.email):
            raise HTTPException(409, "Email already registered")
        uid = await conn.fetchval(
            "INSERT INTO users (tenant_id, email, password_hash, name, role) VALUES ($1,$2,$3,$4,$5) RETURNING user_id",
            tid, body.email, hash_password("accord2026"), body.name, body.role,
        )
    return {"user_id": str(uid), "ok": True}


@router.post("/users/{user_id}/role")
async def change_role(
    user_id: str, body: RoleBody,
    user: dict = Depends(get_current_user),
    _perm: dict = Depends(require_permission("manage_users")),
) -> dict:
    _require_admin(user)
    _require_db()
    if body.role not in ALLOWED_ROLES:
        raise HTTPException(400, f"Invalid role: {body.role}")
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET role=$1, updated_at=NOW() WHERE user_id=$2 AND tenant_id=$3",
            body.role, UUID(user_id), user["tenant_id"],
        )
    return {"ok": True}


@router.post("/users/{user_id}/deactivate")
async def deactivate_user(
    user_id: str,
    user: dict = Depends(get_current_user),
    _perm: dict = Depends(require_permission("manage_users")),
) -> dict:
    _require_admin(user)
    _require_db()
    if str(user_id) == str(user["user_id"]):
        raise HTTPException(400, "You cannot deactivate yourself")
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET is_active=false, updated_at=NOW() WHERE user_id=$1 AND tenant_id=$2",
            UUID(user_id), user["tenant_id"],
        )
    return {"ok": True}


@router.post("/communications")
async def request_info(body: RequestInfoBody, user: dict = Depends(get_current_user)) -> dict:
    """Request docs from the borrower → log the comm, move the loan to
    pending_borrower, notify the requester."""
    _require_db()
    tid, uid = user["tenant_id"], UUID(str(user["user_id"]))
    due = None
    if body.due_date:
        try:
            due = date.fromisoformat(body.due_date[:10])
        except ValueError:
            due = None
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO communications (application_id, tenant_id, type, direction, from_user_id, "
            "recipient_email, subject, body, items_requested, status, due_date) "
            "VALUES ($1,$2,'doc_request','outbound',$3,$4,'Document request',$5,$6::jsonb,'simulated',$7)",
            body.application_id, tid, uid, body.recipient_email, body.note, json.dumps(body.items), due,
        )
        await conn.execute(
            "UPDATE loan_assignments SET status='pending_borrower' WHERE application_id=$1 AND tenant_id=$2 AND assigned_to=$3",
            body.application_id, tid, uid,
        )
        await conn.execute(
            "UPDATE entity_states SET loan_status='pending_borrower' WHERE application_id=$1 AND tenant_id=$2",
            body.application_id, tid,
        )
        title = "Document request sent" + (f" to {body.recipient_email}" if body.recipient_email else "")
        await conn.execute(
            "INSERT INTO notifications (tenant_id, user_id, type, title, application_id) VALUES ($1,$2,'doc_request',$3,$4)",
            tid, uid, title, body.application_id,
        )
    return {"ok": True}


@router.post("/communications/simulate-response")
async def simulate_response(body: dict = Body(...), user: dict = Depends(get_current_user)) -> dict:
    """Demo: pretend the borrower replied — comm delivered, loan back to active
    (marked RETURNED in the queue), assignee notified."""
    _require_db()
    app, tid = body.get("application_id"), user["tenant_id"]
    items = body.get("items") or []
    docs_text = ", ".join(items) if items else "the requested documents"
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT comm_id, from_user_id FROM communications WHERE application_id=$1 AND tenant_id=$2 AND direction='outbound' "
            "ORDER BY created_at DESC LIMIT 1", app, tid,
        )
        if row:
            await conn.execute("UPDATE communications SET responded_at=NOW(), status='delivered' WHERE comm_id=$1", row["comm_id"])
        await conn.execute("UPDATE loan_assignments SET status='active' WHERE application_id=$1 AND tenant_id=$2", app, tid)
        await conn.execute("UPDATE entity_states SET loan_status='active' WHERE application_id=$1 AND tenant_id=$2", app, tid)
        try:
            await conn.execute(
                "INSERT INTO activity_log (tenant_id, application_id, actor, action, target, detail) "
                "VALUES ($1,$2,'Borrower (simulated)','document_upload',$3,$4::jsonb)",
                tid, app, app, json.dumps({"uploaded": items, "note": f"Borrower uploaded {docs_text} (simulated)"}),
            )
        except Exception:  # noqa: BLE001 — activity log is best-effort
            pass
        assignee = await conn.fetchval(
            "SELECT assigned_to FROM loan_assignments WHERE application_id=$1 AND tenant_id=$2 ORDER BY assigned_at DESC LIMIT 1",
            app, tid,
        )
        if assignee:
            await conn.execute(
                "INSERT INTO notifications (tenant_id, user_id, type, title, application_id) "
                "VALUES ($1,$2,'borrower_responded',$3,$4)",
                tid, assignee, f"Borrower uploaded {docs_text}", app,
            )
        # Also notify the ORIGINAL doc requester, if different from the assignee.
        requester = row["from_user_id"] if row else None
        if requester and str(requester) != str(assignee):
            await conn.execute(
                "INSERT INTO notifications (tenant_id, user_id, type, title, application_id) "
                "VALUES ($1,$2,'borrower_responded',$3,$4)",
                tid, requester, f"Borrower uploaded {docs_text} (your request)", app,
            )
    return {"ok": True}


@router.post("/attention-requests")
async def create_attention(body: AttentionBody, user: dict = Depends(get_current_user)) -> dict:
    """Ask a teammate to revisit a decision → log it + notify them."""
    _require_db()
    tid, uid = user["tenant_id"], UUID(str(user["user_id"]))
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO attention_requests (application_id, tenant_id, from_user_id, to_user_id, decision_id, message, priority, status) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,'open')",
            body.application_id, tid, uid, UUID(str(body.to_user_id)), body.decision_id, body.message, body.priority,
        )
        frm = await conn.fetchval("SELECT name FROM users WHERE user_id=$1", uid) or "A teammate"
        await conn.execute(
            "INSERT INTO notifications (tenant_id, user_id, type, title, application_id) VALUES ($1,$2,'attention_request',$3,$4)",
            tid, UUID(str(body.to_user_id)), f"{frm} requested your review", body.application_id,
        )
    return {"ok": True}


class ResolveRequestBody(BaseModel):
    reply: Optional[str] = None


@router.post("/loans/{application_id}/attention-requests/{request_id}/resolve")
async def resolve_attention_request(
    application_id: str, request_id: str, body: ResolveRequestBody,
    user: dict = Depends(get_current_user),
) -> dict:
    """Resolve an internal review request directed at the caller. An optional reply
    is stored on the request and sent back to the requester as a notification. Only
    the request's to_user_id may resolve it — cross-user resolve is rejected."""
    _require_db()
    tid, uid = user["tenant_id"], UUID(str(user["user_id"]))
    try:
        rid = UUID(request_id)
    except ValueError:
        raise HTTPException(400, "Invalid request_id")
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT from_user_id, to_user_id FROM attention_requests "
            "WHERE request_id=$1 AND tenant_id=$2 AND application_id=$3",
            rid, tid, application_id,
        )
        if row is None:
            raise HTTPException(404, "Request not found")
        if str(row["to_user_id"]) != str(uid):
            raise HTTPException(403, "Only the request recipient can resolve it")
        reply = (body.reply or "").strip() or None
        await conn.execute(
            "UPDATE attention_requests SET status='resolved', completed_at=NOW(), response=$1 "
            "WHERE request_id=$2 AND tenant_id=$3 AND to_user_id=$4",
            reply, rid, tid, uid,
        )
        me = await conn.fetchval("SELECT name FROM users WHERE user_id=$1", uid) or "A teammate"
        title = f"{me} resolved your review request" + (f": {reply}" if reply else "")
        await conn.execute(
            "INSERT INTO notifications (tenant_id, user_id, type, title, application_id) "
            "VALUES ($1,$2,'attention_resolved',$3,$4)",
            tid, row["from_user_id"], title, application_id,
        )
    return {"ok": True}


@router.get("/loans/{application_id}/notes")
async def get_notes(application_id: str, user: dict = Depends(get_current_user)) -> dict:
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT n.note_id, n.note, n.note_type, n.created_at, COALESCE(u.name,'Unknown') AS author "
            "FROM loan_notes n LEFT JOIN users u ON u.user_id = n.user_id "
            "WHERE n.application_id=$1 AND n.tenant_id=$2 ORDER BY n.created_at DESC",
            application_id, user["tenant_id"],
        )
    return {"notes": [{
        "note_id": str(r["note_id"]), "note": r["note"], "note_type": r["note_type"],
        "author": r["author"], "created_at": r["created_at"].isoformat() if r["created_at"] else None,
    } for r in rows]}


@router.post("/loans/{application_id}/notes")
async def add_note(application_id: str, body: NoteBody, user: dict = Depends(get_current_user)) -> dict:
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO loan_notes (application_id, tenant_id, user_id, note, note_type) VALUES ($1,$2,$3,$4,$5)",
            application_id, user["tenant_id"], UUID(str(user["user_id"])), body.note, body.note_type,
        )
    return {"ok": True}


@router.get("/notifications")
async def list_notifications(user: dict = Depends(get_current_user)) -> dict:
    _require_db()
    tid, uid = user["tenant_id"], UUID(str(user["user_id"]))
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT notification_id, type, title, body, application_id, is_read, created_at "
            "FROM notifications WHERE tenant_id=$1 AND user_id=$2 ORDER BY created_at DESC LIMIT 50",
            tid, uid,
        )
        unread = await conn.fetchval(
            "SELECT count(*) FROM notifications WHERE tenant_id=$1 AND user_id=$2 AND is_read=false", tid, uid,
        )
    return {"unread_count": unread, "notifications": [{
        "notification_id": str(r["notification_id"]), "type": r["type"], "title": r["title"],
        "body": r["body"], "application_id": r["application_id"], "is_read": r["is_read"],
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
    } for r in rows]}


@router.post("/notifications/read-all")
async def read_all_notifications(user: dict = Depends(get_current_user)) -> dict:
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE notifications SET is_read=true WHERE user_id=$1 AND tenant_id=$2",
            UUID(str(user["user_id"])), user["tenant_id"],
        )
    return {"ok": True}


@router.post("/notifications/{notification_id}/read")
async def read_notification(notification_id: str, user: dict = Depends(get_current_user)) -> dict:
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE notifications SET is_read=true WHERE notification_id=$1 AND user_id=$2",
            UUID(notification_id), UUID(str(user["user_id"])),
        )
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────
# 2) GET /api/accord/loans/{application_id}
# ─────────────────────────────────────────────────────────────────────

# Friendly check name per persona (for the conversational summary).
PERSONA_FRIENDLY = {
    "credit_assessment": "Credit", "fraud_screening": "Identity", "compliance_check": "Compliance",
    "employment_reconciliation": "Employment", "income_verification": "Income", "ltv_assessment": "Collateral",
    "dti_calculation": "DTI", "product_eligibility": "Product", "rate_pricing": "Rate",
    "underwriting_decision": "Underwriting", "approval_routing": "Routing", "closing_readiness": "Closing",
}


def _sig(decision: dict, key: str) -> str:
    for s in decision.get("signals", []):
        if s.get("key") == key:
            return str(s.get("value", ""))
    return ""


def _conversational_summary(decisions: list[dict], m: dict, name: str) -> dict:
    """Plain-English, senior-underwriter-voice summary built from the decisions.
    Handles a clean file or N blocking issues (root cause = lowest wave, with a
    hard block beating an escalate at the same wave)."""
    blockers = sorted(
        [d for d in decisions if d.get("outcome") in ("block", "escalate")],
        key=lambda d: (PERSONAS.get(d["decision_id"], {}).get("wave", 9), 0 if d["outcome"] == "block" else 1),
    )
    passed = [d for d in decisions if d.get("outcome") not in ("block", "escalate")]
    has_block = any(d.get("outcome") == "block" for d in decisions)
    tone = "red" if has_block else ("amber" if blockers else "green")
    score, ltv = m.get("credit_score"), m.get("ltv")
    stated, verified, amount = m.get("income_stated"), m.get("income_verified"), m.get("loan_amount")
    gap = round(abs(stated - verified) / stated * 100) if stated and verified else None
    pids = {d["decision_id"] for d in passed}

    goods = []
    if "credit_assessment" in pids and score:
        goods.append(f"credit {int(score)}")
    if "income_verification" in pids and verified:
        goods.append(f"income {_k(verified)} verified")
    if "ltv_assessment" in pids and ltv is not None:
        goods.append(f"LTV {ltv:.0f}%")
    whats_good = ", ".join(goods) if goods else f"{len(passed)} other checks passed"
    whats_good = whats_good[:1].upper() + whats_good[1:]

    if not blockers:
        clean = (f"This is a clean file. All {len(decisions)} AI checks passed — credit {int(score) if score else '—'}"
                 + (f", income verified within {gap}%" if gap is not None else "")
                 + (f", LTV {ltv:.0f}% with good equity" if ltv is not None else "")
                 + ". Ready to advance to the next stage.")
        return {"summary": clean, "issue": None, "whats_good": whats_good,
                "next_step": "Approve and advance to the next stage",
                "headline": "APPROVE — every check passed", "tone": "green"}

    primary = blockers[0]
    did = primary["decision_id"]
    headline = ("DO NOT APPROVE — resolve the block before proceeding" if has_block
                else "REVIEW — needs your judgment before it advances")

    if "fraud" in did:
        fs, wl = _sig(primary, "Fraud score"), _sig(primary, "Watchlist match")
        summary = (f"{name}'s identity raised red flags"
                   + (f" — a fraud score of {fs}" if fs else "")
                   + (" and a federal watchlist match" if wl == "Yes" else "")
                   + ", with identity confidence and document authenticity both well below our bar. "
                   "This is a mandatory BSA referral before anything else moves on this file. "
                   "The good news: the rest of the loan looks clean — if the identity issue clears, this is a straightforward deal.")
        issue = "Possible identity fraud (watchlist + identity risk)"
        next_step = "Refer to the BSA officer for SAR review before proceeding"
    elif "income" in did or "employment" in did:
        restruct = round((amount * verified / stated) / 1000) * 1000 if (amount and stated and verified) else None
        summary = (f"There's a gap between what {name} states"
                   + (f" (${stated:,.0f}/yr)" if stated else "")
                   + " and what the documents verify"
                   + (f" (${verified:,.0f}/yr)" if verified else "")
                   + (f" — about a {gap}% difference" if gap is not None else "")
                   + ". Two options: ask for a current pay stub showing higher income (maybe a recent raise), "
                   "or restructure to qualify at the verified figure"
                   + (f" (~${restruct:,.0f} max)" if restruct else "") + ".")
        issue = ("Income discrepancy" + (f" {gap}%" if gap is not None else "")
                 + (f" — ${stated:,.0f} stated vs ${verified:,.0f} verified" if stated and verified else ""))
        next_step = "Request a current pay stub + employer VOE, or restructure the loan"
    elif "compliance" in did:
        summary = ("Compliance flagged this file. We can't proceed until disclosures are re-issued and TRID "
                   "timing checks out. The rest of the loan otherwise looks clean.")
        issue = "Compliance / disclosure timing issue"
        next_step = "Re-issue disclosures and confirm TRID timing"
    elif "ltv" in did:
        summary = ("The collateral doesn't support the loan as structured. Either order a review appraisal or "
                   "have the borrower bring more money in. The rest of the file is otherwise clean.")
        issue = "Collateral / LTV above guideline"
        next_step = "Order a review appraisal or increase the down payment"
    else:
        friendly = PERSONA_FRIENDLY.get(did, did.replace("_", " "))
        summary = (f"{primary.get('explanation', '')} {len(passed)} of {len(decisions)} checks passed — "
                   "if this clears, it's a straightforward deal.")
        issue = f"{friendly} — {'blocked' if primary['outcome'] == 'block' else 'needs senior review'}"
        next_step = "Review the flagged decision and clear it or request more information"

    if len(blockers) > 1:
        summary += (f" Heads up: {len(blockers)} checks need attention here — "
                    + ", ".join(PERSONA_FRIENDLY.get(b["decision_id"], b["decision_id"]) for b in blockers) + ".")
    return {"summary": summary, "issue": issue, "whats_good": whats_good,
            "next_step": next_step, "headline": headline, "tone": tone}


_QM_LABEL = {
    "safe_harbor": "Safe Harbor QM",
    "rebuttable_presumption": "Rebuttable Presumption QM",
    "non_qm": "Non-QM",
    "pending": "QM Pending",
}


def _qm_status(e: dict, loan_terms: dict) -> dict:
    """QM / Ability-to-Repay determination (CFPB 12 CFR §1026.43(e)) derived from
    the loan's real metrics. dti_back is in percent units (e.g. 44.27). DTI is the
    governing test; points & fees is not captured in the source data, so it is
    surfaced as informational (pass=None) rather than fabricated, and a missing
    DTI yields a 'pending' determination rather than a false safe harbor."""
    dti = _f(e.get("dti_back"))
    program = ((loan_terms.get("rate_lock") or {}) if isinstance(loan_terms.get("rate_lock"), dict) else {}).get("loan_program") or ""
    pl = program.lower()
    # term in years from the program string (e.g. "Conv 30yr fixed")
    term_yrs = None
    for tok in pl.replace("yr", " yr ").split():
        if tok.isdigit():
            term_yrs = int(tok)
            break
    has_balloon = "balloon" in pl

    tests = []
    if dti and dti > 0:
        tests.append({"test": "DTI", "value": f"{dti:.1f}%", "limit": "≤ 43%", "pass": dti <= 43})
    else:
        tests.append({"test": "DTI", "value": "Not calculated", "limit": "≤ 43%", "pass": None})
    tests.append({"test": "Points & fees", "value": "Not captured", "limit": "≤ 3%", "pass": None})
    if term_yrs:
        tests.append({"test": "Loan term", "value": f"{term_yrs}yr", "limit": "≤ 30yr", "pass": term_yrs <= 30})
    else:
        tests.append({"test": "Loan term", "value": "—", "limit": "≤ 30yr", "pass": None})
    tests.append({"test": "Balloon payment", "value": "Present" if has_balloon else "None",
                  "limit": "Not allowed", "pass": not has_balloon})

    if not dti or dti <= 0:
        status = "pending"
    elif dti > 50:
        status = "non_qm"
    elif dti > 43:
        status = "rebuttable_presumption"
    else:
        status = "safe_harbor"
    if (term_yrs and term_yrs > 30) or has_balloon:  # hard QM disqualifiers
        status = "non_qm"

    return {
        "status": status,
        "determination": _QM_LABEL[status],
        "citation": "12 CFR §1026.43(e) — Ability-to-Repay / QM Rule",
        "tests": tests,
    }


def compute_examiner_readiness(decisions: list[dict], actions: list) -> dict:
    """How examiner-ready this file is: 60% from decisions carrying a rule
    citation, 40% from human actions carrying a >= 25-char reason."""
    total = len(decisions)
    if total == 0:
        return {"score": 0, "missing": ["No decisions recorded"]}
    documented = sum(1 for d in decisions if d.get("rule"))
    human = [a for a in actions if (a["performed_by"] or "") != "system"]
    explained = sum(1 for a in human if len((a["reason_text"] or "")) >= 25)
    score = round((documented / total) * 60 + (explained / max(len(human), 1)) * 40)
    missing: list[str] = []
    if documented < total:
        missing.append(f"{total - documented} decisions missing rule citations")
    if explained < len(human):
        missing.append(f"{len(human) - explained} actions missing explanation")
    return {"score": score, "missing": missing}


async def _current_active_version(conn, tenant_id: str):
    """The tenant's current active rule version row (highest version)."""
    return await conn.fetchrow(
        "SELECT rule_version_id, version, effective_from FROM tenant_rules "
        "WHERE tenant_id=$1 AND status='active' ORDER BY version DESC LIMIT 1",
        tenant_id,
    )


async def compute_rain_check(conn, tenant_id: str, e: dict) -> dict:
    """Rain-check / pipeline-protection status for one loan, from its entity row.

    A loan whose ``pinned_rule_version`` differs from the tenant's current active
    version is *protected*: it was rate-locked under an older rule set and is
    evaluated under that pinned version, not current rules.
    """
    pinned = e.get("pinned_rule_version")  # uuid or None
    current = await _current_active_version(conn, tenant_id)
    current_id = current["rule_version_id"] if current else None
    pinned_num = None
    if pinned is not None:
        pv = await conn.fetchrow("SELECT version FROM tenant_rules WHERE rule_version_id=$1", pinned)
        pinned_num = pv["version"] if pv else None
    protected = pinned is not None and current_id is not None and pinned != current_id
    pinned_at = e.get("pinned_at")
    app_date = e.get("application_date")
    return {
        "rate_locked": bool(e.get("rate_locked")),
        "pinned_rule_version": str(pinned) if pinned else None,
        "pinned_version_number": pinned_num,
        "pinned_at": pinned_at.isoformat() if pinned_at else None,
        "application_date": app_date.isoformat() if app_date else None,
        "current_rule_version_id": str(current_id) if current_id else None,
        "current_version_number": current["version"] if current else None,
        "protected": protected,
        "protection_reason": (
            "Loan was rate-locked before a rule update — evaluated under the rules "
            "active at lock date per pipeline protection policy."
            if protected
            else ("Loan evaluated under current rules." if pinned is None
                  else "Pinned to the current rule version — no version difference.")
        ),
    }


async def resolve_applicable_rules(conn, tenant_id: str, application_id: str, at=None) -> dict:
    """Which tenant_rules version governs this loan, and its rule body.

    Priority: (1) pinned_rule_version (rate lock) → (2) pipeline_cutoff_date
    protection for loans submitted before the cutoff → (3) current active version.
    This is the canonical resolver future evaluations consult so a locked loan is
    always scored under the rules in force when it locked.
    """
    es = await conn.fetchrow(
        "SELECT pinned_rule_version, pinned_at, application_date "
        "FROM entity_states WHERE application_id=$1 AND tenant_id=$2",
        application_id, tenant_id,
    )
    # 1. Explicitly pinned at rate lock.
    if es and es["pinned_rule_version"]:
        row = await conn.fetchrow(
            "SELECT rule_version_id, version, rules FROM tenant_rules WHERE rule_version_id=$1",
            es["pinned_rule_version"],
        )
        if row:
            return {
                "rule_version_id": str(row["rule_version_id"]), "version": row["version"],
                "rules": _J(row["rules"]), "source": "pinned",
                "reason": f"Rate-locked — pinned to rule v{row['version']}",
            }
    # 2. Pipeline-cutoff protection: a newer active version set a cutoff after this
    #    loan's application_date → grandfather it under the prior version.
    app_date = es["application_date"] if es else None
    if app_date:
        prot = await conn.fetchrow(
            """
            SELECT prev.rule_version_id, prev.version, prev.rules, curr.pipeline_cutoff_date
            FROM tenant_rules curr
            JOIN tenant_rules prev ON prev.tenant_id = curr.tenant_id
              AND prev.version = curr.version - 1
            WHERE curr.tenant_id = $1 AND curr.status = 'active'
              AND curr.pipeline_cutoff_date IS NOT NULL
              AND curr.pipeline_cutoff_date > $2
            ORDER BY curr.version DESC LIMIT 1
            """,
            tenant_id, app_date,
        )
        if prot:
            return {
                "rule_version_id": str(prot["rule_version_id"]), "version": prot["version"],
                "rules": _J(prot["rules"]), "source": "pipeline_protection",
                "reason": (f"Submitted before pipeline cutoff {prot['pipeline_cutoff_date']} "
                           f"— grandfathered under rule v{prot['version']}"),
            }
    # 3. Current active version.
    cur = await conn.fetchrow(
        "SELECT rule_version_id, version, rules FROM tenant_rules "
        "WHERE tenant_id=$1 AND status='active' ORDER BY version DESC LIMIT 1",
        tenant_id,
    )
    if cur:
        return {
            "rule_version_id": str(cur["rule_version_id"]), "version": cur["version"],
            "rules": _J(cur["rules"]), "source": "current", "reason": "Current active rule version",
        }
    return {"rule_version_id": None, "version": None, "rules": {}, "source": "none", "reason": "No rules configured"}


# AUS recommendation (loan_terms.aus_findings.recommendation) -> display label.
_AUS_RESULT_LABELS = {
    "approve_eligible":   "Approve/Eligible",
    "refer_with_caution": "Refer with Caution",
    "out_of_scope":       "Out of Scope",
    "approve_ineligible": "Approve/Ineligible",
}


@router.get("/loans/{application_id}")
async def loan_detail(application_id: str, user: dict = Depends(get_current_user)) -> dict:
    _require_db()
    tenant_id = user["tenant_id"]
    pool = await _get_pool()
    async with pool.acquire() as conn:
        entity = await conn.fetchrow(
            "SELECT * FROM entity_states WHERE application_id = $1 AND tenant_id = $2 LIMIT 1",
            application_id, tenant_id,
        )
        if entity is None:
            raise HTTPException(404, f"Unknown application {application_id}")
        approw = await conn.fetchrow(
            """
            SELECT a.loan_type, a.loan_purpose, a.occupancy, a.stated_employer,
                   a.verified_employer, ap.full_name, ap.first_name, ap.dob, ap.email,
                   l.loan_number
            FROM applications a
            LEFT JOIN applicants ap ON ap.applicant_id = a.applicant_id
            LEFT JOIN loan l ON l.application_id = a.application_id
            WHERE a.application_id = $1 LIMIT 1
            """,
            application_id,
        )
        decision_rows = await conn.fetch(
            """
            SELECT DISTINCT ON (dout.decision_id)
                   dout.decision_id, dout.outcome, dout.confidence, dout.mode, dout.wave,
                   dout.human_action, dout.human_reviewer, dout.acted_at, dout.human_override_reason,
                   dout.boundary_matched, dout.boundary_rule, dout.context_snapshot, dout.reasoning, dout.stale,
                   dout.rule_version_id, dout.governed_by,
                   tr.version AS rule_version_number,
                   tr.effective_from AS rule_version_effective_from
            FROM decision_outputs dout
            LEFT JOIN tenant_rules tr ON tr.rule_version_id = dout.rule_version_id
            WHERE dout.application_id = $1 AND dout.tenant_id = $2
            ORDER BY dout.decision_id, dout.version DESC
            """,
            application_id, tenant_id,
        )
        # Current assignment + escalation context (pure DB joins — no hardcoded
        # names/ids). assigned_by is the UW who escalated (set by the escalate /
        # senior_review handlers); the reason/category come from the loan_actions row.
        assign_row = await conn.fetchrow(
            """
            SELECT la.assigned_to, la.assigned_by, la.assigned_at, la.status AS assign_status,
                   la.assignment_type, ut.name AS assigned_to_name, ub.name AS escalated_by_name
            FROM loan_assignments la
            LEFT JOIN users ut ON ut.user_id = la.assigned_to
            LEFT JOIN users ub ON ub.user_id = la.assigned_by
            WHERE la.application_id = $1 AND la.tenant_id = $2
            ORDER BY la.assigned_at DESC NULLS LAST LIMIT 1
            """,
            application_id, tenant_id,
        )
        esc_action = await conn.fetchrow(
            """
            SELECT reason_text, reason_category, performed_at
            FROM loan_actions
            WHERE application_id = $1 AND tenant_id = $2
              AND action_type IN ('escalate', 'senior_review')
            ORDER BY performed_at DESC LIMIT 1
            """,
            application_id, tenant_id,
        )
        # Open internal requests visible to the caller on this loan: either
        # addressed to them (to_user_id) OR on a loan they own (loan_assignments.
        # assigned_to). The 3-table join resolves both the recipient and the
        # assignee so the approve guard fires for the assigned UW even when the
        # request was addressed to someone else. addressed_to_me gates whether the
        # banner shows resolve/reply actions (only the recipient may resolve).
        internal_req_rows = await conn.fetch(
            """
            SELECT * FROM (
              SELECT DISTINCT ON (ar.request_id)
                     ar.request_id, ar.message, ar.priority, ar.created_at, ar.from_user_id,
                     ar.category, ar.source,
                     COALESCE(uf.name, 'A teammate') AS from_name,
                     ut.name AS to_name,
                     (ar.to_user_id = $3) AS addressed_to_me
              FROM attention_requests ar
              LEFT JOIN users uf ON uf.user_id = ar.from_user_id
              LEFT JOIN users ut ON ut.user_id = ar.to_user_id
              LEFT JOIN loan_assignments la
                     ON la.application_id = ar.application_id AND la.tenant_id = ar.tenant_id
              WHERE ar.application_id = $1 AND ar.tenant_id = $2
                AND ar.status = 'open'
                AND (ar.to_user_id = $3 OR la.assigned_to = $3)
              ORDER BY ar.request_id, ar.created_at DESC
            ) t ORDER BY t.created_at DESC
            """,
            application_id, tenant_id, UUID(str(user["user_id"])),
        )
        # Replies to internal requests THIS caller made on this loan (resolved with
        # a response, last 24h) — so the requester sees the answer in the banner.
        my_reply_rows = await conn.fetch(
            """
            SELECT ar.request_id, ar.message, ar.response, ar.completed_at,
                   COALESCE(ut.name, 'A teammate') AS to_name
            FROM attention_requests ar
            LEFT JOIN users ut ON ut.user_id = ar.to_user_id
            WHERE ar.application_id = $1 AND ar.tenant_id = $2
              AND ar.from_user_id = $3 AND ar.status = 'resolved'
              AND ar.response IS NOT NULL
              AND ar.completed_at >= NOW() - INTERVAL '24 hours'
            ORDER BY ar.completed_at DESC
            """,
            application_id, tenant_id, UUID(str(user["user_id"])),
        )
        # Open (unfulfilled) document requests on this loan — so a senior UW who
        # owns it via escalation still sees the pending borrower-doc context.
        pending_doc_rows = await conn.fetch(
            """
            SELECT c.comm_id, c.from_user_id, c.items_requested, c.body, c.created_at,
                   c.due_date, c.recipient_email, COALESCE(u.name, 'A teammate') AS requested_by_name
            FROM communications c LEFT JOIN users u ON u.user_id = c.from_user_id
            WHERE c.application_id = $1 AND c.tenant_id = $2
              AND c.type = 'doc_request' AND c.responded_at IS NULL
            ORDER BY c.created_at DESC
            """,
            application_id, tenant_id,
        )
        doc_rows = await conn.fetch(
            """
            SELECT document_type, document_category, status, confidence_score,
                   extraction_method, extracted_fields
            FROM document_index
            WHERE application_id = $1 AND COALESCE(is_current, true)
            ORDER BY document_category, document_type
            """,
            application_id,
        )
        rel_rows = await conn.fetch(
            """
            SELECT source_doc_id, target_doc_id, relationship_type, field_name,
                   source_value, target_value, delta_pct
            FROM document_relationships WHERE application_id = $1
            """,
            application_id,
        )
        cond_rows = await conn.fetch(
            """
            SELECT condition_id, decision_id, category, description, status,
                   severity, created_by, created_at, cleared_by, cleared_at
            FROM conditions WHERE application_id = $1
            ORDER BY created_at DESC
            """,
            application_id,
        )
        action_rows = await conn.fetch(
            "SELECT performed_by, reason_text FROM loan_actions WHERE application_id = $1 AND tenant_id = $2",
            application_id, tenant_id,
        )
        act_rows = await conn.fetch(
            """
            SELECT actor, action, target, detail, created_at
            FROM activity_log WHERE application_id = $1
            ORDER BY created_at DESC LIMIT 50
            """,
            application_id,
        )
        # Escalation thread — full history merged chronologically from every
        # touchpoint so a re-escalation carries the prior exchange. Sources:
        #   loan_actions        → escalate/senior_review (reasons), approve, deny
        #   attention_requests  → senior_uw_feedback (+category), uw_recommendation
        #   decision_outputs    → human_action='overridden'
        # All scoped to this application_id + tenant_id (never cross-tenant).
        thread_action_rows = await conn.fetch(
            """
            SELECT la.id, la.action_type, la.reason_category, la.reason_text, la.performed_at,
                   COALESCE(u.name, la.performed_by, 'A teammate') AS actor_name,
                   u.role AS actor_role
            FROM loan_actions la
            LEFT JOIN users u ON u.email = la.performed_by AND u.tenant_id = la.tenant_id
            WHERE la.application_id = $1 AND la.tenant_id = $2
              AND la.action_type IN ('escalate', 'senior_review', 'approve', 'deny')
            ORDER BY la.performed_at ASC
            """,
            application_id, tenant_id,
        )
        thread_attention_rows = await conn.fetch(
            """
            SELECT ar.request_id, ar.source, ar.category, ar.message, ar.created_at,
                   COALESCE(u.name, 'A teammate') AS actor_name,
                   COALESCE(u.role, 'senior_uw') AS actor_role
            FROM attention_requests ar
            LEFT JOIN users u ON u.user_id = ar.from_user_id
            WHERE ar.application_id = $1 AND ar.tenant_id = $2
              AND ar.source IN ('senior_uw_feedback', 'uw_recommendation')
            ORDER BY ar.created_at ASC
            """,
            application_id, tenant_id,
        )
        thread_override_rows = await conn.fetch(
            """
            SELECT dout.id, dout.decision_id, dout.human_override_reason, dout.acted_at,
                   COALESCE(u.name, dout.human_reviewer, 'A teammate') AS actor_name,
                   u.role AS actor_role
            FROM decision_outputs dout
            LEFT JOIN users u ON u.name = dout.human_reviewer AND u.tenant_id = dout.tenant_id
            WHERE dout.application_id = $1 AND dout.tenant_id = $2
              AND dout.human_action = 'overridden'
            ORDER BY dout.acted_at ASC
            """,
            application_id, tenant_id,
        )
        rain_check = await compute_rain_check(conn, tenant_id, dict(entity))

    e = dict(entity)
    ap = dict(approw) if approw else {}
    borrower = _J(e.get("borrower"))
    prop = _J(e.get("property"))
    loan_terms = _J(e.get("loan_terms"))
    merged_entity = {
        k: e.get(k) for k in (
            "mid_credit_score", "ltv", "cltv", "dti_front", "dti_back",
            "loan_amount", "appraised_value", "purchase_price",
            "interest_rate", "combined_monthly_income", "monthly_obligations",
            "piti_monthly", "status",
        )
    }

    decisions = []
    flags = {"fraud_block": False, "any_block": False, "pending_human": False, "pending_adverse": False}
    decision_outcomes: dict[str, str] = {}
    for r in sorted(decision_rows, key=lambda r: PERSONAS.get(r["decision_id"], {}).get("wave", 9)):
        did = r["decision_id"]
        outcome = r["outcome"]
        decision_outcomes[did] = outcome
        if outcome == "block":
            flags["any_block"] = True
            if did == "fraud_screening":
                flags["fraud_block"] = True
        if r["human_action"] is None and r["mode"] in ("recommend", "human_approval"):
            flags["pending_human"] = True
        if outcome in ("escalate", "recommend") and r["human_action"] is None:
            flags["pending_adverse"] = True

        ctx = _J(r["context_snapshot"])
        merged_ctx = {**merged_entity, **ctx}
        boundary_rule = r["boundary_rule"]
        effective = (canonical_underwriting_state(outcome, merged_ctx)
                     if did == "underwriting_decision" else outcome)
        vocab = resolve_vocab(did, effective)
        labels = {**DECISION_LABELS.get(did, {}), "kind": vocab["kind"], "vocab": vocab}
        if vocab["kind"] == "routing":
            labels["routing"] = {
                "underwriting_state": canonical_underwriting_state(outcome, merged_ctx),
                "routing_action": "routing the finalized decision",
            }
        signals = build_signals(did, merged_ctx, boundary_rule)
        explanation = explain(effective, boundary_rule, signals, labels)
        decisions.append({
            "decision_id": did,
            "persona_name": PERSONAS.get(did, {}).get("name", did),
            "wave": r["wave"],
            "outcome": outcome,
            "confidence": _f(r["confidence"]),
            "mode": r["mode"],
            "reviewed": r["human_action"] is not None,
            "reviewer": r["human_reviewer"],
            "reviewed_at": r["acted_at"].isoformat() if r["acted_at"] else None,
            "human_action": r["human_action"],
            "stale": bool(r["stale"]) if r["stale"] is not None else False,
            "explanation": explanation,
            "signals": [_signal_view(s) for s in signals],
            "evidence": _evidence_for(did, doc_rows),
            "rule": boundary_rule,
            "rule_version_id": str(r["rule_version_id"]) if r["rule_version_id"] else None,
            "rule_version_short": str(r["rule_version_id"])[:8] if r["rule_version_id"] else None,
            "rule_version_number": r["rule_version_number"],
            "rule_version_effective_from": (
                r["rule_version_effective_from"].isoformat() if r["rule_version_effective_from"] else None
            ),
            "governed_by": _J(r["governed_by"]) if r["governed_by"] else [],
        })

    lock_days = _lock_days(loan_terms)
    status = _derive_status({**flags, "n_decisions": len(decision_rows)})
    urgency = _derive_urgency(flags, lock_days)
    blocking = _blocking_persona({d: {"outcome": o} for d, o in decision_outcomes.items()})

    # Assignment + escalation context (data-driven; keys always present, null when
    # not assigned/escalated). Escalated == there's a real escalate/senior_review
    # action AND the active assignment records who handed it off (assigned_by).
    _asg = dict(assign_row) if assign_row else {}
    _esc = dict(esc_action) if esc_action else {}
    _escalated = bool(_asg.get("assigned_by")) and bool(_esc)
    escalation_ctx = {
        "assigned_to": str(_asg["assigned_to"]) if _asg.get("assigned_to") else None,
        "assigned_to_name": _asg.get("assigned_to_name"),
        "escalated_by": str(_asg["assigned_by"]) if (_escalated and _asg.get("assigned_by")) else None,
        "escalated_by_name": _asg.get("escalated_by_name") if _escalated else None,
        "escalated_at": (_asg["assigned_at"].isoformat() if (_escalated and _asg.get("assigned_at")) else None),
        "escalation_reason": _esc.get("reason_text") if _escalated else None,
        "escalation_category": _esc.get("reason_category") if _escalated else None,
        # Rule-routed straight to a senior role at ingestion — not an escalation.
        "direct_assignment": _asg.get("assignment_type") == "direct_assignment",
    }

    metrics_out = {
        "loan_amount": _f(e.get("loan_amount")),
        "credit_score": int(e["mid_credit_score"]) if e.get("mid_credit_score") else None,
        "ltv": _pct(e.get("ltv")),
        "dti": _pct(e.get("dti_back")),
        "interest_rate": _pct(e.get("interest_rate")),
        "lock_days_remaining": lock_days,
        "income_stated": _f((borrower.get("income") or {}).get("stated_income_annual")),
        "income_verified": _f((borrower.get("income") or {}).get("verified_income_annual")),
    }
    full_name = ap.get("full_name") or e.get("application_id") or "The borrower"

    # Surface fields the frontend reads at top level but the payload omitted.
    # loan_purpose lives in loan_terms.urla (applications.loan_purpose is often
    # NULL); the AUS recommendation lives in loan_terms.aus_findings.
    loan_purpose = (loan_terms.get("urla") or {}).get("loan_purpose") or ap.get("loan_purpose")
    _aus_rec = (loan_terms.get("aus_findings") or {}).get("recommendation")
    aus_result = None
    if _aus_rec:
        aus_result = _AUS_RESULT_LABELS.get(_aus_rec) or _aus_rec.replace("_", " ").title()

    internal_requests = [
        {
            "request_id": str(r["request_id"]),
            "from": r["from_name"],
            "from_user_id": str(r["from_user_id"]),
            "to": r["to_name"],
            "addressed_to_me": bool(r["addressed_to_me"]),
            "message": r["message"],
            "priority": r["priority"],
            "category": r["category"],
            "source": r["source"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in internal_req_rows
    ]
    internal_request_replies = [
        {
            "request_id": str(r["request_id"]), "to": r["to_name"],
            "message": r["message"], "response": r["response"],
            "resolved_at": r["completed_at"].isoformat() if r["completed_at"] else None,
        }
        for r in my_reply_rows
    ]

    # Merge the escalation history into one chronological thread. The first
    # escalation reads 'escalated'; every later one 're_escalated'.
    def _naive_ts(dt):
        if dt is None:
            return datetime.min
        return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt

    _thread_items: list[dict] = []
    _esc_seen = 0
    _decision_action = {"approve": "approved", "deny": "denied"}

    def _thread_add(event_id, actor, role, action, message, category, ts):
        _thread_items.append({
            "event_id": str(event_id) if event_id is not None else None,
            "actor_name": actor,
            "actor_role": role,
            "action": action,
            "message": (message or "") or None,
            "category": category,
            "timestamp": ts.isoformat() if ts else None,
            "time_ago": _time_ago(ts),
            "_sort": _naive_ts(ts),
        })

    for r in thread_action_rows:
        at = r["action_type"]
        if at in ("escalate", "senior_review"):
            _esc_seen += 1
            thr_action = "escalated" if _esc_seen == 1 else "re_escalated"
        else:
            thr_action = _decision_action.get(at)
            if not thr_action:
                continue
        _thread_add(r["id"], r["actor_name"], r["actor_role"], thr_action,
                    r["reason_text"], r["reason_category"], r["performed_at"])
    for r in thread_attention_rows:
        action = "recommend_approval" if r["source"] == "uw_recommendation" else "returned_feedback"
        _thread_add(r["request_id"], r["actor_name"], r["actor_role"], action,
                    r["message"], r["category"], r["created_at"])
    for r in thread_override_rows:
        _thread_add(r["id"], r["actor_name"], r["actor_role"], "overridden",
                    r["human_override_reason"], None, r["acted_at"])

    _thread_items.sort(key=lambda x: x["_sort"])
    escalation_thread = [
        {k: v for k, v in it.items() if k != "_sort"} for it in _thread_items
    ]

    pending_doc_requests = [
        {
            "comm_id": str(r["comm_id"]),
            "requested_by": str(r["from_user_id"]) if r["from_user_id"] else None,
            "requested_by_name": r["requested_by_name"],
            "document_types": _J(r["items_requested"]) or [],
            "message": r["body"],
            "requested_at": r["created_at"].isoformat() if r["created_at"] else None,
            "due_date": r["due_date"].isoformat() if r["due_date"] else None,
            "send_to_email": r["recipient_email"],
        }
        for r in pending_doc_rows
    ]

    return {
        "application_id": application_id,
        "borrower": _borrower_block(ap, borrower, e, loan_terms),
        "borrower_email": ap.get("email"),
        "loan_number": ap.get("loan_number"),
        "loan_purpose": loan_purpose,
        "aus_result": aus_result,
        "metrics": metrics_out,
        **escalation_ctx,
        "internal_requests": internal_requests,
        "internal_request_replies": internal_request_replies,
        "pending_doc_requests": pending_doc_requests,
        "escalation_thread": escalation_thread,
        "qm": _qm_status(e, loan_terms),
        "examiner_readiness": compute_examiner_readiness(decisions, action_rows),
        "rain_check": rain_check,
        "conversational_summary": _conversational_summary(decisions, metrics_out, full_name.split()[0]),
        "status": status,
        "urgency": urgency,
        "blocking_persona": blocking,
        "decisions": decisions,
        "documents": [_document_view(d) for d in doc_rows],
        "graph_edges": [
            {
                "source": r["source_doc_id"], "target": r["target_doc_id"],
                "relationship": r["relationship_type"], "field": r["field_name"],
                "source_value": r["source_value"], "target_value": r["target_value"],
                "delta_pct": _f(r["delta_pct"]),
            }
            for r in rel_rows
        ],
        "conditions": [
            {
                "condition_id": str(r["condition_id"]), "decision_id": r["decision_id"],
                "category": r["category"], "description": r["description"],
                "status": r["status"], "severity": r["severity"],
                "created_by": r["created_by"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in cond_rows
        ],
        "activity": [
            {
                "actor": r["actor"], "action": r["action"], "target": r["target"],
                "detail": _J(r["detail"]),
                "at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in act_rows
        ],
    }


_SIGNAL_STATUS = {"good": "pass", "bad": "fail", "warn": "warn", "missing": "no_data", "neutral": "info"}


def _signal_view(s: dict) -> dict:
    detail = "logged but not gated by the matched rule" if s.get("ungated") else ""
    return {
        "key": s["label"],
        "value": s["display"],
        "status": _SIGNAL_STATUS.get(s.get("state"), "info"),
        "detail": detail,
    }


def _document_view(d) -> dict:
    extracted = _J(d["extracted_fields"])
    return {
        "document": (d["document_type"] or "").replace("_", " ").title(),
        "type": d["document_type"],
        "category": d["document_category"],
        "status": d["status"],
        "confidence": _f(d["confidence_score"]),
        "extraction_method": d["extraction_method"],
        "flags": list(extracted.keys()) if isinstance(extracted, dict) else [],
    }


# Which document categories back each decision.
_DECISION_DOC_CATS = {
    "credit_assessment": {"credit"},
    "income_verification": {"income"},
    "employment_reconciliation": {"income", "employment"},
    "fraud_screening": {"identity"},
    "compliance_check": {"loan_terms", "compliance"},
    "ltv_assessment": {"property", "collateral"},
    "closing_readiness": {"property", "title", "insurance"},
}


def _evidence_for(decision_id: str, doc_rows) -> list[dict]:
    cats = _DECISION_DOC_CATS.get(decision_id)
    out = []
    for d in doc_rows:
        if cats and d["document_category"] in cats:
            out.append({
                "document": (d["document_type"] or "").replace("_", " ").title(),
                "detail": f"{d['status']}"
                          + (f" · {int(d['confidence_score']*100)}% confidence"
                             if d["confidence_score"] is not None else ""),
            })
    return out


def _borrower_block(ap: dict, borrower: dict, entity: dict, loan_terms: dict) -> dict:
    name = ap.get("full_name") or entity.get("application_id")
    first = ap.get("first_name") or (name.split()[0] if name else "The borrower")
    age = None
    dob = ap.get("dob")
    if isinstance(dob, date):
        age = (date.today() - dob).days // 365
    income = borrower.get("income") or {}
    emp_type = (income.get("employment_type") or "borrower").replace("_", "-")
    employer = (ap.get("verified_employer") or ap.get("stated_employer")
                or income.get("stated_employer") or "their employer")
    purpose = {"purchase": "purchasing", "refinance": "refinancing"}.get(
        (ap.get("loan_purpose") or "").lower(), "financing")
    occ = (ap.get("occupancy") or "primary residence").replace("_", " ")

    parts = [
        f"{first} is a"
        + (f" {age}-year-old" if age else "")
        + f" {emp_type} at {employer}, {purpose} a {occ}."
    ]
    verified = _f(income.get("verified_income_annual"))
    stated = _f(income.get("stated_income_annual"))
    if verified and stated and abs(verified - stated) / max(stated, 1) > 0.05:
        parts.append(f"Stated income ${stated:,.0f}/yr but verified at ${verified:,.0f}/yr.")
    elif verified:
        parts.append(f"Verified income ${verified:,.0f}/yr.")
    score = _f(entity.get("mid_credit_score"))
    band = (borrower.get("credit") or {}).get("band") or (income.get("credit_band"))
    if score:
        parts.append(f"Credit score {int(score)}"
                     + (f" ({str(band).replace('_', ' ')} band)." if band else "."))
    return {
        "name": name,
        "employer": employer,
        "age": age,
        "story": " ".join(parts),
    }


# ─────────────────────────────────────────────────────────────────────
# 3-5) Human-review actions
# ─────────────────────────────────────────────────────────────────────


async def _log_activity(conn, *, tenant_id, application_id, actor, action, target, detail) -> None:
    await conn.execute(
        """
        INSERT INTO activity_log (tenant_id, application_id, actor, action, target, detail)
        VALUES ($1,$2,$3,$4,$5,$6::jsonb)
        """,
        tenant_id, application_id, actor, action, target, json.dumps(detail or {}),
    )


async def _latest_decision(conn, application_id, decision_id, tenant_id):
    return await conn.fetchrow(
        """
        SELECT * FROM decision_outputs
        WHERE application_id = $1 AND decision_id = $2 AND tenant_id = $3
          AND version = (
              SELECT MAX(version) FROM decision_outputs d2
              WHERE d2.application_id = decision_outputs.application_id
                AND d2.decision_id = decision_outputs.decision_id
          )
        LIMIT 1
        """,
        application_id, decision_id, tenant_id,
    )


def _decision_view(row) -> dict:
    return {
        "application_id": row["application_id"],
        "decision_id": row["decision_id"],
        "outcome": row["outcome"],
        "human_action": row["human_action"],
        "human_reviewer": row["human_reviewer"],
        "human_override_reason": row["human_override_reason"],
        "acted_at": row["acted_at"].isoformat() if row["acted_at"] else None,
        "version": row["version"],
        "stale": bool(row["stale"]) if row["stale"] is not None else False,
    }


@router.post("/loans/{application_id}/decisions/{decision_id}/approve")
async def approve_decision(
    application_id: str, decision_id: str,
    payload: dict = Body(default={}), tenant_id: str = Depends(get_tenant_id),
) -> dict:
    _require_db()
    reviewer = (payload.get("reviewer") or "anonymous").strip()
    notes = payload.get("notes")
    pool = await _get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            cur = await _latest_decision(conn, application_id, decision_id, tenant_id)
            if cur is None:
                raise HTTPException(404, "Decision not found")
            now = datetime.now(timezone.utc)
            await conn.execute(
                "UPDATE decision_outputs SET human_action='approved', human_reviewer=$1, "
                "acted_at=$2 WHERE id=$3",
                reviewer, now, cur["id"],
            )
            await conn.execute(
                """
                INSERT INTO decision_timeline (application_id, decision_id, wave,
                    from_state, to_state, trigger, transition_at, tenant_id)
                VALUES ($1,$2,$3,$4,$5,'human_approve',$6,$7)
                """,
                application_id, decision_id, cur["wave"], cur["outcome"],
                cur["outcome"], now, cur["tenant_id"],
            )
            await _log_activity(conn, tenant_id=tenant_id, application_id=application_id,
                                actor=reviewer, action="decision_approved",
                                target=decision_id, detail={"notes": notes})
            updated = await _latest_decision(conn, application_id, decision_id, tenant_id)
    invalidate_agg_cache()  # portfolio aggregates changed
    return {"ok": True, "decision": _decision_view(updated)}


@router.post("/loans/{application_id}/decisions/{decision_id}/override")
async def override_decision(
    application_id: str, decision_id: str,
    payload: dict = Body(...), tenant_id: str = Depends(get_tenant_id),
    _perm: dict = Depends(require_permission("override_decision")),
) -> dict:
    _require_db()
    new_outcome = (payload.get("new_outcome") or "").strip()
    if new_outcome not in ("allow", "recommend", "escalate", "block"):
        raise HTTPException(422, "new_outcome must be allow|recommend|escalate|block")
    reviewer = (payload.get("reviewer") or "anonymous").strip()
    reason = payload.get("reason")
    pool = await _get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            cur = await _latest_decision(conn, application_id, decision_id, tenant_id)
            if cur is None:
                raise HTTPException(404, "Decision not found")
            now = datetime.now(timezone.utc)
            # decision_outputs has no override_outcome column — the final
            # outcome IS the overridden value (matches the workbench).
            await conn.execute(
                "UPDATE decision_outputs SET human_action='overridden', human_reviewer=$1, "
                "human_override_reason=$2, outcome=$3, acted_at=$4 WHERE id=$5",
                reviewer, reason, new_outcome, now, cur["id"],
            )
            await conn.execute(
                """
                INSERT INTO decision_timeline (application_id, decision_id, wave,
                    from_state, to_state, trigger, transition_at, tenant_id)
                VALUES ($1,$2,$3,$4,$5,'human_override',$6,$7)
                """,
                application_id, decision_id, cur["wave"], cur["outcome"],
                new_outcome, now, cur["tenant_id"],
            )
            await _log_activity(conn, tenant_id=tenant_id, application_id=application_id,
                                actor=reviewer, action="decision_overridden",
                                target=decision_id,
                                detail={"from": cur["outcome"], "to": new_outcome, "reason": reason})
            updated = await _latest_decision(conn, application_id, decision_id, tenant_id)
    invalidate_agg_cache()  # portfolio aggregates changed
    return {"ok": True, "decision": _decision_view(updated)}


@router.post("/loans/{application_id}/decisions/{decision_id}/revert")
async def revert_decision(
    application_id: str, decision_id: str,
    payload: dict = Body(default={}), tenant_id: str = Depends(get_tenant_id),
) -> dict:
    _require_db()
    reviewer = (payload.get("reviewer") or "anonymous").strip()
    reason = payload.get("reason")
    pool = await _get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            cur = await _latest_decision(conn, application_id, decision_id, tenant_id)
            if cur is None:
                raise HTTPException(404, "Decision not found")
            now = datetime.now(timezone.utc)
            # Original AI outcome = first human-action from_state, else current.
            ai_outcome = await conn.fetchval(
                """
                SELECT from_state FROM decision_timeline
                WHERE application_id=$1 AND decision_id=$2
                  AND trigger IN ('human_approve','human_override')
                ORDER BY transition_at ASC LIMIT 1
                """,
                application_id, decision_id,
            ) or cur["outcome"]
            new_version = int(cur["version"]) + 1
            await conn.execute(
                """
                INSERT INTO decision_outputs (
                    application_id, decision_id, wave, outcome, mode, risk_level,
                    boundary_matched, boundary_rule, context_snapshot, reasoning,
                    confidence, upstream_decisions, human_action, human_override_reason,
                    human_reviewer, decided_at, acted_at, sla_seconds, actual_seconds,
                    version, tenant_id, stale, rule_version_id)
                SELECT application_id, decision_id, wave, $1::varchar, mode, risk_level,
                    boundary_matched, boundary_rule, context_snapshot, reasoning,
                    confidence, upstream_decisions, NULL::varchar, NULL::text,
                    NULL::varchar, decided_at, NULL::timestamptz, sla_seconds,
                    actual_seconds, $2::integer, tenant_id, false, rule_version_id
                FROM decision_outputs WHERE id=$3
                """,
                ai_outcome, new_version, cur["id"],
            )
            await conn.execute(
                """
                INSERT INTO decision_timeline (application_id, decision_id, wave,
                    from_state, to_state, trigger, transition_at, waiting_on, tenant_id)
                VALUES ($1,$2,$3,$4,$5,'human_revert',$6,$7::jsonb,$8)
                """,
                application_id, decision_id, cur["wave"], cur["outcome"], cur["outcome"],
                now, json.dumps({"reverted_by": reviewer, "reason": reason}), cur["tenant_id"],
            )
            downstream = _downstream(decision_id)
            if downstream:
                await conn.execute(
                    """
                    UPDATE decision_outputs SET stale=true
                    WHERE application_id=$1 AND tenant_id=$2 AND decision_id = ANY($3)
                      AND version = (
                          SELECT MAX(version) FROM decision_outputs d2
                          WHERE d2.application_id=decision_outputs.application_id
                            AND d2.decision_id=decision_outputs.decision_id)
                    """,
                    application_id, tenant_id, downstream,
                )
            await _log_activity(conn, tenant_id=tenant_id, application_id=application_id,
                                actor=reviewer, action="decision_reverted",
                                target=decision_id,
                                detail={"reason": reason, "stale_downstream": downstream})
            updated = await _latest_decision(conn, application_id, decision_id, tenant_id)
    invalidate_agg_cache()  # portfolio aggregates changed
    return {"ok": True, "decision": _decision_view(updated), "stale_downstream": downstream}
