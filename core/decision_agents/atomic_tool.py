from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from core.context_store import ContextBuilder, ContextBundle, EntityResolver
from core.normalizer.models import DecisionMode, DecisionOutcome, RiskLevel
from core.policy_engine import (
    PolicyDecision,
    PolicyEvaluator,
    PolicyOutcome,
    UpstreamSummary,
)
from core.trace import (
    CriticAgent,
    CriticReview,
    DecisionTrace,
    SelfReviewError,
    TraceWriter,
)

from .base import AgentReasoning, DecisionAgent, DecisionAgentError
from .mode_router import ModeRouter, RoutedDecision


# ─────────────────────────────────────────────────────────────────────
# Errors and result
# ─────────────────────────────────────────────────────────────────────


class AtomicToolError(RuntimeError):
    """Raised when the bundled atomic tool cannot complete a step.

    Distinct from DecisionAgentError (the agent's reasoning is
    structurally bad) — this fires when context_build, policy_check,
    critic, trace_write or mode_route can't proceed."""


class AtomicToolResult(BaseModel):
    """The single object the atomic_tool returns. Carries everything a
    caller (DAG executor, API, replay tooler) needs without leaking
    handles to the underlying stores."""

    decision_id: str
    application_id: str
    agent_id: str

    bundle_snapshot_id: Any
    policy: PolicyDecision
    reasoning: AgentReasoning
    critic_review: Optional[CriticReview] = None
    final_outcome: DecisionOutcome
    routed: RoutedDecision
    trace: DecisionTrace
    duration_ms: int


# ─────────────────────────────────────────────────────────────────────
# AtomicTool
#
# The single bundled call referenced in PRD section 7. The contract:
#
#   1. context_build  — assembles the typed ContextBundle
#   2. policy_check   — pre-check hard rules + boundary clauses
#   3. agent reason   — agent produces a WorkJournalEntry
#   4. policy_check   — re-evaluate boundary against agent's computed
#                       values (output_payload). The agent's proposed
#                       outcome only stands if a boundary clause matches
#                       it; otherwise the policy engine wins.
#   5. critic_review  — independent critic on medium+ risk
#   6. trace_write    — persist DecisionTrace
#   7. mode_route     — writeback / queue / shadow per mode + outcome
#
# The LLM only ever sees DecisionAgent.reason(). Everything else is
# code-enforced in this module — that is what "AI reasons. Code
# governs." means in practice.
# ─────────────────────────────────────────────────────────────────────


