"""Accord — MiroFish endpoints (debate / simulate / swarm).

Thin HTTP layer over the engines in ``core.mirofish``: run, persist to the
``mirofish_*`` tables, and read back. Reuses the accord pool from
``api.accord.pipeline``.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from api.accord.auth import get_tenant_id, get_current_user

from api.accord.pipeline import _get_pool, _J, _require_db
from core.mirofish import (
    DebateEngine,
    PolicySimulator,
    SwarmAnalyzer,
    SimulationScenario,
    get_scenario,
    list_scenarios,
)

router = APIRouter(prefix="/api/accord/mirofish", tags=["accord-mirofish"])


def _dumps(v: Any) -> str:
    return json.dumps(v, default=str)


def _naive(dt):
    return dt.replace(tzinfo=None) if (dt and getattr(dt, "tzinfo", None)) else dt


def _as_uuid(value: str) -> UUID:
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        raise HTTPException(422, f"Invalid id: {value!r}")


# ─────────────────────────────────────────────────────────────────────
# Debate
# ─────────────────────────────────────────────────────────────────────


@router.post("/debate")
async def run_debate(payload: dict = Body(...), user: dict = Depends(get_current_user)) -> dict:
    _require_db()
    app_id = (payload.get("application_id") or "").strip()
    if not app_id:
        raise HTTPException(422, "application_id is required")
    question = payload.get("question") or "Should this loan be approved?"
    tenant_id = user["tenant_id"]

    pool = await _get_pool()
    res = await DebateEngine(pool).debate(app_id, question=question, tenant_id=tenant_id)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO mirofish_debates (
                debate_id, application_id, tenant_id, question, rounds,
                final_consensus, consensus_count, recommendation,
                emergent_insights, duration_seconds
            ) VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7::jsonb,$8,$9::jsonb,$10)
            """,
            res.debate_id, app_id, tenant_id, question,
            _dumps([r.model_dump(mode="json") for r in res.rounds]),
            res.final_consensus, _dumps(res.consensus_count), res.recommendation,
            _dumps(res.emergent_insights), res.total_duration_seconds,
        )
    return res.model_dump(mode="json")


