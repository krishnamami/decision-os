"""
Platform Studio — CN-PS.

Admin console for the two admin tiers:
  * super_admin (admin@accordlend.com) — sees ALL tenants, can create tenants.
  * admin — sees its OWN tenant only (read-only detail).
No other role may access these endpoints (403).

  GET  /platform-studio/tenants          list (all for super_admin, own for admin)
  GET  /platform-studio/tenants/{id}     read-only per-tenant summary
  POST /platform-studio/tenants          create a tenant + first admin (super_admin only)

NOTE: regulatory_rules / agency_guidelines are a GLOBAL catalogue (not
tenant-scoped), so the per-tenant summary surfaces them as shared counts; the
genuinely per-tenant figures are users, field-mapping rows, and loans.
"""
from __future__ import annotations

import json
import re
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.accord.auth import get_current_user
from api.accord.pipeline import _get_pool, _require_db, _J
from core.auth.security import hash_password
from core.db.tenant_pool import ACCORD_ADMIN, reset_tenant, set_tenant

router = APIRouter(prefix="/api/accord/platform-studio", tags=["accord-platform-studio"])

_STUDIO_ROLES = ("admin", "super_admin")


@asynccontextmanager
async def _admin_conn() -> AsyncIterator[Any]:
    """Acquire a DB connection under the accord_admin RLS sentinel. Platform
    Studio is a cross-tenant admin console — super_admin reads/writes ANY tenant,
    admin reads its own — so it must NOT be scoped to the caller's JWT tenant
    (which would make every write for a new tenant_id fail the RLS WITH CHECK and
    every cross-tenant read return zero rows). The app-layer role checks already
    enforce who may see/create what."""
    token = set_tenant(ACCORD_ADMIN)
    try:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            yield conn
    finally:
        reset_tenant(token)


def _require_studio(user: dict) -> None:
    if user.get("role") not in _STUDIO_ROLES:
        raise HTTPException(403, "Platform Studio requires admin or super_admin")


def _is_super(user: dict) -> bool:
    return user.get("role") == "super_admin"


def _products(v: Any) -> list:
    v = _J(v)
    return v if isinstance(v, list) else []


class CreateTenantBody(BaseModel):
    # Core identity
    tenant_id: str
    name: str
    contact_email: str
    # LOS configuration
    los_type: str = "encompass"            # encompass / bytepro / openclose / custom
    # Loan programs + geography + channels (stored in tenants.settings JSONB)
    programs: list[str] = ["CONVENTIONAL"]  # CONVENTIONAL/FHA/VA/JUMBO/NON_QM/USDA
    licensed_states: list[str] = []
    channels: list[str] = ["retail"]        # retail/wholesale/correspondent/consumer_direct
    # Plan + nav products (tenants.products is NOT NULL)
    plan: str = "starter"
    products: list[str] = ["pipeline"]
    # First admin user (optional at creation)
    admin_email: Optional[str] = None
    admin_name: Optional[str] = None
    admin_password: Optional[str] = None


_LIST_SQL = (
    "SELECT t.tenant_id, t.name, t.plan, t.is_active, t.products, t.created_at, "
    "(SELECT COUNT(*) FROM users u WHERE u.tenant_id = t.tenant_id) AS user_count "
    "FROM tenants t {where} ORDER BY t.tenant_id"
)


def _tenant_row(r) -> dict:
    return {
        "tenant_id": r["tenant_id"], "name": r["name"], "plan": r["plan"],
        "is_active": r["is_active"], "products": _products(r["products"]),
        "user_count": int(r["user_count"]),
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
    }


@router.get("/tenants")
async def list_tenants(user: dict = Depends(get_current_user)) -> dict:
    """super_admin: every tenant. admin: only its own tenant."""
    _require_studio(user)
    _require_db()
    async with _admin_conn() as conn:
        if _is_super(user):
            rows = await conn.fetch(_LIST_SQL.format(where=""))
        else:
            rows = await conn.fetch(_LIST_SQL.format(where="WHERE t.tenant_id = $1"),
                                    user["tenant_id"])
    return {
        "is_super_admin": _is_super(user),
        "own_tenant": user["tenant_id"],
        "tenants": [_tenant_row(r) for r in rows],
    }


@router.get("/tenants/{tenant_id}")
async def tenant_detail(tenant_id: str, user: dict = Depends(get_current_user)) -> dict:
    """Read-only per-tenant summary. admin may only view its own tenant."""
    _require_studio(user)
    _require_db()
    if not _is_super(user) and tenant_id != user["tenant_id"]:
        raise HTTPException(403, "You may only view your own tenant")
    async with _admin_conn() as conn:
        t = await conn.fetchrow(
            "SELECT tenant_id, name, plan, is_active, products, settings, created_at "
            "FROM tenants WHERE tenant_id = $1", tenant_id)
        if not t:
            raise HTTPException(404, "Tenant not found")
        users = await conn.fetch(
            "SELECT email, name, role FROM users WHERE tenant_id = $1 ORDER BY role, email",
            tenant_id)
        mapping_count = await conn.fetchval(
            "SELECT COUNT(*) FROM field_mapping_registry WHERE tenant_id = $1", tenant_id)
        loan_count = await conn.fetchval(
            "SELECT COUNT(*) FROM entity_states WHERE tenant_id = $1", tenant_id)
        # Global catalogue — shared across tenants, shown for context.
        reg = await conn.fetchval("SELECT COUNT(*) FROM regulatory_rules")
        agency = await conn.fetchval("SELECT COUNT(*) FROM agency_guidelines")
    s = _J(t["settings"]) if isinstance(_J(t["settings"]), dict) else {}
    return {
        "tenant_id": t["tenant_id"], "name": t["name"], "plan": t["plan"],
        "is_active": t["is_active"], "products": _products(t["products"]),
        "created_at": t["created_at"].isoformat() if t["created_at"] else None,
        # go-live config from settings JSONB (empty for pre-Section-1 tenants)
        "los_type": s.get("los_type"),
        "programs": s.get("programs", []),
        "licensed_states": s.get("licensed_states", []),
        "channels": s.get("channels", []),
        "contact_email": s.get("contact_email"),
        "user_count": len(users),
        "users": [{"email": u["email"], "name": u["name"], "role": u["role"]} for u in users],
        "mapping_count": int(mapping_count or 0),
        "loan_count": int(loan_count or 0),
        "rules": {"regulatory": int(reg or 0), "agency_guidelines": int(agency or 0),
                  "scope": "global_catalogue"},
    }


