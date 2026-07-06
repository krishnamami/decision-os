"""
Backfill actionable conditions for existing blocked/escalated loans (CN-B).

For every loan across ALL tenants with a latest-version BLOCK/ESCALATE decision but
zero condition instances, generate the mapped conditions_library condition. Uses the
same mapping (persona_map.select_condition_code) and column semantics as the live
ConditionEngine hook, but set-based (templates cached once, per-tenant fetch, bulk
INSERT) so it scales. Idempotent: ON CONFLICT (application_id, tenant_id,
condition_code) DO NOTHING.

Safe by default -- DRY-RUN unless --run:
    python scripts/backfill_conditions_from_decisions.py           # dry-run (counts only)
    python scripts/backfill_conditions_from_decisions.py --run     # live inserts
"""
import asyncio
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from core.conditions.persona_map import select_condition_code

DRY_RUN = "--run" not in sys.argv

INSERT_SQL = """
INSERT INTO loan_condition_instances (
    application_id, tenant_id, condition_code, category, condition_text,
    agency_citation, status, prior_to, sla_hours, due_date, assignee,
    edms_document_type, blocks_closing, auto_satisfy, generated_by, decision_id
) VALUES ($1,$2,$3,$4,$5,$6,'open',$7,$8,$9,$10,$11,$12,$13,'auto_block',$14)
ON CONFLICT (application_id, tenant_id, condition_code) DO NOTHING
"""


async def main():
    import asyncpg
    url = os.environ["DATABASE_URL"].replace("+asyncpg", "").replace("postgresql+psycopg2", "postgresql")
    conn = await asyncpg.connect(url, timeout=60)
    now = datetime.now(timezone.utc)

    lib = {r["code"]: dict(r) for r in await conn.fetch(
        "SELECT code, template_text, category, prior_to, sla_hours, assignee, "
        "edms_document_type, agency_citation, auto_satisfy FROM conditions_library WHERE is_active = true")}
    tenants = [r["tenant_id"] for r in await conn.fetch(
        "SELECT DISTINCT tenant_id FROM entity_states ORDER BY tenant_id")]

    per_tenant, per_code, unmapped = {}, Counter(), Counter()
    print(f"MODE: {'DRY-RUN (no inserts)' if DRY_RUN else 'LIVE (inserting)'}\n")

    for tid in tenants:
        rows = await conn.fetch(
            """
            WITH latest AS (
              SELECT DISTINCT ON (application_id, decision_id)
                     id, application_id, decision_id, outcome, boundary_rule
              FROM decision_outputs
              WHERE tenant_id = $1 AND outcome IN ('block', 'escalate')
              ORDER BY application_id, decision_id, version DESC)
            SELECT l.id, l.application_id, l.decision_id, l.outcome, l.boundary_rule
            FROM latest l
            WHERE NOT EXISTS (SELECT 1 FROM loan_condition_instances lci
                  WHERE lci.application_id = l.application_id AND lci.tenant_id = $1)
            """, tid)

        seen, batch, apps = set(), [], set()
        for r in rows:
            code = select_condition_code(r["decision_id"], r["boundary_rule"], None)
            if not code:
                continue
            apps.add(r["application_id"])
            key = (r["application_id"], code)
            if key in seen:
                continue
            seen.add(key)
            t = lib.get(code)
            if not t:                       # code returned but absent from library
                unmapped[code] += 1
                continue
            sla = t["sla_hours"] or 48
            batch.append((
                r["application_id"], tid, code, t["category"], t["template_text"],
                t["agency_citation"], t["prior_to"], sla, now + timedelta(hours=sla),
                t["assignee"], t["edms_document_type"], (t["prior_to"] == "closing"),
                t["auto_satisfy"], r["id"],
            ))
            per_code[code] += 1

        if batch and not DRY_RUN:
            await conn.executemany(INSERT_SQL, batch)
        per_tenant[tid] = {"loans": len(apps), "conditions": len(batch)}
        print(f"  {tid:<12} loans={len(apps):>6}  conditions={len(batch):>6}")

    print(f"\n  TOTAL loans={sum(v['loans'] for v in per_tenant.values())}"
          f"  conditions={sum(v['conditions'] for v in per_tenant.values())}")
    print("\n  Conditions by code (persona area):")
    for code, n in per_code.most_common():
        print(f"    {code:<32} {n}")
    print(f"\n  Unmapped codes (no library match): {dict(unmapped) or 'none'}")
    await conn.close()


asyncio.run(main())
