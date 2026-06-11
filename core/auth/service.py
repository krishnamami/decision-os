"""Accord auth service — JWT issue/verify + user/tenant lookups over PG."""

import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

import jwt
from fastapi import HTTPException

try:  # ensure .env is loaded before reading JWT_SECRET (idempotent)
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from core.auth.models import Tenant, User
from core.auth.security import hash_password, verify_password

SECRET_KEY = os.getenv("JWT_SECRET", "accord-secret-change-in-prod")
ALGORITHM = "HS256"
TOKEN_EXPIRY_HOURS = 24


def create_token(user_id: Any, tenant_id: str, role: str, email: str) -> str:
    """JWT payload: user_id, tenant_id, role, email, iat, exp."""
    now = datetime.now(timezone.utc)
    payload = {
        "user_id": str(user_id),
        "tenant_id": tenant_id,
        "role": role,
        "email": email,
        "iat": now,
        "exp": now + timedelta(hours=TOKEN_EXPIRY_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode + verify a JWT. Raises 401 if expired or invalid."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid or expired token")


def _as_uuid(v: Any) -> UUID:
    return v if isinstance(v, UUID) else UUID(str(v))


def _jsonb(v: Any, default: Any) -> Any:
    if v is None:
        return default
    return json.loads(v) if isinstance(v, str) else v


def _user(row: Any) -> User:
    return User(
        user_id=row["user_id"],
        tenant_id=row["tenant_id"],
        email=row["email"],
        name=row["name"],
        role=row["role"],
        is_active=row["is_active"],
        last_login=row["last_login"],
    )


def _tenant(row: Any) -> Tenant:
    return Tenant(
        tenant_id=row["tenant_id"],
        name=row["name"],
        plan=row["plan"],
        products=_jsonb(row["products"], ["pipeline"]),
        settings=_jsonb(row["settings"], {}),
        logo_url=row["logo_url"],
    )


class AuthService:
    def __init__(self, db: Any):
        self.db = db  # asyncpg pool

    def create_token(self, user_id: Any, tenant_id: str, role: str, email: str) -> str:
        return create_token(user_id, tenant_id, role, email)

    def verify_token(self, token: str) -> dict:
        return decode_token(token)

    async def get_user(self, user_id: Any) -> User:
        async with self.db.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", _as_uuid(user_id))
        if row is None:
            raise HTTPException(404, "User not found")
        return _user(row)

    async def get_tenant(self, tenant_id: str) -> Tenant:
        async with self.db.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM tenants WHERE tenant_id = $1", tenant_id)
        if row is None:
            raise HTTPException(404, "Tenant not found")
        return _tenant(row)

    async def login(self, email: str, password: str) -> dict:
        async with self.db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM users WHERE email = $1 AND is_active = true", email,
            )
            if row is None or not verify_password(password, row["password_hash"]):
                raise HTTPException(401, "Invalid email or password")
            await conn.execute("UPDATE users SET last_login = NOW() WHERE user_id = $1", row["user_id"])
            tenant_row = await conn.fetchrow("SELECT * FROM tenants WHERE tenant_id = $1", row["tenant_id"])

        user = _user(row)
        token = self.create_token(user.user_id, user.tenant_id, user.role, user.email)
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": user.model_dump(mode="json"),
            "tenant": _tenant(tenant_row).model_dump(mode="json"),
        }

    async def signup(self, tenant_name: str, email: str, password: str, name: str) -> dict:
        slug = re.sub(r"[^a-z0-9]+", "-", tenant_name.lower()).strip("-")[:40] or f"t-{uuid.uuid4().hex[:8]}"
        async with self.db.acquire() as conn:
            if await conn.fetchval("SELECT 1 FROM users WHERE email = $1", email):
                raise HTTPException(409, "Email already registered")
            if await conn.fetchval("SELECT 1 FROM tenants WHERE tenant_id = $1", slug):
                slug = f"{slug}-{uuid.uuid4().hex[:6]}"
            await conn.execute(
                "INSERT INTO tenants (tenant_id, name, plan, products) VALUES ($1, $2, 'starter', '[\"pipeline\"]')",
                slug, tenant_name,
            )
            row = await conn.fetchrow(
                "INSERT INTO users (tenant_id, email, password_hash, name, role) "
                "VALUES ($1, $2, $3, $4, 'admin') RETURNING *",
                slug, email, hash_password(password), name,
            )
            tenant_row = await conn.fetchrow("SELECT * FROM tenants WHERE tenant_id = $1", slug)

        user = _user(row)
        token = self.create_token(user.user_id, user.tenant_id, user.role, user.email)
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": user.model_dump(mode="json"),
            "tenant": _tenant(tenant_row).model_dump(mode="json"),
        }
