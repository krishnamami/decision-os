"""Accord — data freshness dashboard backend.

Surfaces every data source Accord depends on and when it was last verified, from
REAL timestamps: data_source_status (OFAC, FHFA/FHA limits, agency guides, FRED),
the rule-validation suite, the document-extraction pipeline, and credit pulls.
Any timestamp that isn't recorded is returned as null — the UI shows
"Not recorded" rather than fabricating a date.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from api.accord.auth import get_current_user
from api.accord.pipeline import _get_pool, _require_db
from api.accord.validation import run_validation

router = APIRouter(prefix="/api/accord", tags=["accord-health"])

# Category + regulation + human refresh cadence per data_source_status.source_id.
_SOURCE_META: dict[str, dict] = {
    "ofac_sdn": {"category": "federal", "regulation": "31 CFR §1010.520", "next": "Daily at 02:00 UTC"},
    "conforming_limits": {"category": "agency", "regulation": "FHFA Conforming Loan Limits", "next": "Annually (FHFA)"},
    "fha_limits": {"category": "agency", "regulation": "HUD FHA Loan Limits", "next": "Annually (HUD)"},
    "fannie_selling_guide": {"category": "agency", "regulation": "Fannie Mae Selling Guide", "next": "Monitored for SEL announcements"},
    "freddie_guide": {"category": "agency", "regulation": "Freddie Mac Seller/Servicer Guide", "next": "Monitored for Bulletins"},
    "fha_handbook": {"category": "agency", "regulation": "FHA Handbook 4000.1", "next": "Monitored for Mortgagee Letters"},
    "va_handbook": {"category": "agency", "regulation": "VA Lender's Handbook", "next": "Monitored for Circulars"},
    "fred_rates": {"category": "external", "regulation": "Federal Reserve (FRED)", "next": "Weekly"},
}

# How long until a source of each category is considered stale (seconds).
_STALE_AFTER = {"federal": 36 * 3600, "agency": 45 * 86400, "external": 14 * 86400, "system": 7 * 86400}


def _iso(dt) -> str | None:
    return dt.isoformat() if dt is not None else None


def _freshness(category: str, last) -> str:
    if last is None:
        return "unknown"
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - last).total_seconds()
    return "current" if age <= _STALE_AFTER.get(category, 30 * 86400) else "stale"


@router.get("/data-health")
async def data_health(user: dict = Depends(get_current_user)) -> dict:
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT source_id, source_name, last_success, next_scheduled, record_count, status, error_message "
            "FROM data_source_status ORDER BY source_name")
        latest_doc = await conn.fetchval("SELECT MAX(received_at) FROM document_index")
        latest_credit = await conn.fetchval(
            "SELECT MAX(received_at) FROM document_index WHERE document_type='CREDIT_REPORT'")

    sources: list[dict] = []

    # 1) Tracked external/regulatory feeds (real download timestamps).
    for r in rows:
        meta = _SOURCE_META.get(r["source_id"], {"category": "external", "regulation": None, "next": None})
        cat = meta["category"]
        last = r["last_success"]
        ok = r["status"] in ("ok", None)
        sources.append({
            "source": r["source_name"],
            "category": cat,
            "last_updated": _iso(last),
            "next_refresh": meta.get("next") or "On schedule",
            "record_count": int(r["record_count"]) if r["record_count"] is not None else None,
            "status": _freshness(cat, last) if ok else "failing",
            "regulation": meta["regulation"],
            "error": None if ok else (r["error_message"] or "download failed"),
        })

    # 2) Rule validation test suite (run live against the tenant's active rules).
    try:
        rep = await run_validation(user["tenant_id"])
        ran_at, total, passed, failed = rep.get("run_at"), rep.get("total_tests"), rep.get("passed"), rep.get("failed", 0)
    except Exception:
        ran_at = total = passed = failed = None
    sources.append({
        "source": "Rule validation test suite",
        "category": "system",
        "last_updated": ran_at,
        "next_refresh": "On every rule change",
        "tests_total": total,
        "tests_passed": passed,
        "tests_failed": failed,
        "status": "unknown" if total is None else ("failing" if (failed or 0) > 0 else "current"),
        "regulation": None,
    })

    # 3) Document extraction pipeline (latest indexed document).
    sources.append({
        "source": "Document extraction pipeline (EDMS)",
        "category": "system",
        "last_updated": _iso(latest_doc),
        "next_refresh": "On document upload",
        "status": _freshness("system", latest_doc),
        "regulation": None,
    })

    # 4) Credit bureau (latest credit pull).
    sources.append({
        "source": "Credit bureau (Experian)",
        "category": "external",
        "last_updated": _iso(latest_credit),
        "next_refresh": "Per loan request",
        "status": _freshness("external", latest_credit),
        "regulation": "FCRA 15 U.S.C. §1681",
    })

    return {"sources": sources, "as_of": datetime.now(timezone.utc).isoformat()}
