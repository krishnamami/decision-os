from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.connectors import (
    EventSink,
    MockCSVConnector,
    MockHTTPConnector,
    RecordedResponse,
)


SEED_ROOT = Path(__file__).resolve().parent


# ─────────────────────────────────────────────────────────────────────
# Scenario manifest. Each directory under seed_events/ holds:
#
#   events.csv           — push events (LeadReceived, ApplicationSubmitted,
#                          KYCCompleted, IncomeDeclared, PayrollReceived,
#                          PropertyAppraised, etc.) for MockCSVConnector.
#   bureau_responses.json — recorded bureau / fraud pulls for
#                          MockHTTPConnector. CreditPulled +
#                          FraudSignal events emitted on fetch().
#   entities.json        — direct context-store seed rows (Loan,
#                          ComplianceRecord, etc.) that aren't naturally
#                          modelled as events. Loaded via
#                          load_extra_entities().
#
# The expected outcome of replay is captured in the README per scenario;
# the smoke test in tests/ asserts against it.
# ─────────────────────────────────────────────────────────────────────


SCENARIOS: dict[str, dict[str, Any]] = {
    "happy_path": {
        "description": "Clean, auto-approvable lending application.",
        "expected_halt": False,
    },
    "fraud_block": {
        "description": (
            "Fraud screening flags a watchlist hit; "
            "fraud_block_stops_pipeline halts every downstream decision."
        ),
        "expected_halt": True,
        "expected_halt_reason": "fraud_block_stops_pipeline",
    },
    "contamination": {
        "description": (
            "Income verification confidence falls below the 0.75 "
            "contamination_guard threshold; dti_calculation must block."
        ),
        "expected_halt": False,
    },
    "compliance_block": {
        "description": (
            "Compliance check finds a fair-lending violation; "
            "closing_readiness must block via compliance_block_stops_closing."
        ),
        "expected_halt": False,
    },
    "fha": {
        "description": (
            "First-time homebuyer FHA loan with 96.5% LTV. Demonstrates "
            "the multi-agency policy chain — atomic_tool consults BOTH "
            "lender_overlay and FHA PolicyVersions for ltv_assessment, "
            "and the trace.policy_chain captures both consulted ids."
        ),
        "expected_halt": False,
    },
    "jumbo": {
        "description": (
            "High-net-worth jumbo purchase ($1.2M loan, 80% LTV). "
            "loan_type=jumbo → agency_chain=['lender_overlay'] only "
            "(no agency conforming guideline applies). Demonstrates "
            "the lender-only policy path."
        ),
        "expected_halt": False,
    },
    "va": {
        "description": (
            "VA loan — military applicant, 0% down (full VA "
            "entitlement), VA. loan_type=va → agency_chain="
            "['lender_overlay', 'va']. Until a VA PolicyVersion is "
            "seeded (STREAM E2 / D), the chain stays single-entry."
        ),
        "expected_halt": False,
    },
}


# ─────────────────────────────────────────────────────────────────────
# Connector + entity loaders
# ─────────────────────────────────────────────────────────────────────


def scenario_dir(scenario: str) -> Path:
    if scenario not in SCENARIOS:
        raise KeyError(f"unknown scenario {scenario!r}; expected one of {list(SCENARIOS)}")
    return SEED_ROOT / scenario


def csv_connector(scenario: str, sink: EventSink) -> MockCSVConnector:
    """Push connector pre-loaded with the scenario's events.csv."""
    path = scenario_dir(scenario) / "events.csv"
    return MockCSVConnector.from_path(f"seed:{scenario}", sink, path)


def http_connector(scenario: str, sink: EventSink) -> MockHTTPConnector:
    """Pull connector pre-loaded with the scenario's bureau_responses.json.

    Each fixture row is keyed by ``key`` so a query of {"key": "credit"}
    returns the credit_pulled payload, {"key": "fraud"} returns the
    fraud_signal payload, etc."""

    path = scenario_dir(scenario) / "bureau_responses.json"
    if not path.exists():
        return MockHTTPConnector(f"seed:{scenario}", sink, [])
    return MockHTTPConnector.from_path(f"seed:{scenario}", sink, path)


def load_extra_entities(scenario: str) -> list[dict[str, Any]]:
    """Read entities.json — direct context-store seeds not derivable from events."""
    path = scenario_dir(scenario) / "entities.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def expected_outcome(scenario: str) -> dict[str, Any]:
    return SCENARIOS[scenario]


__all__ = [
    "SCENARIOS",
    "SEED_ROOT",
    "csv_connector",
    "expected_outcome",
    "http_connector",
    "load_extra_entities",
    "scenario_dir",
]
