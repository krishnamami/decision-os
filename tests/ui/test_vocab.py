"""Persona kind + vocabulary + pipeline-halt policy.

Routing personas judge their OWN action and must never speak applicant
vocabulary ("approve" / "allow" / "cleared to approve"). The canonical
underwriting layer keeps Senior UW and the router in agreement, and the
halt policy decides what suspends downstream work.
"""

import pytest

from ui.explanations import (
    VOCAB,
    action_label,
    build_signals,
    canonical_underwriting_state,
    downstream_should_run,
    explain,
    halts_pipeline,
    resolve_vocab,
    vocab_badge,
    ROUTING_ACTIONS,
)


def routing_banner(outcome, routing_target, ctx):
    state = canonical_underwriting_state(outcome, ctx)
    vocab = resolve_vocab("approval_routing", outcome)
    labels = {
        "kind": vocab["kind"], "vocab": vocab,
        "routing": {
            "underwriting_state": state,
            "routing_action": ROUTING_ACTIONS.get(routing_target, f"executing the {routing_target} step"),
        },
    }
    signals = build_signals("approval_routing", ctx, None)
    return explain(outcome, None, signals, labels)


# ── Routing persona acting on a DECLINE ──────────────────────────────


def test_routing_decline_badge_is_execute_family_never_allow():
    badge = vocab_badge("approval_routing", "allow")
    assert badge["text"] == "Auto-execute"
    assert "allow" not in badge["text"].lower()
    assert "approve" not in badge["text"].lower()


def test_routing_execute_tone_is_not_green():
    badge = vocab_badge("approval_routing", "allow")
    assert badge["tone"] == "neutral"
    assert badge["color"] not in ("emerald", "green")


def test_routing_banner_names_the_decline():
    ctx = {"routing_target": "decline_notice",
           "underwriting_decision": "{'outcome': 'decline'}",
           "applicant_dispute_flag": False}
    banner = routing_banner("allow", "decline_notice", ctx)
    assert "decline" in banner.lower()
    assert "approve" not in banner.lower()
    assert "allow" not in banner.lower()
    assert "cleared to approve" not in banner.lower()


def test_no_routing_vocab_entry_speaks_applicant_language():
    for outcome, entry in VOCAB["routing"].items():
        blob = " ".join([entry["badge"], entry["banner_verb"], entry["action_label"]]).lower()
        assert "approve" not in blob, (outcome, entry)
        assert "allow" not in blob, (outcome, entry)


def test_routing_action_label_is_not_approve():
    v = resolve_vocab("approval_routing", "allow")
    assert v["action_label"] == "Confirm routing"
    assert "approve" not in v["action_label"].lower()


# ── Canonical underwriting state (block vs decline) ──────────────────


def test_canonical_underwriting_block_with_explicit_decline():
    assert canonical_underwriting_state("block", {"underwriting_outcome": "decline"}) == "decline"


def test_canonical_underwriting_propagated_hard_block_stays_block():
    assert canonical_underwriting_state("block", {"any_upstream_hard_block": True}) == "block"


def test_canonical_reads_embedded_routing_decision_string():
    assert canonical_underwriting_state("allow", {"underwriting_decision": "{'outcome': 'decline'}"}) == "decline"


def test_senior_uw_renders_decline_not_block_badge():
    # raw engine outcome 'block' + explicit decline => badge says Decline
    state = canonical_underwriting_state("block", {"underwriting_outcome": "decline"})
    badge = vocab_badge("underwriting_decision", state)
    assert badge["text"] == "Decline"


# ── Pipeline-halt policy ─────────────────────────────────────────────


def test_fraud_block_halts():
    assert halts_pipeline("fraud_screening", "block") is True


def test_compliance_block_halts():
    assert halts_pipeline("compliance_check", "block") is True


def test_underwriting_decline_does_not_halt():
    assert halts_pipeline("underwriting_decision", "block", {"underwriting_outcome": "decline"}) is False


def test_underwriting_hard_block_halts():
    assert halts_pipeline("underwriting_decision", "block", {"any_upstream_hard_block": True}) is True


def test_routing_decision_never_halts_downstream():
    assert halts_pipeline("approval_routing", "allow") is False


def test_downstream_does_not_run_under_hard_block():
    upstream = [
        ("credit_assessment", "allow", {}),
        ("fraud_screening", "block", {}),          # hard block
        ("income_verification", "allow", {}),
    ]
    assert downstream_should_run(upstream) is False


def test_downstream_runs_for_a_decline():
    upstream = [
        ("underwriting_decision", "block", {"underwriting_outcome": "decline"}),
    ]
    assert downstream_should_run(upstream) is True


# ── Outcome-correct action verbs for routing ─────────────────────────


def test_action_label_routing_execute_is_not_approved():
    assert action_label("approved", "execute") == "Routing confirmed"
    assert "approv" not in action_label("approved", "execute").lower()
