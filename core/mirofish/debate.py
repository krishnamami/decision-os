"""MiroFish DebateEngine — 12 agents debate ONE loan across 3 rounds.

The 12 lending personas don't just check thresholds in isolation — here
they argue. Round 1 each agent forms an INDEPENDENT position (seeded from
its own stored decision in ``decision_outputs`` + the loan's
``entity_states`` context). Round 2 every agent SEES the others and may
revise (contamination from an upstream block, reinforcement when two
agents flag the same thing, time-pressure from an expiring rate lock).
Round 3 they settle, votes are counted, and the engine surfaces
EMERGENT insights no single agent would reach alone.

Two reasoning paths, same output shape:
  • deterministic (default) — cross-agent rules, no API key needed. This
    is the local-first path used by smoke tests and demos.
  • Claude-powered (pass ``anthropic_client``) — each agent reasons over
    the loan + its peers' positions via the Anthropic SDK, exactly like
    ``LendingPersona._reason_anthropic``. Any failure falls back to the
    deterministic position so a debate never half-fails.

DB access mirrors the rest of the codebase: an asyncpg pool *or* a raw
connection (``__init__`` accepts either), reading the same EDMS tables
the workbench reads.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional

from core.mirofish.models import (
    AgentPosition,
    DebateResult,
    DebateRound,
)


# ─────────────────────────────────────────────────────────────────────
# The debate roster — the 12 loan-decision agents (lead_scoring is a
# pre-application lead qualifier, not part of an approval debate). Order
# is wave order: independents → dependents → synthesizers → routing.
# ─────────────────────────────────────────────────────────────────────


ROSTER: list[tuple[str, str, str]] = [
    # (decision_id, display name, one-line role)
    ("credit_assessment",         "Credit Underwriter",   "judges creditworthiness from score, derogatories, utilization"),
    ("fraud_screening",           "Fraud Analyst",        "screens identity, watchlist, document authenticity"),
    ("compliance_check",          "Compliance Officer",   "checks HMDA completeness, fair lending, state rules"),
    ("employment_reconciliation", "Employment Specialist","reconciles employment continuity across providers"),
    ("income_verification",       "Income Underwriter",   "verifies stated vs documented income"),
    ("dti_calculation",           "DTI Analyst",          "computes debt-to-income against guideline caps"),
    ("ltv_assessment",            "Collateral Analyst",   "assesses loan-to-value against the appraisal"),
    ("product_eligibility",       "Product Specialist",   "matches the loan to an eligible program"),
    ("rate_pricing",              "Pricing Analyst",      "prices the rate and watches the rate lock"),
    ("underwriting_decision",     "Senior Underwriter",   "synthesizes all upstream findings into the call"),
    ("approval_routing",          "Loan Ops Router",      "routes the finalized decision to its next action"),
    ("closing_readiness",         "Closer",               "confirms conditions, title, insurance, CD timing"),
]

AGENT_NAME = {aid: name for aid, name, _ in ROSTER}
AGENT_ROLE = {aid: role for aid, _, role in ROSTER}
DEBATE_AGENTS = [aid for aid, _, _ in ROSTER]

POSITIONS = ("allow", "recommend", "escalate", "block")
_SEVERITY = {"allow": 0, "recommend": 1, "escalate": 2, "block": 3}

# Forward dependency for contamination: a decision_id → the decisions it
# feeds (so an upstream block propagates to the right downstream agents).
_SYNTHESIZERS = {
    "underwriting_decision",
    "approval_routing",
    "closing_readiness",
    "product_eligibility",
    "rate_pricing",
    "dti_calculation",
    "income_verification",
}

# Pipeline wave per decision — contamination only flows UPSTREAM → DOWNSTREAM
# (a Closer's late-stage block must not pull a wave-1 agent). Mirrors the
# engine's WAVE_FOR_DECISION.
_WAVE = {
    "credit_assessment": 1, "fraud_screening": 1, "compliance_check": 1,
    "employment_reconciliation": 1,
    "income_verification": 2, "dti_calculation": 2, "ltv_assessment": 2,
    "product_eligibility": 3, "rate_pricing": 3,
    "underwriting_decision": 4,
    "approval_routing": 5, "closing_readiness": 5,
}

# A block from these halts the pipeline — downstream agents go to BLOCK, not
# just escalate (fraud/compliance are hard stops).
_HARD_BLOCK_DECISIONS = {"fraud_screening", "compliance_check"}

_ANTHROPIC_MODEL = "claude-sonnet-4-6"


def _J(v: Any) -> Any:
    """asyncpg returns jsonb as text on an un-typed connection."""
    if isinstance(v, (bytes, bytearray)):
        v = v.decode("utf-8", "replace")
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (ValueError, json.JSONDecodeError):
            return v
    return v


def _f(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class DebateEngine:
    """Runs a 3-round swarm debate over one application and returns a
    fully-explainable :class:`DebateResult`."""

    def __init__(self, db_connection: Any, anthropic_client: Optional[Any] = None):
        """
        db_connection: an asyncpg pool OR a raw asyncpg connection.
        anthropic_client: optional AsyncAnthropic; when None, the engine
                          reasons deterministically from the persona
                          agents' stored decisions + cross-agent rules.
        """
        self.db = db_connection
        self.anthropic = anthropic_client

    # ── DB access — pool or bare connection ──────────────────────────

    @asynccontextmanager
    async def _acquire(self):
        db = self.db
        if hasattr(db, "acquire"):
            async with db.acquire() as conn:
                yield conn
        else:
            yield db

    # ── Public entrypoint ────────────────────────────────────────────

    async def debate(
        self,
        application_id: str,
        question: str = "Should this loan be approved?",
        tenant_id: str = "default",
    ) -> DebateResult:
        started = time.monotonic()
        ctx = await self._load_loan_context(application_id, tenant_id)

        r1 = await self._run_round(1, ctx, prior_positions=None)
        r2 = await self._run_round(2, ctx, prior_positions=[r1])
        r3 = await self._run_round(3, ctx, prior_positions=[r1, r2])
        rounds = [r1, r2, r3]

        final_consensus, consensus_count, dissenting, tier = self._determine_consensus(r3)
        insights = self._generate_emergent_insights(rounds, ctx)
        recommendation = self._build_recommendation(
            r3, final_consensus, tier, consensus_count, dissenting, ctx
        )

        return DebateResult(
            application_id=application_id,
            question=question,
            rounds=rounds,
            final_consensus=final_consensus,
            consensus_count=consensus_count,
            dissenting_agents=dissenting,
            recommendation=recommendation,
            emergent_insights=insights,
            total_duration_seconds=round(time.monotonic() - started, 3),
            created_at=datetime.now(timezone.utc),
        )

    # ── Context loading ──────────────────────────────────────────────

    async def _load_loan_context(self, application_id: str, tenant_id: str) -> dict[str, Any]:
        """Full loan context from EDMS PG, organized by category."""
        async with self._acquire() as conn:
            entity = await conn.fetchrow(
                "SELECT * FROM entity_states WHERE application_id = $1 LIMIT 1",
                application_id,
            )
            decision_rows = await conn.fetch(
                """
                SELECT decision_id, outcome, mode, confidence, boundary_rule,
                       reasoning, context_snapshot, human_action, decided_at
                FROM decision_outputs dout
                WHERE application_id = $1
                  AND version = (
                      SELECT MAX(version) FROM decision_outputs d2
                      WHERE d2.application_id = dout.application_id
                        AND d2.decision_id = dout.decision_id
                  )
                """,
                application_id,
            )
            doc_rows = await conn.fetch(
                """
                SELECT document_type, document_category, status
                FROM document_index
                WHERE application_id = $1 AND COALESCE(is_current, true)
                """,
                application_id,
            )
            rel_rows = await conn.fetch(
                """
                SELECT relationship_type, field_name, source_value,
                       target_value, delta_pct, reasoning
                FROM document_relationships
                WHERE application_id = $1
                """,
                application_id,
            )

        edict = dict(entity) if entity else {}
        borrower = _J(edict.get("borrower")) or {}
        loan_terms = _J(edict.get("loan_terms")) or {}
        prop = _J(edict.get("property")) or {}

        decisions: dict[str, dict[str, Any]] = {}
        for r in decision_rows:
            decisions[r["decision_id"]] = {
                "outcome": r["outcome"],
                "mode": r["mode"],
                "confidence": _f(r["confidence"]),
                "boundary_rule": r["boundary_rule"],
                "reasoning": _J(r["reasoning"]) or {},
                "context": _J(r["context_snapshot"]) or {},
                "human_action": r["human_action"],
                "decided_at": r["decided_at"],
            }

        return {
            "application_id": application_id,
            "tenant_id": tenant_id,
            "borrower_name": self._borrower_name(edict, borrower),
            "entity": {
                k: edict.get(k)
                for k in (
                    "mid_credit_score", "ltv", "cltv", "dti_front", "dti_back",
                    "loan_amount", "appraised_value", "purchase_price",
                    "interest_rate", "combined_monthly_income", "monthly_obligations",
                    "piti_monthly", "status", "completeness_pct", "conflict_count",
                    "critical_conflict_count", "title_clear", "insurance_bound",
                    "rate_locked", "clear_to_close",
                )
            },
            "borrower": borrower,
            "loan_terms": loan_terms,
            "property": prop,
            "rate_lock": loan_terms.get("rate_lock") or {},
            "decisions": decisions,
            "documents": [
                {"type": d["document_type"], "category": d["document_category"], "status": d["status"]}
                for d in doc_rows
            ],
            "document_count": len(doc_rows),
            "doc_relationships": [
                {
                    "type": r["relationship_type"], "field": r["field_name"],
                    "source_value": r["source_value"], "target_value": r["target_value"],
                    "delta_pct": _f(r["delta_pct"]), "reasoning": r["reasoning"],
                }
                for r in rel_rows
            ],
            "contradictions": [
                r for r in rel_rows if r["relationship_type"] == "contradicts"
            ],
        }

    @staticmethod
    def _borrower_name(edict: dict, borrower: dict) -> str:
        ident = borrower.get("identity") if isinstance(borrower, dict) else None
        if isinstance(ident, dict):
            for k in ("full_name", "name", "legal_name"):
                if ident.get(k):
                    return str(ident[k])
        return str(edict.get("application_id") or "the borrower")

    # ── One round ────────────────────────────────────────────────────

    async def _run_round(
        self,
        round_number: int,
        loan_context: dict[str, Any],
        prior_positions: Optional[list[DebateRound]] = None,
    ) -> DebateRound:
        prior_flat: dict[str, AgentPosition] = {}
        if prior_positions:
            for rnd in prior_positions:
                for p in rnd.positions:
                    prior_flat[p.agent_id] = p  # keep the latest

        positions: list[AgentPosition] = []
        for agent_id in DEBATE_AGENTS:
            pos = await self._agent_position(
                agent_id, round_number, loan_context, prior_flat
            )
            positions.append(pos)

        new_signals = self._signals_surfaced(round_number, positions, prior_positions)
        consensus = self._round_consensus(positions)
        return DebateRound(
            round_number=round_number,
            positions=positions,
            new_signals_shared=new_signals,
            consensus_reached=consensus,
        )

    async def _agent_position(
        self,
        agent_id: str,
        round_number: int,
        ctx: dict[str, Any],
        prior_flat: dict[str, AgentPosition],
    ) -> AgentPosition:
        # Claude path (opt-in); any failure falls through to deterministic.
        if self.anthropic is not None:
            llm = await self._claude_position(agent_id, round_number, ctx, prior_flat)
            if llm is not None:
                return llm
        if round_number == 1:
            return self._seed_position(agent_id, ctx)
        return self._revise_position(agent_id, round_number, ctx, prior_flat)

    # ── Deterministic Round 1: independent seed from stored decision ──

    def _seed_position(self, agent_id: str, ctx: dict[str, Any]) -> AgentPosition:
        d = ctx["decisions"].get(agent_id)
        signals = self._key_signals(agent_id, ctx, d)
        if d and d.get("outcome") in POSITIONS:
            position = d["outcome"]
            confidence = d["confidence"] if d["confidence"] is not None else 0.7
            reasoning = self._stored_reasoning(agent_id, d) or (
                f"{AGENT_NAME[agent_id]} {AGENT_ROLE[agent_id]}; independent read: {position}."
            )
        else:
            position, confidence, reasoning = self._derive_position(agent_id, ctx, signals)
        return AgentPosition(
            agent_id=agent_id,
            agent_name=AGENT_NAME[agent_id],
            round=1,
            position=position,
            confidence=round(float(confidence), 2),
            reasoning=reasoning,
            key_signals=signals,
        )

    @staticmethod
    def _stored_reasoning(agent_id: str, d: dict) -> Optional[str]:
        rsn = d.get("reasoning") or {}
        if isinstance(rsn, dict):
            for k in ("conclusion", "human_readable_summary", "hypothesis"):
                if rsn.get(k):
                    return str(rsn[k])
        return d.get("boundary_rule") or None

    def _derive_position(
        self, agent_id: str, ctx: dict[str, Any], signals: list[dict]
    ) -> tuple[str, float, str]:
        """Lightweight fallback when an agent has no stored decision row —
        read the loan's own entity context for a defensible position."""
        e = ctx["entity"]
        name, role = AGENT_NAME[agent_id], AGENT_ROLE[agent_id]
        if agent_id == "credit_assessment":
            s = _f(e.get("mid_credit_score"))
            if s is None:
                return "escalate", 0.5, f"{name}: no credit score on file."
            if s >= 680:
                return "allow", 0.9, f"{name}: mid score {int(s)} is prime."
            if s >= 620:
                return "recommend", 0.7, f"{name}: mid score {int(s)} is near-prime."
            return "block", 0.85, f"{name}: mid score {int(s)} below threshold."
        if agent_id == "dti_calculation":
            dti = _f(e.get("dti_back"))
            if dti is None or dti == 0:
                return "escalate", 0.5, f"{name}: DTI not computed — insufficient data."
            pct = dti * 100 if dti <= 1.5 else dti
            if pct <= 36:
                return "allow", 0.85, f"{name}: back-end DTI {pct:.0f}% within guideline."
            if pct <= 43:
                return "recommend", 0.7, f"{name}: DTI {pct:.0f}% needs compensating factors."
            return "block", 0.8, f"{name}: DTI {pct:.0f}% over the hard cap."
        if agent_id == "ltv_assessment":
            ltv = _f(e.get("ltv"))
            pct = (ltv * 100 if ltv and ltv <= 1.5 else ltv) if ltv is not None else None
            if pct is None:
                return "escalate", 0.5, f"{name}: LTV unavailable."
            if pct <= 80:
                return "allow", 0.85, f"{name}: LTV {pct:.0f}% within conforming."
            if pct <= 95:
                return "recommend", 0.7, f"{name}: LTV {pct:.0f}% — MI likely required."
            return "block", 0.8, f"{name}: LTV {pct:.0f}% over limit."
        # Generic: lean on completeness + conflicts.
        conflicts = _f(e.get("critical_conflict_count")) or 0
        if conflicts > 0:
            return "escalate", 0.6, f"{name} ({role}): {int(conflicts)} critical conflict(s) unresolved."
        return "recommend", 0.55, f"{name} ({role}): no blocking signal in own context; defer to peers."

    # ── Deterministic Round 2/3: cross-agent revision ────────────────

    def _revise_position(
        self,
        agent_id: str,
        round_number: int,
        ctx: dict[str, Any],
        prior_flat: dict[str, AgentPosition],
    ) -> AgentPosition:
        base = prior_flat.get(agent_id) or self._seed_position(agent_id, ctx)
        position = base.position
        confidence = base.confidence
        reasoning = base.reasoning
        responding_to: list[str] = []
        changed_from: Optional[str] = None

        blockers = [a for a, p in prior_flat.items() if p.position == "block" and a != agent_id]
        escalators = [a for a, p in prior_flat.items() if p.position == "escalate" and a != agent_id]
        income_flag = any(
            prior_flat.get(a) and prior_flat[a].position in ("escalate", "block")
            for a in ("income_verification", "employment_reconciliation")
        )

        # 1) Contamination — only from UPSTREAM blockers (lower wave). A
        #    fraud/compliance hard block HALTS downstream (→ block); any other
        #    upstream block escalates (underwriting still blocks).
        agent_wave = _WAVE.get(agent_id, 99)
        upstream_blockers = [a for a in blockers if _WAVE.get(a, 0) < agent_wave]
        hard = [a for a in upstream_blockers if a in _HARD_BLOCK_DECISIONS]
        if upstream_blockers and agent_id in _SYNTHESIZERS and _SEVERITY[position] < _SEVERITY["escalate"]:
            changed_from = position
            if hard:
                position = "block"
                responding_to = hard
                reasoning = (
                    f"Revised after {self._names(hard)} hard-blocked — a fraud/compliance "
                    "block halts the pipeline, so this decision cannot proceed."
                )
            else:
                position = "block" if agent_id == "underwriting_decision" else "escalate"
                responding_to = upstream_blockers[:]
                reasoning = (
                    f"Revised after {self._names(upstream_blockers)} blocked — an upstream "
                    "hard fail contaminates this decision; cannot clear over it."
                )
        # 2) Reinforcement — income + employment both adverse → Fraud raises a flag.
        elif agent_id == "fraud_screening" and income_flag and position == "allow":
            drift = self._employer_drift(ctx)
            changed_from = position
            position = "escalate"
            responding_to = [a for a in ("income_verification", "employment_reconciliation") if a in prior_flat]
            reasoning = (
                "Identity looked clean alone, but income and employment both flag concerns"
                + (f" and employer name match is weak ({drift})" if drift else "")
                + " — combined, this warrants a second look for misrepresentation."
            )
        # 3) Credit acknowledges an income block it can't see on its own.
        elif agent_id == "credit_assessment" and position == "allow" and "income_verification" in blockers:
            responding_to = ["income_verification"]
            confidence = max(0.5, confidence - 0.15)
            note = ("The score still qualifies, but Income blocked on a discrepancy — "
                    "the score alone does not tell the full story.")
            reasoning = reasoning if note in reasoning else f"{reasoning} {note}"
        # 4) LTV fine but DTI high → Product suggests a restructure.
        elif agent_id == "product_eligibility" and self._ltv_ok(ctx) and self._dti_high(ctx):
            responding_to = [a for a in ("dti_calculation", "ltv_assessment") if a in prior_flat]
            if position in ("allow", "recommend"):
                changed_from = position
                position = "recommend"
            reasoning = (
                "Collateral supports the loan but DTI is stretched — a term/product restructure "
                "(longer amortization or a buydown) could bring DTI into range."
            )
        # 5) Pricing flags rate-lock urgency when something blocks downstream.
        elif agent_id == "rate_pricing" and (blockers or escalators):
            days = self._rate_lock_days(ctx)
            if days is not None and days <= 7:
                responding_to = blockers or escalators
                note = (f"Time pressure: the rate lock expires in {days} day(s). If the open "
                        "issues aren't resolved, the rate must be re-locked, likely higher — "
                        "which pushes DTI up further.")
                reasoning = reasoning if note in reasoning else f"{reasoning} {note}"
        else:
            # Hold position; strengthen the reasoning for the record.
            held = "Position held through debate."
            if round_number == 3 and held not in reasoning:
                reasoning = f"{reasoning} {held}"

        # Round 3 synthesizer convergence: Senior UW settles to the room.
        if round_number == 3 and agent_id == "underwriting_decision":
            others = [p.position for a, p in prior_flat.items() if a != agent_id]
            if others:
                majority = Counter(others).most_common(1)[0][0]
                if majority != position and _SEVERITY[majority] >= _SEVERITY["escalate"]:
                    changed_from = changed_from or position
                    position = majority
                    reasoning = (
                        f"Synthesizing the room: the weight of agents lands on '{majority}'. "
                        f"{reasoning}"
                    )

        if changed_from == position:
            changed_from = None

        return AgentPosition(
            agent_id=agent_id,
            agent_name=AGENT_NAME[agent_id],
            round=round_number,
            position=position,
            confidence=round(float(confidence), 2),
            reasoning=reasoning,
            key_signals=base.key_signals,
            responding_to=responding_to or None,
            changed_from=changed_from,
        )

    # ── Signal extraction ────────────────────────────────────────────

    def _key_signals(
        self, agent_id: str, ctx: dict[str, Any], d: Optional[dict]
    ) -> list[dict[str, Any]]:
        """The data points the agent leaned on — from its frozen
        context_snapshot when present, else the loan's entity context."""
        out: list[dict[str, Any]] = []
        snap = (d or {}).get("context") or {}
        fields = _AGENT_SIGNAL_FIELDS.get(agent_id, [])
        for f in fields:
            val = snap.get(f, ctx["entity"].get(f))
            if val is None and isinstance(ctx.get("borrower"), dict):
                for bucket in ctx["borrower"].values():
                    if isinstance(bucket, dict) and f in bucket:
                        val = bucket[f]
                        break
            if val is not None:
                out.append({"signal": f, "value": val, "assessment": self._assess(f, val)})
        return out

    @staticmethod
    def _assess(field: str, value: Any) -> str:
        f = _f(value)
        if field in ("watchlist_match", "synthetic_identity_flag", "fair_lending_violation",
                     "active_bankruptcy", "title_defect", "lien_dispute"):
            return "red" if str(value).lower() in ("true", "1") else "clear"
        if field == "mid_credit_score" and f is not None:
            return "strong" if f >= 680 else ("borderline" if f >= 620 else "weak")
        if field in ("income_discrepancy_pct", "dti_back", "ltv") and f is not None:
            scaled = f * 100 if f <= 1.5 else f
            return "elevated" if scaled >= 36 else "ok"
        if field in ("income_confidence_score", "document_authenticity_score",
                     "identity_match_confidence") and f is not None:
            return "low" if f < 0.7 else "ok"
        return "noted"

    # ── Round-level helpers ──────────────────────────────────────────

    def _signals_surfaced(
        self,
        round_number: int,
        positions: list[AgentPosition],
        prior: Optional[list[DebateRound]],
    ) -> list[str]:
        if round_number == 1:
            seen, out = set(), []
            for p in positions:
                for s in p.key_signals:
                    key = str(s.get("signal"))
                    if key not in seen:
                        seen.add(key)
                        out.append(key)
            return out
        # Later rounds: signals named by agents that just changed position.
        out = []
        for p in positions:
            if p.changed_from and p.responding_to:
                out.append(f"{p.agent_name} moved {p.changed_from}→{p.position}")
        return out

    @staticmethod
    def _round_consensus(positions: list[AgentPosition]) -> bool:
        if not positions:
            return False
        top = Counter(p.position for p in positions).most_common(1)[0][1]
        return top >= 8

    def _determine_consensus(
        self, final_round: DebateRound
    ) -> tuple[str, dict[str, int], list[str], str]:
        counts = Counter(p.position for p in final_round.positions)
        consensus_count = {k: counts.get(k, 0) for k in POSITIONS if counts.get(k)}
        if not counts:
            return "deadlock", {}, [], "deadlock"
        winner, n = counts.most_common(1)[0]
        if n >= 8:
            tier = "consensus"
        elif n >= 6:
            tier = "majority"
        else:
            tier = "deadlock"
        final = winner if tier != "deadlock" else "deadlock"
        dissenting = sorted(
            p.agent_id for p in final_round.positions if p.position != winner
        )
        return final, consensus_count, dissenting, tier

    # ── Emergent insight generation ──────────────────────────────────

    def _generate_emergent_insights(
        self, rounds: list[DebateRound], ctx: dict[str, Any]
    ) -> list[str]:
        insights: list[str] = []
        final = rounds[-1].positions
        by_id = {p.agent_id: p for p in final}

        # 1) Reinforcement — multiple independent agents flag the same theme.
        income_flaggers = [
            by_id[a].agent_name
            for a in ("income_verification", "employment_reconciliation", "fraud_screening")
            if a in by_id and by_id[a].position in ("escalate", "block")
        ]
        if len(income_flaggers) >= 2:
            insights.append(
                f"{len(income_flaggers)} agents independently flagged income/employment "
                f"({', '.join(income_flaggers)}) — this points to a systematic documentation "
                "issue, not a one-off."
            )

        # 2) Score-alone blind spot — credit clears but income/employment don't.
        credit = by_id.get("credit_assessment")
        if credit and credit.position == "allow" and income_flaggers:
            insights.append(
                "Credit approves on the score, but income and employment both flag concerns — "
                "the credit score alone doesn't tell the full story."
            )

        # 3) Cascading risk — a hard block contaminates downstream decisions.
        r1 = {p.agent_id: p for p in rounds[0].positions}
        blockers_r1 = [r1[a].agent_name for a in r1 if r1[a].position == "block"]
        moved = [p for p in final if p.changed_from and p.responding_to]
        if blockers_r1 and moved:
            insights.append(
                f"A hard block from {', '.join(blockers_r1)} cascaded: "
                f"{len(moved)} downstream agent(s) revised their position once they saw it."
            )

        # 4) Time-sensitive interaction — expiring rate lock + unresolved adverse.
        days = self._rate_lock_days(ctx)
        unresolved = any(p.position in ("escalate", "block") for p in final)
        if days is not None and days <= 7 and unresolved:
            insights.append(
                f"Rate lock expires in {days} day(s). If the open issues aren't resolved, the "
                "rate will need to be re-locked at a likely higher rate — further increasing DTI."
            )

        # 5) Document contradictions visible only across the file.
        contras = ctx.get("contradictions") or []
        if len(contras) >= 1:
            fields = sorted({c["field_name"] for c in contras if c.get("field_name")})
            insights.append(
                f"{len(contras)} document contradiction(s) on file"
                + (f" ({', '.join(fields)})" if fields else "")
                + " — the source documents disagree with the application."
            )

        if not insights:
            insights.append(
                "Agents converged without conflict — no cross-signal risk emerged beyond the "
                "individual assessments."
            )
        return insights

    def _build_recommendation(
        self,
        final_round: DebateRound,
        final_consensus: str,
        tier: str,
        consensus_count: dict[str, int],
        dissenting: list[str],
        ctx: dict[str, Any],
    ) -> str:
        by_id = {p.agent_id: p for p in final_round.positions}
        total = len(final_round.positions)
        agreeing = consensus_count.get(final_consensus, 0) if final_consensus != "deadlock" else 0
        head = {
            "consensus": f"CONSENSUS to {final_consensus} ({agreeing}/{total} agents agree).",
            "majority": f"MAJORITY to {final_consensus} ({agreeing}/{total}), with noted dissent.",
            "deadlock": f"DEADLOCK — no outcome reached {max(consensus_count.values()) if consensus_count else 0}/{total}; "
                        "this needs a human decision.",
        }[tier]

        drivers = []
        for a in ("credit_assessment", "income_verification", "dti_calculation", "ltv_assessment"):
            p = by_id.get(a)
            if p:
                drivers.append(f"{p.agent_name} {p.position}")
        why = "Key positions: " + ", ".join(drivers) + "." if drivers else ""

        dissent_txt = ""
        if dissenting:
            names = self._names(dissenting[:3])
            dissent_txt = (
                f" Dissenting: {names}"
                + ("…" if len(dissenting) > 3 else "")
                + " — their concern matters because a single missed block can void the file."
            )

        if final_consensus in ("block", "escalate") or tier == "deadlock":
            nxt = " Next: resolve the blocking signals before any approval; do not route to closing."
        else:
            nxt = " Next: proceed to the human-review queue for sign-off, then routing."

        return f"{head} {why}{dissent_txt}{nxt}".strip()

    # ── Claude path (opt-in) ─────────────────────────────────────────

    async def _claude_position(
        self,
        agent_id: str,
        round_number: int,
        ctx: dict[str, Any],
        prior_flat: dict[str, AgentPosition],
    ) -> Optional[AgentPosition]:
        prompt = self._build_debate_prompt(
            agent_id, AGENT_NAME[agent_id], round_number, ctx, prior_flat
        )
        try:
            resp = await self.anthropic.messages.create(
                model=_ANTHROPIC_MODEL,
                max_tokens=900,
                system=[{"type": "text", "text": prompt["system"],
                         "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": prompt["user"]}],
            )
        except Exception:
            return None
        data = self._parse_json(resp)
        if not isinstance(data, dict) or data.get("position") not in POSITIONS:
            return None
        prior = prior_flat.get(agent_id)
        changed = data.get("changed_from")
        if changed not in POSITIONS:
            changed = (prior.position if prior and prior.position != data["position"] else None)
        return AgentPosition(
            agent_id=agent_id,
            agent_name=AGENT_NAME[agent_id],
            round=round_number,
            position=data["position"],
            confidence=max(0.0, min(1.0, _f(data.get("confidence")) or 0.6)),
            reasoning=str(data.get("reasoning") or "").strip() or f"{AGENT_NAME[agent_id]} position.",
            key_signals=data.get("key_signals") if isinstance(data.get("key_signals"), list)
            else self._key_signals(agent_id, ctx, ctx["decisions"].get(agent_id)),
            responding_to=[a for a in (data.get("responding_to") or []) if isinstance(a, str)] or None,
            changed_from=changed,
        )

    def _build_debate_prompt(
        self,
        agent_id: str,
        agent_name: str,
        round_number: int,
        loan_context: dict[str, Any],
        prior_positions: dict[str, AgentPosition],
    ) -> dict[str, str]:
        """The Claude prompt for one agent in one round (system + user)."""
        d = loan_context["decisions"].get(agent_id) or {}
        system = (
            f"You are the {agent_name} evaluating a mortgage loan application. "
            f"Your role: {AGENT_ROLE.get(agent_id, 'evaluate the loan')}. "
            f"Your boundary outcomes are exactly: allow, recommend, escalate, block. "
            "You reason like an experienced underwriter — grounded only in the data given, "
            "never inventing facts. Return ONLY a JSON object, no prose."
        )

        e = loan_context["entity"]
        loan_lines = self._loan_brief(loan_context)
        own = ""
        if d:
            own = (
                f"\n\nYour own prior finding for this file (decision_outputs): "
                f"{d.get('outcome')} (confidence {d.get('confidence')}); "
                f"rule: {d.get('boundary_rule')}"
            )

        if round_number == 1 or not prior_positions:
            user = (
                "Here is the loan data:\n" + loan_lines + own +
                f"\n\nQuestion: Should this loan be approved?\n\n"
                "State your INDEPENDENT position. Respond as JSON:\n"
                '{"position":"allow|recommend|escalate|block","confidence":0.0-1.0,'
                '"reasoning":"plain English","key_signals":[{"signal":"...","value":"...",'
                '"assessment":"..."}],"changed_from":null,"responding_to":null}'
            )
        else:
            peer_lines = []
            for aid, p in prior_positions.items():
                if aid == agent_id:
                    continue
                peer_lines.append(
                    f"  {p.agent_name}: {p.position.upper()} ({p.confidence:.2f}) — {p.reasoning}"
                )
            mine = prior_positions.get(agent_id)
            mine_txt = (
                f"{mine.position.upper()} ({mine.confidence:.2f}) — {mine.reasoning}"
                if mine else "(no prior position)"
            )
            user = (
                "Loan data:\n" + loan_lines +
                f"\n\nYour Round {round_number-1} position: {mine_txt}\n\n"
                f"What the other agents found in Round {round_number-1}:\n"
                + "\n".join(peer_lines) +
                "\n\nGiven these findings, do you MAINTAIN or REVISE your position? "
                "What new insight emerges from combining your analysis with theirs? "
                "Respond as JSON:\n"
                '{"position":"allow|recommend|escalate|block","confidence":0.0-1.0,'
                '"reasoning":"plain English","key_signals":[...],'
                '"changed_from":null or "prior_position",'
                '"responding_to":["agent_ids that influenced you"]}'
            )
        return {"system": system, "user": user}

    @staticmethod
    def _loan_brief(ctx: dict[str, Any]) -> str:
        e = ctx["entity"]
        rl = ctx.get("rate_lock") or {}
        def pct(v):
            f = _f(v)
            return "—" if f is None else (f"{f*100:.0f}%" if f <= 1.5 else f"{f:.0f}%")
        return (
            f"  Application: {ctx['application_id']} (borrower {ctx['borrower_name']})\n"
            f"  Credit: mid score {e.get('mid_credit_score')}\n"
            f"  Income: combined monthly {e.get('combined_monthly_income')}, "
            f"obligations {e.get('monthly_obligations')}\n"
            f"  Ratios: DTI {pct(e.get('dti_back'))} back / {pct(e.get('dti_front'))} front, "
            f"LTV {pct(e.get('ltv'))}\n"
            f"  Loan: amount {e.get('loan_amount')}, appraised {e.get('appraised_value')}, "
            f"rate {e.get('interest_rate')}\n"
            f"  Rate lock: expires {rl.get('lock_expiry')} at {rl.get('locked_rate')}\n"
            f"  Status: {e.get('status')}, completeness {e.get('completeness_pct')}, "
            f"conflicts {e.get('conflict_count')} ({e.get('critical_conflict_count')} critical)\n"
            f"  Documents on file: {ctx.get('document_count')}; "
            f"contradictions: {len(ctx.get('contradictions') or [])}"
        )

    @staticmethod
    def _parse_json(resp: Any) -> Any:
        content = getattr(resp, "content", None)
        text = ""
        if isinstance(content, list):
            text = "\n".join(getattr(b, "text", "") or "" for b in content)
        elif content:
            text = str(content)
        text = text.strip()
        if not text:
            return None
        # Tolerate a fenced or prose-wrapped JSON object.
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1:
            text = text[start:end + 1]
        try:
            return json.loads(text)
        except (ValueError, json.JSONDecodeError):
            return None

    # ── Small domain helpers ─────────────────────────────────────────

    @staticmethod
    def _names(agent_ids: list[str]) -> str:
        names = [AGENT_NAME.get(a, a) for a in agent_ids]
        if len(names) <= 1:
            return names[0] if names else ""
        return ", ".join(names[:-1]) + f" and {names[-1]}"

    def _rate_lock_days(self, ctx: dict[str, Any]) -> Optional[int]:
        rl = ctx.get("rate_lock") or {}
        expiry = rl.get("lock_expiry")
        if not expiry:
            return None
        try:
            exp = datetime.fromisoformat(str(expiry)[:10]).date()
        except ValueError:
            return None
        return (exp - datetime.now(timezone.utc).date()).days

    def _employer_drift(self, ctx: dict[str, Any]) -> Optional[str]:
        emp = ctx.get("borrower", {}).get("employment") if isinstance(ctx.get("borrower"), dict) else None
        if isinstance(emp, dict):
            m = _f(emp.get("employer_name_match_confidence"))
            if m is not None and m < 0.85:
                return f"match {m:.2f}"
        return None

    def _ltv_ok(self, ctx: dict[str, Any]) -> bool:
        ltv = _f(ctx["entity"].get("ltv"))
        if ltv is None:
            return False
        return (ltv * 100 if ltv <= 1.5 else ltv) <= 90

    def _dti_high(self, ctx: dict[str, Any]) -> bool:
        dti = _f(ctx["entity"].get("dti_back"))
        if dti is None:
            return False
        return (dti * 100 if dti <= 1.5 else dti) >= 43


