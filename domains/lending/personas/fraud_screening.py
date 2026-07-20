from __future__ import annotations

import json
from typing import Optional

from core.context_store import ContextBundle
from core.normalizer.models import DecisionOutcome
from core.policy_engine import PolicyDecision
from core.trace import SignalDirection

from .base import LendingPersona, OfflineReasoning, latest_object, make_signal


def _as_list(val):
    """fraud_signal_records arrives as a JSON list or — depending on the view
    codec — a JSON string. Normalise to a Python list."""
    if val is None:
        return []
    if isinstance(val, str):
        try:
            val = json.loads(val)
        except (ValueError, TypeError):
            return []
    return list(val) if isinstance(val, (list, tuple)) else []


class FraudDetectionAgent(LendingPersona):
    """fraud_screening — high-risk gate. fraud_score, identity match,
    watchlist, synthetic identity. A BLOCK here halts the pipeline."""

    DEFAULT_AGENT_ID = "fraud_detection_agent_v1"

    def __init__(
        self,
        *,
        agent_id: str = DEFAULT_AGENT_ID,
        use_anthropic: bool = False,
        **kw,
    ):
        super().__init__(
            agent_id=agent_id,
            persona="fraud_detection_agent",
            decision_id="fraud_screening",
            use_anthropic=use_anthropic,
            **kw,
        )

    def _compute_offline(
        self, bundle: ContextBundle, policy: Optional[PolicyDecision]
    ) -> OfflineReasoning:
        fraud = latest_object(bundle, "FraudProfile", sort_by="generated_at") or {}
        score = float(fraud.get("fraud_score") or 0.0)
        id_match = float(fraud.get("identity_match_confidence") or 0.0)
        doc_auth = float(fraud.get("document_authenticity_score") or 1.0)
        watchlist = bool(fraud.get("watchlist_match") or False)
        synthetic = bool(fraud.get("synthetic_identity_flag") or False)

        signals = [
            make_signal(
                "fraud_score",
                round(score, 3),
                direction=(
                    SignalDirection.CONTRADICTS
                    if score >= 0.5
                    else SignalDirection.NEUTRAL
                ),
                weight=2.0,
            ),
            make_signal(
                "identity_match_confidence",
                round(id_match, 3),
                direction=(
                    SignalDirection.SUPPORTS
                    if id_match >= 0.95
                    else SignalDirection.NEUTRAL
                ),
            ),
            make_signal("document_authenticity_score", round(doc_auth, 3)),
        ]
        if watchlist:
            signals.append(
                make_signal(
                    "watchlist_match",
                    True,
                    direction=SignalDirection.CONTRADICTS,
                    weight=4.0,
                )
            )
        if synthetic:
            signals.append(
                make_signal(
                    "synthetic_identity_flag",
                    True,
                    direction=SignalDirection.CONTRADICTS,
                    weight=4.0,
                )
            )

        # Fraud threshold — Fannie Mae B3-5.4 standard is 0.70
        # TODO: read from tenant overlay_rules when bundle supports it
        fraud_threshold = 0.70
        if watchlist or synthetic or score >= fraud_threshold:
            outcome = DecisionOutcome.BLOCK
            confidence = 0.95
        elif doc_auth < 0.8:
            outcome = DecisionOutcome.ESCALATE
            confidence = 0.7
        elif score < 0.2 and id_match >= 0.95:
            outcome = DecisionOutcome.ALLOW
            confidence = 0.95
        elif score < 0.5:
            outcome = DecisionOutcome.RECOMMEND
            confidence = 0.7
        else:
            outcome = DecisionOutcome.ESCALATE
            confidence = 0.6

        # ── FR-E: fraud_signals rollup from the detectors (FR-B/C/D) ─────
        # The detectors are async + DB-bound and run as a batch upstream
        # (they write to fraud_signals); this sync, conn-less persona path
        # consumes their output via vw_fraud_screening_context. Branches
        # only escalate to BLOCK/ESCALATE, never relax an existing outcome.
        fraud_signals = _as_list(fraud.get("fraud_signal_records"))
        high_count = int(fraud.get("high_severity_signal_count") or 0)
        auto_block_count = int(fraud.get("auto_block_signal_count") or 0)

        fraud_conditions = []
        for sig in fraud_signals:
            if sig.get("resolved"):
                continue
            code = sig.get("condition_code")
            if code:
                fraud_conditions.append({
                    "code":        code,
                    "text":        sig.get("description", ""),
                    "severity":    sig.get("severity", "medium"),
                    "blocks":      sig.get("auto_block", False),
                    "signal_type": sig.get("signal_type"),
                })

        extra_reason = ""
        if auto_block_count > 0:
            outcome = DecisionOutcome.BLOCK
            confidence = max(confidence, 0.9)
            extra_reason = (
                f" {auto_block_count} auto-block fraud signal(s)."
            )
        elif fraud_signals and outcome in (
            DecisionOutcome.ALLOW, DecisionOutcome.RECOMMEND
        ):
            outcome = DecisionOutcome.ESCALATE
            confidence = max(confidence, 0.7)
            extra_reason = (
                f" {len(fraud_signals)} fraud signal(s) require review "
                f"({high_count} high/critical)."
            )

        if fraud_signals:
            signals.append(
                make_signal(
                    "fraud_signal_count",
                    len(fraud_signals),
                    direction=SignalDirection.CONTRADICTS,
                    weight=2.0,
                    notes=f"{high_count} high/critical, "
                          f"{auto_block_count} auto-block",
                )
            )

        # ── RA-PERSONA-A: evidence quality (advisory, OUTCOME-NEUTRAL) ────
        # Read the fraud_indicator evidence fact (RA-3E) the enricher placed on
        # the bundle. Corroborates the persona's own fraud read with QUALITY
        # signals + provenance but does NOT move the score/watchlist-driven
        # outcome above — so 16/16 holds. Clean loans carry fraud_populated=
        # False → no signal. Graceful: no evidence object → no signals.
        ev = latest_object(bundle, "evidence") or {}
        fraud_evidence_populated = bool(ev.get("fraud_populated"))
        fraud_evidence_conf = ev.get("fraud_indicator_confidence")
        fraud_evidence_conflicts = bool(ev.get("fraud_indicator_conflicts"))
        fraud_evidence_method = ev.get("fraud_indicator_method")
        conf_min = ev.get("income_confidence_min")
        if conf_min is None:
            conf_min = 0.75
        evidence_threshold_trace = ev.get("income_confidence_threshold_trace")
        if fraud_evidence_populated:
            signals.append(make_signal(
                "FRAUD_EVIDENCE_PRESENT",
                (round(float(fraud_evidence_conf), 3)
                 if fraud_evidence_conf is not None else True),
                direction=SignalDirection.CONTRADICTS, source="evidence",
                weight=2.0,
                notes=(f"Fraud-indicator evidence fact present "
                       f"(method: {fraud_evidence_method}). Corroborates the "
                       "fraud signals; UW review."),
            ))
            if (fraud_evidence_conf is not None
                    and fraud_evidence_conf < conf_min):
                signals.append(make_signal(
                    "FRAUD_LOW_CONFIDENCE", round(float(fraud_evidence_conf), 3),
                    direction=SignalDirection.NEUTRAL, source="evidence",
                    notes=(f"Fraud-indicator confidence {fraud_evidence_conf:.0%} "
                           f"below {conf_min:.0%} (Fannie B3-3.1-01) — weaker "
                           "signal, weigh accordingly."),
                ))

        return OfflineReasoning(
            output_payload={
                "fraud_score": round(score, 3),
                "fraud_cleared": outcome == DecisionOutcome.ALLOW,
                # RA-PERSONA-A: fraud-indicator evidence provenance (advisory).
                "fraud_evidence_populated": fraud_evidence_populated,
                "fraud_evidence_confidence": (
                    round(float(fraud_evidence_conf), 3)
                    if fraud_evidence_conf is not None else None
                ),
                "fraud_evidence_conflicts": fraud_evidence_conflicts,
                "fraud_evidence_method": fraud_evidence_method,
                "evidence_threshold_trace": evidence_threshold_trace,
                "identity_match_confidence": round(id_match, 3),
                "document_authenticity_score": round(doc_auth, 3),
                "watchlist_match": watchlist,
                "synthetic_identity_flag": synthetic,
                # FR-E additions
                "fraud_conditions": fraud_conditions,
                "fraud_signal_count": len(fraud_signals),
                "high_severity_count": high_count,
                "auto_block_signal_count": auto_block_count,
            },
            proposed_outcome=outcome,
            confidence=confidence,
            signals=signals,
            contradictions=[],
            hypothesis=(
                "Identity is genuine when fraud_score < 0.2, identity match "
                ">= 0.95, no watchlist hit and no synthetic-identity flag."
            ),
            conclusion=(
                f"fraud_score={score:.2f}, watchlist={watchlist}, "
                f"synthetic={synthetic}, signals={len(fraud_signals)} "
                f"→ {outcome.value}"
            ),
            confidence_basis=(
                "High confidence in BLOCK on watchlist/synthetic hits — "
                "those are deterministic signals; lower confidence in soft "
                "ESCALATE branches because document authenticity is a "
                "probabilistic score."
            ),
            summary=(
                f"Fraud score {score:.2f}; proposed {outcome.value}."
                + extra_reason
            ),
        )


__all__ = ["FraudDetectionAgent"]
