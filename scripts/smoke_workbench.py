"""Smoke test for workbench UIs covering the 4 scenarios.

Each owner_team workbench should render with KPI strip + queue + app
picker. Then drilling into a specific application should show finished
+ pending + waiting + downstream sections matching the scenario."""

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
    print("Workbench smoke -- 4 scenarios x owner-team workbenches")
    print("=" * 70)

    app = create_app(seed_demo_data=True)
    failures = 0
    with TestClient(app) as client:

        # 0. Workbench index renders all 9 owner_teams.
        print("\n[0] GET /ui/workbench (index)")
        r = client.get("/ui/workbench")
        if r.status_code != 200:
            print(f"  FAIL status={r.status_code}")
            return 2
        html = r.text
        for team_label in [
            "Growth Ops", "Underwriting", "Credit Risk", "Fraud Ops",
            "Compliance", "Product Ops", "Secondary Markets", "Loan Ops",
            "Closing Ops",
        ]:
            if not _expect(html, team_label, team_label):
                failures += 1
        for needle, label in [
            ("Open queue",   "KPI: open queue"),
            ("Auto-cleared", "KPI: auto-cleared"),
            ("Blocked",      "KPI: blocked"),
        ]:
            if not _expect(html, needle, label):
                failures += 1

        # 1. happy_path through Underwriting workbench
        print("\n[1] /ui/workbench/underwriting?application_id=app_happy")
        r = client.get("/ui/workbench/underwriting?application_id=app_happy")
        if r.status_code != 200:
            print(f"  FAIL status={r.status_code}")
            return 3
        html = r.text
        for needle, label in [
            ("Underwriting workbench",     "title"),
            ("Open queue",                 "KPI strip"),
            ("Portfolio",                  "portfolio kpi"),
            ("Application",                "app picker"),
            ("app_happy",                  "selected app id"),
            ("What I finished",            "finished section"),
            ("Pending for me",             "pending section"),
            ("Waiting on upstream",        "waiting section"),
            ("Downstream waiting on me",   "downstream section"),
            ("dti_calculation",            "owned decision dti"),
            ("ltv_assessment",             "owned decision ltv"),
            ("income_verification",        "owned decision income_verification"),
            ("underwriting_decision",      "owned decision underwriting"),
        ]:
            if not _expect(html, needle, label):
                failures += 1

        # 2. fraud_block through Fraud Ops workbench
        print("\n[2] /ui/workbench/fraud_ops?application_id=app_fraud")
        r = client.get("/ui/workbench/fraud_ops?application_id=app_fraud")
        if r.status_code != 200:
            print(f"  FAIL status={r.status_code}")
            return 4
        html = r.text
        for needle, label in [
            ("Fraud Ops workbench",        "title"),
            ("app_fraud",                  "selected app"),
            ("fraud_screening",            "owned decision"),
            ("What I finished",            "finished section"),
            ("Downstream waiting on me",   "downstream section"),
            ("block",                      "block outcome present"),
        ]:
            if not _expect(html, needle, label):
                failures += 1

        # 3. contamination through Underwriting (DTI guard fires)
        print("\n[3] /ui/workbench/underwriting?application_id=app_contam")
        r = client.get("/ui/workbench/underwriting?application_id=app_contam")
        if r.status_code != 200:
            print(f"  FAIL status={r.status_code}")
            return 5
        html = r.text
        for needle, label in [
            ("Underwriting workbench",     "title"),
            ("app_contam",                 "selected app"),
            ("dti_calculation",            "owned decision"),
            ("What I finished",            "finished section"),
            ("block",                      "block on dti"),
        ]:
            if not _expect(html, needle, label):
                failures += 1

        # 4. compliance_block through Compliance workbench
        print("\n[4] /ui/workbench/compliance?application_id=app_comp")
        r = client.get("/ui/workbench/compliance?application_id=app_comp")
        if r.status_code != 200:
            print(f"  FAIL status={r.status_code}")
            return 6
        html = r.text
        for needle, label in [
            ("Compliance workbench",       "title"),
            ("app_comp",                   "selected app"),
            ("compliance_check",           "owned decision"),
            ("Downstream waiting on me",   "downstream section"),
            ("closing_readiness",          "downstream decision"),
        ]:
            if not _expect(html, needle, label):
                failures += 1

        # 5. Closing Ops workbench should show closing_readiness blocked
        # for app_comp (compliance_block_stops_closing).
        print("\n[5] /ui/workbench/closing_ops?application_id=app_comp")
        r = client.get("/ui/workbench/closing_ops?application_id=app_comp")
        if r.status_code != 200:
            print(f"  FAIL status={r.status_code}")
            return 7
        html = r.text
        for needle, label in [
            ("Closing Ops workbench",      "title"),
            ("app_comp",                   "selected app"),
            ("closing_readiness",          "owned decision"),
            ("Waiting on upstream",        "waiting section"),
        ]:
            if not _expect(html, needle, label):
                failures += 1

        # 6. No-app-selected mode: queue table rendering
        print("\n[6] /ui/workbench/underwriting (no app selected)")
        r = client.get("/ui/workbench/underwriting")
        if r.status_code != 200:
            print(f"  FAIL status={r.status_code}")
            return 8
        html = r.text
        for needle, label in [
            ("My queue",          "queue table heading"),
            ("Application",       "app picker present"),
        ]:
            if not _expect(html, needle, label):
                failures += 1

    print("\n" + "=" * 70)
    if failures:
        print(f"{failures} miss(es)")
        return 1
    print("Workbench smoke OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
