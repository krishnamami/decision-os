from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Optional, Union

from pydantic import BaseModel, Field

from core.normalizer.models import DecisionMode, RiskLevel


# ─────────────────────────────────────────────────────────────────────
# Loader + validator for domains/<domain>/decisions.yaml.
#
# Until now both ContextBuilder and PolicyEvaluator have parsed
# decisions.yaml ad hoc — each accepts either a path or a pre-parsed
# dict, and neither validates anything beyond what its own code path
# happens to touch. That is fine while there is one domain pack and one
# author, but it means a malformed decisions.yaml fails at runtime in
# whichever layer trips on it first, with whatever error that layer
# happens to raise.
#
# This module is the single load+validate path. It:
#   - Loads YAML once (lazy import so tests don't require PyYAML).
#   - Validates the structural invariants that hard rules in PRD §5
#     depend on: every decision has an owner (no_decision_without_owner),
#     every depends_on references an existing decision, every mode and
#     risk_level is a recognised enum value, execution_order references
#     only known decisions and uses each at most once.
#   - Returns a typed `DecisionsSpec` that wraps the dict so callers can
#     keep using `spec["decisions"]` if they want, but get helpers and
#     pre-built indexes for free.
# ─────────────────────────────────────────────────────────────────────


# Hard rules listed in decisions.yaml `hard_rules:`. We don't validate
# the *enforcement* of each rule here (that's distributed across the
# runtime — policy engine, executor, atomic tool) but we do require the
# spec to opt into the named rules so a fresh domain pack can't silently
# skip a check.
KNOWN_HARD_RULES: frozenset[str] = frozenset({
    "no_decision_without_owner",
    "no_action_without_policy",
    "no_context_without_lineage",
    "no_agent_without_permissions",
    "no_execution_without_trace",
    "fraud_block_stops_pipeline",
    "compliance_block_stops_closing",
    "upstream_block_propagates_to_dependents",
})


class DecisionsConfigError(ValueError):
    """Raised when decisions.yaml fails structural or semantic validation."""


# ─────────────────────────────────────────────────────────────────────
# DecisionsSpec — typed view over decisions.yaml.
# ─────────────────────────────────────────────────────────────────────


class DecisionsSpec(BaseModel):
    """Validated, indexed view over decisions.yaml.

    Construct via `DecisionsSpec.from_path()` or `DecisionsSpec.validate()`.
    Holds the raw dict so callers that pass it through to existing
    constructors (ContextBuilder, PolicyEvaluator, DAGExecutor) keep
    working unchanged."""

    domain: str
    version: str
    raw: dict[str, Any]

    decisions: list[dict[str, Any]] = Field(default_factory=list)
    decision_index: dict[str, dict[str, Any]] = Field(default_factory=dict)
    hard_rules: list[str] = Field(default_factory=list)
    shared_data: list[str] = Field(default_factory=list)
    execution_waves: list[list[str]] = Field(default_factory=list)
    reflection: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_path(cls, path: Union[str, Path]) -> "DecisionsSpec":
        return cls.validate(_load_yaml(path))

    @classmethod
    def validate(cls, raw: dict[str, Any]) -> "DecisionsSpec":
        if not isinstance(raw, dict):
            raise DecisionsConfigError(
                f"decisions config must be a dict, got {type(raw).__name__}"
            )

        domain = raw.get("domain")
        if not domain or not isinstance(domain, str):
            raise DecisionsConfigError("decisions.domain is required (string)")
        version = str(raw.get("version", "0.0.0"))

        decisions = raw.get("decisions") or []
        if not isinstance(decisions, list) or not decisions:
            raise DecisionsConfigError("decisions list is empty")

        index: dict[str, dict[str, Any]] = {}
        for d in decisions:
            _validate_decision(d, index)
            index[d["id"]] = d

        # Cross-decision references resolved only after the index exists.
        for d in decisions:
            for dep in d.get("depends_on") or []:
                target = dep.get("decision") if isinstance(dep, dict) else None
                if target not in index:
                    raise DecisionsConfigError(
                        f"decision {d['id']!r} depends_on unknown decision {target!r}"
                    )

        hard_rules = list(raw.get("hard_rules") or [])
        for rule in hard_rules:
            if rule not in KNOWN_HARD_RULES:
                raise DecisionsConfigError(
                    f"unknown hard rule {rule!r}; expected one of {sorted(KNOWN_HARD_RULES)}"
                )

        waves = _validate_execution_order(raw.get("execution_order") or {}, index)

        return cls(
            domain=domain,
            version=version,
            raw=raw,
            decisions=list(decisions),
            decision_index=index,
            hard_rules=hard_rules,
            shared_data=list(raw.get("shared_data") or []),
            execution_waves=waves,
            reflection=dict(raw.get("reflection") or {}),
        )

    # ── Convenience helpers ───────────────────────────────────────────

    def decision(self, decision_id: str) -> dict[str, Any]:
        try:
            return self.decision_index[decision_id]
        except KeyError as err:
            raise KeyError(f"unknown decision_id: {decision_id!r}") from err

    def decision_ids(self) -> list[str]:
        return list(self.decision_index.keys())

    def upstream_for(self, decision_id: str) -> list[str]:
        spec = self.decision(decision_id)
        return [d["decision"] for d in spec.get("depends_on") or []]

    def to_dict(self) -> dict[str, Any]:
        """Return the original raw dict — what existing constructors expect."""
        return self.raw


