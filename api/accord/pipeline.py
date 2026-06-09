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
from datetime import date, datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Body, HTTPException, Query

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
    tenant_id: str = Query("default"),
) -> dict:
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        flags_by_app = await _decision_flags(conn, tenant_id)

        # KPIs over the full portfolio (independent of list filters).
        kpis = {"total": 0, "in_review": 0, "blocked": 0, "clear_to_close": 0, "halted": 0}
        for flags in flags_by_app.values():
            kpis["total"] += 1
            st = _derive_status(flags)
            if st in kpis:
                kpis[st] += 1

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
# 2) GET /api/accord/loans/{application_id}
# ─────────────────────────────────────────────────────────────────────


@router.get("/loans/{application_id}")
async def loan_detail(application_id: str, tenant_id: str = Query("default")) -> dict:
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
                   a.verified_employer, ap.full_name, ap.first_name, ap.dob
            FROM applications a
            LEFT JOIN applicants ap ON ap.applicant_id = a.applicant_id
            WHERE a.application_id = $1 LIMIT 1
            """,
            application_id,
        )
        decision_rows = await conn.fetch(
            """
            SELECT DISTINCT ON (decision_id)
                   decision_id, outcome, confidence, mode, wave,
                   human_action, human_reviewer, acted_at, human_override_reason,
                   boundary_matched, boundary_rule, context_snapshot, reasoning, stale
            FROM decision_outputs
            WHERE application_id = $1 AND tenant_id = $2
            ORDER BY decision_id, version DESC
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
        act_rows = await conn.fetch(
            """
            SELECT actor, action, target, detail, created_at
            FROM activity_log WHERE application_id = $1
            ORDER BY created_at DESC LIMIT 50
            """,
            application_id,
        )

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
        })

    lock_days = _lock_days(loan_terms)
    status = _derive_status({**flags, "n_decisions": len(decision_rows)})
    urgency = _derive_urgency(flags, lock_days)
    blocking = _blocking_persona({d: {"outcome": o} for d, o in decision_outcomes.items()})

    return {
        "application_id": application_id,
        "borrower": _borrower_block(ap, borrower, e, loan_terms),
        "metrics": {
            "loan_amount": _f(e.get("loan_amount")),
            "credit_score": int(e["mid_credit_score"]) if e.get("mid_credit_score") else None,
            "ltv": _pct(e.get("ltv")),
            "dti": _pct(e.get("dti_back")),
            "interest_rate": _pct(e.get("interest_rate")),
            "lock_days_remaining": lock_days,
        },
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
    payload: dict = Body(default={}), tenant_id: str = Query("default"),
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
    return {"ok": True, "decision": _decision_view(updated)}


@router.post("/loans/{application_id}/decisions/{decision_id}/override")
async def override_decision(
    application_id: str, decision_id: str,
    payload: dict = Body(...), tenant_id: str = Query("default"),
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
    return {"ok": True, "decision": _decision_view(updated)}


@router.post("/loans/{application_id}/decisions/{decision_id}/revert")
async def revert_decision(
    application_id: str, decision_id: str,
    payload: dict = Body(default={}), tenant_id: str = Query("default"),
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
                    version, tenant_id, stale)
                SELECT application_id, decision_id, wave, $1::varchar, mode, risk_level,
                    boundary_matched, boundary_rule, context_snapshot, reasoning,
                    confidence, upstream_decisions, NULL::varchar, NULL::text,
                    NULL::varchar, decided_at, NULL::timestamptz, sla_seconds,
                    actual_seconds, $2::integer, tenant_id, false
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
    return {"ok": True, "decision": _decision_view(updated), "stale_downstream": downstream}
