"""Story-driven review copy for the persona workbenches.

ONE generator, ``explain()``, produces the "Why this needs your review"
banner for every persona. There is no per-persona narrative code — a
persona contributes only DATA:

  SIGNAL_SPECS[decision_id]   → its rule's signals: label, format,
                                pass/fail polarity, and the tokens the
                                matched rule gates on.
  DECISION_LABELS[decision_id]→ a thin label map (subject noun).

``explain`` names only the signals that actually DROVE the outcome — the
gated conditions the application fails (block / escalate / recommend) or
satisfies (allow). It never cites an ungated signal, never cites a
passing signal as a reason to escalate, deduplicates drivers, renders
missing inputs as "no data" (never 0), and assembles the sentence from
real values so there are no template tokens to leave unsubstituted.

Public surface used by ``ui/edms_routes.py``:

  build_signals(decision_id, ctx, matched_rule)   → signal checklist
  explain(outcome, matched_rule, signals, labels) → the "Why" banner
  summarize_outcome(outcome)                       → pill colour + label
  action_label(human_action, outcome)             → outcome-correct verb
"""

from __future__ import annotations

import re
from typing import Any, Optional


# ─────────────────────────────────────────────────────────────────────
# Value helpers — tolerant of None / strings / mixed scales.
# ─────────────────────────────────────────────────────────────────────


def _as_float(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _as_bool(v: Any) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("true", "yes", "1", "t", "y"):
        return True
    if s in ("false", "no", "0", "f", "n"):
        return False
    return None


def _fmt_money(v: Any) -> str:
    f = _as_float(v)
    return "—" if f is None else f"${f:,.0f}"


def _fmt_pct(v: Any) -> str:
    f = _as_float(v)
    if f is None:
        return "—"
    if -1.5 <= f <= 1.5:
        f *= 100.0
    return f"{f:.1f}%"


def _humanize(v: Any) -> str:
    if v is None or v == "":
        return "—"
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".")
    return str(v).replace("_", " ")


def _title(v: Any) -> str:
    s = _humanize(v)
    return s[:1].upper() + s[1:] if s and s != "—" else s


def _g(ctx: dict, *keys: str, default: Any = None) -> Any:
    for k in keys:
        if k in ctx and ctx[k] is not None:
            return ctx[k]
    return default


# ─────────────────────────────────────────────────────────────────────
# SIGNAL SPECS — per decision, the signals the rule weighs.
#
#   key   : context field (or tuple, first present wins)
#   label : human label
#   kind  : bool | credit | pct | score | rate | money | money_or_pct
#           | days | count | recon | text
#   good  : (bool) the GOOD/green value
#   sev   : (bool) 'danger' → red when not-good, 'warn' → amber
#   fail / ok : (bool) prose fragments for the failing / passing cases
#   judge : (num) (direction, warn, danger); 'high' bigger-is-worse,
#           'low' smaller-is-worse; omit → neutral
#   gate  : tokens to look for in the matched rule (drives "driving
#           signal" detection + the ungated tag)
#   data_gate : companion key(s); when their sample is empty (0 / [] /
#           None) the signal is "no data" rather than a real 0.
# ─────────────────────────────────────────────────────────────────────


