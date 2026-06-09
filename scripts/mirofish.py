#!/usr/bin/env python
"""MiroFish CLI — run the multi-agent debate, policy simulator, and swarm.

Examples
--------
  python scripts/mirofish.py debate APP-SC04-001
  python scripts/mirofish.py debate APP-SC02-001 --question "Is this fraud?"
  python scripts/mirofish.py simulate --scenario "DTI threshold: 43% → 36%"
  python scripts/mirofish.py simulate --list
  python scripts/mirofish.py swarm
  python scripts/mirofish.py swarm --severity critical
  python scripts/mirofish.py migrate            # apply the DB migration

Reads DATABASE_URL from .env (same as the rest of the repo). Runs the
deterministic engines by default; pass --llm to enrich with Claude when
ANTHROPIC_API_KEY is set. Results persist to the mirofish_* tables when
they exist (run `migrate` first); use --no-save to skip.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# Make `core.mirofish` importable when run as `python scripts/mirofish.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:  # keep the box-drawing / ⚠ glyphs alive on a Windows console
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

import asyncpg  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from core.mirofish import (  # noqa: E402
    DebateEngine,
    PolicySimulator,
    SwarmAnalyzer,
    get_scenario,
    list_scenarios,
)

MIGRATION = Path(__file__).resolve().parent / "migrations" / "create_mirofish_tables.sql"
_NAME_W = 22
_SEV_ICON = {"critical": "⚠", "warning": "⚠", "info": "ℹ", "emergent": "✦"}
_SEV_ORDER = ["critical", "warning", "info", "emergent"]


# ─────────────────────────────────────────────────────────────────────
# Optional Claude client
# ─────────────────────────────────────────────────────────────────────


def _maybe_client(use_llm: bool):
    if not use_llm:
        return None
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("  (--llm requested but ANTHROPIC_API_KEY is unset — running deterministic)")
        return None
    try:
        from anthropic import AsyncAnthropic  # type: ignore
    except ImportError:
        print("  (anthropic SDK not installed — running deterministic)")
        return None
    return AsyncAnthropic()


def _jsonb(value) -> str:
    """Serialize a pydantic-derived value for a JSONB bind ($n::jsonb)."""
    return json.dumps(value, default=str)


def _naive(dt):
    """Drop tzinfo for the migration's TIMESTAMP (without time zone)
    columns — the engine's timestamps are already UTC."""
    return dt.replace(tzinfo=None) if (dt and dt.tzinfo) else dt


# ─────────────────────────────────────────────────────────────────────
# DEBATE
# ─────────────────────────────────────────────────────────────────────


async def _loan_brief(pool, app_id: str) -> str:
    row = await pool.fetchrow(
        """
        SELECT loan_amount, mid_credit_score, ltv, borrower, loan_terms
        FROM entity_states WHERE application_id = $1 LIMIT 1
        """,
        app_id,
    )
    if not row:
        return f"{app_id} — (no entity_states row)"
    lt = row["loan_terms"]
    lt = json.loads(lt) if isinstance(lt, str) else (lt or {})
    borrower = row["borrower"]
    borrower = json.loads(borrower) if isinstance(borrower, str) else (borrower or {})
    name = ((borrower.get("identity") or {}).get("full_name")
            or (borrower.get("identity") or {}).get("name") or app_id)
    loan = row["loan_amount"]
    loan_txt = f"${loan/1000:,.0f}K" if loan else "$—"
    ltype = (lt.get("loan_type") or "—").title()
    score = int(row["mid_credit_score"]) if row["mid_credit_score"] else "—"
    ltv = row["ltv"]
    ltv_txt = f"{(ltv*100 if ltv and ltv <= 1.5 else ltv):.1f}%" if ltv else "—"
    return f"Borrower: {name} | {loan_txt} {ltype} | Score {score} | LTV {ltv_txt}"


