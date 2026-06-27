"""Accord — data freshness dashboard backend.

Surfaces every data source Accord depends on and when it was last verified, from
REAL timestamps: data_source_status (OFAC, FHFA/FHA limits, agency guides, FRED),
the rule-validation suite, the document-extraction pipeline, and credit pulls.
Any timestamp that isn't recorded is returned as null — the UI shows
"Not recorded" rather than fabricating a date.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from api.accord.auth import get_current_user
from api.accord.pipeline import DATABASE_URL, _get_pool, _require_db
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
    """Fallback freshness for sources with no published schedule (system feeds)."""
    if last is None:
        return "unknown"
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - last).total_seconds()
    return "current" if age <= _STALE_AFTER.get(category, 30 * 86400) else "stale"


def _scheduled_freshness(ok: bool, last, next_scheduled) -> str:
    """A tracked feed is stale only when it has missed a FULL refresh cycle past
    its published schedule — so an annual source isn't 'stale' five months in, and
    a daily source isn't 'stale' the moment it ticks a few hours past 02:00."""
    if not ok:
        return "failing"
    if last is None:
        return "unknown"
    now = datetime.now(timezone.utc)
    if next_scheduled is None:
        return "current"
    ns = next_scheduled if next_scheduled.tzinfo else next_scheduled.replace(tzinfo=timezone.utc)
    if now <= ns:
        return "current"
    ls = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
    cycle = (ns - ls).total_seconds()          # the source's own refresh interval
    overdue = (now - ns).total_seconds()
    return "stale" if cycle <= 0 or overdue > cycle else "current"


@router.get("/health/deep")
async def health_deep(user: dict = Depends(get_current_user)) -> dict:
    """HA-B — DEEP readiness probe (per-component), distinct from the cheap public
    liveness probe ``GET /api/accord/health`` ({"status":"ok"}) the ALB target group
    hits every 30s. This one measures real dependencies, so it is authenticated and
    used by ops / uptime monitors, NOT by the ALB (a DB round-trip per 30s liveness
    check would be an anti-pattern). Read-only — decision-path-inert.

    Returns: db_latency_ms, sqs_configured, s3_configured, test_count,
    last_decision_timestamp. ``status`` is degraded if the DB is unreachable.
    """
    components: dict = {}

    # 1) DB — measure a real round-trip latency.
    db_latency_ms = None
    db_ok = False
    if DATABASE_URL:
        try:
            pool = await _get_pool()
            t0 = time.perf_counter()
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            db_latency_ms = round((time.perf_counter() - t0) * 1000, 1)
            db_ok = True
        except Exception as exc:  # noqa: BLE001 — health must never raise
            components["db_error"] = str(exc)[:200]
    components["db_latency_ms"] = db_latency_ms

    # 2) SQS — configured? (graceful no-AWS: false locally, IN-A pattern)
    try:
        from core.infra.sqs_consumer import SQSConsumer
        components["sqs_configured"] = SQSConsumer().is_configured()
    except Exception:  # noqa: BLE001
        components["sqs_configured"] = False

    # 3) S3 — bucket env present? (graceful no-AWS: RA-P0-A pattern)
    components["s3_configured"] = bool(os.environ.get("S3_BUCKET"))

    # 4) Test count (manifest of automated coverage; null if unrecorded).
    components["test_count"] = _read_test_count()

    # 5) Last decision produced (the HA-E / IN-C watermark).
    last_decision = None
    if db_ok:
        try:
            pool = await _get_pool()
            async with pool.acquire() as conn:
                last_decision = await conn.fetchval(
                    "SELECT MAX(created_at) FROM decision_outputs")
        except Exception:  # noqa: BLE001
            last_decision = None
    components["last_decision_timestamp"] = _iso(last_decision)

    status = "ok" if db_ok else "degraded"
    return {"status": status, **components,
            "timestamp": datetime.now(timezone.utc).isoformat()}


def _read_test_count() -> int | None:
    """Best-effort automated-test count from a recorded manifest; null if absent.
    Never shells out to pytest (a health probe must be cheap + side-effect-free)."""
    path = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "ha", "test_count.txt")
    try:
        with open(os.path.abspath(path), encoding="utf-8") as fh:
            return int(fh.read().strip())
    except Exception:  # noqa: BLE001
        return None


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
            "status": _scheduled_freshness(ok, last, r["next_scheduled"]),
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