@router.get("/debates")
async def list_debates(
    application_id: Optional[str] = Query(None),
    tenant_id: str = Depends(get_tenant_id),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    _require_db()
    pool = await _get_pool()
    where = ["tenant_id = $1"]
    params: list[Any] = [tenant_id]
    if application_id:
        params.append(application_id)
        where.append(f"application_id = ${len(params)}")
    params.append(limit)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT debate_id, application_id, question, final_consensus,
                   consensus_count, duration_seconds, created_at
            FROM mirofish_debates WHERE {' AND '.join(where)}
            ORDER BY created_at DESC LIMIT ${len(params)}
            """,
            *params,
        )
    return {
        "total": len(rows),
        "debates": [
            {
                "debate_id": str(r["debate_id"]),
                "application_id": r["application_id"],
                "question": r["question"],
                "final_consensus": r["final_consensus"],
                "consensus_count": _J(r["consensus_count"]),
                "duration_seconds": r["duration_seconds"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ],
    }


@router.get("/debates/{debate_id}")
async def get_debate(debate_id: str) -> dict:
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "SELECT * FROM mirofish_debates WHERE debate_id = $1", _as_uuid(debate_id)
        )
    if r is None:
        raise HTTPException(404, "Debate not found")
    return {
        "debate_id": str(r["debate_id"]),
        "application_id": r["application_id"],
        "question": r["question"],
        "rounds": _J(r["rounds"]),
        "final_consensus": r["final_consensus"],
        "consensus_count": _J(r["consensus_count"]),
        "recommendation": r["recommendation"],
        "emergent_insights": _J(r["emergent_insights"]),
        "total_duration_seconds": r["duration_seconds"],
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
    }


# ─────────────────────────────────────────────────────────────────────
# Simulate  (literal sub-paths declared before /{simulation_id})
# ─────────────────────────────────────────────────────────────────────


@router.get("/simulate/prebuilt")
async def simulate_prebuilt() -> dict:
    return {"scenarios": list_scenarios()}


@router.get("/simulate/history")
async def simulate_history(
    tenant_id: str = Depends(get_tenant_id), limit: int = Query(50, ge=1, le=200)
) -> dict:
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT simulation_id, scenario_name, scenario_type, status,
                   total_apps, affected_apps, impact, created_at
            FROM mirofish_simulations WHERE tenant_id = $1
            ORDER BY created_at DESC LIMIT $2
            """,
            tenant_id, limit,
        )
    return {
        "total": len(rows),
        "simulations": [
            {
                "simulation_id": str(r["simulation_id"]),
                "scenario_name": r["scenario_name"],
                "scenario_type": r["scenario_type"],
                "status": r["status"],
                "total_apps": r["total_apps"],
                "affected_apps": r["affected_apps"],
                "impact": _J(r["impact"]),
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ],
    }


@router.post("/simulate")
async def run_simulate(payload: dict = Body(...), user: dict = Depends(get_current_user)) -> dict:
    _require_db()
    tenant_id = user["tenant_id"]
    scenario: Optional[SimulationScenario] = None

    if payload.get("scenario_name"):
        scenario = get_scenario(payload["scenario_name"])
        if scenario is None:
            raise HTTPException(404, f"Unknown scenario: {payload['scenario_name']}")
    elif payload.get("custom"):
        custom = payload["custom"]
        overrides = custom.get("overrides") or {}
        if not overrides:
            raise HTTPException(422, "custom.overrides is required")
        stype = custom.get("type")
        if stype not in ("policy", "stress", "regulatory"):
            stype = "stress" if "_stress" in overrides else "policy"
        scenario = SimulationScenario(
            name=custom.get("name") or "Custom scenario",
            type=stype,
            description=custom.get("description") or "Custom what-if.",
            overrides=overrides,
        )
    else:
        raise HTTPException(422, "Provide scenario_name or custom.overrides")

    scenario.tenant_id = tenant_id
    pool = await _get_pool()
    res = await PolicySimulator(pool).simulate(scenario)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO mirofish_simulations (
                simulation_id, tenant_id, scenario_name, scenario_type,
                scenario_config, status, total_apps, affected_apps,
                flipped, impact, agent_insights, started_at, completed_at
            ) VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7,$8,$9::jsonb,$10::jsonb,$11::jsonb,$12,$13)
            ON CONFLICT (simulation_id) DO UPDATE SET
                scenario_config = EXCLUDED.scenario_config,
                status          = EXCLUDED.status,
                total_apps      = EXCLUDED.total_apps,
                affected_apps   = EXCLUDED.affected_apps,
                flipped         = EXCLUDED.flipped,
                impact          = EXCLUDED.impact,
                agent_insights  = EXCLUDED.agent_insights,
                started_at      = EXCLUDED.started_at,
                completed_at    = EXCLUDED.completed_at
            """,
            res.simulation_id, tenant_id, res.scenario.name, res.scenario.type,
            _dumps(res.scenario.overrides), res.status, res.total_apps, res.affected_apps,
            _dumps([f.model_dump(mode="json") for f in res.flipped]),
            _dumps(res.impact), _dumps(res.agent_insights),
            _naive(res.started_at), _naive(res.completed_at),
        )
    return res.model_dump(mode="json")


@router.get("/simulate/{simulation_id}")
async def get_simulate(simulation_id: str) -> dict:
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "SELECT * FROM mirofish_simulations WHERE simulation_id = $1",
            _as_uuid(simulation_id),
        )
    if r is None:
        raise HTTPException(404, "Simulation not found")
    return {
        "simulation_id": str(r["simulation_id"]),
        "scenario": {
            "name": r["scenario_name"], "type": r["scenario_type"],
            "overrides": _J(r["scenario_config"]),
        },
        "status": r["status"],
        "total_apps": r["total_apps"],
        "affected_apps": r["affected_apps"],
        "flipped": _J(r["flipped"]),
        "impact": _J(r["impact"]),
        "agent_insights": _J(r["agent_insights"]),
        "started_at": r["started_at"].isoformat() if r["started_at"] else None,
        "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
    }


# ─────────────────────────────────────────────────────────────────────
# Swarm  (literal /latest before /{swarm_id})
# ─────────────────────────────────────────────────────────────────────


@router.post("/swarm")
async def run_swarm(payload: dict = Body(default={}), user: dict = Depends(get_current_user)) -> dict:
    _require_db()
    tenant_id = user["tenant_id"]
    pool = await _get_pool()
    res = await SwarmAnalyzer(pool).analyze(tenant_id)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO mirofish_swarm_runs (
                swarm_id, tenant_id, total_apps_scanned, insights, agent_summaries
            ) VALUES ($1,$2,$3,$4::jsonb,$5::jsonb)
            """,
            res.swarm_id, tenant_id, res.total_apps_scanned,
            _dumps([i.model_dump(mode="json") for i in res.insights]),
            _dumps(res.agent_summaries),
        )
    return res.model_dump(mode="json")


@router.get("/swarm/latest")
async def swarm_latest(tenant_id: str = Depends(get_tenant_id)) -> dict:
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "SELECT * FROM mirofish_swarm_runs WHERE tenant_id = $1 "
            "ORDER BY created_at DESC LIMIT 1",
            tenant_id,
        )
    if r is None:
        raise HTTPException(404, "No swarm runs yet")
    return _swarm_view(r)


@router.get("/swarm/{swarm_id}")
async def get_swarm(swarm_id: str) -> dict:
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "SELECT * FROM mirofish_swarm_runs WHERE swarm_id = $1", _as_uuid(swarm_id)
        )
    if r is None:
        raise HTTPException(404, "Swarm run not found")
    return _swarm_view(r)


def _swarm_view(r) -> dict:
    return {
        "swarm_id": str(r["swarm_id"]),
        "tenant_id": r["tenant_id"],
        "total_apps_scanned": r["total_apps_scanned"],
        "insights": _J(r["insights"]),
        "agent_summaries": _J(r["agent_summaries"]),
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
    }
