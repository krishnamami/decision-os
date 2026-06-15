from __future__ import annotations

from typing import Optional
from uuid import UUID

import asyncpg

from .reflection import AgentLearning


class PostgresLearningStore:
    """Production replacement for InMemoryLearningStore.

    Lessons survive container restarts and deployments. Implements the
    LearningStore protocol (write / get / list_for_agent / list_for_decision)
    so a ReflectionService can be constructed against it unchanged."""

    def __init__(self, pool: asyncpg.Pool, tenant_id: str):
        self._pool = pool
        self._tenant_id = tenant_id

    async def write(self, learning: AgentLearning) -> UUID:
        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO agent_learnings (
                    agent_learning_id, tenant_id, agent_id, persona,
                    decision_id, trace_id, application_id,
                    original_ai_decision, human_decision,
                    override_reason, override_reason_code,
                    reviewer_role, reviewer_id, lesson,
                    similarity_tags, captured_at, expires_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)
                ON CONFLICT (agent_learning_id) DO NOTHING
            """,
                learning.agent_learning_id,
                self._tenant_id,
                learning.agent_id,
                learning.persona,
                learning.decision_id,
                learning.trace_id,
                getattr(learning, 'application_id', None),
                learning.original_ai_decision.value,
                learning.human_decision.value,
                learning.override_reason,
                learning.override_reason_code,
                learning.reviewer_role,
                learning.reviewer_id,
                learning.lesson,
                learning.similarity_tags,
                learning.captured_at,
                learning.expires_at,
            )
        return learning.agent_learning_id

    async def get(self, learning_id: UUID) -> Optional[AgentLearning]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM agent_learnings WHERE agent_learning_id=$1",
                learning_id,
            )
        return self._row_to_learning(row) if row else None

    async def list_for_agent(
        self, agent_id: str, decision_id: Optional[str] = None
    ) -> list[AgentLearning]:
        async with self._pool.acquire() as conn:
            if decision_id:
                rows = await conn.fetch("""
                    SELECT * FROM agent_learnings
                    WHERE tenant_id=$1 AND agent_id=$2
                      AND decision_id=$3 AND expires_at > NOW()
                    ORDER BY captured_at DESC LIMIT 50
                """, self._tenant_id, agent_id, decision_id)
            else:
                rows = await conn.fetch("""
                    SELECT * FROM agent_learnings
                    WHERE tenant_id=$1 AND agent_id=$2
                      AND expires_at > NOW()
                    ORDER BY captured_at DESC LIMIT 50
                """, self._tenant_id, agent_id)
        return [self._row_to_learning(r) for r in rows]

    async def list_for_decision(self, decision_id: str) -> list[AgentLearning]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM agent_learnings
                WHERE tenant_id=$1 AND decision_id=$2
                  AND expires_at > NOW()
                ORDER BY captured_at DESC LIMIT 50
            """, self._tenant_id, decision_id)
        return [self._row_to_learning(r) for r in rows]

    def _row_to_learning(self, row) -> AgentLearning:
        from core.normalizer.models import DecisionOutcome
        d = dict(row)
        return AgentLearning(
            agent_learning_id=d['agent_learning_id'],
            agent_id=d['agent_id'],
            persona=d['persona'],
            decision_id=d['decision_id'],
            trace_id=d.get('trace_id'),
            application_id=d.get('application_id'),
            original_ai_decision=DecisionOutcome(d['original_ai_decision']),
            human_decision=DecisionOutcome(d['human_decision']),
            override_reason=d['override_reason'],
            override_reason_code=d.get('override_reason_code'),
            reviewer_role=d['reviewer_role'],
            reviewer_id=d.get('reviewer_id'),
            lesson=d['lesson'],
            similarity_tags=list(d.get('similarity_tags') or []),
            captured_at=d['captured_at'],
            expires_at=d['expires_at'],
        )


__all__ = ['PostgresLearningStore']
