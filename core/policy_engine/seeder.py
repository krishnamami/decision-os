from __future__ import annotations

from datetime import datetime
from typing import Any

from core.policy_engine.loader import DecisionsSpec
from core.policy_engine.store import (
    PolicyRecord,
    PolicyStore,
    PolicyVersionRecord,
)


# ─────────────────────────────────────────────────────────────────────
# Seed lender_overlay policies from decisions.yaml.
#
# Migration plan from CONTEXT.md (Session 9, STREAM C):
#   Option 1 — keep decisions.yaml as the lender_overlay seed for v1.
#   Real agency connectors (Freddie / Fannie / FHA / VA / USDA) will
#   later create new PolicyVersions with their own agency tags. Once
#   real overlays land, decisions.yaml is deprecated (Option 3).
#
# For each decision in the spec we write:
#   - one Policy with policy_id = f"lender_overlay::{decision_id}",
#                   agency      = "lender_overlay",
#                   decision_id = decision_id,
#                   product/state scope = [] (all)
#   - one PolicyVersion at version_number=1, valid_from=epoch,
#                   valid_to=null (currently in force),
#                   boundary    = the decision's `boundary` block,
#                   contamination_guard = the decision's
#                                         `contamination_guard` block,
#                   hard_rules_subscribed = spec.hard_rules.
#
# Idempotent: PolicyStore.put_* skips writes when the value blob is
# byte-identical to the active row. So booting twice does not churn
# the supersession chain.
#
# Why valid_from = 1970-01-01 instead of datetime.min: Postgres
# TIMESTAMPTZ accepts datetime.min but the value reads strangely in
# UIs and logs. 1970-01-01 is the universal "epoch" — recognisable,
# semantically clear, and well inside any sensible time bounds.
# ─────────────────────────────────────────────────────────────────────


SEED_AGENCY = "lender_overlay"
SEED_VALID_FROM = datetime(1970, 1, 1)
SEED_INGESTED_BY = "core.policy_engine.seeder"


def policy_id_for(decision_id: str, *, agency: str = SEED_AGENCY) -> str:
    return f"{agency}::{decision_id}"


def policy_version_id_for(
    decision_id: str, *, agency: str = SEED_AGENCY, version_number: int = 1
) -> str:
    return f"{policy_id_for(decision_id, agency=agency)}::v{version_number}"


async def seed_policies_from_yaml(
    spec: DecisionsSpec, policy_store: PolicyStore
) -> tuple[list[str], list[str]]:
    """Walk DecisionsSpec, write one Policy + one PolicyVersion per
    decision under agency=lender_overlay.

    Returns (policy_ids, policy_version_ids) — stable across re-runs.

    Idempotency: if a Policy / PolicyVersion already exists, the
    existing `created_at` / `ingested_at` are preserved so re-seeding
    produces byte-identical bytes and triggers no supersession.
    PolicyStore.put_* short-circuits when bytes match the active row.
    """

    now = datetime.utcnow()
    written_policies: list[str] = []
    written_versions: list[str] = []

    for decision in spec.decisions:
        decision_id = decision["id"]
        owner_team = decision.get("owner_team", "unknown")
        boundary = decision.get("boundary") or {}
        contamination_guard = decision.get("contamination_guard")

        policy_id = policy_id_for(decision_id)
        existing_policy = await policy_store.get_policy(policy_id)
        policy = PolicyRecord(
            policy_id=policy_id,
            name=f"{decision.get('name', decision_id)} — lender overlay",
            description=(decision.get("description") or "").strip(),
            owner_team=owner_team,
            agency=SEED_AGENCY,
            decision_id=decision_id,
            product_scope=[],
            state_scope=[],
            created_at=existing_policy.created_at if existing_policy else now,
        )
        await policy_store.put_policy(policy, written_by=SEED_INGESTED_BY)
        written_policies.append(policy.policy_id)

        version_id = policy_version_id_for(decision_id)
        existing_version = await policy_store.get_policy_version(version_id)
        version = PolicyVersionRecord(
            policy_version_id=version_id,
            policy_id=policy.policy_id,
            version_number=1,
            valid_from=SEED_VALID_FROM,
            valid_to=None,
            source_url=None,
            source_revision=f"decisions.yaml v{spec.version}",
            boundary=_clone_dict(boundary),
            contamination_guard=_clone_dict(contamination_guard) if contamination_guard else None,
            hard_rules_subscribed=list(spec.hard_rules),
            ingested_at=existing_version.ingested_at if existing_version else now,
            ingested_by=SEED_INGESTED_BY,
        )
        await policy_store.put_policy_version(
            version, written_by=SEED_INGESTED_BY
        )
        written_versions.append(version.policy_version_id)

    return written_policies, written_versions