# ─────────────────────────────────────────────────────────────────────
# Internal validation helpers
# ─────────────────────────────────────────────────────────────────────


_VALID_MODES: frozenset[str] = frozenset(m.value for m in DecisionMode)
_VALID_RISKS: frozenset[str] = frozenset(r.value for r in RiskLevel)


def _validate_decision(d: Any, seen_index: dict[str, dict[str, Any]]) -> None:
    if not isinstance(d, dict):
        raise DecisionsConfigError(f"decision entries must be dicts, got {type(d).__name__}")

    decision_id = d.get("id")
    if not decision_id or not isinstance(decision_id, str):
        raise DecisionsConfigError("decision.id is required (string)")
    if decision_id in seen_index:
        raise DecisionsConfigError(f"duplicate decision id {decision_id!r}")

    # no_decision_without_owner
    if not d.get("owner_team"):
        raise DecisionsConfigError(
            f"decision {decision_id!r} has no owner_team (no_decision_without_owner)"
        )

    mode = d.get("mode")
    if mode not in _VALID_MODES:
        raise DecisionsConfigError(
            f"decision {decision_id!r} has invalid mode {mode!r}; "
            f"expected one of {sorted(_VALID_MODES)}"
        )

    risk = d.get("risk_level")
    if risk not in _VALID_RISKS:
        raise DecisionsConfigError(
            f"decision {decision_id!r} has invalid risk_level {risk!r}; "
            f"expected one of {sorted(_VALID_RISKS)}"
        )

    if "boundary" in d and not isinstance(d["boundary"], dict):
        raise DecisionsConfigError(
            f"decision {decision_id!r} boundary must be a dict if present"
        )

    deps = d.get("depends_on") or []
    if not isinstance(deps, list):
        raise DecisionsConfigError(
            f"decision {decision_id!r} depends_on must be a list"
        )
    for dep in deps:
        if not isinstance(dep, dict) or "decision" not in dep:
            raise DecisionsConfigError(
                f"decision {decision_id!r} depends_on entry must be a dict with "
                f"a `decision:` key, got {dep!r}"
            )


def _validate_execution_order(
    order: dict[str, Any], index: dict[str, dict[str, Any]]
) -> list[list[str]]:
    waves: list[list[str]] = []

    parallel = order.get("parallel_independent") or []
    if parallel:
        if not isinstance(parallel, list):
            raise DecisionsConfigError("execution_order.parallel_independent must be a list")
        waves.append(list(parallel))

    seq = order.get("sequential_dependent") or []
    if not isinstance(seq, list):
        raise DecisionsConfigError("execution_order.sequential_dependent must be a list")

    for wave in seq:
        if isinstance(wave, str):
            waves.append([wave])
            continue
        if not isinstance(wave, list):
            raise DecisionsConfigError(
                "execution_order.sequential_dependent entries must be lists or strings"
            )
        waves.append(list(wave))

    seen: set[str] = set()
    for wave in waves:
        for decision_id in wave:
            if decision_id in seen:
                raise DecisionsConfigError(
                    f"decision {decision_id!r} appears in execution_order more than once"
                )
            seen.add(decision_id)
            if decision_id not in index:
                raise DecisionsConfigError(
                    f"execution_order references unknown decision {decision_id!r}"
                )

    # Independent decisions in the parallel wave must not depend on anything;
    # the wave model in DAGExecutor relies on this.
    if parallel:
        for decision_id in parallel:
            spec = index[decision_id]
            if spec.get("depends_on"):
                raise DecisionsConfigError(
                    f"decision {decision_id!r} appears in parallel_independent "
                    "but has depends_on; move it to sequential_dependent"
                )

    return waves


def _load_yaml(path: Union[str, Path]) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError as err:  # pragma: no cover
        raise ImportError(
            "PyYAML is required to load decisions.yaml; "
            "install with `pip install pyyaml`"
        ) from err
    p = Path(path)
    if not p.exists():
        raise DecisionsConfigError(f"decisions.yaml not found at {p}")
    with p.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise DecisionsConfigError(
            f"decisions.yaml must be a mapping at the top level, got {type(data).__name__}"
        )
    return data


# ─────────────────────────────────────────────────────────────────────
# Public convenience
# ─────────────────────────────────────────────────────────────────────


def load_spec(path: Union[str, Path]) -> DecisionsSpec:
    """Load + validate decisions.yaml from disk."""
    return DecisionsSpec.from_path(path)


def validate_spec(raw: dict[str, Any]) -> DecisionsSpec:
    """Validate an already-parsed dict (handy for tests with inline YAML)."""
    return DecisionsSpec.validate(raw)


__all__: Iterable[str] = (
    "DecisionsConfigError",
    "DecisionsSpec",
    "KNOWN_HARD_RULES",
    "load_spec",
    "validate_spec",
)
