"""Accord — the product API the React frontend calls.

Read/write endpoints over the EDMS PostgreSQL tables. Mounted by
``api.main`` alongside the existing Decision OS routes.
"""

from api.accord.pipeline import router
from api.accord.mirofish_routes import router as mirofish_router
from api.accord.analytics import router as analytics_router
from api.accord.audit import router as audit_router

# Every Accord router — api.main includes them all.
routers = [router, mirofish_router, analytics_router, audit_router]

__all__ = ["router", "mirofish_router", "analytics_router", "audit_router", "routers"]