def _clone_dict(value: Any) -> dict[str, Any]:
    """Shallow-copy a dict so the seeded record doesn't share refs with
    the spec's raw dict (the spec is reused across calls; pickling its
    internals would couple replay state to the loader)."""
    if not isinstance(value, dict):
        return {}
    return {k: v for k, v in value.items()}


# ─────────────────────────────────────────────────────────────────────
# Demo agency overlays — STREAM B (Session 9).
#
# Real agency PolicyVersions land via STREAM E2 connectors that poll
# Freddie / Fannie / FHA / VA / USDA bulletins and write parsed
# clauses. For now we hand-seed a small FHA overlay so the multi-agency
# chain can be exercised end-to-end:
#
#   - lender_overlay::ltv_assessment::v1  block_if ltv > 0.97 (from YAML)
#   - fha::ltv_assessment::v1             block_if ltv > 0.965  (FHA's published cap)
#
# When a loan_type=fha application runs ltv_assessment, the
# atomic_tool's agency_chain becomes [lender_overlay, fha]. The
# evaluator walks both, finds an active version for each, picks the
# overlay (overlay-first precedence) for the boundary check, and
# stamps a 2-element policy_chain on the trace. Auditable proof of
# multi-agency consultation.
# ─────────────────────────────────────────────────────────────────────


# Hand-crafted FHA overlay clauses for the demo. Keys = decision_id;
# value carries (boundary, contamination_guard, source_revision). When
# real connectors land these get superseded by parsed bulletin output.
_FHA_DEMO_OVERLAYS: dict[str, dict[str, Any]] = {
    "ltv_assessment": {
        "boundary": {
            "automate_if": ["ltv <= 0.80"],
            "recommend_if": ["ltv > 0.80", "ltv <= 0.95"],
            "block_if":   ["ltv > 0.965"],            # FHA cap
            "escalate_if": ["appraisal_disputed == true"],
        },
        "contamination_guard": None,
        "source_revision": "FHA HUD Handbook 4000.1 — LTV cap (demo overlay)",
        "source_url": "https://www.hud.gov/program_offices/housing/sfh/handbook_4000-1",
    },
}


async def seed_fha_demo_policies(policy_store: PolicyStore) -> list[str]:
    """Seed hand-crafted FHA agency PolicyVersions for the demo.

    Idempotent — preserves existing ingested_at on re-runs the same way
    seed_policies_from_yaml does. Returns the policy_version_ids
    written. Real bulletins land via STREAM E2 connectors; until then
    this seeder is the only source of FHA agency rules in the store.
    """

    now = datetime.utcnow()
    written: list[str] = []

    for decision_id, overlay in _FHA_DEMO_OVERLAYS.items():
        policy_id = policy_id_for(decision_id, agency="fha")
        existing_policy = await policy_store.get_policy(policy_id)
        policy = PolicyRecord(
            policy_id=policy_id,
            name=f"FHA · {decision_id} (HUD Handbook 4000.1, demo overlay)",
            description=(
                "FHA Single-Family Origination overlay seeded for the "
                "demo. Replaced by real HUD-bulletin connector output "
                "in STREAM E2."
            ),
            owner_team="compliance",
            agency="fha",
            decision_id=decision_id,
            product_scope=["fha"],
            state_scope=[],
            created_at=existing_policy.created_at if existing_policy else now,
        )
        await policy_store.put_policy(policy, written_by="fha_demo_seeder")

        version_id = policy_version_id_for(decision_id, agency="fha")
        existing_version = await policy_store.get_policy_version(version_id)
        version = PolicyVersionRecord(
            policy_version_id=version_id,
            policy_id=policy_id,
            version_number=1,
            valid_from=SEED_VALID_FROM,
            valid_to=None,
            source_url=overlay.get("source_url"),
            source_revision=overlay["source_revision"],
            boundary=_clone_dict(overlay["boundary"]),
            contamination_guard=overlay.get("contamination_guard"),
            hard_rules_subscribed=[],
            ingested_at=existing_version.ingested_at if existing_version else now,
            ingested_by="fha_demo_seeder",
        )
        await policy_store.put_policy_version(version, written_by="fha_demo_seeder")
        written.append(version_id)

    return written


__all__ = [
    "SEED_AGENCY",
    "SEED_INGESTED_BY",
    "SEED_VALID_FROM",
    "policy_id_for",
    "policy_version_id_for",
    "seed_fha_demo_policies",
    "seed_policies_from_yaml",
]
