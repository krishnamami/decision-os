"""Quick smoke — count what the cron runner wrote into EDMS."""
import asyncio
import os

import asyncpg
from dotenv import load_dotenv

load_dotenv()


async def main() -> None:
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])
    n_out = await pool.fetchval(
        "SELECT COUNT(*) FROM decision_outputs WHERE decision_id = $1",
        "credit_assessment",
    )
    n_tl = await pool.fetchval(
        "SELECT COUNT(*) FROM decision_timeline WHERE decision_id = $1",
        "credit_assessment",
    )
    sample = await pool.fetch(
        """
        SELECT application_id, outcome, mode, risk_level, confidence,
               sla_seconds, actual_seconds, version
        FROM decision_outputs
        WHERE decision_id = $1
        ORDER BY decided_at DESC
        LIMIT 5
        """,
        "credit_assessment",
    )
    timeline = await pool.fetch(
        """
        SELECT application_id, from_state, to_state, trigger,
               pipeline_position, time_in_prev_state_seconds
        FROM decision_timeline
        WHERE decision_id = $1
        ORDER BY transition_at DESC
        LIMIT 5
        """,
        "credit_assessment",
    )
    print("decision_outputs(credit_assessment):", n_out)
    print("decision_timeline(credit_assessment):", n_tl)
    print("--- sample outputs ---")
    for r in sample:
        print(dict(r))
    print("--- sample timeline ---")
    for r in timeline:
        print(dict(r))
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