class AtomicTool:
    """The bundled `context_build + policy_check + trace_write +
    mode_route` call defined in PRD section 7. Construct once with
    the platform components, then call ``run(agent, application_id,
    resolver)`` per decision execution."""

    def __init__(
        self,
        *,
        builder: ContextBuilder,
        evaluator: PolicyEvaluator,
        critic: Optional[CriticAgent],
        trace_writer: TraceWriter,
        router: ModeRouter,
    ):
        self._builder = builder
        self._evaluator = evaluator
        self._critic = critic
        self._trace_writer = trace_writer
        self._router = router

    # ── Public entrypoint ────────────────────────────────────────────

    async def run(
        self,
        agent: DecisionAgent,
        *,
        application_id: str,
        resolver: EntityResolver,
        upstream: Optional[list[UpstreamSummary]] = None,
        spec_version: Optional[str] = None,
    ) -> AtomicToolResult:
        started = datetime.utcnow()
        upstream = upstream or []

        spec = self._builder.decision_spec(agent.decision_id)
        mode = self._mode_from_spec(spec)
        risk_level = self._risk_from_spec(spec)
        persona = spec.get("persona", agent.persona)

        # ── 1. context_build ─────────────────────────────────────────
        bundle = await self._builder.build(application_id, agent.decision_id, resolver)

        # ── 2. policy pre-check (hard rules + contamination) ─────────
        pre_policy = self._evaluator.evaluate(
            agent.decision_id, self._policy_context(bundle, {}), upstream
        )

        # ── 3. agent reasoning ───────────────────────────────────────
        try:
            reasoning = await agent.reason(bundle, pre_policy)
        except DecisionAgentError:
            raise
        except Exception as err:
            raise AtomicToolError(
                f"agent {agent.agent_id!r} failed during reason(): {err}"
            ) from err
        self._validate_reasoning(reasoning)

        # ── 4. policy_check (final, against agent's computed values) ─
        post_policy = self._evaluator.evaluate(
            agent.decision_id,
            self._policy_context(bundle, reasoning.output_payload),
            upstream,
        )

        # The policy engine has the last word on outcome. The agent's
        # proposed_outcome is allowed only if it matches a permissive
        # clause. Hard rules (block / contamination / fraud_block /
        # compliance_block) always win.
        final_outcome = self._reconcile(post_policy, reasoning)

        # ── 5. critic review (medium+ risk only) ─────────────────────
        critic_review: Optional[CriticReview] = None

        # ── 6. build the trace (will be updated with critic + outcome) ─
        ended = datetime.utcnow()
        trace = DecisionTrace(
            decision_id=agent.decision_id,
            application_id=application_id,
            agent_id=agent.agent_id,
            persona=persona,
            mode=mode,
            risk_level=risk_level,
            inputs_snapshot_id=bundle.snapshot_id,
            upstream_decision_ids=list(bundle.upstream_decision_ids),
            context_window_days=bundle.context_window_days,
            reasoning=reasoning.journal,
            outcome=final_outcome,
            confidence=reasoning.confidence,
            matched_clause=post_policy.matched_clause,
            output_payload=reasoning.output_payload,
            policy_decision_outcome=self._to_decision_outcome(post_policy.outcome),
            policy_matched_clause=post_policy.matched_clause,
            policy_reasons=list(post_policy.reasons),
            contamination=post_policy.contamination,
            started_at=started,
            ended_at=ended,
            duration_ms=int((ended - started).total_seconds() * 1000),
            spec_version=spec_version,
        )

        if self._critic is not None and self._critic.is_in_scope(trace):
            try:
                critic_review = self._critic.review(trace)
            except SelfReviewError:
                # Re-raise — a self-review is a configuration bug we
                # want loud, not silent.
                raise
            except Exception as err:
                raise AtomicToolError(
                    f"critic {self._critic.critic_id!r} failed: {err}"
                ) from err
            trace = trace.model_copy(update={"critic_review": critic_review})

        # ── 7. trace_write ──────────────────────────────────────────
        await self._trace_writer.write(trace)

        # ── 8. mode_route ───────────────────────────────────────────
        routed = await self._router.route(
            agent_id=agent.agent_id,
            decision_id=agent.decision_id,
            application_id=application_id,
            mode=mode,
            outcome=final_outcome,
            confidence=reasoning.confidence,
            output_payload=reasoning.output_payload,
            bundle=bundle,
            reasons=post_policy.reasons,
        )

        return AtomicToolResult(
            decision_id=agent.decision_id,
            application_id=application_id,
            agent_id=agent.agent_id,
            bundle_snapshot_id=bundle.snapshot_id,
            policy=post_policy,
            reasoning=reasoning,
            critic_review=critic_review,
            final_outcome=final_outcome,
            routed=routed,
            trace=trace,
            duration_ms=trace.duration_ms or 0,
        )

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _mode_from_spec(spec: dict[str, Any]) -> DecisionMode:
        raw = spec.get("mode", "shadow")
        # decisions.yaml uses "recommend"; DecisionMode enum value is
        # also "recommend" so this is a direct construction.
        return DecisionMode(raw)

    @staticmethod
    def _risk_from_spec(spec: dict[str, Any]) -> RiskLevel:
        raw = spec.get("risk_level", "low")
        return RiskLevel(raw)

    @staticmethod
    def _policy_context(
        bundle: ContextBundle, output_payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Flatten bundle.objects + upstream_outputs + agent output into
        a single dict the policy evaluator can dot-walk.

        Precedence: agent output_payload > bundle objects > upstream.
        Agent-computed signals (dti, ltv, intent_score, ...) win because
        they are the definitive computed values for the boundary clauses
        in decisions.yaml. Upstream summary keys are layered in by the
        evaluator itself via ``_merge_upstream_into_context``."""

        ctx: dict[str, Any] = {}

        # Upstream outputs first (lowest precedence among data we layer).
        for upstream_id, payload in bundle.upstream_outputs.items():
            inner = payload.get("payload") if isinstance(payload, dict) else None
            if isinstance(inner, dict):
                for k, v in inner.items():
                    ctx.setdefault(k, v)
            ctx.setdefault(upstream_id, payload)

        # Bundle objects: flatten each entity's fields into the top-level
        # dict, but also expose them nested under their object_type_id
        # so dotted-path rules like "Application.requested_amount" work.
        for ot_id, entities in bundle.objects.items():
            for entity_id, fields in entities.items():
                if not isinstance(fields, dict):
                    continue
                for k, v in fields.items():
                    if k.startswith("_"):
                        continue
                    ctx.setdefault(k, v)
                ctx.setdefault(ot_id, fields)

        # Agent computed values (highest precedence) — these override
        # any default bundle values.
        for k, v in (output_payload or {}).items():
            ctx[k] = v

        return ctx

    @staticmethod
    def _to_decision_outcome(outcome: PolicyOutcome) -> DecisionOutcome:
        return DecisionOutcome(outcome.value)

    def _reconcile(
        self, policy: PolicyDecision, reasoning: AgentReasoning
    ) -> DecisionOutcome:
        """Decide the final outcome.

        The policy engine has the last word — that is the
        ``no_action_without_policy`` hard rule. The agent's
        proposed_outcome is informational; if it conflicts with the
        policy outcome the policy wins."""

        return self._to_decision_outcome(policy.outcome)

    @staticmethod
    def _validate_reasoning(reasoning: AgentReasoning) -> None:
        # Pydantic already validated structure; this catches the
        # semantic gaps a critic would flag, but earlier — so the
        # atomic tool fails fast instead of producing a garbage trace.
        journal = reasoning.journal
        for field in (
            "hypothesis_tested",
            "conclusion",
            "confidence_basis",
            "human_readable_summary",
        ):
            if not getattr(journal, field).strip():
                raise DecisionAgentError(
                    f"reasoning.journal.{field} is empty"
                )
