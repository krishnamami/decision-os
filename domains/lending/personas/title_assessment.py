from __future__ import annotations

import json
from typing import Optional

from core.context_store import ContextBundle
from core.normalizer.models import DecisionOutcome
from core.policy_engine import PolicyDecision
from core.title.lien_resolver import LienResolver
from core.trace import SignalDirection

from .base import LendingPersona, OfflineReasoning, first_object, make_signal


def _as_list(val):
    """Title context arrays arrive as a JSON list or (depending on the view
    codec) a JSON string. Normalise to a Python list."""
    if val is None:
        return []
    if isinstance(val, str):
        try:
            val = json.loads(val)
        except (ValueError, TypeError):
            return []
    return list(val) if isinstance(val, (list, tuple)) else []


class TitleAssessmentAgent(LendingPersona):
    """title_assessment — Wave 0 independent leaf, parallel with
    fraud_screening. Reads the title context (property_encumbrances /
    title_findings / ownership_chain via vw_title_assessment_context),
    runs LienResolver over the encumbrances, and rolls everything up to a
    single ``title_disposition`` the boundary maps to an outcome:

      BLOCK    any auto_block lien (IRS / tax / judgment / mechanics /
               child-support) or an unresolvable defect (lis pendens).
      ESCALATE resolvable liens (HOA), a non-borrower owner who must sign,
               or a title not yet cleared per the commitment.
      ALLOW    no encumbrances and title clear.
    """

    DEFAULT_AGENT_ID = "title_assessment_agent_v1"

    def __init__(self, *, agent_id: str = DEFAULT_AGENT_ID,
                 use_anthropic: bool = False, **kw):
        super().__init__(
            agent_id=agent_id,
            persona="title_assessment_agent",
            decision_id="title_assessment",
            use_anthropic=use_anthropic,
            **kw,
        )
        self._resolver = LienResolver()

    def _compute_offline(
        self, bundle: ContextBundle, policy: Optional[PolicyDecision]
    ) -> OfflineReasoning:
        title = first_object(bundle, "TitleProfile") or {}
        encumbrances = _as_list(title.get("encumbrances"))
        non_borrower_owners = _as_list(title.get("non_borrower_owners"))
        title_clear = title.get("title_clear")

        resolution = self._resolver.resolve_all(encumbrances)
        overall = resolution["overall_status"]          # clear/conditions/block/fatal_block
        blocking = resolution["blocking_count"]
        payoff = resolution["total_payoff"]
        conditions = resolution["conditions"]

        # A clear lien picture can still need UW attention: a non-borrower owner
        # who must sign, or a title the commitment hasn't cleared -> escalate.
        if overall == "clear" and non_borrower_owners:
            overall = "conditions"
            reason = (f"Non-borrower owner(s) on title: {non_borrower_owners}. "
                      "Must sign closing docs or provide a quitclaim deed.")
        elif overall == "clear" and title_clear is False:
            overall = "conditions"
            reason = "Title not clear per commitment. Title company review required."
        elif overall == "fatal_block":
            reason = "Unresolvable title defect (e.g. lis pendens). Cannot close; legal review."
        elif overall == "block":
            reason = (f"{blocking} blocking lien(s) totaling ${payoff:,.0f} must be "
                      "satisfied before closing.")
        elif overall == "conditions":
            reason = (f"{len(encumbrances)} encumbrance(s) found; resolvable at closing "
                      "with conditions.")
        else:
            reason = "Title clear. No encumbrances."

        if overall in ("block", "fatal_block"):
            outcome, confidence = DecisionOutcome.BLOCK, 0.95
        elif overall == "conditions":
            outcome, confidence = DecisionOutcome.ESCALATE, 0.8
        else:
            outcome, confidence = DecisionOutcome.ALLOW, 0.95

        signals = [
            make_signal("title_disposition", overall,
                        direction=(SignalDirection.CONTRADICTS
                                   if overall in ("block", "fatal_block")
                                   else SignalDirection.NEUTRAL), weight=2.0),
            make_signal("blocking_lien_count", blocking,
                        direction=(SignalDirection.CONTRADICTS if blocking
                                   else SignalDirection.SUPPORTS)),
            make_signal("total_payoff_required", round(payoff, 2)),
            make_signal("non_borrower_owners", len(non_borrower_owners)),
        ]

        return OfflineReasoning(
            output_payload={
                "title_disposition": overall,
                "lien_count": len(encumbrances),
                "blocking_lien_count": blocking,
                "total_payoff_required": round(payoff, 2),
                "conditions_generated": conditions,
                "non_borrower_owners": non_borrower_owners,
                "title_clear": title_clear,
            },
            proposed_outcome=outcome,
            confidence=confidence,
            signals=signals,
            contradictions=[],
            hypothesis=(
                "Title is clear-to-close when no auto-block lien is present, no "
                "unresolvable defect exists, all owners are borrowers (or will "
                "sign), and the commitment shows the title cleared."
            ),
            conclusion=f"disposition={overall}, blocking={blocking}, payoff=${payoff:,.0f} -> {outcome.value}",
            confidence_basis=(
                "High confidence on deterministic lien classification (LIEN_RULES); "
                "the escalate branch is a routing judgement for UW/title review."
            ),
            summary=reason,
        )


__all__ = ["TitleAssessmentAgent"]