SIGNAL_SPECS: dict[str, list[dict[str, Any]]] = {
    "credit_assessment": [
        {"key": "credit_score", "label": "Credit score", "kind": "credit", "gate": ["credit_score", "score"]},
        {"key": "credit_band", "label": "Credit band", "kind": "text", "gate": ["band"]},
        {"key": "active_bankruptcy", "label": "Active bankruptcy", "kind": "bool", "good": False, "sev": "danger",
         "fail": "an active bankruptcy", "ok": "no active bankruptcy", "gate": ["bankruptcy"]},
        {"key": "foreclosure_last_36_months", "label": "Foreclosure (last 36 mo)", "kind": "bool", "good": False, "sev": "danger",
         "fail": "a foreclosure in the last 36 months", "ok": "no recent foreclosure", "gate": ["foreclosure"]},
        {"key": "thin_file", "label": "Thin credit file", "kind": "bool", "good": False, "sev": "warn",
         "fail": "a thin credit file", "ok": "a full credit file", "gate": ["thin_file"]},
        {"key": "no_derogatory_last_24_months", "label": "No derogatory (24 mo)", "kind": "bool", "good": True, "sev": "warn",
         "fail": "recent derogatory marks", "ok": "no derogatory marks in 24 months", "gate": ["derogatory"]},
        {"key": "derogatory_marks", "label": "Derogatory marks", "kind": "count", "judge": ("high", 1, 3), "gate": ["derogatory"]},
        {"key": "open_tradelines", "label": "Open tradelines", "kind": "count", "gate": ["tradeline"]},
        {"key": "credit_utilization", "label": "Credit utilization", "kind": "pct", "judge": ("high", 0.30, 0.50), "gate": ["utilization"]},
        {"key": "monthly_obligations", "label": "Monthly obligations", "kind": "money", "gate": ["obligation"]},
    ],
    "fraud_screening": [
        {"key": "fraud_score", "label": "Fraud score", "kind": "score", "judge": ("high", 0.20, 0.50), "gate": ["fraud_score"]},
        {"key": "identity_match_confidence", "label": "Identity match", "kind": "pct", "judge": ("low", 0.90, 0.70), "gate": ["identity_match", "identity"]},
        {"key": "document_authenticity_score", "label": "Document authenticity", "kind": "pct", "judge": ("low", 0.85, 0.60), "gate": ["document", "doc"]},
        {"key": "watchlist_match", "label": "Watchlist match", "kind": "bool", "good": False, "sev": "danger",
         "fail": "a watchlist match", "ok": "no watchlist match", "gate": ["watchlist"]},
        {"key": "synthetic_identity_flag", "label": "Synthetic identity flag", "kind": "bool", "good": False, "sev": "danger",
         "fail": "a synthetic-identity flag", "ok": "no synthetic-identity flag", "gate": ["synthetic"]},
    ],
    "compliance_check": [
        {"key": "all_hmda_fields_complete", "label": "HMDA fields complete", "kind": "bool", "good": True, "sev": "warn",
         "fail": "incomplete HMDA fields", "ok": "complete HMDA fields", "gate": ["hmda"]},
        {"key": "no_fair_lending_flags", "label": "No fair-lending flags", "kind": "bool", "good": True, "sev": "danger",
         "fail": "fair-lending flags", "ok": "no fair-lending flags", "gate": ["fair_lending"]},
        {"key": "fair_lending_violation", "label": "Fair-lending violation", "kind": "bool", "good": False, "sev": "danger",
         "fail": "a fair-lending violation", "ok": "no fair-lending violation", "gate": ["fair_lending", "violation"]},
        {"key": "state_rules_passed", "label": "State rules passed", "kind": "bool", "good": True, "sev": "danger",
         "fail": "a failed state-rule check", "ok": "state rules passed", "gate": ["state_rules", "state"]},
        {"key": "missing_required_disclosures", "label": "Missing disclosures", "kind": "bool", "good": False, "sev": "danger",
         "fail": "missing disclosures", "ok": "all disclosures present", "gate": ["disclosure"]},
        {"key": "regulatory_ambiguity", "label": "Regulatory ambiguity", "kind": "bool", "good": False, "sev": "warn",
         "fail": "regulatory ambiguity", "ok": "no regulatory ambiguity", "gate": ["ambiguity", "regulatory"]},
        {"key": "mixed_jurisdiction", "label": "Mixed jurisdiction", "kind": "bool", "good": False, "sev": "warn",
         "fail": "a mixed jurisdiction", "ok": "single jurisdiction", "gate": ["jurisdiction"]},
        {"key": "minor_data_gap", "label": "Minor data gap", "kind": "bool", "good": False, "sev": "warn",
         "fail": "a minor data gap", "ok": "no data gaps", "gate": ["minor_data_gap", "data_gap"]},
        {"key": "cd_timing_compliant", "label": "CD timing compliant", "kind": "bool", "good": True, "sev": "warn",
         "fail": "non-compliant CD timing", "ok": "compliant CD timing", "gate": ["cd_timing", "cd"]},
    ],
    "employment_reconciliation": [
        {"key": "reconciliation_status", "label": "Employment reconciliation", "kind": "recon", "gate": ["reconciliation_status", "reconciliation"]},
        {"key": "continuity_coverage_pct", "label": "Continuity coverage", "kind": "pct", "judge": ("low", 0.80, 0.50),
         "gate": ["continuity", "coverage"], "data_gate": ["prior_employer_count", "employer_records"]},
        {"key": "max_gap_days", "label": "Max employment gap", "kind": "days", "judge": ("high", 30, 90), "gate": ["gap"]},
        {"key": "employer_name_match_confidence", "label": "Employer name match", "kind": "pct", "judge": ("low", 0.85, 0.60),
         "gate": ["employer_name_match", "employer_match", "match"], "data_gate": ["prior_employer_count", "employer_records"]},
        {"key": "stated_vs_verified_drift_pct", "label": "Stated vs verified drift", "kind": "pct", "judge": ("high", 0.10, 0.25), "gate": ["stated_drift", "drift"]},
        {"key": "employer_on_watchlist", "label": "Employer on watchlist", "kind": "bool", "good": False, "sev": "danger",
         "fail": "employer on a watchlist", "ok": "employer not on a watchlist", "gate": ["watchlist"]},
    ],
    "income_verification": [
        {"key": ("stated_income", "_stated_income"), "label": "Stated income", "kind": "money", "gate": ["stated"]},
        {"key": "verified_income", "label": "Verified income", "kind": "money", "gate": ["verified"]},
        {"key": "income_discrepancy_pct", "label": "Income discrepancy", "kind": "pct", "judge": ("high", 0.10, 0.25), "gate": ["discrepancy"]},
        {"key": "employment_type", "label": "Employment type", "kind": "text", "gate": ["employment_type", "salaried", "self"]},
        {"key": "payroll_verified", "label": "Payroll verified", "kind": "bool", "good": True, "sev": "warn",
         "fail": "unverified payroll", "ok": "verified payroll", "gate": ["payroll"]},
        {"key": "income_confidence_score", "label": "Income confidence", "kind": "score", "judge": ("low", 0.90, 0.70), "gate": ["confidence"]},
        {"key": "income_stability", "label": "Income stability", "kind": "text", "gate": ["stability", "stable"]},
        {"key": "reconciliation_status", "label": "Employment reconciliation", "kind": "recon", "gate": ["reconciliation"]},
    ],
    "ltv_assessment": [
        {"key": ("ltv", "ltv_ratio"), "label": "Loan-to-value", "kind": "pct", "judge": ("high", 0.80, 0.95), "gate": ["ltv"]},
        {"key": "appraised_value", "label": "Appraised value", "kind": "money", "gate": ["appraised", "appraisal"]},
        {"key": ("purchase_price", "loan_amount"), "label": "Purchase price", "kind": "money", "gate": ["purchase", "price"]},
        {"key": "down_payment", "label": "Down payment", "kind": "money", "gate": ["down_payment", "down"]},
        {"key": "appraisal_disputed", "label": "Appraisal disputed", "kind": "bool", "good": False, "sev": "warn",
         "fail": "a disputed appraisal", "ok": "an undisputed appraisal", "gate": ["dispute"]},
        {"key": "condition_rating", "label": "Condition rating", "kind": "text", "gate": ["condition"]},
        {"key": ("conforming_limit", "max_allowable_ltv"), "label": "Conforming limit", "kind": "money_or_pct", "gate": ["conforming", "limit", "max_allowable"]},
        {"key": "loan_amount_classification", "label": "Loan classification", "kind": "text", "gate": ["classification", "conforming"]},
    ],
    "dti_calculation": [
        {"key": ("dti_back", "dti", "dti_ratio"), "label": "Back-end DTI", "kind": "pct", "judge": ("high", 0.36, 0.50), "gate": ["dti"]},
        {"key": "dti_front", "label": "Front-end DTI", "kind": "pct", "judge": ("high", 0.28, 0.40), "gate": ["dti_front", "front"]},
        {"key": ("proposed_payment", "piti_monthly"), "label": "Proposed payment (PITI)", "kind": "money", "gate": ["piti", "payment"]},
        {"key": "monthly_obligations", "label": "Monthly obligations", "kind": "money", "gate": ["obligation"]},
        {"key": ("qualifying_monthly_income", "monthly_income"), "label": "Qualifying monthly income", "kind": "money", "gate": ["income"]},
        {"key": "income_confidence", "label": "Income confidence", "kind": "score", "judge": ("low", 0.90, 0.70), "gate": ["confidence", "income_confidence"]},
    ],
    "product_eligibility": [
        {"key": "program_name", "label": "Program", "kind": "text", "gate": ["program"]},
        {"key": "product_name", "label": "Product", "kind": "text", "gate": ["product"]},
        {"key": ("governing_authority", "authority"), "label": "Governing authority", "kind": "text", "gate": ["authority"]},
        {"key": "credit_band", "label": "Credit band", "kind": "text", "gate": ["band"]},
        {"key": ("ltv_ratio", "ltv"), "label": "LTV vs product max", "kind": "pct", "judge": ("high", 0.80, 0.95), "gate": ["ltv"]},
        {"key": ("dti_ratio", "dti"), "label": "DTI vs product max", "kind": "pct", "judge": ("high", 0.43, 0.50), "gate": ["dti"]},
        {"key": "within_conforming_limit", "label": "Within conforming limit", "kind": "bool", "good": True, "sev": "warn",
         "fail": "over the conforming limit", "ok": "within the conforming limit", "gate": ["conforming", "limit"]},
        {"key": "guideline_exception_required", "label": "Guideline exception required", "kind": "bool", "good": False, "sev": "warn",
         "fail": "a guideline exception", "ok": "no guideline exception", "gate": ["exception"]},
    ],
    "rate_pricing": [
        {"key": ("interest_rate", "rate"), "label": "Interest rate", "kind": "rate", "gate": ["rate", "interest"]},
        {"key": "locked_rate", "label": "Locked rate", "kind": "rate", "gate": ["lock", "locked"]},
        {"key": "llpa_adjustment", "label": "LLPA adjustment", "kind": "rate", "gate": ["llpa"]},
        {"key": "rate_within_normal_band", "label": "Rate within normal band", "kind": "bool", "good": True, "sev": "warn",
         "fail": "a rate outside the normal band", "ok": "a rate within the normal band", "gate": ["normal_band", "band"]},
        {"key": "concurrent_rate_lock_conflict", "label": "Rate-lock conflict", "kind": "bool", "good": False, "sev": "danger",
         "fail": "a rate-lock conflict", "ok": "no rate-lock conflict", "gate": ["lock_conflict", "conflict"]},
        {"key": "rate_exceeds_usury", "label": "Exceeds usury cap", "kind": "bool", "good": False, "sev": "danger",
         "fail": "a rate above the usury cap", "ok": "a rate below the usury cap", "gate": ["usury"]},
        {"key": ("rate_schedule_name", "loan_type"), "label": "Rate schedule", "kind": "text", "gate": ["schedule", "loan_type"]},
        {"key": "arm_index_type", "label": "ARM index", "kind": "text", "gate": ["arm", "index"]},
    ],
    "underwriting_decision": [
        {"key": "underwriting_outcome", "label": "AUS recommendation", "kind": "text", "gate": ["underwriting_outcome", "outcome"]},
        {"key": "risk_score", "label": "Composite risk score", "kind": "score", "judge": ("high", 0.50, 0.80), "gate": ["risk"]},
        {"key": "any_upstream_hard_block", "label": "Any upstream hard block", "kind": "bool", "good": False, "sev": "danger",
         "fail": "an upstream hard block", "ok": "no upstream hard block", "gate": ["upstream", "block"]},
        {"key": "all_upstream_auto_cleared", "label": "All upstream auto-cleared", "kind": "bool", "good": True, "sev": "warn",
         "fail": "upstream not all auto-cleared", "ok": "all upstream auto-cleared", "gate": ["auto_cleared", "upstream"]},
        {"key": "senior_underwriter_review_required", "label": "Senior review required", "kind": "bool", "good": False, "sev": "warn",
         "fail": "senior review required", "ok": "no senior review required", "gate": ["senior", "review"]},
    ],
    "closing_readiness": [
        {"key": "all_conditions_cleared", "label": "All conditions cleared", "kind": "bool", "good": True, "sev": "warn",
         "fail": "outstanding conditions", "ok": "all conditions cleared", "gate": ["conditions"]},
        {"key": "cd_timing_compliant", "label": "CD timing compliant", "kind": "bool", "good": True, "sev": "danger",
         "fail": "non-compliant CD timing", "ok": "compliant CD timing", "gate": ["cd_timing", "cd"]},
        {"key": "title_clear", "label": "Title clear", "kind": "bool", "good": True, "sev": "danger",
         "fail": "an unclear title", "ok": "a clear title", "gate": ["title"]},
        {"key": "title_defect", "label": "Title defect", "kind": "bool", "good": False, "sev": "danger",
         "fail": "a title defect", "ok": "no title defect", "gate": ["title_defect", "title"]},
        {"key": "lien_dispute", "label": "Lien dispute", "kind": "bool", "good": False, "sev": "danger",
         "fail": "a lien dispute", "ok": "no lien dispute", "gate": ["lien"]},
        {"key": "insurance_gap", "label": "Insurance gap", "kind": "bool", "good": False, "sev": "warn",
         "fail": "an insurance gap", "ok": "no insurance gap", "gate": ["insurance"]},
        {"key": ("total_closing_costs", "closing_costs"), "label": "Total closing costs", "kind": "money", "gate": ["closing_cost", "cost"]},
        {"key": "rate_lock_expiry", "label": "Rate-lock expiry", "kind": "text", "gate": ["lock_expiry", "expiry"]},
        {"key": "zero_tolerance_fee_count", "label": "Zero-tolerance fee count", "kind": "count", "judge": ("high", 1, 3), "gate": ["tolerance", "fee"]},
    ],
    "approval_routing": [
        {"key": "routing_target", "label": "Routing target", "kind": "text", "gate": ["routing"]},
        {"key": "timeline", "label": "Timeline", "kind": "text", "gate": ["timeline"]},
        {"key": "communication_channel", "label": "Channel", "kind": "text", "gate": ["channel", "communication"]},
        {"key": "applicant_dispute_flag", "label": "Applicant dispute", "kind": "bool", "good": False, "sev": "warn",
         "fail": "an applicant dispute", "ok": "no applicant dispute", "gate": ["dispute"]},
    ],
}


