from __future__ import annotations

from typing import Optional

from core.context_store import ContextBundle
from core.normalizer.models import DecisionOutcome
from core.policy_engine import PolicyDecision
from core.trace import SignalDirection

from .base import LendingPersona, OfflineReasoning, latest_object, make_signal


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

        if watchlist or synthetic or score >= 0.5:
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

        return OfflineReasoning(
            output_payload={
                "fraud_score": round(score, 3),
                "fraud_cleared": outcome == DecisionOutcome.ALLOW,
                "identity_match_confidence": round(id_match, 3),
                "document_authenticity_score": round(doc_auth, 3),
                "watchlist_match": watchlist,
                "synthetic_identity_flag": synthetic,
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
                f"synthetic={synthetic} → {outcome.value}"
            ),
            confidence_basis=(
                "High confidence in BLOCK on watchlist/synthetic hits — "
                "those are deterministic signals; lower confidence in soft "
                "ESCALATE branches because document authenticity is a "
                "probabilistic score."
            ),
            summary=(
                f"Fraud score {score:.2f}; proposed {outcome.value}."
            ),
        )


__all__ = ["FraudDetectionAgent"]
