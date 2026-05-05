"""employment_continuity scenario smoke — STAGE A gap demo.

Demonstrates the multi-source income-verification gap that the
brainstorm in CONTEXT.md (Session 11 prep) identified. Today the
income_verification persona reads a single IncomeProfile blob; this
smoke shows what that blob looks like when two providers (TWN-style
and Argyle-style payroll feeds) disagree on employer name + comp,
plus an unattached prior-employer W-2 sits in EDMS, plus a pending
1099 represents the gig year — and prints an explicit list of the
gaps the trace cannot surface.

The smoke does NOT change architecture. It produces evidence that
STAGE B (employment_reconciliation as a DAG node) is needed.

Run:
  python -X utf8 scripts/smoke_employment_continuity.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api.deps import build_default_platform  # noqa: E402
from core.policy_engine import seed_policies_from_yaml  # noqa: E402
from domains.lending.personas import register_with_platform  # noqa: E402
from domains.lending.seed_events.runner import run_scenario  # noqa: E402


def _ok(label: str, cond: bool) -> int:
    print(f"  [{'OK' if cond else 'MISS'}] {label}")
    return 0 if cond else 1


def _months_between(start_iso: str, end: date) -> int:
    y, m, d = (int(p) for p in start_iso.split("-"))
    return (end.year - y) * 12 + (end.month - m)


async def main() -> int:
    print("=" * 72)
    print("employment_continuity smoke — STAGE A gap demo")
    print("=" * 72)

    failures = 0

    # ── Phase 1: boot + run scenario ────────────────────────────────────
    print("\n[1] platform boot + run scenario")
    p = build_default_platform()
    register_with_platform(p)
    await seed_policies_from_yaml(p.spec, p.policy_store)
    result = await run_scenario(p, "employment_continuity")

    failures += _ok("scenario completed", result.execution is not None)
    failures += _ok(
        "12 decisions executed",
        len(result.execution.results) == 12,
    )

    # ── Phase 2: how many PayrollReceived events fired ──────────────────
    print("\n[2] EntityHydrator collapse — multi-provider into one IncomeProfile")
    payroll_events = [e for e in result.events if e.event_type.value == "payroll_received"]
    failures += _ok(
        "two PayrollReceived events arrived from the connector",
        len(payroll_events) == 2,
    )

    if len(payroll_events) >= 2:
        twn_evt, argyle_evt = payroll_events[0], payroll_events[1]
        print(
            f"     - first  feed: employer={twn_evt.employer!r:40} "
            f"gross=${twn_evt.gross_amount:,.0f}"
        )
        print(
            f"     - second feed: employer={argyle_evt.employer!r:40} "
            f"gross=${argyle_evt.gross_amount:,.0f}"
        )

    # ── Phase 3: IncomeProfile after both events hydrated ───────────────
    print("\n[3] IncomeProfile state after both feeds — last-write-wins")
    durable_records = list(p.store._durable._records)  # type: ignore[attr-defined]
    income_records = [
        r
        for r in durable_records
        if r.entity_type == "IncomeProfile"
        and r.superseded_at is None
        and (r.value or {}).get("application_id") == "app_continuity"
    ]
    failures += _ok(
        "exactly one IncomeProfile row exists (multi-provider collapse)",
        len(income_records) == 1,
    )

    if income_records:
        income = income_records[0].value
        print(f"     verified_income      : ${income.get('verified_income'):,.0f}")
        print(f"     payroll_verified     : {income.get('payroll_verified')}")
        print(f"     income_confidence    : {income.get('income_confidence_score')}")
        print(f"     stated_income        : ${income.get('stated_income'):,.0f}")
        # employer is NOT a field on IncomeProfile today — confirm that
        failures += _ok(
            "IncomeProfile carries no employer field (cannot detect name divergence)",
            "employer" not in income,
        )
        failures += _ok(
            "IncomeProfile carries no period_start / period_end (cannot detect "
            "tenure vs continuity)",
            "period_start" not in income and "period_end" not in income,
        )
        failures += _ok(
            "IncomeProfile carries no source / provider field (cannot record which "
            "provider's data won)",
            "source" not in income and "provider" not in income,
        )

    # ── Phase 4: income_verification trace — high confidence anyway ─────
    print("\n[4] income_verification trace — confidence from incomplete picture")
    all_app_traces = await p.trace_writer.list_for_application("app_continuity")
    iv_traces = [t for t in all_app_traces if t.decision_id == "income_verification"]
    failures += _ok("income_verification trace exists", len(iv_traces) == 1)

    if iv_traces:
        iv = iv_traces[0]
        out = iv.output_payload or {}
        confidence = out.get("income_confidence_score") or iv.confidence
        print(f"     proposed_outcome     : {iv.outcome.value}")
        print(f"     verified_income      : ${out.get('verified_income', 0):,.0f}")
        print(f"     income_confidence    : {confidence}")
        # The persona happily produces >= 0.85 from one provider's data.
        # That's the gap.
        failures += _ok(
            "persona produced >= 0.85 confidence DESPITE multi-provider conflict",
            (confidence or 0) >= 0.85,
        )
        # Quick scan — does any field on the trace mention "employer"?
        # output_payload + WorkJournalEntry text. Today the answer is no
        # because the persona has no employer concept.
        text_blob = " ".join(
            [
                str(out),
                str(iv.reasoning.model_dump() if iv.reasoning else {}),
                str(iv.policy_reasons or []),
            ]
        ).lower()
        failures += _ok(
            "trace mentions no employer-name discrepancy",
            "employer" not in text_blob,
        )

    # ── Phase 5: EDMS contains evidence the system can't yet leverage ───
    print("\n[5] EDMS holds Documents the system can't yet attach or reason over")
    docs = [
        r
        for r in durable_records
        if r.entity_type == "Document"
        and r.superseded_at is None
        and (
            (r.value or {}).get("application_id") == "app_continuity"
            or (r.value or {}).get("application_id") in (None, "")
        )
    ]
    claims = [
        r
        for r in durable_records
        if r.entity_type == "Claim"
        and r.superseded_at is None
        and (
            (r.value or {}).get("application_id") == "app_continuity"
            or (r.value or {}).get("application_id") in (None, "")
        )
    ]
    failures += _ok("4 Documents seeded in EDMS", len(docs) == 4)
    failures += _ok("4 Claims extracted across them", len(claims) == 4)

    unattached_docs = [
        d
        for d in docs
        if (d.value.get("applicant_id") in (None, ""))
    ]
    failures += _ok(
        "Beta Inc W-2 sits unattached (applicant_id=null) — entity-resolution gap",
        any(
            d.value.get("document_id") == "doc_continuity_beta_w2"
            for d in unattached_docs
        ),
    )
    pending_claims = [c for c in claims if c.value.get("status") == "pending"]
    failures += _ok(
        "Beta Inc employer claim pending verification",
        any(
            c.value.get("claim_id") == "claim_continuity_beta_employer"
            for c in pending_claims
        ),
    )

    # ── Phase 6: hidden gaps — what the trace SHOULD have surfaced ──────
    print("\n[6] HIDDEN GAPS — what the system cannot see today")

    # Employer-name divergence between the two payroll feeds.
    if len(payroll_events) >= 2:
        twn, ar = payroll_events[0], payroll_events[1]
        print(
            f"  - employer-name divergence: {twn.employer!r} vs {ar.employer!r} "
            f"(both verified) collapsed to whichever wrote last."
        )
        print(
            f"  - comp divergence: ${twn.gross_amount:,.0f} vs "
            f"${ar.gross_amount:,.0f} — only the winner survived."
        )

    # Tenure mismatch (stated vs claim-derived).
    tenure_claim = next(
        (
            c
            for c in claims
            if c.value.get("claim_id") == "claim_continuity_acme_tenure_start"
        ),
        None,
    )
    if tenure_claim:
        start = tenure_claim.value.get("field_value")
        verified_months = _months_between(start, date(2026, 4, 30))
        print(
            f"  - stated tenure 18 months; claim-derived tenure from "
            f"employment_start_date={start} is {verified_months} months. "
            f"Mismatch invisible to income_verification."
        )

    # Prior-employer continuity gap.
    print(
        "  - prior employer Beta Inc covers ~16 months of the 24-month window; "
        "today not joined to applicant, so income_verification sees a 0% "
        "prior-employer corroboration without flagging it."
    )

    # 1099 gig year.
    gig_doc = next(
        (
            d
            for d in docs
            if d.value.get("document_id") == "doc_continuity_1099_gig"
        ),
        None,
    )
    if gig_doc:
        print(
            f"  - 2022 gig year 1099 status='{gig_doc.value.get('status')}' — "
            f"would normally trigger 4506-C tax-transcript pull and a send_back "
            f"outcome. Today: silent."
        )

    # Sabbatical gap.
    print(
        "  - 2021 sabbatical year has no documents at all. A real "
        "employment_reconciliation step would queue a gap-letter request; "
        "today: silent."
    )

    # ── Phase 7: architectural moves the gap demands ───────────────────
    print("\n[7] What this scenario justifies (next slices)")
    print("  1. EmploymentRecord ObjectType — per-employer per-applicant, "
          "with start/end + source list, replacing the single IncomeProfile blob.")
    print("  2. VerificationAttempt ObjectType — append-only per (provider, "
          "applicant, time) so TWN $100k and Argyle $92k both survive.")
    print("  3. employment_reconciliation decision — DAG node before "
          "income_verification. Joins attempts into a timeline, produces a "
          "reconciliation_status, queues manual VOE on partial coverage.")
    print("  4. PolicyVersion clauses for continuity_coverage_pct, "
          "max_gap_days, min_corroborating_sources, "
          "stated_vs_verified_drift_max — auto bar lives in policy.")
    print("  5. send_back outcome — async path for 4506-C tax transcript "
          "fetch and applicant gap-letter request.")

    print("\n" + "=" * 72)
    print(f"failures: {failures}")
    print("=" * 72)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
