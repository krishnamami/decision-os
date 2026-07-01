"""Per-request tenant context for Postgres RLS enforcement.

Every DB statement must run with app.tenant_id set, transaction-scoped, via
set_config(..., is_local=true) — the parameterised, injection-safe equivalent
of SET LOCAL. TenantPool wraps any asyncpg pool so that BOTH pool.acquire() and
direct pool.fetch()/execute() establish that context before any statement runs.

Fail-closed: the default tenant is '' (empty). With RLS enforced, an unset/empty
app.tenant_id matches no row, so a forgotten context yields ZERO rows — never a
cross-tenant leak. Platform/migration code sets ACCORD_ADMIN to bypass tenant
scoping via the policies' 'accord_admin' sentinel.
"""
from __future__ import annotations

import contextvars
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

ACCORD_ADMIN = "accord_admin"

_current_tenant: contextvars.ContextVar[str] = contextvars.ContextVar(
    "app_tenant_id", default="")


def set_tenant(tenant_id: Optional[str]) -> "contextvars.Token[str]":
    """Set the tenant for the current async context. Pass ACCORD_ADMIN for
    platform/cross-tenant work. Returns a token for reset_tenant()."""
    return _current_tenant.set(tenant_id or "")


def reset_tenant(token: "contextvars.Token[str]") -> None:
    _current_tenant.reset(token)


def current_tenant() -> str:
    return _current_tenant.get()


async def _apply_tenant(conn: Any) -> None:
    # is_local=true  ==  SET LOCAL: scoped to THIS transaction only, never the
    # pooled connection. Parameter binding = no SQL injection via tenant id.
    await conn.execute(
        "SELECT set_config('app.tenant_id', $1, true)", _current_tenant.get())


@asynccontextmanager
async def _tenant_acquire(pool: Any) -> AsyncIterator[Any]:
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _apply_tenant(conn)
            yield conn


class TenantPool:
    """Drop-in wrapper over an asyncpg pool. Enforces tenant context on every
    access path. Existing `async with pool.acquire() as conn:` sites work
    unchanged; direct pool.fetch()/execute() are routed through a scoped acquire."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    # Same call shape as asyncpg — supports `async with pool.acquire() as conn:`
    def acquire(self, *args: Any, **kwargs: Any):
        return _tenant_acquire(self._pool)

    async def execute(self, *a: Any, **k: Any) -> Any:
        async with _tenant_acquire(self._pool) as conn:
            return await conn.execute(*a, **k)

    async def executemany(self, *a: Any, **k: Any) -> Any:
        async with _tenant_acquire(self._pool) as conn:
            return await conn.executemany(*a, **k)

    async def fetch(self, *a: Any, **k: Any) -> Any:
        async with _tenant_acquire(self._pool) as conn:
            return await conn.fetch(*a, **k)

    async def fetchrow(self, *a: Any, **k: Any) -> Any:
        async with _tenant_acquire(self._pool) as conn:
            return await conn.fetchrow(*a, **k)

    async def fetchval(self, *a: Any, **k: Any) -> Any:
        async with _tenant_acquire(self._pool) as conn:
            return await conn.fetchval(*a, **k)

    def __getattr__(self, name: str) -> Any:
        # Delegate everything else (close, terminate, get_size, etc.).
        return getattr(self._pool, name)