async def cmd_debate(pool, args) -> None:
    eng = DebateEngine(pool, anthropic_client=_maybe_client(args.llm))
    res = await eng.debate(args.application_id, question=args.question, tenant_id=args.tenant)

    print(f"\n═══ MIROFISH DEBATE: {res.application_id} ═══")
    print(await _loan_brief(pool, res.application_id))
    print(f"Question: {res.question}\n")

    titles = {
        1: "ROUND 1: Independent Analysis",
        2: "ROUND 2: Cross-Agent Response",
        3: "ROUND 3: Final Consensus",
    }
    for rnd in res.rounds:
        print(f"─── {titles.get(rnd.round_number, 'ROUND ' + str(rnd.round_number))} ───\n")
        if rnd.round_number == 1:
            for p in rnd.positions:
                print(f"  {p.agent_name:<{_NAME_W}} {p.position.upper():<9} "
                      f"({p.confidence:.2f})  {p.reasoning}")
        else:
            changed = [p for p in rnd.positions if p.changed_from or p.responding_to]
            for p in changed:
                arrow = (f"{p.changed_from.upper()} → {p.position.upper()}"
                         if p.changed_from else p.position.upper())
                print(f"  {p.agent_name:<{_NAME_W}} {arrow}  ({p.confidence:.2f})")
                print(f'    "{p.reasoning}"')
            held = len(rnd.positions) - len(changed)
            if held:
                print(f"\n  [... {held} agents held their position ...]")
        print()

    # Final tally by position.
    final = res.rounds[-1].positions
    print("─── Vote tally ───\n")
    by_pos: dict[str, list[str]] = {}
    for p in final:
        by_pos.setdefault(p.position, []).append(p.agent_name)
    for pos in ("block", "escalate", "recommend", "allow"):
        if pos in by_pos:
            names = ", ".join(by_pos[pos])
            print(f"  {pos.upper():<10} {len(by_pos[pos]):>2} agents ({names})")

    n = res.consensus_count.get(res.final_consensus, max(res.consensus_count.values(), default=0))
    print(f"\n═══ CONSENSUS: {res.final_consensus.upper()} ({n}/{len(final)} agents) ═══\n")
    print("RECOMMENDATION:")
    print(f"  {res.recommendation}\n")
    if res.emergent_insights:
        print("EMERGENT INSIGHTS:")
        for i, ins in enumerate(res.emergent_insights, 1):
            print(f"  {i}. {ins}")
    print(f"\n  (debate {res.debate_id} · {res.total_duration_seconds}s)")

    if args.save:
        await _save_debate(pool, res, args.tenant)


