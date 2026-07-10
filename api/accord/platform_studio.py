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
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.accord.auth import get_current_user
from api.accord.pipeline import _get_pool, _require_db, _J
from core.auth.security import hash_password

router = APIRouter(prefix="/api/accord/platform-studio", tags=["accord-platform-studio"])

_STUDIO_ROLES = ("admin", "super_admin")


def _require_studio(user: dict) -> None:
    if user.get("role") not in _STUDIO_ROLES:
        raise HTTPException(403, "Platform Studio requires admin or super_admin")


def _is_super(user: dict) -> bool:
    return user.get("role") == "super_admin"


def _products(v: Any) -> list:
    v = _J(v)
    return v if isinstance(v, list) else []


class CreateTenantBody(BaseModel):
    tenant_id: str
    name: str
    plan: str = "starter"
    products: list[str] = ["pipeline"]
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
    pool = await _get_pool()
    async with pool.acquire() as conn:
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
    pool = await _get_pool()
    async with pool.acquire() as conn:
        t = await conn.fetchrow(
            "SELECT tenant_id, name, plan, is_active, products, created_at "
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
    return {
        "tenant_id": t["tenant_id"], "name": t["name"], "plan": t["plan"],
        "is_active": t["is_active"], "products": _products(t["products"]),
        "created_at": t["created_at"].isoformat() if t["created_at"] else None,
        "user_count": len(users),
        "users": [{"email": u["email"], "name": u["name"], "role": u["role"]} for u in users],
        "mapping_count": int(mapping_count or 0),
        "loan_count": int(loan_count or 0),
        "rules": {"regulatory": int(reg or 0), "agency_guidelines": int(agency or 0),
                  "scope": "global_catalogue"},
    }


@router.post("/tenants")
async def create_tenant(body: CreateTenantBody, user: dict = Depends(get_current_user)) -> dict:
    """Create a tenant (+ optional first admin). super_admin only."""
    if not _is_super(user):
        raise HTTPException(403, "Only super_admin may create tenants")
    _require_db()
    slug = re.sub(r"[^a-z0-9_]+", "-", body.tenant_id.lower()).strip("-")[:40]
    if not slug:
        raise HTTPException(400, "Invalid tenant_id")
    if not (body.name or "").strip():
        raise HTTPException(400, "Tenant name is required")
    pool = await _get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            if await conn.fetchval("SELECT 1 FROM tenants WHERE tenant_id = $1", slug):
                raise HTTPException(409, "Tenant already exists")
            await conn.execute(
                "INSERT INTO tenants (tenant_id, name, plan, products) VALUES ($1,$2,$3,$4::jsonb)",
                slug, body.name.strip(), body.plan or "starter",
                json.dumps(body.products or ["pipeline"]))
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
    return {"ok": True, "tenant_id": slug, "admin_created": admin_created}


__all__ = ["router"]
