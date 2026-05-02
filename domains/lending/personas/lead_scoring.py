from __future__ import annotations

from typing import Optional

from core.context_store import ContextBundle
from core.normalizer.models import DecisionOutcome
from core.policy_engine import PolicyDecision
from core.trace import SignalDirection

from .base import LendingPersona, OfflineReasoning, first_object, make_signal


class LeadQualificationAgent(LendingPersona):
    """lead_scoring — gauge inbound lead intent.

    Computes intent_score from utm + session signals, exposes channel +
    source so the boundary's `automate_if`, `recommend_if`, and `block_if`
    clauses can match. Risk is low; this runs auto_execute when intent
    is strong and the channel is digital or api_partner."""

    DEFAULT_AGENT_ID = "lead_qualification_agent_v1"

    def __init__(
        self,
        *,
        agent_id: str = DEFAULT_AGENT_ID,
        use_anthropic: bool = False,
        **kw,
    ):
        super().__init__(
            agent_id=agent_id,
            persona="lead_qualification_agent",
            decision_id="lead_scoring",
            use_anthropic=use_anthropic,
            **kw,
        )

    def _compute_offline(
        self, bundle: ContextBundle, policy: Optional[PolicyDecision]
    ) -> OfflineReasoning:
        applicant = first_object(bundle, "Applicant") or {}
        utm = applicant.get("utm_params") or {}
        session = applicant.get("session_behavior") or {}
        prior_inquiries = int(applicant.get("prior_inquiries") or 0)
        channel = applicant.get("channel") or utm.get("source") or "digital"
        source = applicant.get("lead_source") or utm.get("medium") or "web_form"

        # Crude intent: more pages viewed + more time + low prior-inquiry
        # spam → higher intent. Bounded [0, 1].
        pages = float(session.get("pages_viewed") or session.get("pages") or 1)
        seconds = float(session.get("time_on_site_seconds") or 60)
        intent_score = min(
            1.0,
            0.35
            + 0.05 * pages
            + 0.0008 * seconds
            - 0.05 * max(0, prior_inquiries - 2),
        )
        ambiguous_identity = bool(applicant.get("ambiguous_identity") or False)

        signals = [
            make_signal(
                "intent_score",
                round(intent_score, 3),
                direction=(
                    SignalDirection.SUPPORTS
                    if intent_score >= 0.7
                    else SignalDirection.NEUTRAL
                ),
                weight=1.0,
                source="session",
            ),
            make_signal("channel", channel, source="utm_params"),
            make_signal("lead_source", source, source="utm_params"),
            make_signal(
                "prior_inquiries", prior_inquiries, source="applicant"
            ),
        ]
        if ambiguous_identity:
            signals.append(
                make_signal(
                    "ambiguous_identity",
                    True,
                    direction=SignalDirection.CONTRADICTS,
                    weight=2.0,
                    source="kyc",
                )
            )

        # Boundary translation:
        #   automate_if   intent_score >= 0.7 AND channel in [digital, api_partner]
        #   recommend_if  0.5 <= intent_score < 0.7
        if ambiguous_identity:
            outcome = DecisionOutcome.ESCALATE
        elif intent_score >= 0.7 and channel in ("digital", "api_partner"):
            outcome = DecisionOutcome.ALLOW
        elif intent_score >= 0.5:
            outcome = DecisionOutcome.RECOMMEND
        else:
            outcome = DecisionOutcome.ESCALATE

        confidence = 0.6 + 0.4 * intent_score
        if ambiguous_identity:
            confidence = min(confidence, 0.5)

        return OfflineReasoning(
            output_payload={
                "intent_score": round(intent_score, 3),
                "channel": channel,
                "source": source,
                "ambiguous_identity": ambiguous_identity,
                "lead_priority": (
                    "high" if intent_score >= 0.7
                    else "medium" if intent_score >= 0.5
                    else "low"
                ),
                "channel_fit": channel in ("digital", "api_partner"),
            },
            proposed_outcome=outcome,
            confidence=round(confidence, 3),
            signals=signals,
            contradictions=[],
            hypothesis=(
                "Lead qualifies for auto-routing if intent_score is high "
                "AND channel is digital/api_partner AND identity is unambiguous."
            ),
            conclusion=(
                f"intent_score={intent_score:.2f} on channel={channel!r} → "
                f"{outcome.value}"
            ),
            confidence_basis=(
                "Intent score is derived from session signals only; would "
                "increase with confirmed kyc, would decrease on watchlist hit."
            ),
            summary=(
                f"Lead from {source!r} via {channel!r} with intent_score "
                f"{intent_score:.2f} — proposed {outcome.value}."
            ),
        )


__all__ = ["LeadQualificationAgent"]
