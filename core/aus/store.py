"""AUS response persistence (RA-AUS-A).

Stores a parsed DU response in aus_responses (one row per app+tenant+system) and
loads it back for the enricher. The parser (du_parser.DUParser) does the shaping;
this module is just the thin DB layer. Population happens via ingest_du_response
(future MISMO adapter / demo seeding); load_aus_result is read by the enricher.
"""
from __future__ import annotations

import json
from typing import Optional

from core.aus.du_parser import DUParser


async def ingest_du_response(
    conn, application_id: str, tenant_id: str, du_response: dict,
) -> dict:
    """Parse a raw DU response dict and upsert it into aus_responses. Returns the
    parsed result. Idempotent on (application_id, tenant_id, aus_system)."""
    parsed = DUParser().parse(du_response)
    await conn.execute(
        """
        INSERT INTO aus_responses (
            application_id, tenant_id, aus_system, recommendation,
            raw_recommendation, approve, eligible, risk_class, findings,
            conditions, casefile_id, submission_date, parsed_response)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10::jsonb,$11,
                $12,$13::jsonb)
        ON CONFLICT (application_id, tenant_id, aus_system) DO UPDATE SET
            recommendation=EXCLUDED.recommendation,
            raw_recommendation=EXCLUDED.raw_recommendation,
            approve=EXCLUDED.approve, eligible=EXCLUDED.eligible,
            risk_class=EXCLUDED.risk_class, findings=EXCLUDED.findings,
            conditions=EXCLUDED.conditions, casefile_id=EXCLUDED.casefile_id,
            submission_date=EXCLUDED.submission_date,
            parsed_response=EXCLUDED.parsed_response
        """,
        application_id, tenant_id, parsed["system"], parsed["recommendation"],
        parsed["raw_recommendation"], parsed["approve"], parsed["eligible"],
        parsed["risk_class"], json.dumps(parsed["findings"]),
        json.dumps(parsed["conditions"]), parsed["casefile_id"],
        parsed["submission_date"] or None, json.dumps(parsed),
    )
    return parsed


async def load_aus_result(
    conn, application_id: str, tenant_id: str, aus_system: str = "DU",
) -> Optional[dict]:
    """Return the parsed AUS result for an application, or None if none exists."""
    row = await conn.fetchrow(
        """SELECT parsed_response FROM aus_responses
           WHERE application_id=$1 AND tenant_id=$2 AND aus_system=$3""",
        application_id, tenant_id, aus_system,
    )
    if not row or row["parsed_response"] is None:
        return None
    pr = row["parsed_response"]
    return json.loads(pr) if isinstance(pr, str) else pr


__all__ = ["ingest_du_response", "load_aus_result"]