# The only other per-persona data: a subject noun for the banner lead.
DECISION_LABELS: dict[str, dict[str, str]] = {
    "credit_assessment": {"subject": "credit"},
    "fraud_screening": {"subject": "fraud screen"},
    "compliance_check": {"subject": "compliance"},
    "employment_reconciliation": {"subject": "employment"},
    "income_verification": {"subject": "income"},
    "ltv_assessment": {"subject": "collateral"},
    "dti_calculation": {"subject": "DTI"},
    "product_eligibility": {"subject": "product fit"},
    "rate_pricing": {"subject": "pricing"},
    "underwriting_decision": {"subject": "underwriting"},
    "closing_readiness": {"subject": "closing"},
    "approval_routing": {"subject": "routing"},
}


# ─────────────────────────────────────────────────────────────────────
# Signal rendering
# ─────────────────────────────────────────────────────────────────────


def _judge_num(judge: Optional[tuple], f: Optional[float]) -> str:
    if not judge or f is None:
        return "neutral"
    direction, warn, danger = judge
    if direction == "high":
        return "bad" if f >= danger else ("warn" if f >= warn else "good")
    return "bad" if f <= danger else ("warn" if f <= warn else "good")


def _credit_state(score: Optional[float]) -> str:
    if score is None:
        return "neutral"
    return "good" if score >= 680 else ("warn" if score >= 620 else "bad")