# Default active ruleset seeded at go-live. Uses the REAL tenant_rules shape
# (percents + engine keys), NOT fractions — tenant_rules is a versioned table
# (version + status required); dti.review_band is the senior-review zone.
_DEFAULT_RULES = {
    "credit": {"min_score": 620, "prime_threshold": 700},
    "dti": {"back_max": 50, "front_max": 43, "review_band": [43, 50]},
    "ltv": {"max": 97, "jumbo_max": 85, "no_mi_threshold": 80},
    "fraud": {"identity_min": 0.85, "watchlist_threshold": 0.25},
    "income": {"min_confidence": 0.75},
    "reserves": {"months_required": 2},
}


@router.post("/tenants")
async def create_tenant(body: CreateTenantBody, user: dict = Depends(get_current_user)) -> dict:
    """Create a tenant (+ optional first admin) and seed go-live config:
    LOS integration endpoint, an active tenant_rules v1, and default overlay
    rules. super_admin only."""
    if not _is_super(user):
        raise HTTPException(403, "Only super_admin may create tenants")
    _require_db()
    slug = re.sub(r"[^a-z0-9_]+", "-", body.tenant_id.lower()).strip("-")[:40]
    if not slug:
        raise HTTPException(400, "Invalid tenant_id")
    if not (body.name or "").strip():
        raise HTTPException(400, "Tenant name is required")
    if not (body.contact_email or "").strip():
        raise HTTPException(400, "Contact email is required")

    settings = {
        "los_type": body.los_type,
        "programs": body.programs,
        "licensed_states": body.licensed_states,
        "channels": body.channels,
        "contact_email": body.contact_email,
    }
    async with _admin_conn() as conn:
        async with conn.transaction():
            if await conn.fetchval("SELECT 1 FROM tenants WHERE tenant_id = $1", slug):
                raise HTTPException(409, "Tenant already exists")
            await conn.execute(
                "INSERT INTO tenants (tenant_id, name, plan, products, settings) "
                "VALUES ($1,$2,$3,$4::jsonb,$5::jsonb)",
                slug, body.name.strip(), body.plan or "starter",
                json.dumps(body.products or ["pipeline"]), json.dumps(settings))

            admin_created = None
            if body.admin_email and body.admin_password:
                if await conn.fetchval("SELECT 1 FROM users WHERE email = $1", body.admin_email):
                    raise HTTPException(409, "Admin email already registered")
                await conn.execute(
                    "INSERT INTO users (tenant_id, email, password_hash, name, role) "
                    "VALUES ($1,$2,$3,$4,'admin')",
                    slug, body.admin_email, hash_password(body.admin_password),
                    body.admin_name or body.admin_email.split("@")[0])
                admin_created = body.admin_email

            # LOS integration endpoint (real columns; UNIQUE(tenant_id, system_name)).
            await conn.execute(
                "INSERT INTO integration_endpoint "
                "(tenant_id, system_name, system_type, source_format, auth_type, is_active) "
                "VALUES ($1,$2,'los','json','api_key',true) "
                "ON CONFLICT (tenant_id, system_name) DO NOTHING",
                slug, body.los_type)

            # tenant_rules v1 active — versioned table needs version + status.
            # (Direct VALUES: the tenant is guaranteed new — a 409 fired above —
            # so no NOT EXISTS guard, which also avoids an $1 type ambiguity.)
            tr = await conn.fetchval(
                "INSERT INTO tenant_rules (tenant_id, version, status, rules, programs) "
                "VALUES ($1, 1, 'active', $2::jsonb, $3::jsonb) RETURNING rule_version_id",
                slug, json.dumps(_DEFAULT_RULES),
                json.dumps([p.lower() for p in body.programs]))

            # overlay_rules defaults (real columns: rule_type / overlay_value / direction).
            ov = await conn.execute(
                "INSERT INTO overlay_rules (tenant_id, rule_type, overlay_value, direction, is_active) "
                "VALUES ($1, 'uw_auto_approve_risk_max', 0.25, 'stricter', true), "
                "       ($1, 'uw_escalate_risk_min', 0.60, 'stricter', true)",
                slug)
    return {
        "ok": True,
        "tenant_id": slug,
        "admin_created": admin_created,
        "integration_endpoint_created": True,
        "tenant_rules_seeded": tr is not None,
        "overlay_rules_seeded": int(ov.split()[-1]) if ov else 0,
    }


__all__ = ["router"]
