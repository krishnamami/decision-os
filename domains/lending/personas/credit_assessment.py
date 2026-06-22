from __future__ import annotations

import json
from typing import Optional

from core.context_store import ContextBundle
from core.normalizer.models import DecisionOutcome
from core.policy_engine import PolicyDecision
from core.trace import SignalDirection

from .base import LendingPersona, OfflineReasoning, latest_object, make_signal


def _as_list(val):
    """Credit context arrays (tradelines / credit_findings) arrive as a JSON
    list or — depending on the view codec — a JSON string. Normalise to a
    Python list."""
    if val is None:
        return []
    if isinstance(val, str):
        try:
            val = json.loads(val)
        except (ValueError, TypeError):
            return []
    return list(val) if isinstance(val, (list, tuple)) else []


_BAND_THRESHOLDS = [
    (760, "super_prime"),
    (700, "prime"),
    (660, "near_prime"),
    (600, "subprime"),
    (0, "deep_subprime"),
]


class CreditRiskAgent(LendingPersona):
    """credit_assessment — interpret bureau pull, emit credit_score +
    credit_band."""

    DEFAULT_AGENT_ID = "credit_risk_agent_v1"

    def __init__(
        self,
        *,
        agent_id: str = DEFAULT_AGENT_ID,
        use_anthropic: bool = False,
        **kw,
    ):
        super().__init__(
            agent_id=agent_id,
            persona="credit_risk_agent",
            decision_id="credit_assessment",
            use_anthropic=use_anthropic,
            **kw,
        )

    def _compute_offline(
        self, bundle: ContextBundle, policy: Optional[PolicyDecision]
    ) -> OfflineReasoning:
        credit = latest_object(bundle, "CreditProfile", sort_by="pulled_at") or {}
        # Qualify on the governing (lower) score when a co-borrower exists.
        # The view's governing_credit_score falls back to the primary's score
        # for single-borrower loans, so this is a no-op there.
        score = credit.get("governing_credit_score")
        if score is None:
            score = credit.get("credit_score")
        active_bk = bool(credit.get("active_bankruptcy") or False)
        foreclosure_36 = bool(credit.get("foreclosure_last_36_months") or False)
        thin_file = bool(credit.get("thin_file") or False)
        no_derog_24 = bool(credit.get("no_derogatory_last_24_months") or False)

        band = _band_for(score)
        if thin_file:
            band = "thin_file"

        signals = [
            make_signal("credit_score", score, source="bureau"),
            make_signal("credit_band", band, source="derived"),
            make_signal("derogatory_marks", credit.get("derogatory_marks", 0)),
            make_signal("open_tradelines", credit.get("open_tradelines", 0)),
            make_signal(
                "credit_utilization",
                credit.get("credit_utilization"),
                direction=(
                    SignalDirection.CONTRADICTS
                    if (credit.get("credit_utilization") or 0) > 0.6
                    else SignalDirection.NEUTRAL
                ),
            ),
        ]
        if active_bk or foreclosure_36:
            signals.append(
                make_signal(
                    "derogatory_event",
                    "active_bankruptcy" if active_bk else "foreclosure_last_36_months",
                    direction=SignalDirection.CONTRADICTS,
                    weight=3.0,
                )
            )

        if active_bk or foreclosure_36:
            outcome = DecisionOutcome.BLOCK
        elif score is None or thin_file:
            outcome = DecisionOutcome.ESCALATE
        elif score >= 680 and no_derog_24:
            outcome = DecisionOutcome.ALLOW
        elif score >= 600:
            outcome = DecisionOutcome.RECOMMEND
        elif score < 580:
            # Below the FHA floor (580) — uninsurable on any agency program.
            outcome = DecisionOutcome.BLOCK
        else:
            outcome = DecisionOutcome.ESCALATE

        # ── CR-E: tradeline + findings resolvers ─────────────────────────
        # Only engages when the CR-A entity tables hold rows for this loan;
        # otherwise the view returns empty arrays and outcome is unchanged.
        # These branches can only escalate the outcome to BLOCK, never relax
        # an existing one.
        tradelines = _as_list(credit.get("tradelines"))
        findings = _as_list(credit.get("credit_findings"))
        conditions: list[dict] = []
        tradeline_obligations = None
        extra_reason = ""

        # RA-4B: catalogue-resolved credit rules injected via the bundle (the
        # runner loaded them through rule_loader; resolvers stay sync/DB-less).
        credit_rules_obj = latest_object(bundle, "credit_rules") or {}
        credit_rule_values = credit_rules_obj or None
        credit_rule_trace = {
            k: {"governed_by": v.get("governed_by"), "layers": v.get("layers")}
            for k, v in credit_rules_obj.items()
        } if credit_rules_obj else None

        if tradelines:
            from core.credit.tradeline_analyzer import TradelineAnalyzer

            tl_result = TradelineAnalyzer(credit_rule_values).analyze_all(tradelines)
            conditions.extend(tl_result.get("all_conditions", []))
            if tl_result["total_obligations"] > 0:
                tradeline_obligations = tl_result["total_obligations"]
            if tl_result.get("has_disputed_derogatory"):
                outcome = DecisionOutcome.BLOCK
                extra_reason += (
                    " Disputed derogatory account(s) ("
                    f"{', '.join(tl_result['disputed_accounts'])}) must be "
                    "resolved before closing."
                )

        if findings:
            from core.credit.findings_resolver import CreditFindingsResolver

            fnd_result = CreditFindingsResolver(credit_rule_values).resolve_all(findings)
            conditions.extend(fnd_result.get("conditions", []))
            if fnd_result["overall_status"] == "block":
                outcome = DecisionOutcome.BLOCK
                extra_reason += (
                    " Credit finding blocks: "
                    f"{fnd_result['blocking_count']} finding(s)."
                )

        # Independent guard: disputed-derogatory count straight from the view
        # (covers loans whose tradeline rows weren't expanded above).
        disputed_count = int(credit.get("disputed_derogatory_count") or 0)
        if disputed_count > 0 and outcome is not DecisionOutcome.BLOCK:
            outcome = DecisionOutcome.BLOCK
            extra_reason += (
                f" {disputed_count} disputed derogatory account(s) must be "
                "resolved before closing."
            )

        confidence = 0.95 if score and not thin_file else 0.5

        return OfflineReasoning(
            output_payload={
                "credit_score": score,
                "credit_band": band,
                "thin_file": thin_file,
                "active_bankruptcy": active_bk,
                "foreclosure_last_36_months": foreclosure_36,
                "no_derogatory_last_24_months": no_derog_24,
                # CR-E additions
                "conditions": conditions,
                "tradeline_findings": bool(tradelines),
                "tradeline_count": len(tradelines),
                "tradeline_obligations": tradeline_obligations,
                "credit_findings_count": len(findings),
                "disputed_derogatory_count": disputed_count,
                # RA-4B: catalogue provenance per credit rule (governed_by +
                # federal/agency/overlay layers) for the workbench.
                "credit_rule_trace": credit_rule_trace,
            },
            proposed_outcome=outcome,
            confidence=confidence,
            signals=signals,
            contradictions=[],
            hypothesis=(
                "Credit profile is acceptable when score >= 680, no active "
                "bankruptcy or recent foreclosure, no derogatory marks in "
                "the last 24 months."
            ),
            conclusion=(
                f"score={score}, band={band!r}, thin_file={thin_file}, "
                f"active_bankruptcy={active_bk} → {outcome.value}"
            ),
            confidence_basis=(
                "High confidence on a populated bureau pull; reduced when "
                "the file is thin or the score is unavailable."
            ),
            summary=(
                f"Credit score {score} ({band!r}) — proposed {outcome.value}."
                + extra_reason
            ),
        )


def _band_for(score: Optional[int]) -> str:
    if score is None:
        return "thin_file"
    for threshold, label in _BAND_THRESHOLDS:
        if score >= threshold:
            return label
    return "deep_subprime"


__all__ = ["CreditRiskAgent"]
