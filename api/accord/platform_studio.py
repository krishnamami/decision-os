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
import logging
import os
import re
from contextlib import asynccontextmanager
from difflib import SequenceMatcher
from typing import Any, AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.accord.auth import get_current_user
from api.accord.pipeline import _get_pool, _require_db, _J
from core.auth.security import hash_password
from core.db.tenant_pool import ACCORD_ADMIN, reset_tenant, set_tenant

logger = logging.getLogger(__name__)
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


# ── Field Mapper (CN-PS Section 2): NLP source->canonical mapping ──
_VALID_TRANSFORMS = {"direct", "enum", "split", "compute", "encrypt", "date", "discard"}
_FIELD_MAP_MODEL = "claude-sonnet-4-6"   # matches _ANTHROPIC_DEFAULT_MODEL


async def _canonical_vocabulary(conn) -> dict:
    """Global canonical schema (entity -> [columns]) — NOT tenant-scoped."""
    rows = await conn.fetch(
        "SELECT DISTINCT canonical_entity, canonical_column FROM field_mapping_registry "
        "ORDER BY canonical_entity, canonical_column")
    ent: dict[str, list] = {}
    for r in rows:
        ent.setdefault(r["canonical_entity"], []).append(r["canonical_column"])
    return ent


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _parse_source_fields(input_type: str, raw: str) -> list[str]:
    raw = (raw or "").strip()
    if not raw:
        return []
    fields: list[str] = []
    if input_type == "json_keys":
        try:
            obj = json.loads(raw)
            if isinstance(obj, list) and obj and isinstance(obj[0], dict):
                obj = obj[0]
            if isinstance(obj, dict):
                fields = [str(k) for k in obj.keys()]
        except Exception:  # noqa: BLE001
            fields = []
    elif input_type == "csv_headers":
        first = raw.splitlines()[0] if raw.splitlines() else ""
        fields = [h.strip().strip('"').strip("'") for h in first.split(",")]
    else:  # paste — split on comma or newline
        fields = [p.strip() for p in re.split(r"[,\n]", raw)]
    # dedup (preserve order), drop empties, cap to keep the prompt bounded
    seen, out = set(), []
    for f in fields:
        if f and f not in seen:
            seen.add(f)
            out.append(f)
    return out[:150]


def _heuristic_suggest(source_fields: list[str], ent: dict) -> list[dict]:
    flat = [(e, c) for e, cols in ent.items() for c in cols]
    out = []
    for sf in source_fields:
        n = _norm(sf)
        best, best_r = None, 0.0
        for e, c in flat:
            r = SequenceMatcher(None, n, _norm(c)).ratio()
            if r > best_r:
                best_r, best = r, (e, c)
        if best and best_r > 0.7:
            out.append({"source_field": sf, "canonical_entity": best[0], "canonical_column": best[1],
                        "confidence": round(best_r, 2), "reasoning": f"Fuzzy name match ({best_r:.0%})"})
        else:
            out.append({"source_field": sf, "canonical_entity": None, "canonical_column": None,
                        "confidence": 0.3, "reasoning": "No close canonical match"})
    return out


def _validate_suggestions(raw: Any, source_fields: list[str], ent: dict) -> list[dict]:
    valid = {(e, c) for e, cols in ent.items() for c in cols}
    by_src: dict[str, dict] = {}
    for it in (raw or []):
        if not isinstance(it, dict) or not it.get("source_field"):
            continue
        e, c = it.get("canonical_entity"), it.get("canonical_column")
        if not (e and c and (e, c) in valid):     # drop hallucinated / null targets
            e, c = None, None
        try:
            conf = max(0.0, min(1.0, float(it.get("confidence", 0))))
        except (TypeError, ValueError):
            conf = 0.0
        by_src[it["source_field"]] = {
            "source_field": it["source_field"], "canonical_entity": e, "canonical_column": c,
            "confidence": round(conf, 2), "reasoning": str(it.get("reasoning") or "")[:200]}
    return [by_src.get(sf, {"source_field": sf, "canonical_entity": None, "canonical_column": None,
                            "confidence": 0.0, "reasoning": "No suggestion returned"})
            for sf in source_fields]


