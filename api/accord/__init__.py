"""Accord — the product API the React frontend calls.

Read/write endpoints over the EDMS PostgreSQL tables. Mounted by
``api.main`` alongside the existing Decision OS routes.
"""

from api.accord.pipeline import router
from api.accord.mirofish_routes import router as mirofish_router
from api.accord.analytics import router as analytics_router
from api.accord.audit import router as audit_router
from api.accord.auth import router as auth_router
from api.accord.rules import router as rules_router
from api.accord.documents import router as documents_router
from api.accord.validation import router as validation_router
from api.accord.comparison import router as comparison_router

# Every Accord router — api.main includes them all.
# auth_router is public for /login + /signup; all other routers enforce a JWT.
routers = [auth_router, router, mirofish_router, analytics_router, audit_router, rules_router, documents_router, validation_router, comparison_router]

__all__ = ["router", "mirofish_router", "analytics_router", "audit_router", "auth_router", "rules_router", "documents_router", "validation_router", "comparison_router", "routers"]
