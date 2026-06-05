"""One generator, one set of guarantees — asserted per persona.

These tests are hermetic: they build signals from synthetic context +
the matched-rule evidence string (the same shape the decision engine
writes) and assert the banner ``explain()`` produces. No DB, no app.

Every persona's banner must:
  (a) name exactly the DRIVING signals (gated + failing/satisfying),
  (b) contain zero unsubstituted "{...}" template tokens,
  (c) repeat no driver phrase,
  (d) use outcome-correct vocabulary,
  (e) say "no data" — never "0" / "0%" — for an empty-sample input.
"""

import re

import pytest

from ui.explanations import (
    action_label,
    build_signals,
    explain,
    DECISION_LABELS,
)


def banner(decision_id, outcome, rule, ctx):
    signals = build_signals(decision_id, ctx, rule)
    return explain(outcome, rule, signals, DECISION_LABELS.get(decision_id))


def assert_no_tokens(text):
    assert "{" not in text and "}" not in text, f"template token leaked: {text!r}"


def assert_no_dup_phrases(text):
    # Split the driver list on commas / 'and' and check for repeats.
    body = text.split("—", 1)[-1].split(":", 1)[-1]
    parts = [p.strip(" .").lower() for p in re.split(r",|\band\b", body) if p.strip(" .")]
    assert len(parts) == len(set(parts)), f"duplicated phrase in: {text!r}"


# ── Credit ───────────────────────────────────────────────────────────


def test_credit_recommend_names_only_the_score():
    rule = "score=660, band='near_prime', thin_file=False, active_bankruptcy=False → recommend"
    ctx = {
        "credit_score": 660, "credit_band": "near_prime", "thin_file": False,
        "active_bankruptcy": False, "foreclosure_last_36_months": False,
        "no_derogatory_last_24_months": True,
    }
    text = banner("credit_assessment", "recommend", rule, ctx)
    assert "credit score 660" in text.lower()
    # passing signals must NOT be cited as a reason
    assert "bankruptcy" not in text.lower()
    assert "foreclosure" not in text.lower()
    assert_no_tokens(text)
    assert_no_dup_phrases(text)


def test_credit_block_uses_block_vocabulary():
    rule = "score=540, active_bankruptcy=True → block"
    ctx = {"credit_score": 540, "active_bankruptcy": True, "credit_band": "subprime"}
    text = banner("credit_assessment", "block", rule, ctx)
    assert text.startswith("Blocked")
    assert "active bankruptcy" in text.lower()
    assert_no_tokens(text)


# ── Fraud ────────────────────────────────────────────────────────────


def test_fraud_block_no_duplicate_watchlist():
    rule = "fraud_score=0.91, watchlist=True, synthetic=False → block"
    ctx = {
        "fraud_score": 0.91, "watchlist_match": True, "synthetic_identity_flag": False,
        "identity_match_confidence": 0.35, "document_authenticity_score": 0.4,
    }
    text = banner("fraud_screening", "block", rule, ctx)
    assert text.lower().count("watchlist") == 1, text
    assert "fraud score 0.91" in text.lower()
    # synthetic flag is False (passing) → not a driver
    assert "synthetic" not in text.lower()
    assert text.startswith("Blocked")
    assert_no_tokens(text)
    assert_no_dup_phrases(text)


# ── Employment ───────────────────────────────────────────────────────


def test_employment_escalate_cites_drivers_not_passing_drift():
    rule = ("reconciliation_status=partial, coverage=0% on 0 employer window(s), "
            "max_gap=730d, employer_match=0.00, comp_drift=0%, stated_drift=0% → escalate")
    ctx = {
        "reconciliation_status": "partial", "continuity_coverage_pct": 0.0,
        "max_gap_days": 730, "employer_name_match_confidence": 0.0,
        "stated_vs_verified_drift_pct": 0.0, "comp_drift_pct": 0.0,
        "prior_employer_count": 0, "employer_records": [],
    }
    text = banner("employment_reconciliation", "escalate", rule, ctx)
    low = text.lower()
    # the passing green signal (0% drift) must NOT be the reason
    assert "drift" not in low, text
    # real drivers present
    assert "max employment gap 730 days" in low
    assert "reconciliation" in low
    # empty-sample inputs render as no-data, never 0%
    assert "no data" in low
    assert "0%" not in low and " 0 " not in low
    # outcome-correct lead, no placeholders, no dups
    assert text.startswith("Escalated for senior review")
    assert_no_tokens(text)
    assert_no_dup_phrases(text)


def test_employment_no_placeholder_employer_tokens():
    rule = "reconciliation_status=partial, employer_match=0.00 → escalate"
    ctx = {"reconciliation_status": "partial", "employer_name_match_confidence": 0.0,
           "prior_employer_count": 0, "employer_records": []}
    text = banner("employment_reconciliation", "escalate", rule, ctx)
    assert "the stated employer" not in text
    assert "the verified record" not in text
    assert_no_tokens(text)


# ── Income ───────────────────────────────────────────────────────────


def test_income_block_names_discrepancy_and_confidence():
    rule = ("reconciliation_status=partial; verified $95,000 vs stated $150,000 "
            "(discrepancy 37%); confidence 0.65 → block")
    ctx = {
        "verified_income": 95000.0, "income_discrepancy_pct": 0.367,
        "income_confidence_score": 0.65, "reconciliation_status": "partial",
        "employment_type": "salaried", "payroll_verified": True,
    }
    text = banner("income_verification", "block", rule, ctx)
    low = text.lower()
    assert text.startswith("Blocked")
    assert "income discrepancy 36.7%" in low
    assert "income confidence 0.65" in low
    # payroll_verified is True (passing) → not a driver
    assert "payroll" not in low
    assert_no_tokens(text)
    assert_no_dup_phrases(text)


# ── Missing-data discipline (DTI / coverage class) ───────────────────


def test_missing_sample_renders_no_data_not_zero():
    rule = "coverage=0% on 0 employer window(s) → escalate"
    ctx = {"continuity_coverage_pct": 0.0, "prior_employer_count": 0, "employer_records": []}
    signals = build_signals("employment_reconciliation", ctx, rule)
    cov = next(s for s in signals if s["key"] == "continuity_coverage_pct")
    assert cov["state"] == "missing"
    assert cov["display"] == "no data"


def test_allow_lists_satisfied_checks_only():
    rule = "score=742, band='prime', thin_file=False, active_bankruptcy=False → allow"
    ctx = {"credit_score": 742, "credit_band": "prime", "thin_file": False,
           "active_bankruptcy": False, "no_derogatory_last_24_months": True}
    text = banner("credit_assessment", "allow", rule, ctx)
    assert text.startswith("Cleared to approve")
    assert "credit score 742" in text.lower()
    assert_no_tokens(text)
    assert_no_dup_phrases(text)


# ── Outcome-correct human-action vocabulary ──────────────────────────


@pytest.mark.parametrize("action,outcome,expected", [
    ("approved", "block", "Confirmed block"),
    ("approved", "escalate", "Confirmed escalation"),
    ("approved", "recommend", "Confirmed recommendation"),
    ("approved", "allow", "Approved (allow)"),
    ("overridden", "recommend", "Overridden to recommend"),
    ("auto_approved", "allow", "Auto-approved"),
])
def test_action_label_is_outcome_correct(action, outcome, expected):
    assert action_label(action, outcome) == expected


def test_block_never_reads_approved():
    assert action_label("approved", "block") != "approved"
    assert "approv" not in action_label("approved", "block").lower()
