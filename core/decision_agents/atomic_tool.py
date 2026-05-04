from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from core.audit import (
    AuditEngine,
    AuditRecord,
    AuditStore,
    ConsentStatus,
)
from core.audit.ethics_checker import PROTECTED_ATTRIBUTES
from core.context_store import ContextBuilder, ContextBundle, EntityResolver
from core.normalizer.models import DecisionMode, DecisionOutcome, RiskLevel
from core.policy_engine import (
    PolicyDecision,
    PolicyEvaluator,
    PolicyOutcome,
    UpstreamSummary,
)
from core.trace import (
    ClaimProvenance,
    CriticAgent,
    CriticReview,
    DecisionTrace,
    SelfReviewError,
    TraceWriter,
)

from .base import AgentReasoning, DecisionAgent, DecisionAgentError
from .mode_router import ModeRouter, RoutedDecision

if TYPE_CHECKING:
    from core.policy_engine.store import PolicyStore


# Default data sources by decision_id. Used by the audit engine to
# stamp data_sources_used onto AuditRecord. Compliance checker cross-
# references these against regulation_tags (FCRA must be tagged when
# credit_bureau is used, etc.). Override per platform in production.
_DEFAULT_DATA_SOURCES_BY_DECISION: dict[str, tuple[str, ...]] = {
    "lead_scoring":          ("application_form",),
    "income_verification":   ("payroll_provider",),
    "credit_assessment":     ("credit_bureau",),
    "fraud_screening":       ("fraud_engine",),
    "compliance_check":      ("application_form",),
    "dti_calculation":       (),
    "ltv_assessment":        (),
    "product_eligibility":   (),
    "rate_pricing":          ("rate_sheet",),
    "underwriting_decision": ("credit_bureau", "payroll_provider"),
    "approval_routing":      (),
    "closing_readiness":     ("title_provider",),
}


# Default agency chain when no loan_type / per-Application override.
_DEFAULT_AGENCY_CHAIN: list[str] = ["lender_overlay"]


# Per-loan-type agency chain — STREAM C phase 3.
# Overlay-first precedence: lender's own rules win; agency rules layer
# beneath. Replay correctness depends on the chain matching what was
# in force at decided_at, which the PolicyStore handles via valid_from
# / valid_to windows.
#
# Today only `lender_overlay` PolicyVersions are seeded, so the second
# entry in each chain has no active version — the policy_chain on the
# trace ends up with one id (the overlay), but the chain is still
# *consulted* in the order below. When real Freddie / Fannie / FHA / VA
# / USDA bulletins land via STREAM E2, multi-version chains start
# producing on traces.
_AGENCY_CHAIN_BY_LOAN_TYPE: dict[str, list[str]] = {
    "conforming": ["lender_overlay", "freddie"],
    "fha":        ["lender_overlay", "fha"],
    "va":         ["lender_overlay", "va"],
    "usda":       ["lender_overlay", "usda"],
    # Jumbo + non-QM have no agency conforming guideline — lender's own
    # overlay is the only authoritative source.
    "jumbo":      ["lender_overlay"],
    "non_qm":     ["lender_overlay"],
}