def _resolve_key(ctx: dict, key: Any) -> tuple[str, Any]:
    keys = key if isinstance(key, tuple) else (key,)
    for k in keys:
        if k in ctx and ctx[k] is not None:
            return k, ctx[k]
    return keys[0], None


def _no_data(ctx: dict, data_gate: Any) -> bool:
    """True when a signal's underlying sample is empty — so a 0 means
    'no data', not a real zero."""
    keys = data_gate if isinstance(data_gate, (list, tuple)) else [data_gate]

    def empty(v: Any) -> bool:
        if v is None:
            return True
        if isinstance(v, (list, tuple, dict, str)):
            return len(v) == 0
        f = _as_float(v)
        return f is not None and f == 0

    return all(empty(ctx.get(k)) for k in keys)


def _is_gated(spec: dict, rule_text: Optional[str]) -> bool:
    if not rule_text:
        return False
    low = rule_text.lower()
    tokens = spec.get("gate") or [spec["key"]]
    return any(str(t).lower() in low for t in tokens)


def _render_signal(spec: dict, ctx: dict, rule_text: Optional[str]) -> dict:
    field, value = _resolve_key(ctx, spec["key"])
    kind = spec["kind"]
    present = value is not None
    state = "neutral"
    display = "—"

    # Empty-sample guard: an absent input must never read as a real 0.
    no_data = present and "data_gate" in spec and _no_data(ctx, spec["data_gate"])

    if not present:
        state = "missing"
    elif no_data:
        state, display = "missing", "no data"
    elif kind == "bool":
        b = _as_bool(value)
        display = "Yes" if b else "No"
        good = spec.get("good")
        if b is None or good is None:
            state = "neutral"
        elif b == good:
            state = "good"
        else:
            state = "bad" if spec.get("sev", "danger") == "danger" else "warn"
    elif kind == "credit":
        f = _as_float(value)
        display = str(int(f)) if f is not None else _humanize(value)
        state = _credit_state(f)
    elif kind == "pct":
        display = _fmt_pct(value)
        state = _judge_num(spec.get("judge"), _as_float(value))
    elif kind == "score":
        f = _as_float(value)
        display = f"{f:.2f}" if f is not None else _humanize(value)
        state = _judge_num(spec.get("judge"), f)
    elif kind == "rate":
        f = _as_float(value)
        display = f"{f:.3f}%" if f is not None else _humanize(value)
        state = "neutral"
    elif kind == "money":
        display = _fmt_money(value)
    elif kind == "money_or_pct":
        f = _as_float(value)
        display = _fmt_pct(value) if (f is not None and abs(f) <= 1.5) else _fmt_money(value)
    elif kind == "days":
        f = _as_float(value)
        display = f"{int(f)} days" if f is not None else _humanize(value)
        state = _judge_num(spec.get("judge"), f)
    elif kind == "count":
        f = _as_float(value)
        display = str(int(f)) if f is not None else _humanize(value)
        state = _judge_num(spec.get("judge"), f)
    elif kind == "recon":
        display = _title(value)
        state = {"auto_verified": "good", "verified": "good",
                 "partial": "warn", "conflict": "bad"}.get(str(value).lower(), "neutral")
    else:  # text
        display = _title(value)

    gated = _is_gated(spec, rule_text)
    return {
        "key": field,
        "label": spec["label"],
        "display": display,
        "state": state,                     # good | bad | warn | neutral | missing
        "present": present,
        "gated": gated,
        "ungated": present and bool(rule_text) and not gated,
        "kind": kind,
        "good": spec.get("good"),
        "fail": spec.get("fail"),
        "ok": spec.get("ok"),
    }


