"""MiroFish — prebuilt what-if scenarios for the PolicySimulator.

Three families:
  • policy      — move a boundary threshold (DTI cap, credit floor, LTV cap)
  • stress      — shock the loan DATA (rates up, home prices down) and let
                  PITI / DTI / LTV recompute
  • regulatory  — change a product rule (the conforming limit) so loans
                  reclassify between conforming and jumbo

Each is a :class:`SimulationScenario`; ``overrides`` is the parameter map
the simulator interprets. ``_stress`` is the reserved key for data shocks.
"""

from __future__ import annotations

from typing import Optional

from core.mirofish.models import SimulationScenario


PREBUILT_SCENARIOS: list[SimulationScenario] = [
    SimulationScenario(
        name="DTI threshold: 43% → 36%",
        type="policy",
        description=(
            "Tighten DTI to Fannie preferred limit. Self-employed and "
            "high-obligation borrowers most affected."
        ),
        overrides={"dti_calculation": {"back_dti_max": 36}},
    ),
    SimulationScenario(
        name="DTI threshold: 43% → 50%",
        type="policy",
        description="Expand DTI for FHA-style eligibility with compensating factors.",
        overrides={"dti_calculation": {"back_dti_max": 50}},
    ),
    SimulationScenario(
        name="Credit floor: 620 → 680",
        type="policy",
        description="Raise minimum credit for conventional. Near-prime borrowers affected.",
        overrides={"credit_assessment": {"min_score": 680}},
    ),
    SimulationScenario(
        name="LTV cap: 97% → 90%",
        type="policy",
        description="Tighten LTV. High-LTV and FHA borrowers need more down payment.",
        overrides={"ltv_assessment": {"max_ltv": 90}},
    ),
    SimulationScenario(
        name="Rate shock +100bps",
        type="stress",
        description="Interest rates increase 1%. Recalculate PITI and DTI for all loans.",
        overrides={"_stress": {"rate_delta": 1.0}},
    ),
    SimulationScenario(
        name="Rate shock +200bps",
        type="stress",
        description="Interest rates increase 2%. Significant DTI impact on borderline loans.",
        overrides={"_stress": {"rate_delta": 2.0}},
    ),
    SimulationScenario(
        name="Rate shock +300bps",
        type="stress",
        description="Severe rate increase. Tests portfolio resilience under extreme conditions.",
        overrides={"_stress": {"rate_delta": 3.0}},
    ),
    SimulationScenario(
        name="Home price decline -10%",
        type="stress",
        description="Property values drop 10%. LTV recalculated for all loans.",
        overrides={"_stress": {"price_delta_pct": -10}},
    ),
    SimulationScenario(
        name="Home price decline -20%",
        type="stress",
        description="Severe price correction. Tests collateral risk.",
        overrides={"_stress": {"price_delta_pct": -20}},
    ),
    SimulationScenario(
        name="Combined: +200bps and -10% prices",
        type="stress",
        description="Rate shock with price decline. Worst-case stress test.",
        overrides={"_stress": {"rate_delta": 2.0, "price_delta_pct": -10}},
    ),
    SimulationScenario(
        name="Conforming limit: $766K → $800K",
        type="regulatory",
        description="FHFA raises conforming limit. Jumbo loans may reclassify.",
        overrides={"product_eligibility": {"conforming_limit": 800000}},
    ),
    SimulationScenario(
        name="Conforming limit: $766K → $700K",
        type="regulatory",
        description="FHFA lowers conforming limit. More loans become jumbo.",
        overrides={"product_eligibility": {"conforming_limit": 700000}},
    ),
]


def get_scenario(name: str) -> Optional[SimulationScenario]:
    """Return a fresh copy of the prebuilt scenario with this name (so a
    caller can set ``tenant_id`` without mutating the shared template)."""
    for s in PREBUILT_SCENARIOS:
        if s.name == name:
            return s.model_copy(deep=True)
    return None


def list_scenarios() -> list[dict]:
    """Lightweight catalog for a picker UI: name · type · description."""
    return [
        {"name": s.name, "type": s.type, "description": s.description}
        for s in PREBUILT_SCENARIOS
    ]


__all__ = ["PREBUILT_SCENARIOS", "get_scenario", "list_scenarios"]
