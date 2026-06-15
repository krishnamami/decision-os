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
from api.accord.auth import get_current_user, get_tenant_id
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

        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    return _pool


def _require_db() -> None:
    if not DATABASE_URL:
        raise HTTPException(503, "DATABASE_URL not configured")


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
            SELECT ar.application_id, ar.message, ar.priority, u.name AS from_name
            FROM attention_requests ar LEFT JOIN users u ON u.user_id = ar.from_user_id
            WHERE ar.to_user_id = $1 AND ar.status = 'open'
            """,
            UUID(str(target_uid)),
        )
        attn = {r["application_id"]: dict(r) for r in attn_rows}
        comm_rows = await conn.fetch(
            """
            SELECT DISTINCT ON (application_id) application_id, items_requested, due_date, created_at, recipient_email, responded_at
            FROM communications
            WHERE tenant_id = $1 AND application_id = ANY($2) AND direction = 'outbound'
            ORDER BY application_id, created_at DESC
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
            "attention_request": ({"from": a["from_name"], "message": a["message"], "priority": a["priority"]} if a else None),
            "senior_review": app in sr_apps,
        }
        if st == "pending_borrower":
            c = comms.get(app)
            if c:
                card["requesting"] = _jsonb(c["items_requested"])
                card["sent"] = c["created_at"].isoformat() if c.get("created_at") else None
                card["due_date"] = c["due_date"].isoformat() if c.get("due_date") else None
                card["recipient_email"] = c.get("recipient_email")
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
            "attention_request": {"from": a["from_name"], "message": a["message"], "priority": a["priority"]},
        })

    active.sort(key=lambda c: (0 if c["urgency"] == "urgent" else 1, -(c["days_in_queue"] or 0)))
    return {
        "user": {"name": urow["name"], "role": urow["role"]},
        "counts": {"active": len(active), "pending": len(pending), "decided": len(decided)},
        "active": active,
        "pending": pending,
        "decided": decided,
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
    action: str  # approve | deny | escalate
    note: Optional[str] = None


@router.post("/pipeline/decide")
async def decide(body: DecideBody, user: dict = Depends(get_current_user)) -> dict:
    """Finalize a loan: approve/deny move it to the decided/denied lifecycle;
    escalate hands it to a Senior UW. Read-only roles can't decide."""
    if user.get("role") in ("viewer", "compliance"):
        raise HTTPException(403, "Read-only role cannot decide")
    _require_db()
    tid, uid = user["tenant_id"], UUID(str(user["user_id"]))
    app = body.application_id
    pool = await _get_pool()
    async with pool.acquire() as conn:
        if body.action == "approve":
            await conn.execute("UPDATE loan_assignments SET status='decided', completed_at=NOW() WHERE application_id=$1 AND tenant_id=$2 AND assigned_to=$3", app, tid, uid)
            await conn.execute("UPDATE entity_states SET loan_status='decided' WHERE application_id=$1 AND tenant_id=$2", app, tid)
            title = "Loan approved — advanced to the next stage"
        elif body.action == "deny":
            await conn.execute("UPDATE loan_assignments SET status='denied', completed_at=NOW() WHERE application_id=$1 AND tenant_id=$2 AND assigned_to=$3", app, tid, uid)
            await conn.execute("UPDATE entity_states SET loan_status='denied' WHERE application_id=$1 AND tenant_id=$2", app, tid)
            title = "Loan denied — adverse-action notice queued"
        elif body.action == "escalate":
            senior = await conn.fetchval(
                "SELECT user_id FROM users WHERE tenant_id=$1 AND role='senior_uw' AND is_active=true ORDER BY name LIMIT 1", tid,
            )
            if senior:
                await conn.execute("UPDATE loan_assignments SET previous_assignee=assigned_to, assigned_to=$1, status='active', stage='decide', assigned_at=NOW() WHERE application_id=$2 AND tenant_id=$3", senior, app, tid)
                await conn.execute("UPDATE entity_states SET assigned_to=$1, current_stage='decide' WHERE application_id=$2 AND tenant_id=$3", senior, app, tid)
                await conn.execute("INSERT INTO notifications (tenant_id,user_id,type,title,application_id) VALUES ($1,$2,'escalation',$3,$4)", tid, senior, "Loan escalated to you for senior review", app)
            title = "Escalated to Senior UW"
        else:
            raise HTTPException(400, f"Unknown action: {body.action}")
        try:
            await conn.execute(
                "INSERT INTO activity_log (tenant_id, application_id, actor, action, target, detail) VALUES ($1,$2,$3,$4,$5,$6::jsonb)",
                tid, app, user.get("email", "user"), body.action, app, json.dumps({"note": body.note or ""}),
            )
        except Exception:  # noqa: BLE001 — best-effort
            pass
        await conn.execute("INSERT INTO notifications (tenant_id,user_id,type,title,application_id) VALUES ($1,$2,'decision_made',$3,$4)", tid, uid, title, app)
    return {"ok": True, "title": title}


ALLOWED_ROLES = ["admin", "manager", "processor", "underwriter", "senior_uw", "closer", "compliance", "viewer"]


class InviteBody(BaseModel):
    email: str
    name: str
    role: str = "processor"


class RoleBody(BaseModel):
    role: str


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
async def invite_user(body: InviteBody, user: dict = Depends(get_current_user)) -> dict:
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
async def change_role(user_id: str, body: RoleBody, user: dict = Depends(get_current_user)) -> dict:
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
async def deactivate_user(user_id: str, user: dict = Depends(get_current_user)) -> dict:
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
            "SELECT comm_id FROM communications WHERE application_id=$1 AND tenant_id=$2 AND direction='outbound' "
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


@router.get("/loans/{application_id}")
async def loan_detail(application_id: str, tenant_id: str = Depends(get_tenant_id)) -> dict:
    _require_db()
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

    return {
        "application_id": application_id,
        "borrower": _borrower_block(ap, borrower, e, loan_terms),
        "borrower_email": ap.get("email"),
        "loan_number": ap.get("loan_number"),
        "metrics": metrics_out,
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
