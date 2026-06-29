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
from api.accord.onboarding import router as onboarding_router
from api.accord.examiner import router as examiner_router
from api.accord.health import router as health_router
from api.accord.workbench import router as workbench_router
from api.accord.conditions import router as conditions_router
from api.accord.trace import router as trace_router
from api.accord.intelligence import router as intelligence_router
from api.accord.qa import router as qa_router
from api.accord.infra import router as infra_router
from api.accord.model_risk import router as model_risk_router
from api.accord.dashboard import router as dashboard_router

# Every Accord router — api.main includes them all.
# auth_router is public for /login + /signup; all other routers enforce a JWT.
routers = [auth_router, router, mirofish_router, analytics_router, audit_router, rules_router, documents_router, validation_router, comparison_router, onboarding_router, examiner_router, health_router, workbench_router, conditions_router, trace_router, intelligence_router, qa_router, infra_router, model_risk_router, dashboard_router]

__all__ = ["router", "mirofish_router", "analytics_router", "audit_router", "auth_router", "rules_router", "documents_router", "validation_router", "comparison_router", "onboarding_router", "examiner_router", "health_router", "workbench_router", "conditions_router", "trace_router", "intelligence_router", "qa_router", "infra_router", "model_risk_router", "dashboard_router", "routers"]
