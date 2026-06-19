"""Accord auth endpoints + the JWT dependency used to protect every route.

  POST /api/accord/auth/login   (public)
  POST /api/accord/auth/signup  (public)
  GET  /api/accord/auth/me      (Bearer token)
  POST /api/accord/auth/logout  (client discards token)

`get_current_user` decodes the Bearer JWT (no DB hit) and is applied to all
other Accord routes via `get_tenant_id`, so the tenant always comes from the
token — never from the client.
"""

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException

from core.auth.models import LoginRequest, SignupRequest, ROLE_PERMISSIONS
from core.auth.service import AuthService, decode_token

router = APIRouter(prefix="/api/accord/auth", tags=["auth"])


async def _service() -> AuthService:
    # Lazy import keeps auth.py free of a circular dependency on pipeline.py.
    from api.accord.pipeline import _get_pool

    return AuthService(await _get_pool())


# ── Action-level RBAC (Phase 1: app-layer only, no DB enforcement) ───
# Cache of role_name -> permission flags from the `role_permissions` table.
# The table is a tiny static seed, so we load it once and reuse it; this keeps
# get_current_user (the universal auth gate) off the DB hot path.
_ACTION_PERMS_CACHE: Optional[dict] = None


async def _load_action_permissions() -> dict:
    """role_name -> {permission: bool}. Fail-safe: on any DB error returns {}
    WITHOUT caching, so a later request retries and auth itself never breaks.
    Gated endpoints then fail closed (403) until the table is reachable."""
    global _ACTION_PERMS_CACHE
    if _ACTION_PERMS_CACHE is not None:
        return _ACTION_PERMS_CACHE
    try:
        from api.accord.pipeline import _get_pool

        pool = await _get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT role_name, permissions FROM role_permissions")
        _ACTION_PERMS_CACHE = {
            r["role_name"]: (
                json.loads(r["permissions"]) if isinstance(r["permissions"], str)
                else dict(r["permissions"])
            )
            for r in rows
        }
        return _ACTION_PERMS_CACHE
    except Exception:
        return {}  # DB unavailable / table missing — never break the auth gate


# ── Dependencies (used by every protected Accord route) ──────────────
async def get_current_user(authorization: str = Header(None)) -> dict:
    """Decode the Bearer JWT and attach the role's action permissions.

    PHASE 1: loads `permissions` for app-level RBAC. Does NOT set
    app.tenant_id and does NOT enforce RLS — both are deferred to Phase 2.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    token = authorization[len("Bearer "):]
    user = decode_token(token)  # raises 401 if expired/invalid
    perms = await _load_action_permissions()
    user["permissions"] = perms.get(user.get("role", "read_only"), {})
    return user


def require_permission(permission: str):
    """FastAPI dependency for action-level checks. App-layer enforcement —
    works immediately, independent of DB RLS.

    Usage:
        @router.post("/.../override")
        async def override(user: dict = Depends(require_permission("override_decision"))):
            ...
    """
    async def check(user: dict = Depends(get_current_user)) -> dict:
        if not user.get("permissions", {}).get(permission):
            raise HTTPException(403, f"Permission denied: {permission}")
        return user

    return check


async def get_tenant_id(user: dict = Depends(get_current_user)) -> str:
    """The tenant the request is scoped to — straight from the JWT."""
    return user["tenant_id"]


# ── Endpoints ────────────────────────────────────────────────────────
@router.post("/login")
async def login(body: LoginRequest) -> dict:
    svc = await _service()
    return await svc.login(body.email, body.password)


@router.post("/signup")
async def signup(body: SignupRequest) -> dict:
    svc = await _service()
    return await svc.signup(body.tenant_name, body.email, body.password, body.name)


@router.get("/me")
async def me(user: dict = Depends(get_current_user)) -> dict:
    svc = await _service()
    u = await svc.get_user(user["user_id"])
    t = await svc.get_tenant(user["tenant_id"])
    return {
        "user": u.model_dump(mode="json"),
        "tenant": t.model_dump(mode="json"),
        # Product/nav access (unchanged — frontend nav guards read this).
        "permissions": ROLE_PERMISSIONS.get(user.get("role", "viewer"), []),
        # Action-level RBAC flags from the role_permissions table (Phase 1).
        "action_permissions": user.get("permissions", {}),
    }


@router.post("/logout")
async def logout() -> dict:
    # Stateless JWT — the client just discards the token.
    return {"message": "Logged out"}