async def _claude_suggest(source_fields: list[str], ent: dict) -> Optional[list]:
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return None
    try:
        from anthropic import AsyncAnthropic
        canonical_list = [f"{e}.{c}" for e, cols in ent.items() for c in cols]
        user_msg = (
            f"Map these {len(source_fields)} source fields to canonical mortgage fields.\n\n"
            f"SOURCE FIELDS:\n{json.dumps(source_fields)}\n\n"
            f"CANONICAL SCHEMA (entity.column):\n{json.dumps(canonical_list)}\n\n"
            "Return a JSON array, one object per source field:\n"
            '[{"source_field":"...","canonical_entity":"entity or null",'
            '"canonical_column":"column or null","confidence":0.0-1.0,"reasoning":"brief"}]\n\n'
            "Rules:\n- If confident (>0.85): map it.\n- If unsure: entity+column null, confidence<0.5.\n"
            "- Never guess wildly — null beats wrong.\n"
            "- Patterns: loan_amt->loan.loan_amount, fico->credit.mid_score, dti->qualification.back_end_dti.")
        resp = await AsyncAnthropic().messages.create(
            model=_FIELD_MAP_MODEL, max_tokens=8192,
            system="You are a mortgage data field mapper. Map source LOS field names to canonical "
                   "mortgage data fields. Return JSON only, no prose.",
            messages=[{"role": "user", "content": user_msg}])
        text = "".join(getattr(b, "text", "") for b in resp.content)
        i, j = text.find("["), text.rfind("]")
        return json.loads(text[i:j + 1]) if i >= 0 and j > i else None
    except Exception as exc:  # noqa: BLE001 — degrade to heuristic
        logger.warning("[field-mapper] Claude failed, using heuristic: %s", str(exc)[:160])
        return None


class SuggestBody(BaseModel):
    source_system: str = "encompass"
    input_type: str = "paste"          # csv_headers | json_keys | paste
    raw_input: str


class SaveMapping(BaseModel):
    source_field: str
    canonical_entity: str
    canonical_column: str
    transform_rule: str = "direct"
    notes: Optional[str] = None


class SaveBody(BaseModel):
    source_system: str = "encompass"
    mappings: list[SaveMapping]


def _studio_tenant_guard(user: dict, tenant_id: str) -> None:
    _require_studio(user)
    _require_db()
    if not _is_super(user) and tenant_id != user["tenant_id"]:
        raise HTTPException(403, "You may only manage your own tenant")


@router.get("/tenants/{tenant_id}/field-mapper/canonical")
async def field_mapper_canonical(tenant_id: str, user: dict = Depends(get_current_user)) -> dict:
    """The global canonical schema (entity -> columns) for the edit dropdowns."""
    _studio_tenant_guard(user, tenant_id)
    async with _admin_conn() as conn:
        ent = await _canonical_vocabulary(conn)
    return {"entities": ent, "total": sum(len(v) for v in ent.values())}


@router.post("/tenants/{tenant_id}/field-mapper/suggest")
async def field_mapper_suggest(tenant_id: str, body: SuggestBody,
                               user: dict = Depends(get_current_user)) -> dict:
    """Claude-suggested source->canonical mappings; heuristic fallback if no key."""
    _studio_tenant_guard(user, tenant_id)
    source_fields = _parse_source_fields(body.input_type, body.raw_input)
    if not source_fields:
        raise HTTPException(400, "No source fields found in the input")
    async with _admin_conn() as conn:
        ent = await _canonical_vocabulary(conn)
    claude = await _claude_suggest(source_fields, ent)
    if claude is not None:
        return {"suggestions": _validate_suggestions(claude, source_fields, ent),
                "method": "claude", "model": _FIELD_MAP_MODEL}
    return {"suggestions": _heuristic_suggest(source_fields, ent),
            "method": "heuristic", "model": "fuzzy_match"}


@router.post("/tenants/{tenant_id}/field-mapper/save")
async def field_mapper_save(tenant_id: str, body: SaveBody,
                            user: dict = Depends(get_current_user)) -> dict:
    """Upsert confirmed mappings into field_mapping_registry (under accord_admin)."""
    _studio_tenant_guard(user, tenant_id)
    rows = [m for m in body.mappings if m.source_field and m.canonical_entity and m.canonical_column]
    if not rows:
        raise HTTPException(400, "No valid mappings to save")
    async with _admin_conn() as conn:
        async with conn.transaction():
            for m in rows:
                tr = m.transform_rule if m.transform_rule in _VALID_TRANSFORMS else "direct"
                await conn.execute(
                    "INSERT INTO field_mapping_registry (tenant_id, source_system, source_field, "
                    "canonical_entity, canonical_column, transform_rule, is_active, notes) "
                    "VALUES ($1,$2,$3,$4,$5,$6,true,$7) "
                    "ON CONFLICT (tenant_id, source_system, source_field) DO UPDATE SET "
                    "canonical_entity=EXCLUDED.canonical_entity, canonical_column=EXCLUDED.canonical_column, "
                    "transform_rule=EXCLUDED.transform_rule, is_active=true, notes=EXCLUDED.notes",
                    tenant_id, body.source_system, m.source_field, m.canonical_entity,
                    m.canonical_column, tr, m.notes)
    return {"saved": len(rows), "skipped": len(body.mappings) - len(rows)}


__all__ = ["router"]