# Which loan signals each agent surfaces in its position (drawn from the
# agent's frozen context_snapshot first, then the loan's entity_states).
_AGENT_SIGNAL_FIELDS: dict[str, list[str]] = {
    "credit_assessment": ["mid_credit_score", "credit_score", "active_bankruptcy",
                          "credit_utilization", "no_derogatory_last_24_months"],
    "fraud_screening": ["fraud_score", "watchlist_match", "synthetic_identity_flag",
                        "identity_match_confidence", "document_authenticity_score"],
    "compliance_check": ["all_hmda_fields_complete", "fair_lending_violation",
                         "state_rules_passed", "missing_required_disclosures"],
    "employment_reconciliation": ["reconciliation_status", "continuity_coverage_pct",
                                  "max_gap_days", "employer_name_match_confidence",
                                  "stated_vs_verified_drift_pct"],
    "income_verification": ["verified_income", "income_discrepancy_pct",
                            "income_confidence_score", "employment_type", "payroll_verified"],
    "dti_calculation": ["dti_back", "dti_front", "monthly_obligations", "monthly_income"],
    "ltv_assessment": ["ltv", "appraised_value", "loan_amount", "appraisal_disputed"],
    "product_eligibility": ["program_name", "within_conforming_limit",
                            "guideline_exception_required"],
    "rate_pricing": ["interest_rate", "rate_within_normal_band", "llpa_adjustment",
                     "rate_exceeds_usury"],
    "underwriting_decision": ["risk_score", "any_upstream_hard_block",
                              "underwriting_outcome", "senior_underwriter_review_required"],
    "approval_routing": ["routing_target", "applicant_dispute_flag"],
    "closing_readiness": ["all_conditions_cleared", "cd_timing_compliant",
                          "title_clear", "title_defect", "insurance_gap"],
}
