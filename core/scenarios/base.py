"""SC-B — canonical Scenario object (data definitions, read-only).

A `Scenario` is the single source of truth for a test/demo loan: its identity,
loan inputs, the expected KEY-decision outcome (what the eval verifies), the
overall underwriting outcome, and provenance (which thresholds it breaches, who
to notify, the demo narrative). It REPLACES the two loose dicts that lived in
`scripts/evaluate_meridian_scenarios.py` (EXPECTED_OUTCOMES + SCENARIO_NOTES).

RULE 11: every instance carries `data_source` + `missing_inputs`; a field that
cannot be populated from the live data (e.g. SC03's NULL dti) is recorded in
`missing_inputs`, never fabricated.

Pure data + helpers — no DB access, no engine calls, nothing written.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ScenarioCondition:
    """A threshold breach computed from the loan's value vs the applied threshold."""
    rule_name: str
    borrower_value: float
    threshold_value: float
    breach: float
    direction: str          # 'above' (ceiling breached) | 'below' (floor breached)
    citation: str
    layer: str              # 'federal' | 'agency' | 'overlay'


@dataclass
class Scenario:
    """Canonical scenario object — identity + inputs + expected outcomes + provenance."""
    # Identity
    scenario_id: str
    application_id: str
    tenant_id: str
    title: str
    intent: str             # what this scenario is designed to exercise

    # Expected outcomes. expected_key_decision/expected_outcome come from the live
    # EXPECTED_OUTCOMES dict (the per-persona decision the eval checks for 16/16).
    # underwriting_outcome is the OVERALL loan outcome (the underwriting_decision
    # aggregate) — kept distinct because they legitimately differ (e.g. SC16's key
    # decision closing_readiness=escalate while the loan overall = recommend).
    expected_key_decision: str
    expected_outcome: str
    underwriting_outcome: Optional[str] = None

    # Loan inputs (from entity_states — real values, never placeholders)
    mid_credit_score: Optional[float] = None
    ltv: Optional[float] = None
    dti_back: Optional[float] = None
    loan_amount: Optional[float] = None
    qualifying_monthly: Optional[float] = None
    piti_monthly: Optional[float] = None
    total_liquid_assets: Optional[float] = None
    monthly_obligations: Optional[float] = None

    # Provenance
    conditions: list = field(default_factory=list)   # list[ScenarioCondition]
    evidence_ids: list = field(default_factory=list)  # fact_node ids (linkage deferred)
    notify_role: Optional[str] = None                 # derived routing hint (see data_source)
    explanation: Optional[str] = None                 # demo narrative (SCENARIO_NOTES or derived)

    # RULE 11
    data_source: str = ("entity_states (inputs) + EXPECTED_OUTCOMES (key decision) + "
                        "underwriting_decision.upstream_decisions (aggregate); notify_role "
                        "is a derived routing hint; evidence_ids linkage deferred to a later slice")
    missing_inputs: list = field(default_factory=list)

    def reserve_months(self) -> Optional[float]:
        """Liquid reserves expressed in months of PITI (0.0 when assets are 0)."""
        if self.total_liquid_assets is not None and self.piti_monthly:
            return round(self.total_liquid_assets / self.piti_monthly, 1)
        return None

    def is_multi_block(self) -> bool:
        """True when more than one threshold gate is breached."""
        return len(self.conditions) > 1

    def demo_talking_points(self) -> list:
        points: list[str] = []
        head = self.underwriting_outcome or self.expected_outcome
        key = f"key: {self.expected_key_decision}={self.expected_outcome}"
        if head in ("block", "deny"):
            points.append(f"Loan BLOCKED ({key})")
            for c in self.conditions:
                points.append(
                    f"{c.rule_name}: borrower {c.borrower_value} vs threshold "
                    f"{c.threshold_value} ({c.layer} — {c.citation})")
        elif head == "escalate":
            points.append(f"ESCALATED to manual review ({key})")
        else:
            points.append(f"Clean approval — overall recommend ({key})")
        rm = self.reserve_months()
        if rm is not None:
            points.append(f"Reserves: {rm} months PITI")
        if self.missing_inputs:
            points.append(f"Data gap: {'; '.join(self.missing_inputs)}")
        return points


__all__ = ["Scenario", "ScenarioCondition"]
