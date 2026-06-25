"""Exception population job (EX-C) — the WRITE path.

Persona stays DB-less (RULES 5/6); this post-decision writer reads what
approval_routing already emitted (decision_outputs.context_snapshot.output_payload:
exception_analysis from EX-A + compensating_factors_analysis from EX-B) and
persists loan_exceptions + compensating_factors. Same pattern as the
adverse_action_notices / hmda_lar backfills. Idempotent per decision_output
(clears + re-inserts). NEVER touches decision_outputs or any eval data.

NOTE: decision_outputs stores the persona payload in `context_snapshot` (there is
no output_payload column); the approval_level is persisted inside the row's
compensating_factors JSONB so the workflow can read the required level back.
"""
from __future__ import annotations

import json


def _payload(snapshot) -> dict:
    snap = json.loads(snapshot) if isinstance(snapshot, str) else (snapshot or {})
    return snap.get("output_payload", snap) if isinstance(snap, dict) else {}


async def populate_exception_records(
    conn, application_id: str, tenant_id: str, decision_output_id: str,
) -> dict:
    """Persist loan_exceptions + compensating_factors for one approval_routing
    decision_output, from its emitted exception_analysis + compensating_factors_
    analysis. Idempotent. Returns a summary dict."""
    row = await conn.fetchrow(
        """SELECT context_snapshot, outcome FROM decision_outputs
           WHERE id=$1 AND tenant_id=$2""",
        decision_output_id, tenant_id,
    )
    if not row:
        return {"written": False, "reason": "decision_output_not_found"}

    payload = _payload(row["context_snapshot"])
    exc_analysis = payload.get("exception_analysis") or {}
    cf_analysis = payload.get("compensating_factors_analysis") or {}
    if not exc_analysis:
        return {"written": False, "reason": "no_exception_analysis"}

    eligible = [e for e in exc_analysis.get("exceptions_available", [])
                if e.get("eligible_for_exception")]
    if not eligible:
        return {"written": False, "reason": "no_eligible_exceptions",
                "exceptions_created": 0}

    present_factors = [f for f in cf_analysis.get("factors", []) if f.get("present")]
    cf_blob = json.dumps({
        "approval_level": cf_analysis.get("approval_level"),
        "exception_score": cf_analysis.get("exception_score"),
        "factors": present_factors,
    })

    # Idempotent: clear prior rows for this decision_output (compensating_factors
    # FK loan_exceptions, so delete children first).
    await conn.execute(
        """DELETE FROM compensating_factors WHERE exception_id IN (
               SELECT id FROM loan_exceptions
               WHERE decision_output_id=$1 AND tenant_id=$2)""",
        decision_output_id, tenant_id,
    )
    await conn.execute(
        """DELETE FROM loan_exceptions WHERE decision_output_id=$1 AND tenant_id=$2""",
        decision_output_id, tenant_id,
    )

    written_ids = []
    for exc in eligible:
        exc_id = await conn.fetchval(
            """INSERT INTO loan_exceptions (
                   application_id, tenant_id, decision_output_id, exception_type,
                   blocked_persona, blocked_signal, blocked_value, threshold_value,
                   breach_pct, below_agency_floor, threshold_source, status,
                   compensating_factors)
               VALUES ($1,$2,$3,$4,'approval_routing',$5,$6,$7,$8,$9,$10,'requested',$11::jsonb)
               RETURNING id""",
            application_id, tenant_id, decision_output_id,
            exc.get("exception_type", "other"),
            exc.get("blocked_signal", ""),
            exc.get("actual_value"),
            exc.get("overlay_threshold"),
            exc.get("breach_pct"),
            exc.get("reason") == "below_agency_floor",
            cf_analysis.get("approval_level"),   # threshold_source = required level
            cf_blob,
        )
        for f in present_factors:
            await conn.execute(
                """INSERT INTO compensating_factors (
                       exception_id, application_id, tenant_id, factor_type,
                       factor_value, factor_numeric, threshold_met, evidence_source,
                       citation)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
                exc_id, application_id, tenant_id, f.get("factor_type"),
                str(f.get("strength", "")),
                f.get("reserves_months") or f.get("delta") or f.get("down_pct")
                or f.get("debt_pct") or f.get("tenure_months"),
                bool(f.get("present", False)), f.get("data_source", ""),
                f.get("citation", ""),
            )
        written_ids.append(str(exc_id))

    return {
        "written": True,
        "exceptions_created": len(written_ids),
        "exception_ids": written_ids,
        "approval_level": cf_analysis.get("approval_level"),
        "exception_score": cf_analysis.get("exception_score"),
    }


__all__ = ["populate_exception_records"]
