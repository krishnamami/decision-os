"""
Explanation Engine — EX2-A

Generates human-readable narratives from decision traces (TR-A/TR-B) using
Claude, for three audiences:

  loan_officer:  plain English, action-oriented
  underwriter:   technical, evidence-cited
  regulator:     formal, rule-cited, audit-ready

Reads decision_trace + loan_condition_instances + fraud_signals. Falls back to
a deterministic template when no Anthropic API key is configured (local-first:
the engine must work end-to-end without cloud credentials).

NB on the Anthropic client: it is resolved lazily and key-gated. The spec built
`anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))` in __init__,
which raises at construction when no key is set — that would break the template
fallback path too. Here the client is None unless a key is present, and explain()
uses templates whenever the client is None or the call fails. The async client
(AsyncAnthropic) is used so the call doesn't block the event loop.
"""

import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional


# Default model: env-overridable, defaults to the codebase persona convention
# (claude-sonnet-4-6). Set CLAUDE_MODEL_ID to override.
DEFAULT_MODEL = os.environ.get("CLAUDE_MODEL_ID", "claude-sonnet-4-6")


LOAN_OFFICER_PROMPT = """
You are an AI mortgage assistant explaining a loan decision to a loan officer.

Write a clear, concise explanation (3-5 sentences) covering:
1. The decision outcome
2. The key reason (DTI, credit, fraud flag, etc.)
3. What the borrower needs to do next (conditions, documents)
4. Expected timeline if conditions are met

Be direct. Use dollar amounts and percentages. Avoid jargon. Focus on what the
LO needs to communicate to the borrower.

Decision data:
{trace_summary}
"""

UNDERWRITER_PROMPT = """
You are a senior underwriter reviewing an AI-generated mortgage decision.

Write a technical underwriting narrative (5-8 sentences) covering:
1. Income qualification and method used
2. Credit profile and any derogatory items
3. Asset verification and any flags
4. Collateral and LTV assessment
5. Any fraud signals or cross-document conflicts
6. Overall risk assessment
7. Specific conditions and why each is required

Cite specific evidence (W2 box1, paystub YTD, credit mid score, bank balance)
and agency rules where relevant (Fannie B3-3.1-01, FHA 4000.1, etc.).

Decision data:
{trace_summary}
"""

REGULATOR_PROMPT = """
You are documenting a mortgage lending decision for regulatory audit purposes.

Write a formal audit narrative (5-7 sentences) documenting:
1. Which agency guidelines applied
2. The specific thresholds evaluated (DTI, LTV, credit) and the values found
3. Which thresholds passed and which failed
4. The tenant overlay rules that applied (if stricter than agency)
5. The final decision and its basis
6. Any adverse action triggers

Use formal language. Cite specific rule references. This narrative must be
defensible in a CFPB exam.

Decision data:
{trace_summary}
"""

PROMPTS = {
    "loan_officer": LOAN_OFFICER_PROMPT,
    "underwriter": UNDERWRITER_PROMPT,
    "regulator": REGULATOR_PROMPT,
}


def _f(v: Any) -> float:
    if isinstance(v, Decimal):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _jsonb(v: Any) -> Any:
    if isinstance(v, (dict, list)) or v is None:
        return v
    if isinstance(v, (bytes, bytearray)):
        v = v.decode("utf-8")
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (ValueError, TypeError):
            return {}
    return v


