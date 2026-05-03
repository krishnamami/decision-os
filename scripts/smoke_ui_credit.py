"""Smoke test for the new credit_assessment persona panel + cross-cutting
strip (routing pill, read-permissions chips, atomic-tool pipeline,
upstream status, boundary lit).

Boots the app via the bootstrap lifespan (which seeds the 4 scenarios)
and renders every UI route relevant to the change. Asserts on substring
markers so we catch missing wiring without snapshotting full HTML.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from api.main import create_app  # noqa: E402


def _expect(html: str, needle: str, label: str) -> bool:
    ok = needle in html
    print(f"  [{'OK' if ok else 'MISS'}] {label}")
    return ok


def main() -> int:
    print("=" * 70)
    print("UI smoke -- credit_assessment panel + cross-cutting strip")
    print("=" * 70)

    app = create_app(seed_demo_data=True)
    failures = 0
    with TestClient(app) as client:

        # 1. credit_assessment (auto, has panel)
        print("\n[1] GET /ui/applications/app_happy/decisions/credit_assessment")
        r = client.get("/ui/applications/app_happy/decisions/credit_assessment")
        if r.status_code != 200:
            print(f"  FAIL status={r.status_code}")
            return 2
        html = r.text
        for needle, label in [
            # Header
            ("Credit assessment",                 "title"),
            ("auto · written back",               "routing target pill"),
            # Read-permissions chips (PRD no_agent_without_permissions)
            ("no_agent_without_permissions",      "read-perm row label"),
            ("Applicant",                          "Applicant chip"),
            ("CreditProfile",                     "CreditProfile chip"),
            # Atomic tool pipeline strip (PRD §7)
            ("Atomic tool",                       "atomic strip header"),
            ("PRD §7",                            "PRD reference"),
            ("context_build",                     "step 1"),
            ("policy_pre_check",                  "step 2"),
            ("agent reason",                       "step 3"),
            ("policy_check",                      "step 4"),
            ("trace_write",                       "step 6"),
            ("mode_route",                        "step 7"),
            # Boundary lit panel
            ("lit against output_payload",        "boundary lit subhead"),
            ("automate_if",                       "automate clause"),
            ("block_if",                          "block clause"),
            # Persona panel: credit-specific
            ("Credit assessment · persona view",  "persona panel header"),
            ("Credit score",                      "score gauge label"),
            ("auto ≥ 680",                        "auto threshold pill"),
            ("recommend ≥ 600",                   "recommend threshold pill"),
            ("Boundary triggers from output_payload", "trigger grid header"),
            ("active_bankruptcy",                 "block trigger"),
            ("foreclosure_last_36_months",        "block trigger 2"),
            ("thin_file",                         "escalate trigger"),
            ("no_derogatory_last_24_months",      "auto trigger"),
        ]:
            if not _expect(html, needle, label):
                failures += 1

        # 2. lead_scoring (auto, NO panel -- fallback)
        print("\n[2] GET /ui/applications/app_happy/decisions/lead_scoring")
        r = client.get("/ui/applications/app_happy/decisions/lead_scoring")
        if r.status_code != 200:
            print(f"  FAIL status={r.status_code}")
            return 3
        html = r.text
        for needle, label in [
            ("Lead scoring",                      "title"),
            ("auto · written back",               "routing pill present"),
            ("Atomic tool",                       "atomic strip present"),
            ("automate_if",                       "boundary clause"),
        ]:
            if not _expect(html, needle, label):
                failures += 1
        # Persona panel must NOT render for lead_scoring
        if "persona view" in html.lower() and "credit_risk_agent" in html.lower():
            print("  [MISS] credit panel leaked into lead_scoring")
            failures += 1
        else:
            print("  [OK] no persona panel on lead_scoring (fallback ok)")

        # 3. dti_calculation (dependent -- has upstream + contamination)
        print("\n[3] GET /ui/applications/app_happy/decisions/dti_calculation")
        r = client.get("/ui/applications/app_happy/decisions/dti_calculation")
        if r.status_code != 200:
            print(f"  FAIL status={r.status_code}")
            return 4
        html = r.text
        for needle, label in [
            ("DTI calculation",                   "title"),
            ("Upstream status",                   "upstream strip header"),
            ("upstream_block_propagates_to_dependents", "upstream rule label"),
            ("income_verification",               "upstream link"),
            ("Contamination guard",               "contamination guard row"),
            ("reject_if_upstream_confidence_below", "guard threshold key"),
        ]:
            if not _expect(html, needle, label):
                failures += 1

        # 4. underwriting (dependent, human_approval -- queued routing)
        print("\n[4] GET /ui/applications/app_happy/decisions/underwriting_decision")
        r = client.get("/ui/applications/app_happy/decisions/underwriting_decision")
        if r.status_code != 200:
            print(f"  FAIL status={r.status_code}")
            return 5
        html = r.text
        for needle, label in [
            ("Underwriting decision",             "title"),
            ("Upstream status",                   "upstream present"),
            ("Contamination guard",               "guard present"),
            ("fail_if_any_upstream_blocked",      "uw guard key"),
        ]:
            if not _expect(html, needle, label):
                failures += 1
        # Underwriting in happy_path is recommend (queue), so:
        if "queued · human review" not in html and "auto · written back" not in html:
            print(f"  [MISS] no routing pill found")
            failures += 1
        else:
            print("  [OK] routing pill present")

    print("\n" + "=" * 70)
    if failures:
        print(f"{failures} miss(es)")
        return 1
    print("UI smoke OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
