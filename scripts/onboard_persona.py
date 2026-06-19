"""Persona onboarding — the standard process for adding a new Decision OS
lending persona end to end.

This reflects the REAL Decision OS architecture (verified against the live
codebase), which differs from a naive "view + persona file" model. A persona
has SIX wiring points:

  1. A Postgres view  vw_<id>_context           (projects entity_states JSONB)
  2. EdmsContextStore.VIEW_MAPPINGS             (view -> bundle ObjectType)
  3. The persona class                          (LendingPersona subclass)
  4. LENDING_PERSONA_CLASSES                     (domains/lending/personas/__init__.py)
  5. core/cron/runner.py                         (WAVE_CONFIG / WAVES / DECISION_DEFAULTS)
  6. domains/lending/decisions.yaml              (boundary the PolicyEvaluator reads)

What this script automates safely (create / append / apply — low risk):
  - Generates + applies the view DDL to the live RDS (CREATE OR REPLACE).
  - Writes the persona file (a real LendingPersona stub, or caller-supplied code).
  - Appends the decisions.yaml boundary block.
  - Runs a smoke test: project a sample view row -> AssetProfile-style dict ->
    run the persona's _compute_offline().

What it prints for human review (editing Python dict/tuple literals in core
files is too risky to do blindly): the exact snippets for points 2, 4, 5.

Note on RLS: row-level security is provisioned but NOT enforced yet (the app
connects as a BYPASSRLS role — see scripts/migrations/security_foundation.py).
So the smoke test verifies projection + reasoning, NOT cross-tenant isolation;
isolation becomes testable only after the Phase-2 enforcement switch.

Usage (scaffold a brand-new persona stub):
  python scripts/onboard_persona.py \
    --persona-id asset_verification \
    --display-name "Asset Verification" \
    --view-name vw_asset_verification_context \
    --object-type AssetProfile \
    --description "Large deposits, gift funds, reserves adequacy" \
    --dry-run

Programmatic use (full persona, as scripts/create_asset_verification.py does):
  from scripts.onboard_persona import onboard_persona
  await onboard_persona(persona_id=..., persona_code=<full file>, view_select=[...],
                        decisions_yaml_entry=<yaml>, ...)
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PERSONAS_DIR = ROOT / "domains" / "lending" / "personas"
DECISIONS_YAML = ROOT / "domains" / "lending" / "decisions.yaml"
EDMS_STORE = ROOT / "core" / "edms_store.py"
REGISTRY = PERSONAS_DIR / "__init__.py"
RUNNER = ROOT / "core" / "cron" / "runner.py"


def _class_name(persona_id: str) -> str:
    return "".join(w.capitalize() for w in persona_id.split("_")) + "Agent"


def _u() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "").replace("postgresql+psycopg2", "postgresql")


# ── Prerequisites ────────────────────────────────────────────────────
def check_prerequisites(persona_id: str, view_name: str) -> bool:
    errors = []
    if (PERSONAS_DIR / f"{persona_id}.py").exists():
        errors.append(f"persona file already exists: domains/lending/personas/{persona_id}.py")
    if f'"{persona_id}"' in REGISTRY.read_text():
        errors.append(f"{persona_id} already in LENDING_PERSONA_CLASSES")
    if f"id: {persona_id}" in DECISIONS_YAML.read_text():
        errors.append(f"{persona_id} already in decisions.yaml")
    if errors:
        print("  prerequisites NOT met (already onboarded?):")
        for e in errors:
            print(f"    - {e}")
        return False
    print("  prerequisites OK — nothing exists yet")
    return True


# ── View DDL ─────────────────────────────────────────────────────────
def generate_view_ddl(view_name: str, view_select: list[str]) -> str:
    """view_select: full SQL select expressions (e.g.
    "((entity_states.borrower -> 'assets') ->> 'reserves_months')::double precision AS reserves_months")."""
    lines = ",\n".join(f"    {expr}" for expr in view_select)
    return (
        f"CREATE OR REPLACE VIEW {view_name} AS\nSELECT\n"
        f"    entity_states.application_id,\n"
        f"    entity_states.tenant_id,\n"
        f"{lines},\n"
        f"    entity_states.status\nFROM entity_states;"
    )


async def apply_view_to_rds(view_ddl: str, view_name: str) -> bool:
    try:
        import asyncpg
        from dotenv import load_dotenv

        load_dotenv()
        conn = await asyncpg.connect(_u())
        try:
            await conn.execute(view_ddl)
            for role in ("accord_app", "accord_readonly"):
                try:
                    await conn.execute(f"GRANT SELECT ON {view_name} TO {role}")
                except Exception as e:  # noqa: BLE001
                    print(f"    grant warn: {e}")
        finally:
            await conn.close()
        return True
    except Exception as e:  # noqa: BLE001
        print(f"    ERROR applying view: {e}")
        return False


# ── Persona stub (real LendingPersona interface) ─────────────────────
def generate_persona_stub(persona_id: str, display_name: str, description: str,
                          view_name: str, object_type: str) -> str:
    cls = _class_name(persona_id)
    return f'''from __future__ import annotations

from typing import Optional

from core.context_store import ContextBundle
from core.normalizer.models import DecisionOutcome
from core.policy_engine import PolicyDecision

from .base import LendingPersona, OfflineReasoning, latest_object, make_signal


class {cls}(LendingPersona):
    """{persona_id} — {description}

    Reads the {object_type} projected from {view_name}.
    """

    DEFAULT_AGENT_ID = "{persona_id}_agent_v1"

    def __init__(self, *, agent_id: str = DEFAULT_AGENT_ID,
                 use_anthropic: bool = False, **kw):
        super().__init__(agent_id=agent_id, persona="{persona_id}_agent",
                         decision_id="{persona_id}", use_anthropic=use_anthropic, **kw)

    def _compute_offline(self, bundle: ContextBundle,
                         policy: Optional[PolicyDecision]) -> OfflineReasoning:
        obj = latest_object(bundle, "{object_type}") or {{}}

        # TODO: implement {persona_id} logic. Set output_payload fields that
        # your decisions.yaml boundary clauses reference, and a matching
        # proposed_outcome so the safe-default fallback agrees with the policy.
        outcome = DecisionOutcome.ALLOW
        return OfflineReasoning(
            output_payload={{}},
            proposed_outcome=outcome,
            confidence=0.6,
            signals=[make_signal("placeholder", True)],
            contradictions=[],
            hypothesis="TODO",
            conclusion="TODO",
            confidence_basis="TODO",
            summary="TODO",
        )


__all__ = ["{cls}"]
'''


# ── Smoke test ───────────────────────────────────────────────────────
async def smoke_test(persona_id: str, view_name: str, object_type: str,
                     id_field: str, field_map: dict) -> bool:
    try:
        import asyncpg
        from dotenv import load_dotenv

        load_dotenv()
        conn = await asyncpg.connect(_u())
        try:
            row = await conn.fetch(f"SELECT * FROM {view_name} LIMIT 1")
        finally:
            await conn.close()
        if not row:
            print("    (view has no rows yet — projection check skipped)")
            return True

        # Project the row the way EdmsContextStore does, then reason.
        from core.context_store import ContextBundle
        from datetime import datetime, timezone
        from uuid import uuid4
        import importlib

        r = dict(row[0])
        fields = {fn: r.get(vc) for vc, fn in field_map.items() if r.get(vc) is not None}
        eid = str(r.get(id_field) or r.get("application_id"))
        bundle = ContextBundle(
            decision_id=persona_id, application_id=r["application_id"],
            snapshot_id=uuid4(), snapshot_at=datetime.now(timezone.utc),
            objects={object_type: {eid: fields}}, upstream_outputs={}, upstream_decision_ids=[])

        mod = importlib.import_module("domains.lending.personas")
        cls = mod.LENDING_PERSONA_CLASSES.get(persona_id)
        if cls is None:
            print(f"    persona {persona_id} not yet in LENDING_PERSONA_CLASSES — wire point 4 then re-run smoke test")
            return False
        reasoning = cls()._compute_offline(bundle, None)
        print(f"    projected {object_type}={fields}")
        print(f"    _compute_offline -> {reasoning.proposed_outcome.value} "
              f"(payload keys: {list(reasoning.output_payload)})")
        print("    NOTE: RLS not enforced yet (BYPASSRLS app role) — isolation NOT asserted here.")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"    smoke test error: {e}")
        return False


# ── Manual-wiring snippets (points 2, 4, 5) ──────────────────────────
def print_wiring(persona_id: str, view_name: str, object_type: str,
                 id_field: str, field_map: dict, wave: int) -> None:
    cls = _class_name(persona_id)
    fm = "\n".join(f'                "{vc}": "{fn}",' for vc, fn in field_map.items())
    print("\n  -- Wire these 3 Python registries (review before saving) --")
    print(f"\n  [2] core/edms_store.py  VIEW_MAPPINGS — add:")
    print(f'        "{persona_id}": {{\n            "view": "{view_name}",\n'
          f'            "object_type": "{object_type}",\n            "field_map": {{\n{fm}\n            }},\n'
          f'            "id_field": "{id_field}",\n        }},')
    print(f"\n  [4] domains/lending/personas/__init__.py:")
    print(f"        from .{persona_id} import {cls}")
    print(f'        # in LENDING_PERSONA_CLASSES:  "{persona_id}": {cls},')
    print(f"\n  [5] core/cron/runner.py:")
    print(f'        WAVE_CONFIG:      "{persona_id}": {{"wave": {wave}, "upstream": []}},')
    print(f'        WAVES[{wave - 1}]:        add "{persona_id}"')
    print(f'        DECISION_DEFAULTS: "{persona_id}": {{"sla_seconds": 30, "risk_level": "medium", "mode": "recommend"}},')


# ── Orchestration ────────────────────────────────────────────────────
async def onboard_persona(
    *,
    persona_id: str,
    display_name: str,
    view_name: str,
    object_type: str,
    description: str = "",
    view_select: list[str] | None = None,
    field_map: dict | None = None,
    id_field: str = "application_id",
    wave: int = 1,
    persona_code: str | None = None,
    decisions_yaml_entry: str = "",
    dry_run: bool = False,
) -> None:
    print(f"\n{'=' * 60}\nOnboarding persona: {display_name}  ({persona_id})\n{'=' * 60}")

    print("\nSTEP 1 — prerequisites")
    fresh = check_prerequisites(persona_id, view_name)

    print("\nSTEP 2 — view DDL")
    view_ddl = generate_view_ddl(view_name, view_select or [])
    if dry_run:
        print(view_ddl)

    print("\nSTEP 3 — apply view to RDS")
    if dry_run:
        print("  (dry-run — skipped)")
    else:
        ok = await apply_view_to_rds(view_ddl, view_name)
        print(f"  {'applied' if ok else 'FAILED'} {view_name}")

    print("\nSTEP 4 — persona file")
    pf = PERSONAS_DIR / f"{persona_id}.py"
    code = persona_code or generate_persona_stub(persona_id, display_name, description, view_name, object_type)
    if dry_run:
        print(f"  (dry-run — would write {pf})")
    elif pf.exists():
        print(f"  already exists — left untouched: {pf}")
    else:
        pf.write_text(code, encoding="utf-8")
        print(f"  wrote {pf}")

    print("\nSTEP 5 — decisions.yaml boundary")
    if decisions_yaml_entry:
        text = DECISIONS_YAML.read_text(encoding="utf-8")
        if f"id: {persona_id}" in text:
            print("  already present — left untouched")
        elif dry_run:
            print("  (dry-run — would append boundary block before execution_order)")
        else:
            anchor = "\n# ─────────────────────────────────────────────\n# DECISION EXECUTION ORDER"
            if anchor in text:
                text = text.replace(anchor, decisions_yaml_entry.rstrip() + "\n" + anchor, 1)
            else:
                text += "\n" + decisions_yaml_entry
            DECISIONS_YAML.write_text(text, encoding="utf-8")
            print("  appended boundary block")
    else:
        print("  (no boundary supplied — stub mode)")

    print("\nSTEP 6 — registry wiring (points 2, 4, 5)")
    if field_map:
        print_wiring(persona_id, view_name, object_type, id_field, field_map, wave)

    print("\nSTEP 7 — smoke test")
    if dry_run:
        print("  (dry-run — skipped)")
    elif field_map:
        await smoke_test(persona_id, view_name, object_type, id_field, field_map)

    print(f"\n{'=' * 60}")
    print("DRY RUN — no changes made" if dry_run else f"ONBOARD STEPS DONE for {persona_id}")
    print(f"{'=' * 60}")
    print("Remaining: confirm the 3 Python-registry edits above are in place, then")
    print("  run: python scripts/evaluate_meridian_scenarios.py")


def main() -> None:
    p = argparse.ArgumentParser(description="Onboard a new Decision OS lending persona")
    p.add_argument("--persona-id", required=True)
    p.add_argument("--display-name", required=True)
    p.add_argument("--view-name", required=True)
    p.add_argument("--object-type", required=True)
    p.add_argument("--description", default="")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    asyncio.run(onboard_persona(
        persona_id=a.persona_id, display_name=a.display_name, view_name=a.view_name,
        object_type=a.object_type, description=a.description, dry_run=a.dry_run))


if __name__ == "__main__":
    main()
