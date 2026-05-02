from __future__ import annotations

from typing import Any, Optional

from core.decision_agents import DecisionAgent

from .approval_routing import WorkflowRoutingAgent
from .base import LendingPersona, OfflineReasoning
from .closing_readiness import ClosingAgent
from .compliance_check import ComplianceAgent
from .credit_assessment import CreditRiskAgent
from .dti_calculation import DTICalculationAgent
from .fraud_screening import FraudDetectionAgent
from .income_verification import IncomeVerificationAgent
from .lead_scoring import LeadQualificationAgent
from .ltv_assessment import LTVAssessmentAgent
from .product_eligibility import ProductEligibilityAgent
from .rate_pricing import PricingAgent
from .underwriting_decision import SeniorUnderwritingAgent


# decision_id → persona class. Registered alongside decisions.yaml so a
# missing persona is loud.
LENDING_PERSONA_CLASSES: dict[str, type[LendingPersona]] = {
    "lead_scoring":          LeadQualificationAgent,
    "income_verification":   IncomeVerificationAgent,
    "credit_assessment":     CreditRiskAgent,
    "fraud_screening":       FraudDetectionAgent,
    "compliance_check":      ComplianceAgent,
    "dti_calculation":       DTICalculationAgent,
    "ltv_assessment":        LTVAssessmentAgent,
    "product_eligibility":   ProductEligibilityAgent,
    "rate_pricing":          PricingAgent,
    "underwriting_decision": SeniorUnderwritingAgent,
    "approval_routing":      WorkflowRoutingAgent,
    "closing_readiness":     ClosingAgent,
}


def build_lending_personas(
    *,
    use_anthropic: bool = False,
    anthropic_client: Optional[Any] = None,
) -> dict[str, DecisionAgent]:
    """Instantiate every persona for the lending domain.

    use_anthropic flips the LLM path on for every persona at once. When
    off (default), each persona reasons through its deterministic
    `_compute_offline()` path so the runtime works end-to-end without
    an API key — exactly what the seed-events replays and the scheduled
    real-backend verification need."""

    return {
        decision_id: cls(
            use_anthropic=use_anthropic,
            anthropic_client=anthropic_client,
        )
        for decision_id, cls in LENDING_PERSONA_CLASSES.items()
    }


def register_with_platform(platform: Any, **kwargs: Any) -> None:
    """Register every persona with a Platform instance.

    `platform` is api.deps.Platform; we accept Any to avoid a hard
    import dependency from the personas package on the API package."""

    for agent in build_lending_personas(**kwargs).values():
        platform.register_agent(agent)


__all__ = [
    "LENDING_PERSONA_CLASSES",
    "LendingPersona",
    "OfflineReasoning",
    "build_lending_personas",
    "register_with_platform",
    # individual agents
    "ClosingAgent",
    "ComplianceAgent",
    "CreditRiskAgent",
    "DTICalculationAgent",
    "FraudDetectionAgent",
    "IncomeVerificationAgent",
    "LeadQualificationAgent",
    "LTVAssessmentAgent",
    "PricingAgent",
    "ProductEligibilityAgent",
    "SeniorUnderwritingAgent",
    "WorkflowRoutingAgent",
]