def build_signals(
    decision_id: str, ctx: dict, matched_rule: Optional[str] = None
) -> list[dict]:
    """Render the signal checklist. Present signals come back with a
    label, formatted value, colour state, gated flag, and the fragments
    ``explain`` needs. Truly-absent signals are dropped; signals whose
    sample is empty render as 'no data' (state 'missing')."""
    specs = SIGNAL_SPECS.get(decision_id, [])
    ctx = dict(ctx or {})
    # Derive stated income when only the verified figure + discrepancy
    # are present (stated = verified / (1 − discrepancy)).
    if decision_id == "income_verification" and ctx.get("stated_income") is None:
        ver = _as_float(ctx.get("verified_income"))
        disc = _as_float(ctx.get("income_discrepancy_pct"))
        if ver is not None and disc is not None and 0 < disc < 0.95:
            ctx["_stated_income"] = round(ver / (1.0 - disc), -2)
    out = []
    for spec in specs:
        rendered = _render_signal(spec, ctx, matched_rule)
        if rendered["present"]:
            out.append(rendered)
    return out


# ─────────────────────────────────────────────────────────────────────
# explain() — the one banner generator
# ─────────────────────────────────────────────────────────────────────


_ADVERSE = ("block", "escalate", "recommend")
_LEAD = {
    "block": "Blocked",
    "escalate": "Escalated for senior review",
    "recommend": "Flagged for your decision",
    "allow": "Cleared to approve",
}
_STATE_RANK = {"bad": 0, "warn": 1, "missing": 2}