async def _save_debate(pool, res, tenant) -> None:
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO mirofish_debates (
                    debate_id, application_id, tenant_id, question, rounds,
                    final_consensus, consensus_count, recommendation,
                    emergent_insights, duration_seconds
                ) VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7::jsonb,$8,$9::jsonb,$10)
                """,
                res.debate_id, res.application_id, tenant, res.question,
                _jsonb([r.model_dump(mode="json") for r in res.rounds]),
                res.final_consensus, _jsonb(res.consensus_count), res.recommendation,
                _jsonb(res.emergent_insights), res.total_duration_seconds,
            )
        print(f"  saved → mirofish_debates ({res.debate_id})")
    except asyncpg.UndefinedTableError:
        print("  (not saved — run `python scripts/mirofish.py migrate` first)")


# ─────────────────────────────────────────────────────────────────────
# SIMULATE
# ─────────────────────────────────────────────────────────────────────


def _print_scenario_list() -> None:
    print("\n═══ MIROFISH SCENARIOS ═══\n")
    by_type: dict[str, list[dict]] = {}
    for s in list_scenarios():
        by_type.setdefault(s["type"], []).append(s)
    for typ in ("policy", "stress", "regulatory"):
        if typ in by_type:
            print(f"  {typ.upper()}")
            for s in by_type[typ]:
                print(f"    • {s['name']}")
                print(f"        {s['description']}")
            print()


async def cmd_simulate(pool, args) -> None:
    if args.list or not args.scenario:
        _print_scenario_list()
        if not args.list:
            print("  Pick one with:  simulate --scenario \"<name>\"")
        return

    scenario = get_scenario(args.scenario)
    if scenario is None:
        print(f"Unknown scenario: {args.scenario!r}. Use --list to see options.")
        sys.exit(2)
    scenario.tenant_id = args.tenant

    res = await PolicySimulator(pool, anthropic_client=_maybe_client(args.llm)).simulate(scenario)
    im = res.impact

    print(f"\n═══ MIROFISH SIMULATION: {scenario.name} ═══")
    print(f"Type: {scenario.type} | {res.total_apps:,} apps scanned | "
          f"{res.affected_apps:,} affected\n")

    print("─── Impact ───\n")
    print(f"  Approval rate:  {im['approval_rate_before']*100:.1f}%  →  "
          f"{im['approval_rate_after']*100:.1f}%  ({im['approval_rate_change']*100:+.1f} pts)")
    print(f"  Approved volume: ${im['volume_before']/1e6:,.1f}M  →  "
          f"${im['volume_after']/1e6:,.1f}M  (${im['volume_change']/1e6:+,.1f}M)")
    print(f"  New blocks: {im['new_blocks']:,}   New approvals: {im['new_allows']:,}\n")

    if res.flipped:
        print(f"─── Flips ({len(res.flipped)}) — first 8 ───\n")
        for fl in res.flipped[:8]:
            print(f"  {fl.application_id}  {fl.decision_id}: "
                  f"{fl.from_outcome.upper()} → {fl.to_outcome.upper()}  "
                  f"(${fl.loan_amount/1000:,.0f}K)")
            print(f"    {fl.reason}")
        if len(res.flipped) > 8:
            print(f"\n  … and {len(res.flipped) - 8:,} more")
        print()

    if res.agent_insights:
        print("─── Agent insights ───\n")
        for ins in res.agent_insights:
            print(f"  • {ins}")

    print(f"\n  (simulation {res.simulation_id})")
    if args.save:
        await _save_simulation(pool, res, args.tenant)


async def _save_simulation(pool, res, tenant) -> None:
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO mirofish_simulations (
                    simulation_id, tenant_id, scenario_name, scenario_type,
                    scenario_config, status, total_apps, affected_apps,
                    flipped, impact, agent_insights, started_at, completed_at
                ) VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7,$8,$9::jsonb,$10::jsonb,$11::jsonb,$12,$13)
                """,
                res.simulation_id, tenant, res.scenario.name, res.scenario.type,
                _jsonb(res.scenario.overrides), res.status, res.total_apps, res.affected_apps,
                _jsonb([f.model_dump(mode="json") for f in res.flipped]),
                _jsonb(res.impact), _jsonb(res.agent_insights),
                _naive(res.started_at), _naive(res.completed_at),
            )
        print(f"  saved → mirofish_simulations ({res.simulation_id})")
    except asyncpg.UndefinedTableError:
        print("  (not saved — run `python scripts/mirofish.py migrate` first)")


# ─────────────────────────────────────────────────────────────────────
# SWARM
# ─────────────────────────────────────────────────────────────────────


