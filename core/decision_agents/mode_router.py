from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from core.context_store import ContextBundle, LendingContextStore
from core.normalizer.models import DecisionMode, DecisionOutcome


# ─────────────────────────────────────────────────────────────────────
# Routing actions
#
# Maps directly onto section 13 of the PRD (outcome routing diagram):
#   AUTO_WRITEBACK   — auto_execute + clean outcome → write decision record now
#   QUEUE_HUMAN      — recommend / human_approval / escalate → reviewer must act
#   SHADOW_RECORD    — shadow mode → trace recorded, no record persisted
#   BLOCK            — hard fail → write block decision record, no human queue,
#                       no external writeback (downstream will see the block
#                       via upstream_block_propagates_to_dependents)
# ─────────────────────────────────────────────────────────────────────


class RouteAction(str, Enum):
    AUTO_WRITEBACK = "auto_writeback"
    QUEUE_HUMAN = "queue_human"
    SHADOW_RECORD = "shadow_record"
    BLOCK = "block"


class HumanQueueItem(BaseModel):
    """One item placed on the human queue when a decision needs review."""

    id: UUID = Field(default_factory=uuid4)
    decision_id: str
    application_id: str
    agent_id: str
    proposed_outcome: DecisionOutcome
    confidence: float
    payload: dict[str, Any] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    enqueued_at: datetime = Field(default_factory=datetime.utcnow)


class HumanQueue(Protocol):
    async def enqueue(self, item: HumanQueueItem) -> UUID: ...
    async def list_open(self) -> list[HumanQueueItem]: ...


class InMemoryHumanQueue:
    """Reference implementation. Swap for a Redis/Postgres-backed queue
    in production — the protocol is intentionally narrow."""

    def __init__(self) -> None:
        self._items: dict[UUID, HumanQueueItem] = {}

    async def enqueue(self, item: HumanQueueItem) -> UUID:
        self._items[item.id] = item
        return item.id

    async def list_open(self) -> list[HumanQueueItem]:
        return list(self._items.values())


# ─────────────────────────────────────────────────────────────────────
# RoutedDecision — what the atomic_tool returns to the orchestrator.
# ─────────────────────────────────────────────────────────────────────


class RoutedDecision(BaseModel):
    action: RouteAction
    final_outcome: DecisionOutcome
    mode: DecisionMode
    decision_record_id: Optional[str] = None
    queue_item_id: Optional[UUID] = None
    notes: list[str] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────
# ModeRouter
# ─────────────────────────────────────────────────────────────────────


class ModeRouter:
    """Decides what to do with a (mode, outcome) pair after the agent
    has reasoned and the policy engine has confirmed the outcome.

    Writeback semantics:
      - AUTO_WRITEBACK: the decision record is written through the
        DecisionScopedStore so dependents can read the upstream output.
      - BLOCK: same — the record is written so the block propagates;
        the hard rule upstream_block_propagates_to_dependents needs the
        downstream decisions to be able to *see* the block.
      - QUEUE_HUMAN: nothing is written to the context store yet. The
        human's resolution drives the eventual writeback (handled by
        the upcoming reflection layer; out of scope for STEP 5).
      - SHADOW_RECORD: nothing is written. The decision was observed,
        not enacted."""

    def __init__(self, store: LendingContextStore, queue: HumanQueue):
        self._store = store
        self._queue = queue

    async def route(
        self,
        *,
        agent_id: str,
        decision_id: str,
        application_id: str,
        mode: DecisionMode,
        outcome: DecisionOutcome,
        confidence: float,
        output_payload: dict[str, Any],
        bundle: ContextBundle,
        reasons: Optional[list[str]] = None,
    ) -> RoutedDecision:
        reasons = list(reasons or [])

        # ── Hard block path — always writeback so dependents propagate ─
        if outcome == DecisionOutcome.BLOCK:
            record_id = await self._writeback(
                agent_id=agent_id,
                decision_id=decision_id,
                application_id=application_id,
                outcome=outcome,
                confidence=confidence,
                output_payload=output_payload,
                bundle=bundle,
            )
            return RoutedDecision(
                action=RouteAction.BLOCK,
                final_outcome=outcome,
                mode=mode,
                decision_record_id=record_id,
                notes=reasons + ["block writeback for downstream propagation"],
            )

        # ── Shadow — observe only ──────────────────────────────────────
        if mode == DecisionMode.SHADOW:
            return RoutedDecision(
                action=RouteAction.SHADOW_RECORD,
                final_outcome=outcome,
                mode=mode,
                notes=reasons + ["shadow: trace only, no writeback"],
            )

        # ── Recommend / human_approval / escalate → human queue ───────
        if (
            mode in (DecisionMode.RECOMMEND, DecisionMode.HUMAN_APPROVAL)
            or outcome in (DecisionOutcome.RECOMMEND, DecisionOutcome.ESCALATE)
        ):
            qid = await self._queue.enqueue(
                HumanQueueItem(
                    decision_id=decision_id,
                    application_id=application_id,
                    agent_id=agent_id,
                    proposed_outcome=outcome,
                    confidence=confidence,
                    payload=output_payload,
                    reasons=reasons,
                )
            )
            return RoutedDecision(
                action=RouteAction.QUEUE_HUMAN,
                final_outcome=outcome,
                mode=mode,
                queue_item_id=qid,
                notes=reasons + [f"queued for human review ({mode.value})"],
            )

        # ── auto_execute + ALLOW → writeback ──────────────────────────
        record_id = await self._writeback(
            agent_id=agent_id,
            decision_id=decision_id,
            application_id=application_id,
            outcome=outcome,
            confidence=confidence,
            output_payload=output_payload,
            bundle=bundle,
        )
        return RoutedDecision(
            action=RouteAction.AUTO_WRITEBACK,
            final_outcome=outcome,
            mode=mode,
            decision_record_id=record_id,
            notes=reasons + ["auto_execute writeback"],
        )

    async def _writeback(
        self,
        *,
        agent_id: str,
        decision_id: str,
        application_id: str,
        outcome: DecisionOutcome,
        confidence: float,
        output_payload: dict[str, Any],
        bundle: ContextBundle,
    ) -> str:
        """Persist the decision output through the DecisionScopedStore.

        The decision-scoped key matches what the ContextBuilder reads
        when it expands ``upstream_decision_ids`` — see
        LendingContextStore.snapshot()."""

        scoped = self._store.for_decision(decision_id)
        value = {
            "decision_id": decision_id,
            "outcome": outcome.value,
            "confidence": confidence,
            "payload": output_payload,
        }
        await scoped.set(
            entity_type="decision",
            entity_id=f"{application_id}:{decision_id}",
            value=value,
            agent=agent_id,
            confidence=confidence,
            upstream_decision_ids=list(bundle.upstream_decision_ids),
        )
        return f"{application_id}:{decision_id}"
