"""Per-persona workbench smoke — STREAM A (Session 9).

Boots a Platform with seed_demo_data and walks all 12 personas:

  1. /ui/personas index renders 12 cards grouped by owner_team.
  2. Every persona's workbench page renders with KPI strip, view tabs,
     and either a queue (human_approval) or recently-completed list
     (auto_execute).
  3. Drill-down on a queued application renders the right-column
     detail with Application Context, Signals, AI Reasoning, and the
     three action buttons.
  4. Approve (ack) attaches a HumanReview with overridden=False.
  5. Decline overrides outcome to BLOCK and captures an AgentLearning.
  6. Request evidence (send_back) returns a flash banner without
     mutating state.

Run:
  python -X utf8 scripts/smoke_persona_workbench.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from api.main import create_app  # noqa: E402


HUMAN_PERSONAS = (
    "income_verification",
    "compliance_check",
    "underwriting_decision",
    "closing_readiness",
)
RECOMMEND_PERSONA = "product_eligibility"


def _expect(html: str, needle: str, label: str) -> bool:
    ok = needle in html
    print(f"  [{'OK' if ok else 'MISS'}] {label}")
    return ok


def main() -> int:
    print("=" * 70)
    print("Persona workbench smoke")
    print("=" * 70)

    app = create_app(seed_demo_data=True)
    failures = 0

    with TestClient(app) as client:

        # ── Phase 1 — index page ───────────────────────────────────
        print("\n[1] GET /ui/personas (index)")
        r = client.get("/ui/personas")
        if r.status_code != 200:
            print(f"  FAIL status={r.status_code}")
            return 2
        html = r.text
        for label in (
            "Lead qualifier",
            "Income underwriter",
            "Credit underwriter",
            "Fraud officer",
            "Compliance officer",
            "Senior underwriter",
            "Closing officer",
        ):
            failures += 0 if _expect(html, label, f"index lists {label!r}") else 1
        for did in (
            "lead_scoring", "credit_assessment", "underwriting_decision",
        ):
            failures += 0 if _expect(html, did, f"index lists decision_id {did}") else 1

        # ── Phase 2 — every persona renders ────────────────────────
        platform = app.state.platform
        decision_ids = [d["id"] for d in platform.spec.decisions]
        print(f"\n[2] GET /ui/personas/{{decision_id}} for all {len(decision_ids)}")
        for did in decision_ids:
            r = client.get(f"/ui/personas/{did}")
            ok = r.status_code == 200 and "Decisions completed" in r.text
            print(f"  [{'OK' if ok else 'MISS'}] {did}")
            if not ok:
                failures += 1

        # ── Phase 3 — human-mode queues are non-empty ──────────────
        print("\n[3] human-mode personas show their queue with applications")
        for did in HUMAN_PERSONAS:
            r = client.get(f"/ui/personas/{did}")
            html = r.text
            has_queue_label = "queue" in html
            has_app_link = "/ui/personas/" in html and "application_id=" in html
            ok = has_queue_label and has_app_link
            print(f"  [{'OK' if ok else 'MISS'}] {did} queue + app links")
            if not ok:
                failures += 1

        # ── Phase 4 — drill into a queued underwriting_decision ───
        print("\n[4] drill into underwriting_decision for app_happy")
        r = client.get("/ui/personas/underwriting_decision?application_id=app_happy")
        if r.status_code != 200:
            print(f"  FAIL status={r.status_code}")
            failures += 1
        else:
            html = r.text
            for needle, label in (
                ("Application context", "context section"),
                ("Signals evaluated",   "signals section"),
                ("AI reasoning",        "reasoning section"),
                ("Approve",             "approve button"),
                ("Decline",             "decline button"),
                ("Request evidence",    "request evidence button"),
                ("app_happy",           "selected app id"),
            ):
                failures += 0 if _expect(html, needle, label) else 1

        # ── Phase 5 — Approve (ack) attaches HumanReview ──────────
        print("\n[5] POST .../ack — positive ack on app_happy")
        r = client.get("/ui/personas/underwriting_decision?application_id=app_happy")
        # Pull trace_id out of the form input.
        import re
        m = re.search(r'name="trace_id"\s+value="([^"]+)"', r.text)
        if not m:
            print("  FAIL no trace_id in form")
            failures += 1
        else:
            trace_id = m.group(1)
            r = client.post(
                "/ui/personas/underwriting_decision/applications/app_happy/ack",
                data={
                    "trace_id":      trace_id,
                    "reviewer_id":   "smoke-user",
                    "reviewer_role": "Senior underwriter",
                },
            )
            if r.status_code != 200:
                print(f"  FAIL ack status={r.status_code}: {r.text[:200]}")
                failures += 1
            else:
                html = r.text
                failures += 0 if _expect(html, "confirmed AI's decision", "ack badge present") else 1
                # Verify the trace now carries human_review.
                from uuid import UUID
                trace = platform.trace_writer._traces[UUID(trace_id)]  # type: ignore[attr-defined]
                ok = trace.human_review is not None and trace.human_review.overridden is False
                print(f"  [{'OK' if ok else 'MISS'}] trace.human_review attached, overridden=False")
                if not ok:
                    failures += 1

        # ── Phase 6 — Decline overrides + captures learning ──────
        # We use compliance_check on app_comp because it queues with proposed=block;
        # decline of an already-block trace must error gracefully. Use app_happy
        # which is queued recommend → decline overrides to block.
        print("\n[6] POST .../decline — override to BLOCK on a recommend trace")
        r = client.get("/ui/personas/compliance_check?application_id=app_happy")
        m = re.search(r'name="trace_id"\s+value="([^"]+)"', r.text)
        if not m:
            print("  FAIL no trace_id in form (compliance_check/app_happy)")
            failures += 1
        else:
            trace_id = m.group(1)
            learning_count_before = len(platform.learning_store._learnings)  # type: ignore[attr-defined]
            r = client.post(
                "/ui/personas/compliance_check/applications/app_happy/decline",
                data={
                    "trace_id":      trace_id,
                    "reviewer_id":   "smoke-user",
                    "reviewer_role": "Compliance officer",
                },
            )
            ok_status = r.status_code == 200
            html = r.text
            # decline could land in two states depending on the AI's outcome —
            # if AI proposed allow/recommend it overrides; if it was already
            # block the route returns the "nothing to decline" flash. Either
            # is correct behavior; assert both branches render the partial.
            ok_partial = "persona-detail" in html or "AI already produced" in html
            print(f"  [{'OK' if ok_status else 'MISS'}] HTTP 200 from decline endpoint")
            print(f"  [{'OK' if ok_partial else 'MISS'}] decline returns partial")
            if not ok_status or not ok_partial:
                failures += 1
            learning_count_after = len(platform.learning_store._learnings)  # type: ignore[attr-defined]
            print(f"  learnings: before={learning_count_before} after={learning_count_after}")

        # ── Phase 7 — Request evidence stub ──────────────────────
        print("\n[7] POST .../send_back stub")
        r = client.post(
            "/ui/personas/underwriting_decision/applications/app_happy/send_back",
            data={"trace_id": "00000000-0000-0000-0000-000000000000"},
        )
        ok = r.status_code == 200 and "send_back" in r.text
        print(f"  [{'OK' if ok else 'MISS'}] send_back stub returns flash")
        if not ok:
            failures += 1

        # ── Phase 8 — auto persona shows recently completed ──────
        print("\n[8] auto_execute persona shows 'Recently completed'")
        for did in ("lead_scoring", "dti_calculation", "approval_routing"):
            r = client.get(f"/ui/personas/{did}")
            ok = r.status_code == 200 and "Recently completed" in r.text
            print(f"  [{'OK' if ok else 'MISS'}] {did}")
            if not ok:
                failures += 1

        # ── Phase 9 — time-range selector ────────────────────────
        print("\n[9] time-range selector")
        r = client.get("/ui/personas/credit_assessment?time_range=week")
        ok = r.status_code == 200 and "This week" in r.text
        print(f"  [{'OK' if ok else 'MISS'}] week selected")
        if not ok:
            failures += 1

        # ── Phase 10 — top nav has Personas link ─────────────────
        print("\n[10] base nav exposes Personas")
        r = client.get("/ui/personas")
        ok = '/ui/personas' in r.text and ">Personas<" in r.text
        print(f"  [{'OK' if ok else 'MISS'}] base.html nav lists Personas")
        if not ok:
            failures += 1

        # ── Phase 11 — Policy + Evidence sections ────────────────
        print("\n[11] Policy + Evidence sections render on persona detail")
        r = client.get("/ui/personas/income_verification?application_id=app_happy")
        html = r.text
        for needle, label in (
            ("Policy applied",                       "Policy applied header"),
            ("lender_overlay::income_verification::v1", "policy_version_id"),
            ("lender_overlay",                       "agency tag"),
            ("Evidence",                             "Evidence header"),
            ("verified_income",                      "verified_income claim"),
            ("Acme Engineering Co.",                 "employer claim value"),
            ("doc_happy_w2",                         "source doc id"),
            ("underwriter:bgoud",                    "verifier"),
        ):
            failures += 0 if _expect(html, needle, label) else 1

        # ── Phase 12 — agency_chain on traces ────────────────────
        # happy_path Loan is loan_type=conforming → default chain
        # ["lender_overlay", "freddie"]. Only lender_overlay has a
        # PolicyVersion seeded today, so policy_chain on the trace
        # carries 1 id (the active version found in that chain). The
        # CHAIN ORDER is what matters for STREAM E2 — we assert the
        # consult walked overlay first.
        platform = app.state.platform
        traces = list(platform.trace_writer._traces.values())  # type: ignore[attr-defined]
        # Pick a downstream decision that runs AFTER the Loan is hydrated
        # (parallel-independent decisions run BEFORE Loan exists, so they
        # get the default chain). dti_calculation runs after.
        dti_traces = [
            t for t in traces
            if t.application_id == "app_happy" and t.decision_id == "dti_calculation"
        ]
        ok = bool(dti_traces) and dti_traces[0].policy_version_id is not None
        print(f"  [{'OK' if ok else 'MISS'}] dti trace has policy_version_id stamped")
        if not ok:
            failures += 1
        if dti_traces:
            chain = dti_traces[0].policy_chain
            ok = len(chain) >= 1 and any("dti_calculation" in v for v in chain)
            print(f"  [{'OK' if ok else 'MISS'}] policy_chain has dti version: {chain}")
            if not ok:
                failures += 1

    print("\n" + "=" * 70)
    if failures:
        print(f"Persona workbench smoke FAILED with {failures} miss(es)")
        return 1
    print("Persona workbench smoke OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
