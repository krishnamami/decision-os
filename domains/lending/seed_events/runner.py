from __future__ import annotations

from typing import Any, Optional

from core.context_store.base import Lineage
from core.execution.dag_executor import ExecutionResult
from core.normalizer.models import BaseEvent

from . import (
    SCENARIOS,
    csv_connector,
    expected_outcome,
    http_connector,
    load_extra_entities,
    scenario_dir,
)


# ─────────────────────────────────────────────────────────────────────
# Scenario runner.
#
# Replays a seed_events scenario against a Platform end-to-end:
#   1. Push events.csv through MockCSVConnector.listen()
#   2. Pull credit + fraud responses through MockHTTPConnector.fetch()
#   3. Seed any extra entities (Loan, ComplianceRecord) directly into
#      the SHARED context scope so the personas see them
#   4. Run the DAG executor for the scenario's application_id
#
# Returns the ExecutionResult plus the resolved application_id and the
# list of canonical events that were emitted, so test code can assert
# end-to-end without having to dig through the trace writer.
# ─────────────────────────────────────────────────────────────────────


# scenario → application_id present in the fixtures. Kept here rather
# than in __init__.py so the manifest stays focused on metadata.
APPLICATION_IDS: dict[str, str] = {
    "happy_path":      "app_happy",
    "fraud_block":     "app_fraud",
    "contamination":   "app_contam",
    "compliance_block": "app_comp",
    "fha":             "app_fha",
    "jumbo":           "app_jumbo",
    "va":              "app_va",
    "employment_continuity": "app_continuity",
}


class ScenarioRunResult:
    """What `run_scenario` returns. Plain class so tests can poke at it
    without importing pydantic models."""

    def __init__(
        self,
        scenario: str,
        application_id: str,
        events: list[BaseEvent],
        execution: ExecutionResult,
    ):
        self.scenario = scenario
        self.application_id = application_id
        self.events = events
        self.execution = execution

    @property
    def expected(self) -> dict[str, Any]:
        return expected_outcome(self.scenario)


async def run_scenario(
    platform: Any,
    scenario: str,
    *,
    application_id: Optional[str] = None,
) -> ScenarioRunResult:
    """Replay one scenario end-to-end against the supplied Platform.

    Platform must already have the lending personas registered (via
    domains.lending.personas.register_with_platform). All inputs are
    pushed through the canonical normalize_event → connector → sink
    pipeline so the run exercises the same path live deployments take."""

    if scenario not in SCENARIOS:
        raise KeyError(f"unknown scenario {scenario!r}")
    application_id = application_id or APPLICATION_IDS[scenario]

    emitted: list[BaseEvent] = []

    async def _capture(event: BaseEvent) -> None:
        emitted.append(event)
        await platform.sink(event)

    # 1. Push events.csv
    csv = csv_connector(scenario, _capture)
    await csv.listen()

    # 2. Pull credit + fraud (one fetch per recorded response key)
    pull_dir = scenario_dir(scenario)
    if (pull_dir / "bureau_responses.json").exists():
        http = http_connector(scenario, _capture)
        await http.fetch({"key": "credit"})
        await http.fetch({"key": "fraud"})

    # 3. Seed direct entities (Loan, ComplianceRecord)
    for row in load_extra_entities(scenario):
        await platform.store.set(
            row["entity_type"],
            row["entity_id"],
            row["value"],
            Lineage(
                decision_id=None,
                agent="seed_events.runner",
                written_by="seed_events.runner",
                notes=f"scenario={scenario}",
            ),
        )

    # 4. Run the DAG
    execution = await platform.executor().run_application(
        application_id, platform.entity_resolver
    )

    return ScenarioRunResult(
        scenario=scenario,
        application_id=application_id,
        events=emitted,
        execution=execution,
    )


__all__ = ["APPLICATION_IDS", "ScenarioRunResult", "run_scenario"]