class ExplanationEngine:

    def __init__(self, conn, anthropic_client=None):
        self.conn = conn
        self.client = anthropic_client or self._lazy_client()
        self.model = DEFAULT_MODEL

    @staticmethod
    def _lazy_client():
        """AsyncAnthropic only when a key is present and the SDK importable;
        otherwise None so explain() uses the template fallback."""
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return None
        try:
            from anthropic import AsyncAnthropic  # type: ignore
        except ImportError:
            return None
        return AsyncAnthropic()

    async def explain(
        self,
        application_id: str,
        tenant_id: str,
        audience: str = "loan_officer",
    ) -> dict:
        """Generate an explanation for a decision. audience: loan_officer |
        underwriter | regulator."""
        trace = await self.conn.fetchrow(
            """
            SELECT final_outcome, outcome_reason, input_snapshot,
                   evidence_trace, policy_trace, persona_traces,
                   conditions_snapshot, loan_amount, ltv, dti,
                   credit_score, loan_type, decided_at
            FROM decision_trace
            WHERE application_id = $1 AND tenant_id = $2
            AND superseded_by IS NULL
            ORDER BY created_at DESC LIMIT 1
            """,
            application_id, tenant_id,
        )
        if not trace:
            return {"error": "No trace found", "audience": audience}

        conditions = await self.conn.fetch(
            """
            SELECT condition_code, condition_text, status,
                   blocks_closing, prior_to, assignee
            FROM loan_condition_instances
            WHERE application_id = $1 AND tenant_id = $2
            AND status IN ('open','submitted','in_review')
            ORDER BY blocks_closing DESC
            """,
            application_id, tenant_id,
        )
        fraud = await self.conn.fetch(
            """
            SELECT signal_type, severity, description, variance_pct
            FROM fraud_signals
            WHERE application_id = $1 AND tenant_id = $2
            AND resolved = false
            """,
            application_id, tenant_id,
        )

        t = dict(trace)
        evidence = _jsonb(t.get("evidence_trace")) or {}
        policy = _jsonb(t.get("policy_trace")) or {}
        trace_summary = self._build_summary(t, evidence, policy, conditions, fraud)

        narrative = None
        used_model = self.model
        if self.client is not None:
            try:
                prompt = PROMPTS.get(audience, LOAN_OFFICER_PROMPT).format(
                    trace_summary=trace_summary
                )
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=1000,
                    messages=[{"role": "user", "content": prompt}],
                )
                narrative = next(
                    (b.text for b in response.content if b.type == "text"), None
                )
            except Exception:
                narrative = None

        if narrative is None:
            narrative = self._template_narrative(t, conditions, fraud, audience)
            used_model = "template_fallback"

        return {
            "application_id": application_id,
            "audience": audience,
            "outcome": t["final_outcome"],
            "narrative": narrative,
            "model": used_model,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _build_summary(self, trace, evidence, policy, conditions, fraud) -> str:
        """Structured summary fed to the LLM prompt. evidence_trace is a flat
        dict keyed by fact_type (qualifying_income / verified_assets /
        governing_credit_score / employment_continuity)."""
        lines = [f"DECISION: {trace['final_outcome']}"]
        if trace.get("outcome_reason"):
            lines.append(f"REASON: {trace['outcome_reason']}")
        lines.append(
            f"LOAN: ${_f(trace.get('loan_amount')):,.0f} "
            f"{trace.get('loan_type') or 'conventional'}"
        )
        lines.append(
            f"LTV: {_f(trace.get('ltv')):.1f}% | DTI: {_f(trace.get('dti')):.1f}% | "
            f"CREDIT: {trace.get('credit_score')}"
        )

        # Evidence facts (flat by fact_type).
        def _fact(key):
            f = evidence.get(key)
            return f if isinstance(f, dict) else None

        inc = _fact("qualifying_income")
        if inc:
            lines.append(
                f"INCOME: {inc.get('text') or inc.get('value')} "
                f"(conf {inc.get('confidence')})"
            )
            if inc.get("conflicts"):
                lines.append("  ! INCOME CONFLICT DETECTED")
        assets = _fact("verified_assets")
        if assets:
            lines.append(f"ASSETS: {assets.get('text') or assets.get('value')}")
            if assets.get("conflicts"):
                lines.append("  ! UNSOURCED DEPOSIT")
        credit = _fact("governing_credit_score")
        if credit:
            lines.append(f"CREDIT FACT: {credit.get('text') or credit.get('value')}")
        emp = _fact("employment_continuity")
        if emp:
            lines.append(f"EMPLOYMENT: {emp.get('text') or emp.get('value')}")

        # Policy evaluations.
        evals = policy.get("evaluations") or []
        if evals:
            lines.append("POLICY CHECKS:")
            for e in evals:
                mark = "PASS" if e.get("result") == "pass" else "FAIL"
                lines.append(
                    f"  [{mark}] {e.get('check')}: {e.get('actual')} vs "
                    f"{e.get('effective_limit')} ({e.get('source')})"
                )

        if conditions:
            lines.append(f"OPEN CONDITIONS ({len(conditions)}):")
            for c in conditions[:5]:
                block = "[BLOCKS] " if c["blocks_closing"] else ""
                lines.append(
                    f"  {block}{c['condition_code']}: "
                    f"{(c['condition_text'] or '')[:80]}"
                )

        if fraud:
            lines.append(f"FRAUD SIGNALS ({len(fraud)}):")
            for s in fraud:
                lines.append(
                    f"  * {s['signal_type']} ({s['severity']}): "
                    f"{(s['description'] or '')[:80]}"
                )

        return "\n".join(lines)

    def _template_narrative(self, trace, conditions, fraud, audience) -> str:
        """Deterministic fallback when Claude is unavailable."""
        outcome = trace["final_outcome"]
        dti = f"{_f(trace['dti']):.1f}"
        ltv = f"{_f(trace['ltv']):.1f}"
        score = trace["credit_score"]
        amount = _f(trace.get("loan_amount"))
        n_conds = len(conditions)
        n_fraud = len(fraud)

        if audience == "loan_officer":
            if outcome in ("approve", "approve_with_conditions"):
                tail = (
                    f"Please satisfy the {n_conds} open condition(s) before closing."
                    if n_conds else "Loan is ready to proceed."
                )
                return (
                    f"The loan has been approved"
                    f"{' with conditions' if n_conds else ''}. Borrower qualifies "
                    f"with DTI {dti}%, LTV {ltv}%, credit score {score}. {tail}"
                )
            if outcome == "escalate":
                return (
                    f"This loan has been escalated for underwriter review. "
                    f"DTI {dti}%, LTV {ltv}%, credit {score}. "
                    f"{str(n_conds) + ' condition(s) require attention. ' if n_conds else ''}"
                    f"{'Fraud signals detected — UW review required.' if n_fraud else ''}"
                ).strip()
            return (
                "This loan has been blocked. Review the open conditions and "
                "contact underwriting."
            )

        if audience == "regulator":
            return (
                f"Decision: {outcome}. Loan amount ${amount:,.0f}. DTI {dti}% "
                f"evaluated against the effective limit per tenant overlay. LTV "
                f"{ltv}% evaluated against the agency maximum. Credit score "
                f"{score} evaluated against the agency floor. Decision generated "
                f"by the Accord AI underwriting system with full evidence and "
                f"policy trace retained."
            )

        # underwriter
        return (
            f"Loan ${amount:,.0f}: DTI {dti}%, LTV {ltv}%, credit {score}. "
            f"Outcome: {outcome}. {n_conds} open condition(s), "
            f"{n_fraud} fraud signal(s)."
        )


__all__ = ["ExplanationEngine"]