def _natural_join(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def _drivers(outcome: str, matched_rule: Optional[str], signals: list[dict]) -> list[dict]:
    """The signals that actually drove the outcome: gated conditions the
    application fails (adverse) or satisfies (allow). When the rule text
    is known, an ungated signal can never be a driver."""
    adverse = outcome in _ADVERSE
    out = []
    for s in signals:
        if not s.get("present"):
            continue
        if matched_rule and not s.get("gated"):
            continue
        st = s.get("state")
        if adverse and st in ("bad", "warn", "missing"):
            out.append(s)
        elif outcome == "allow" and st == "good":
            out.append(s)
    if adverse:
        out.sort(key=lambda s: _STATE_RANK.get(s.get("state"), 9))
    return out


def _phrase(signal: dict, outcome: str) -> str:
    if signal.get("state") == "missing":
        return f"{signal['label'].lower()}: no data"
    if signal.get("kind") == "bool":
        if outcome == "allow":
            return signal.get("ok") or f"{signal['label'].lower()} confirmed"
        return signal.get("fail") or signal["label"].lower()
    value = signal["display"]
    if signal.get("kind") in ("recon", "text"):
        value = value.lower()
    return f"{signal['label'].lower()} {value}"


def _dedup(phrases: list[str]) -> list[str]:
    seen, out = set(), []
    for p in phrases:
        k = p.lower().strip()
        if k and k not in seen:
            seen.add(k)
            out.append(p)
    return out


def _cap(text: str) -> str:
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text[:1].upper() + text[1:] if text else text


def explain(
    outcome: Optional[str],
    matched_rule: Optional[str],
    signals: list[dict],
    labels: Optional[dict] = None,
) -> str:
    """The plain-English "Why this needs your review" banner. Names only
    the driving signals, deduplicated, with no template tokens and 'no
    data' for missing inputs. Identical for every persona."""
    outcome = (outcome or "").lower()
    labels = labels or {}
    subject = labels.get("subject")
    drivers = _drivers(outcome, matched_rule, signals)
    phrases = _dedup([_phrase(s, outcome) for s in drivers])
    lead = _LEAD.get(outcome, "Needs your review")

    if outcome == "allow":
        if phrases:
            body = f"{lead}: {_natural_join(phrases)} — all within the rule's thresholds."
        else:
            body = f"{lead}: all gated checks pass."
        return _cap(body)

    if not phrases:
        # Gated drivers couldn't be identified — state the outcome plainly
        # rather than inventing a reason.
        noun = f" {subject}" if subject else ""
        return _cap(f"{lead} — the matched{noun} rule's thresholds were not met.")

    all_missing = all(s.get("state") == "missing" for s in drivers)
    joined = _natural_join(phrases)
    if all_missing:
        return _cap(f"{lead} — insufficient data: {joined}.")
    return _cap(f"{lead} — driven by {joined}.")


# ─────────────────────────────────────────────────────────────────────
# Outcome / action vocabulary
# ─────────────────────────────────────────────────────────────────────


_OUTCOME_META = {
    "allow": ("emerald", "Approve recommended"),
    "recommend": ("amber", "Recommendation — needs a decision"),
    "escalate": ("orange", "Escalated — senior review"),
    "block": ("rose", "Hard block"),
}


def summarize_outcome(outcome: Optional[str]) -> dict:
    color, label = _OUTCOME_META.get(str(outcome or "").lower(), ("slate", "Pending"))
    return {"color": color, "label": label}


def action_label(human_action: Optional[str], outcome: Optional[str] = None) -> Optional[str]:
    """Outcome-correct verb for a recorded human action. A confirmed
    BLOCK reads 'Confirmed block', never 'approved'."""
    a = str(human_action or "").lower()
    o = str(outcome or "").lower()
    if not a:
        return None
    if a == "overridden":
        return f"Overridden to {o}" if o else "Overridden"
    if a in ("auto_approved", "auto_verified"):
        return "Auto-approved"
    if a == "info_requested":
        return "Information requested"
    if a == "approved":
        return {
            "block": "Confirmed block",
            "escalate": "Confirmed escalation",
            "recommend": "Confirmed recommendation",
            "allow": "Approved (allow)",
        }.get(o, "Approved")
    return a.replace("_", " ").capitalize()
