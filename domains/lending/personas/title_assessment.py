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

    # LienResolver (TL-C) emits a couple of condition codes that predate the
    # conditions_library (TL-E) naming. Map them to the library's canonical
    # codes so every resolved lien resolves to a seeded row.
    _CODE_ALIASES = {
        "TITLE_EASEMENT": "TITLE_EASEMENT_REVIEW",
        "TITLE_OTHER_LIEN": "TITLE_OTHER_ENCUMBRANCE",
    }

    def __init__(self, *, agent_id: str = DEFAULT_AGENT_ID,
                 use_anthropic: bool = False, **kw):
        super().__init__(
            agent_id=agent_id,
            persona="title_assessment_agent",
            decision_id="title_assessment",
            use_anthropic=use_anthropic,
            **kw,
        )

    def _compute_offline(
        self, bundle: ContextBundle, policy: Optional[PolicyDecision]
    ) -> OfflineReasoning:
        title = first_object(bundle, "TitleProfile") or {}
        encumbrances = _as_list(title.get("encumbrances"))
        non_borrower_owners = _as_list(title.get("non_borrower_owners"))
        title_clear = title.get("title_clear")

        # RA-4D: catalogue-resolved lien treatments injected via the bundle
        # (the runner loaded them through rule_loader; resolver stays sync).
        lien_obj = first_object(bundle, "lien_rules") or {}
        lien_rule_trace = lien_obj.get("trace")
        resolution = LienResolver(lien_obj.get("values")).resolve_all(encumbrances)
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

        # ── RA-PERSONA-C: evidence quality (advisory, OUTCOME-NEUTRAL) ────
        # Append QUALITY signals + provenance; never move proposed_outcome → 16/16
        # holds. Threshold is the catalogue documentation-confidence floor (Fannie
        # B3-3.1-01, governed_by=agency); the constant is a safety net only.
        ev = first_object(bundle, "evidence") or {}
        evidence_populated = bool(ev.get("evidence_populated"))
        evidence_any_conflicts = bool(ev.get("evidence_any_conflicts"))
        evidence_overall_conf = ev.get("evidence_overall_confidence")
        evidence_threshold_trace = ev.get("income_confidence_threshold_trace")
        if ev and not evidence_populated:
            signals.append(make_signal(
                "TITLE_MISSING_EVIDENCE", True,
                direction=SignalDirection.CONTRADICTS, source="evidence", weight=2.0,
                notes=("No evidence facts on file — title posture cannot be "
                       "corroborated from documentary evidence."),
            ))
        elif evidence_populated and evidence_any_conflicts:
            signals.append(make_signal(
                "TITLE_EVIDENCE_CONFLICT", True,
                direction=SignalDirection.CONTRADICTS, source="evidence",
                notes=("Evidence conflict on file — review alongside the title "
                       "commitment before clearing."),
            ))

        return OfflineReasoning(
            output_payload={
                "title_disposition": overall,
                # RA-PERSONA-C: evidence provenance (advisory).
                "evidence_populated": evidence_populated,
                "title_evidence_confidence": (
                    round(float(evidence_overall_conf), 3)
                    if evidence_overall_conf is not None else None
                ),
                "title_evidence_conflicts": evidence_any_conflicts,
                "title_evidence_governed_by": (
                    (evidence_threshold_trace or {}).get("governed_by")
                ),
                "evidence_threshold_trace": evidence_threshold_trace,
                "lien_count": len(encumbrances),
                "blocking_lien_count": blocking,
                "total_payoff_required": round(payoff, 2),
                "conditions_generated": conditions,
                "non_borrower_owners": non_borrower_owners,
                "title_clear": title_clear,
                # RA-4D: catalogue provenance per lien treatment.
                "lien_rule_trace": lien_rule_trace,
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

    async def _get_conditions(self, conn, resolutions: list) -> list:
        """Fetch condition templates from conditions_library (TL-E) and fill
        their variables from the resolved lien data.

        ``resolutions`` are LienResolution objects from
        ``LienResolver.resolve_all(...)["resolutions"]``. This is the
        DB-backed enrichment path: the offline reasoning hot path stays
        conn-less and uses the resolver's inline condition_text, while the
        title context view / EDMS condition generation call this to attach
        agency citations, SLAs, assignees, and EDMS document types.
        """
        filled_conditions = []
        for res in resolutions:
            code = self._CODE_ALIASES.get(res.condition_code, res.condition_code)
            row = await conn.fetchrow(
                """SELECT template_text, prior_to, sla_hours, assignee,
                          edms_document_type, agency_citation
                   FROM conditions_library
                   WHERE code = $1 AND is_active = true""",
                code,
            )
            if not row:
                continue
            text = (
                row["template_text"]
                .replace(
                    "${amount}",
                    f"${res.lien_amount:,.0f}" if res.lien_amount else "",
                )
                .replace("${holder}", res.lien_holder or "unknown")
            )
            filled_conditions.append({
                "code":      code,
                "text":      text,
                "prior_to":  row["prior_to"],
                "sla_hours": row["sla_hours"],
                "assignee":  row["assignee"],
                "doc_type":  row["edms_document_type"],
                "citation":  row["agency_citation"],
                "blocks":    res.blocks_closing,
            })
        return filled_conditions


__all__ = ["TitleAssessmentAgent"]