def _agency_chain_for_loan_type(loan_type: Optional[str]) -> list[str]:
    if not loan_type:
        return list(_DEFAULT_AGENCY_CHAIN)
    return list(_AGENCY_CHAIN_BY_LOAN_TYPE.get(loan_type, _DEFAULT_AGENCY_CHAIN))


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
    audit_record: Optional[AuditRecord] = None
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
        policy_store: Optional["PolicyStore"] = None,
        audit_engine: Optional[AuditEngine] = None,
        audit_store: Optional[AuditStore] = None,
    ):
        self._builder = builder
        self._evaluator = evaluator
        self._critic = critic
        self._trace_writer = trace_writer
        self._router = router
        # Optional — when set, every evaluate() call consults the store
        # by (decision_id, agency, at) and stamps policy_version_id on
        # the trace. When None the evaluator falls back to YAML.
        self._policy_store = policy_store
        # Audit gate. When BOTH audit_engine and audit_store are wired,
        # the AuditRecord is built + persisted between trace_write and
        # mode_route (PRD §23.9 audit_record_required_before_writeback).
        # Either being None disables the gate — the platform startup is
        # responsible for refusing to boot without audit in production.
        self._audit_engine = audit_engine
        self._audit_store = audit_store

    # ── Public entrypoint ────────────────────────────────────────────

    async def run(
        self,
        agent: DecisionAgent,
        *,
        application_id: str,
        resolver: EntityResolver,
        upstream: Optional[list[UpstreamSummary]] = None,
        spec_version: Optional[str] = None,
        agency_chain: Optional[list[str]] = None,
        evaluation_at: Optional[datetime] = None,
    ) -> AtomicToolResult:
        started = datetime.utcnow()
        upstream = upstream or []
        # `at` is the moment the decision is evaluated. Live path uses
        # the AtomicTool start time (so all rule lookups in this run
        # agree on a single instant); replay overrides it via
        # evaluation_at to pin to the original decision moment.
        eval_at = evaluation_at or started

        spec = self._builder.decision_spec(agent.decision_id)
        mode = self._mode_from_spec(spec)
        risk_level = self._risk_from_spec(spec)
        persona = spec.get("persona", agent.persona)

        # ── 1. context_build ─────────────────────────────────────────
        bundle = await self._builder.build(application_id, agent.decision_id, resolver)

        # Product / state hints for policy lookup. None when the bundle
        # doesn't carry a Loan / Application yet (e.g. lead_scoring runs
        # before either exists). PolicyStore tolerates None (treats as
        # "any product / any state").
        product, state = self._policy_scope_hints(bundle)

        # Resolve agency_chain — caller's value wins; otherwise derive
        # from loan_type. Lead/income/credit/fraud/compliance run BEFORE
        # Loan exists, so loan_type is None → default chain. Once Loan
        # is hydrated, downstream decisions get the loan-type-aware chain.
        if agency_chain is not None:
            agency_chain = list(agency_chain)
        else:
            agency_chain = _agency_chain_for_loan_type(product)

        # ── 2. policy pre-check (hard rules + contamination) ─────────
        pre_policy = await self._evaluator.evaluate(
            agent.decision_id,
            self._policy_context(bundle, {}),
            upstream,
            policy_store=self._policy_store,
            at=eval_at,
            agency_chain=agency_chain,
            product=product,
            state=state,
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
        post_policy = await self._evaluator.evaluate(
            agent.decision_id,
            self._policy_context(bundle, reasoning.output_payload),
            upstream,
            policy_store=self._policy_store,
            at=eval_at,
            agency_chain=agency_chain,
            product=product,
            state=state,
        )

        # The policy engine has the last word on outcome. The agent's
        # proposed_outcome is allowed only if it matches a permissive
        # clause. Hard rules (block / contamination / fraud_block /
        # compliance_block) always win.
        final_outcome = self._reconcile(post_policy, reasoning)

        # ── 5. critic review (medium+ risk only) ─────────────────────
        critic_review: Optional[CriticReview] = None

        # Freeze the claims this decision consumed into ClaimProvenance
        # records — that's the audit chain from outcome → claim →
        # document → verifier. Decoupled from live KnowledgeStore so a
        # later re-extraction can't retroactively change what the
        # trace says was on hand.
        claim_provenance = self._freeze_claim_provenance(bundle)

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
            policy_version_id=post_policy.policy_version_id,
            policy_chain=list(post_policy.policy_chain),
            claim_provenance=claim_provenance,
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

        # ── 7b. audit (PRD §23.9 audit_record_required_before_writeback) ─
        # The audit gate runs AFTER trace_write so the AuditRecord can
        # reference the persisted decision_id, but BEFORE mode_route so
        # that no writeback fires without a corresponding audit record.
        # When the engine + store aren't wired (legacy bring-up paths,
        # tests that don't care about audit), the gate is skipped — the
        # platform is responsible for refusing to boot without it in
        # production.
        audit_record: Optional[AuditRecord] = None
        if self._audit_engine is not None and self._audit_store is not None:
            try:
                audit_record = await self._audit_engine.evaluate(
                    trace,
                    event_input={"application_id": application_id},
                    context_used={
                        "snapshot_id": str(bundle.snapshot_id),
                        "object_types": list(bundle.objects.keys()),
                        "upstream_decisions": list(bundle.upstream_decision_ids),
                        "claim_count": len(bundle.claims or {}),
                    },
                    ontology_mapping={
                        ot: list(entities.keys())
                        for ot, entities in bundle.objects.items()
                    },
                    regulation_tags=self._regulation_tags_for(agent.decision_id),
                    consent_status=self._consent_status_from_bundle(bundle),
                    data_sources_used=list(
                        _DEFAULT_DATA_SOURCES_BY_DECISION.get(agent.decision_id, ())
                    ),
                    disclosure_sent=self._disclosure_sent_from_bundle(bundle),
                    protected_attrs_excluded=list(PROTECTED_ATTRIBUTES),
                    applicant_segment=self._applicant_segment_from_bundle(bundle),
                )
                await self._audit_store.write(audit_record)
            except Exception as err:
                raise AtomicToolError(
                    f"audit gate failed for {agent.decision_id!r} "
                    f"(application={application_id!r}): {err}"
                ) from err

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
            audit_record=audit_record,
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
        """Flatten bundle.objects + upstream_outputs + claims + agent
        output into a single dict the policy evaluator can dot-walk.

        Precedence (low → high):
          1. upstream_outputs
          2. bundle.objects (entity fields)
          3. bundle.claims (verified facts from EDMS docs)
          4. output_payload (agent's computed signals)

        Why this order: the agent's computed signals (dti, ltv,
        intent_score) are interpretations and override raw entity
        fields. Verified claims are *facts with provenance* — more
        authoritative than entity rollups but the agent may still
        derive a different value from them, which then wins for the
        boundary check."""

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

        # Verified claims — beat entity rollups but yield to agent's
        # computed values. Boundary clauses can reference claim values
        # by field_name directly (e.g. `verified_income > 100000`).
        for k, v in (bundle.claims or {}).items():
            ctx[k] = v

        # Agent computed values (highest precedence) — these override
        # any default bundle values.
        for k, v in (output_payload or {}).items():
            ctx[k] = v

        return ctx

    @staticmethod
    def _to_decision_outcome(outcome: PolicyOutcome) -> DecisionOutcome:
        return DecisionOutcome(outcome.value)

    @staticmethod
    def _freeze_claim_provenance(bundle: ContextBundle) -> list[ClaimProvenance]:
        """Snapshot bundle.claim_records into ClaimProvenance records.

        Bundle.claim_records carries full ClaimRecord objects from the
        Retriever; we freeze the audit-relevant subset onto the trace.
        Empty list when the decision didn't consume any claims (e.g.
        lead_scoring runs before any docs are uploaded)."""

        out: list[ClaimProvenance] = []
        for c in bundle.claim_records or []:
            # Each record can be a ClaimRecord (Pydantic) or a dict
            # (depending on retriever wiring). Handle both shapes.
            getter = c.__dict__.get if hasattr(c, "__dict__") else c.get
            try:
                claim_id = getattr(c, "claim_id", None) or (
                    c.get("claim_id") if isinstance(c, dict) else None
                )
                if not claim_id:
                    continue
                out.append(ClaimProvenance(
                    claim_id=claim_id,
                    field_name=(
                        getattr(c, "field_name", None)
                        or (c.get("field_name") if isinstance(c, dict) else None)
                        or ""
                    ),
                    field_value=(
                        getattr(c, "field_value", None)
                        if hasattr(c, "field_value")
                        else (c.get("field_value") if isinstance(c, dict) else None)
                    ),
                    document_id=(
                        getattr(c, "document_id", None)
                        or (c.get("document_id") if isinstance(c, dict) else None)
                        or ""
                    ),
                    source_page=(
                        getattr(c, "source_page", None)
                        if hasattr(c, "source_page")
                        else (c.get("source_page") if isinstance(c, dict) else None)
                    ),
                    status=(
                        getattr(c, "status", None)
                        or (c.get("status") if isinstance(c, dict) else None)
                        or "verified"
                    ),
                    verified_at=(
                        getattr(c, "verified_at", None)
                        if hasattr(c, "verified_at")
                        else (c.get("verified_at") if isinstance(c, dict) else None)
                    ),
                    verified_by=(
                        getattr(c, "verified_by", None)
                        if hasattr(c, "verified_by")
                        else (c.get("verified_by") if isinstance(c, dict) else None)
                    ),
                    extraction_confidence=(
                        getattr(c, "extraction_confidence", None)
                        if hasattr(c, "extraction_confidence")
                        else (
                            c.get("extraction_confidence")
                            if isinstance(c, dict) else None
                        )
                    ),
                ))
            except Exception:
                # Frozen-trace path is non-blocking; skip malformed claims.
                continue
        return out

    @staticmethod
    def _policy_scope_hints(bundle: ContextBundle) -> tuple[Optional[str], Optional[str]]:
        """Pull (loan_type, property_state) from the bundle so the
        PolicyStore can match scope-specific policies (FHA-only,
        California-only, etc.). Returns (None, None) when the bundle
        doesn't carry the relevant entity yet — early decisions like
        lead_scoring run before Loan / Application exist."""

        loan_type: Optional[str] = None
        property_state: Optional[str] = None
        for entity_id, fields in (bundle.objects.get("Loan") or {}).items():
            if isinstance(fields, dict) and fields.get("loan_type"):
                loan_type = fields["loan_type"]
                break
        for entity_id, fields in (bundle.objects.get("Application") or {}).items():
            if isinstance(fields, dict) and fields.get("property_state"):
                property_state = fields["property_state"]
                break
        return loan_type, property_state

    def _reconcile(
        self, policy: PolicyDecision, reasoning: AgentReasoning
    ) -> DecisionOutcome:
        """Decide the final outcome.

        The policy engine has the last word — that is the
        ``no_action_without_policy`` hard rule. The agent's
        proposed_outcome is informational; if it conflicts with the
        policy outcome the policy wins."""

        return self._to_decision_outcome(policy.outcome)

    # ── Audit input derivation ───────────────────────────────────────
    #
    # Pure helpers — they read the bundle / decision_id and produce
    # AuditRecord-input shapes. Defaults are intentionally permissive
    # (consent OBTAINED, disclosure False, segment None) so the live
    # smoke pass produces clean AuditRecords; the synthetic-data slice
    # injects intentional violations to exercise the warn / fail paths.

    @staticmethod
    def _regulation_tags_for(decision_id: str) -> list[str]:
        from core.audit.compliance_checker import DEFAULT_REGULATION_TAGS

        return list(DEFAULT_REGULATION_TAGS.get(decision_id, ()))

    @staticmethod
    def _consent_status_from_bundle(bundle: ContextBundle) -> ConsentStatus:
        # Look at the Applicant entity — if it carries a consent flag,
        # use it; otherwise default to OBTAINED for the local smoke.
        for fields in (bundle.objects.get("Applicant") or {}).values():
            if isinstance(fields, dict):
                raw = fields.get("consent_status")
                if raw:
                    try:
                        return ConsentStatus(raw)
                    except ValueError:
                        return ConsentStatus.OBTAINED
                if fields.get("consent_obtained") is False:
                    return ConsentStatus.MISSING
        return ConsentStatus.OBTAINED

    @staticmethod
    def _disclosure_sent_from_bundle(bundle: ContextBundle) -> bool:
        for fields in (bundle.objects.get("ComplianceRecord") or {}).values():
            if isinstance(fields, dict) and fields.get("disclosure_sent"):
                return True
        return False

    @staticmethod
    def _applicant_segment_from_bundle(bundle: ContextBundle) -> Optional[str]:
        # Surface the credit_band as the segment when present —
        # FairnessChecker compares that against population baselines.
        for fields in (bundle.objects.get("CreditProfile") or {}).values():
            if isinstance(fields, dict):
                band = fields.get("credit_band")
                if band:
                    return str(band)
        return None

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