async def cmd_swarm(pool, args) -> None:
    print("\n═══ MIROFISH PORTFOLIO SWARM ═══")
    res = await SwarmAnalyzer(pool, anthropic_client=_maybe_client(args.llm)).analyze(args.tenant)
    print(f"Scanned {res.total_apps_scanned:,} applications across 12 agents.\n")

    wanted = {args.severity} if args.severity else set(_SEV_ORDER)
    shown = [i for i in res.insights if i.severity in wanted]
    if not shown:
        print(f"  No insights at severity '{args.severity}'." if args.severity
              else "  No insights surfaced.")
    n = 0
    for sev in _SEV_ORDER:
        group = [i for i in res.insights if i.severity == sev and i.severity in wanted]
        if not group:
            continue
        print(f"{_SEV_ICON.get(sev, '•')} {sev.upper()} INSIGHTS:\n")
        for ins in group:
            n += 1
            agents = " + ".join(ins.detected_by)
            print(f"  {n}. {ins.insight_type.upper()} ({agents})")
            print(f"     {ins.description}")
            if ins.affected_apps:
                sample = ", ".join(ins.affected_apps[:6])
                more = f", … (+{len(ins.affected_apps) - 6})" if len(ins.affected_apps) > 6 else ""
                print(f"     Affected: {sample}{more}")
            print()

    if not args.severity:
        print("AGENT SUMMARIES:")
        for aid, summary in res.agent_summaries.items():
            label = aid.replace("_", " ").title()
            print(f"  {label}: {summary}")

    print(f"\n  (swarm {res.swarm_id})")
    if args.save:
        await _save_swarm(pool, res, args.tenant)


async def _save_swarm(pool, res, tenant) -> None:
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO mirofish_swarm_runs (
                    swarm_id, tenant_id, total_apps_scanned, insights, agent_summaries
                ) VALUES ($1,$2,$3,$4::jsonb,$5::jsonb)
                """,
                res.swarm_id, tenant, res.total_apps_scanned,
                _jsonb([i.model_dump(mode="json") for i in res.insights]),
                _jsonb(res.agent_summaries),
            )
        print(f"  saved → mirofish_swarm_runs ({res.swarm_id})")
    except asyncpg.UndefinedTableError:
        print("  (not saved — run `python scripts/mirofish.py migrate` first)")


# ─────────────────────────────────────────────────────────────────────
# MIGRATE
# ─────────────────────────────────────────────────────────────────────


async def cmd_migrate(pool, args) -> None:
    if not MIGRATION.exists():
        print(f"Migration file not found: {MIGRATION}")
        sys.exit(2)
    sql = MIGRATION.read_text(encoding="utf-8")
    async with pool.acquire() as conn:
        await conn.execute(sql)
    tables = await pool.fetch(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_name IN ('mirofish_debates','mirofish_simulations',
                             'mirofish_swarm_runs','activity_log','conditions')
        ORDER BY table_name
        """
    )
    print("Migration applied. Present tables:")
    for t in tables:
        print(f"  ✓ {t['table_name']}")


# ─────────────────────────────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mirofish", description="MiroFish multi-agent CLI")
    p.add_argument("--tenant", default="default", help="tenant_id (default: 'default')")
    p.add_argument("--llm", action="store_true", help="enrich with Claude (needs ANTHROPIC_API_KEY)")
    p.add_argument("--no-save", dest="save", action="store_false", help="don't persist the result")
    p.set_defaults(save=True)
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("debate", help="run a 3-round debate on one loan")
    d.add_argument("application_id")
    d.add_argument("--question", default="Should this loan be approved?")

    s = sub.add_parser("simulate", help="run a portfolio what-if scenario")
    s.add_argument("--scenario", help="scenario name (see --list)")
    s.add_argument("--list", action="store_true", help="list available scenarios")

    w = sub.add_parser("swarm", help="scan the portfolio for emergent patterns")
    w.add_argument("--severity", choices=["critical", "warning", "info", "emergent"],
                   help="only show this severity")

    sub.add_parser("migrate", help="apply the MiroFish DB migration")
    return p


async def _run(args) -> None:
    db_url = os.environ.get("DATABASE_URL", "").strip()
    if not db_url:
        print("DATABASE_URL is not set (.env). Cannot connect.")
        sys.exit(2)
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=4)
    try:
        handler = {
            "debate": cmd_debate, "simulate": cmd_simulate,
            "swarm": cmd_swarm, "migrate": cmd_migrate,
        }[args.command]
        await handler(pool, args)
    finally:
        await pool.close()


def main() -> None:
    args = _build_parser().parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
