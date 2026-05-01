from __future__ import annotations

from datetime import datetime

from core.normalizer.models import DecisionOutcome, RiskLevel

from .trace_schema import (
    CriticReview,
    CriticVerdict,
    DecisionTrace,
    WorkJournalEntry,
)


class SelfReviewError(RuntimeError):
    """Raised when a CriticAgent is asked to review its own output.

    Hard rule: the critic must be independent of the decision agent it
    reviews. Allowing self-review would reduce the critic to a
    rubber-stamp."""


class CriticAgent:
    """Independent reviewer of medium-risk decisions before execution.

    Takes a DecisionTrace and returns one of approved / flagged /
    escalated. The critic does not produce decisions of its own; it
    audits the WorkJournalEntry inside the trace and the trace's
    alignment with the policy outcome.

    Design choices baked into the heuristics:
      - Missing required journal fields → ESCALATED. A trace that
        cannot be audited cannot be approved.
      - Unresolved contradictions → ESCALATED. The agent saw conflicting
        signals and ignored them.
      - Policy/outcome mismatch → ESCALATED. The decision deviates from
        the boundary engine without an explicit override path.
      - High confidence with thin evidence → FLAGGED.
      - Low confidence on an ALLOW outcome → FLAGGED.
      - Otherwise → APPROVED.
    """

    DEFAULT_MIN_SIGNALS = 3
    HIGH_CONFIDENCE_THRESHOLD = 0.9
    LOW_CONFIDENCE_THRESHOLD = 0.6

    def __init__(
        self,
        critic_id: str = "critic_v1",
        min_signals: int = DEFAULT_MIN_SIGNALS,
        target_risk_levels: tuple[RiskLevel, ...] = (RiskLevel.MEDIUM,),
    ):
        if not critic_id:
            raise ValueError("critic_id is required (no_agent_without_permissions)")
        self._critic_id = critic_id
        self._min_signals = min_signals
        self._target_risk_levels = tuple(target_risk_levels)

    @property
    def critic_id(self) -> str:
        return self._critic_id

    @property
    def target_risk_levels(self) -> tuple[RiskLevel, ...]:
        return self._target_risk_levels

    def is_in_scope(self, trace: DecisionTrace) -> bool:
        return trace.risk_level in self._target_risk_levels

    def review(self, trace: DecisionTrace) -> CriticReview:
        if trace.agent_id == self._critic_id:
            raise SelfReviewError(
                f"CriticAgent {self._critic_id!r} cannot critique its own output"
            )

        findings: list[str] = []
        escalate = False

        # ── Journal completeness ──────────────────────────────────────
        journal_missing = self._missing_journal_fields(trace.reasoning)
        if journal_missing:
            findings.extend(
                f"missing reasoning field: {f}" for f in journal_missing
            )
            escalate = True

        # ── Signals ──────────────────────────────────────────────────
        n_signals = len(trace.reasoning.signals_evaluated)
        if n_signals == 0:
            findings.append("no signals evaluated")
            escalate = True
        elif n_signals < self._min_signals:
            findings.append(
                f"only {n_signals} signals evaluated (min {self._min_signals})"
            )

        # ── Contradictions ───────────────────────────────────────────
        unresolved = [
            c for c in trace.reasoning.contradictions_found if not c.resolved
        ]
        if unresolved:
            findings.append(
                f"{len(unresolved)} unresolved contradiction(s): "
                + "; ".join(c.description for c in unresolved)
            )
            escalate = True

        # ── Policy / outcome alignment ───────────────────────────────
        if (
            trace.policy_decision_outcome is not None
            and trace.policy_decision_outcome != trace.outcome
        ):
            findings.append(
                f"outcome {trace.outcome.value!r} does not match policy "
                f"engine outcome {trace.policy_decision_outcome.value!r}"
            )
            escalate = True

        # ── Confidence sanity ────────────────────────────────────────
        conf = trace.confidence
        if not 0.0 <= conf <= 1.0:
            findings.append(f"confidence {conf} out of [0, 1]")
            escalate = True
        else:
            if conf >= self.HIGH_CONFIDENCE_THRESHOLD and n_signals < self._min_signals:
                findings.append(
                    f"high confidence ({conf:.2f}) with thin evidence "
                    f"({n_signals} signals)"
                )
            if conf < self.LOW_CONFIDENCE_THRESHOLD and trace.outcome == DecisionOutcome.ALLOW:
                findings.append(
                    f"low confidence ({conf:.2f}) on an ALLOW outcome"
                )
            if conf < self.LOW_CONFIDENCE_THRESHOLD and trace.outcome == DecisionOutcome.BLOCK:
                findings.append(
                    f"low confidence ({conf:.2f}) on a BLOCK outcome"
                )

        # ── Contamination ────────────────────────────────────────────
        if trace.contamination:
            findings.append("trace flagged as contaminated by upstream confidence")
            escalate = True

        # ── Verdict ──────────────────────────────────────────────────
        if escalate:
            verdict = CriticVerdict.ESCALATED
        elif findings:
            verdict = CriticVerdict.FLAGGED
        else:
            verdict = CriticVerdict.APPROVED

        return CriticReview(
            critic_id=self._critic_id,
            reviewed_at=datetime.utcnow(),
            verdict=verdict,
            findings=findings,
            confidence=self._review_confidence(findings, escalate),
        )

    @staticmethod
    def _missing_journal_fields(journal: WorkJournalEntry) -> list[str]:
        missing: list[str] = []
        if not journal.hypothesis_tested.strip():
            missing.append("hypothesis_tested")
        if not journal.conclusion.strip():
            missing.append("conclusion")
        if not journal.confidence_basis.strip():
            missing.append("confidence_basis")
        if not journal.human_readable_summary.strip():
            missing.append("human_readable_summary")
        return missing

    @staticmethod
    def _review_confidence(findings: list[str], escalated: bool) -> float:
        if not findings:
            return 1.0
        if escalated:
            return 0.4
        return 0.7
