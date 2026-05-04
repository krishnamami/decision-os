"""End-to-end audit + reports smoke.

  python -X utf8 scripts/smoke_audit_reports.py

  1. Boot a Platform (in-memory)
  2. Generate 24 synthetic applicants (deterministic seed=42)
  3. Run the DAG for each — atomic_tool fires the audit gate per
     decision, AuditRecord goes to InMemoryAuditStore
  4. Generate all six reports across the audit corpus
  5. Print summary + flag counts so you can eyeball that:
       - fair_lending shows multiple segments with rates
       - bias report has fairness/disparate signals
       - hmda report rolls up by state
       - overrides / security / ai_trail return clean shapes

This script is the primary local-simulation handle for §23 — run it
after every meaningful change to the audit code.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from api.deps import build_default_platform  # noqa: E402
from core.audit.reports import (  # noqa: E402
    generate_ai_trail_report,
    generate_bias_report,
    generate_fair_lending_report,
    generate_hmda_report,
    generate_overrides_report,
    generate_security_report,
)
from core.policy_engine import (  # noqa: E402
    seed_fha_demo_policies,
    seed_policies_from_yaml,
)
from domains.lending.personas import register_with_platform  # noqa: E402
from domains.lending.synthetic import (  # noqa: E402
    build_synthetic_applicants,
    inject_into_platform,
)


N_APPLICANTS = 24


async def main() -> int:
    print(f"\n=== boot platform + register 12 personas ===")
    platform = build_default_platform()
    register_with_platform(platform)
    await seed_policies_from_yaml(platform.spec, platform.policy_store)
    await seed_fha_demo_policies(platform.policy_store)
    print(f"  agents registered: {len(platform.agents)}")

    print(f"\n=== generate {N_APPLICANTS} synthetic applicants ===")
    profiles = build_synthetic_applicants(N_APPLICANTS, seed=42)
    by_segment: dict[str, int] = {}
    by_loan_type: dict[str, int] = {}
    by_overlay: dict[str, int] = {}
    for p in profiles:
        by_segment[p.credit_band] = by_segment.get(p.credit_band, 0) + 1
        by_loan_type[p.loan_type] = by_loan_type.get(p.loan_type, 0) + 1
        kind = (
            "consent_missing" if p.overlay.consent_missing else
            "protected_attr_leak" if p.overlay.protected_attr_leak else
            "no_disclosure" if p.overlay.no_disclosure else
            "clean"
        )
        by_overlay[kind] = by_overlay.get(kind, 0) + 1
    print(f"  segments:    {by_segment}")
    print(f"  loan types:  {by_loan_type}")
    print(f"  overlays:    {by_overlay}")

    print(f"\n=== inject applicants + run DAG ===")
    application_ids = await inject_into_platform(platform, profiles)
    completed = 0
    failed = 0
    for app_id in application_ids:
        try:
            res = await platform.executor().run_application(
                app_id, platform.entity_resolver
            )
            completed += 1 if not res.halted else 0
            if res.halted:
                failed += 1
        except Exception as err:
            print(f"  {app_id} raised: {err}")
            failed += 1
    print(f"  completed: {completed}, halted: {failed}")

    # Pull every audit record out of the store for the reports.
    audit_store = platform.audit_store
    all_records: list = []
    for app_id in application_ids:
        all_records.extend(await audit_store.list_for_application(app_id))
    print(f"  audit records: {len(all_records)}")

    # Status breakdown
    by_status: dict[str, int] = {}
    fail_by_decision: dict[str, int] = {}
    fail_by_check: dict[str, int] = {}
    warn_by_decision: dict[str, int] = {}
    warn_by_check: dict[str, int] = {}
    for r in all_records:
        s = r.overall_status.value
        by_status[s] = by_status.get(s, 0) + 1
        for chk_name, chk_status in (
            ("compliance", r.compliance_status.value),
            ("security",   r.security_status.value),
            ("ethics",     r.ethics_status.value),
            ("fairness",   r.fairness_status.value),
        ):
            if chk_status == "fail":
                fail_by_check[chk_name] = fail_by_check.get(chk_name, 0) + 1
            elif chk_status == "warn":
                warn_by_check[chk_name] = warn_by_check.get(chk_name, 0) + 1
        if s == "fail":
            fail_by_decision[r.decision_type] = fail_by_decision.get(r.decision_type, 0) + 1
        elif s == "warn":
            warn_by_decision[r.decision_type] = warn_by_decision.get(r.decision_type, 0) + 1
    print(f"  status mix:        {by_status}")
    print(f"  warns per decision: {warn_by_decision}")
    print(f"  warns per check:    {warn_by_check}")
    print(f"  fails per decision: {fail_by_decision}")
    print(f"  fails per check:    {fail_by_check}")

    print(f"\n=== reports ===")
    window_start = datetime.utcnow() - timedelta(days=1)
    window_end = datetime.utcnow() + timedelta(days=1)

    for name, gen in (
        ("hmda",         generate_hmda_report),
        ("fair_lending", generate_fair_lending_report),
        ("ai_trail",     generate_ai_trail_report),
        ("security",     generate_security_report),
        ("bias",         generate_bias_report),
        ("overrides",    generate_overrides_report),
    ):
        report = gen(all_records, window_start, window_end)
        print(f"\n--- {name} ({report.cadence}) ---")
        print(f"  records:  {report.record_count}")
        print(f"  flags:    {len(report.flags)}")
        print(f"  summary:  {json.dumps(report.summary, indent=2, default=str)[:500]}")

    print("\n=== done ===\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
