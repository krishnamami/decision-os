"""Smoke test for all 12 persona panels.

Boots the app via the bootstrap lifespan (which seeds the 4 scenarios)
and renders every decision detail page across two scenarios:
  - app_happy: pipeline runs to completion
  - app_fraud: fraud_screening BLOCKS, downstream skipped

For each route, asserts that the persona panel header renders. For
fraud_screening on app_fraud, also assert the halt warning appears.
For compliance_check on app_comp, assert halts_closing warning.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from api.main import create_app  # noqa: E402


PANEL_HEADERS = {
    "lead_scoring":          "Lead scoring · persona view",
    "income_verification":   "Income verification · persona view",
    "credit_assessment":     "Credit assessment · persona view",
    "fraud_screening":       "Fraud screening · persona view",
    "compliance_check":      "Compliance check · persona view",
    "dti_calculation":       "DTI calculation · persona view",
    "ltv_assessment":        "LTV assessment · persona view",
    "product_eligibility":   "Product eligibility · persona view",
    "rate_pricing":          "Rate pricing · persona view",
    "underwriting_decision": "Underwriting decision · persona view",
    "approval_routing":      "Approval routing · persona view",
    "closing_readiness":     "Closing readiness · persona view",
}


def main() -> int:
    print("=" * 70)
    print("UI smoke -- 12 persona panels across happy + fraud scenarios")
    print("=" * 70)

    app = create_app(seed_demo_data=True)
    failures = 0
    with TestClient(app) as client:

        # 1. happy_path -- every panel should render.
        print("\n[A] app_happy -- every persona panel header present")
        for did, header in PANEL_HEADERS.items():
            r = client.get(f"/ui/applications/app_happy/decisions/{did}")
            if r.status_code != 200:
                print(f"  [HTTP {r.status_code}] {did}")
                failures += 1
                continue
            if header not in r.text:
                print(f"  [MISS] {did}: header not found")
                failures += 1
                continue
            print(f"  [OK]   {did}")

        # 2. app_fraud -- fraud_screening should show halt warning.
        print("\n[B] app_fraud -- fraud_screening halt warning")
        r = client.get("/ui/applications/app_fraud/decisions/fraud_screening")
        if r.status_code != 200:
            print(f"  [HTTP {r.status_code}]")
            failures += 1
        else:
            for needle, label in [
                ("Fraud screening · persona view",        "panel header"),
                ("fraud_block_stops_pipeline",            "halt rule label"),
                ("7 downstream decisions skipped",        "halt scope"),
            ]:
                if needle in r.text:
                    print(f"  [OK]   {label}")
                else:
                    print(f"  [MISS] {label}")
                    failures += 1

        # 3. app_comp -- compliance_check should show halts_closing warning.
        print("\n[C] app_comp -- compliance_check halts_closing warning")
        r = client.get("/ui/applications/app_comp/decisions/compliance_check")
        if r.status_code != 200:
            print(f"  [HTTP {r.status_code}]")
            failures += 1
        else:
            for needle, label in [
                ("Compliance check · persona view",        "panel header"),
                ("compliance_block_stops_closing",         "halt rule label"),
                ("closing_readiness will block",           "halt scope"),
            ]:
                if needle in r.text:
                    print(f"  [OK]   {label}")
                else:
                    print(f"  [MISS] {label}")
                    failures += 1

        # 4. contamination -- dti_calculation guard should fire.
        print("\n[D] app_contam -- dti_calculation contamination guard fired")
        r = client.get("/ui/applications/app_contam/decisions/dti_calculation")
        if r.status_code != 200:
            print(f"  [HTTP {r.status_code}]")
            failures += 1
        else:
            for needle, label in [
                ("DTI calculation · persona view",         "panel header"),
                ("Contamination guard",                    "guard section"),
                ("guard fired · BLOCK",                    "guard fired badge"),
            ]:
                if needle in r.text:
                    print(f"  [OK]   {label}")
                else:
                    print(f"  [MISS] {label}")
                    failures += 1

    print("\n" + "=" * 70)
    if failures:
        print(f"{failures} miss(es)")
        return 1
    print("UI smoke OK -- all 12 panels render")
    return 0


if __name__ == "__main__":
    sys.exit(main())
