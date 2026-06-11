"""Accord auth endpoints + the JWT dependency used to protect every route.

  POST /api/accord/auth/login   (public)
  POST /api/accord/auth/signup  (public)
  GET  /api/accord/auth/me      (Bearer token)
  POST /api/accord/auth/logout  (client discards token)

`get_current_user` decodes the Bearer JWT (no DB hit) and is applied to all
other Accord routes via `get_tenant_id`, so the tenant always comes from the
token — never from the client.
"""

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException

from core.auth.models import LoginRequest, SignupRequest, ROLE_PERMISSIONS
from core.auth.service import AuthService, decode_token

router = APIRouter(prefix="/api/accord/auth", tags=["auth"])


async def _service() -> AuthService:
    # Lazy import keeps auth.py free of a circular dependency on pipeline.py.
    from api.accord.pipeline import _get_pool

    return AuthService(await _get_pool())


# ── Dependencies (used by every protected Accord route) ──────────────
async def get_current_user(authorization: str = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    token = authorization[len("Bearer "):]
    return decode_token(token)  # raises 401 if expired/invalid


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
        "permissions": ROLE_PERMISSIONS.get(user.get("role", "viewer"), []),
    }


@router.post("/logout")
async def logout() -> dict:
    # Stateless JWT — the client just discards the token.
    return {"message": "Logged out"}
