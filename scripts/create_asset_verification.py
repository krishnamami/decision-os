"""Onboard the asset_verification persona (SC15) via onboard_persona.py.

This is executable documentation of the asset_verification onboarding AND an
idempotent re-verifier: re-applies the view, confirms the wiring is present,
and smoke-tests the persona. The persona logic itself lives in
domains/lending/personas/asset_verification.py (a real LendingPersona); the
six wiring points (VIEW_MAPPINGS, registry, runner waves, decisions.yaml) are
committed in the repo.

SC15 — Maria Santos: $47K undocumented deposit, 3.2 months reserves.
Expected: escalate (source the deposit; a large unsourced deposit is sourced
by UW, not denied — Fannie Mae B3-4.3-04).

Run:
  python scripts/create_asset_verification.py            # apply + verify
  python scripts/create_asset_verification.py --dry-run
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.onboard_persona import onboard_persona

# Full SQL select expressions for vw_asset_verification_context (borrower.assets).
VIEW_SELECT = [
    "entity_states.borrower ->> 'applicant_id' AS applicant_id",
    "((entity_states.borrower -> 'assets') ->> 'large_deposit_amount')::double precision  AS large_deposit_amount",
    "((entity_states.borrower -> 'assets') ->> 'large_deposit_documented')::boolean        AS large_deposit_documented",
    "((entity_states.borrower -> 'assets') ->> 'liquid_assets_total')::double precision     AS liquid_assets_total",
    "((entity_states.borrower -> 'assets') ->> 'reserves_months')::double precision         AS reserves_months",
    "((entity_states.borrower -> 'assets') ->> 'checking_savings')::double precision        AS checking_savings",
    "((entity_states.borrower -> 'assets') ->> 'gift_funds')::double precision              AS gift_funds",
    "((entity_states.borrower -> 'assets') ->> 'gift_funds_documented')::boolean            AS gift_funds_documented",
    "entity_states.assets_verified",
    "entity_states.total_liquid_assets",
]

# view column -> bundle field (EdmsContextStore.VIEW_MAPPINGS).
FIELD_MAP = {
    "large_deposit_amount": "large_deposit_amount",
    "large_deposit_documented": "large_deposit_documented",
    "liquid_assets_total": "liquid_assets_total",
    "reserves_months": "reserves_months",
    "checking_savings": "checking_savings",
    "gift_funds": "gift_funds",
    "gift_funds_documented": "gift_funds_documented",
    "assets_verified": "assets_verified",
    "total_liquid_assets": "total_liquid_assets",
}

DECISIONS_YAML_ENTRY = """
  - id: asset_verification
    name: Asset verification
    atomic_tool: asset_verification_tool
    context_window_days: 90
    type: independent
    description: >
      Evaluates asset documentation quality — large deposits, gift funds,
      and reserves adequacy. A large unsourced deposit is escalated for
      sourcing (not denied); a reserves shortfall is a hard block.
    own_data:
      - bank_statements
      - asset_documents
      - gift_letters
    shared_data:
      - reserves_requirement
    persona: asset_verification_agent
    mode: recommend
    risk_level: medium
    owner_team: underwriting_ops
    boundary:
      automate_if:
        - assets_clear == true
      block_if:
        - expression: reserves_insufficient == true
          governed_by:
            type: agency_guidelines
            authority: fannie_mae
            rule_name: Reserves Requirements
            citation: Fannie Mae B3-4.4-01
      escalate_if:
        - needs_sourcing == true
    sla_seconds: 30
    trace_required: true
"""


async def _run(dry_run: bool) -> None:
    await onboard_persona(
        persona_id="asset_verification",
        display_name="Asset Verification",
        view_name="vw_asset_verification_context",
        object_type="AssetProfile",
        description="Evaluates large deposits, gift funds, and reserves adequacy (SC15).",
        view_select=VIEW_SELECT,
        field_map=FIELD_MAP,
        id_field="application_id",
        wave=1,
        persona_code=None,  # real persona already committed at personas/asset_verification.py
        decisions_yaml_entry=DECISIONS_YAML_ENTRY,
        dry_run=dry_run,
    )


def main() -> None:
    p = argparse.ArgumentParser(description="Onboard the asset_verification persona (SC15)")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    asyncio.run(_run(a.dry_run))


if __name__ == "__main__":
    main()
