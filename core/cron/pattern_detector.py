"""
PatternDetector — finds recurring override patterns and proposes
policy changes. Runs daily via cron.

A pattern = same decision_id + boundary_rule overridden 3+ times
in 30 days. Creates a policy_proposals record for admin review.

Note: the decision_outputs alias is ``dout`` (not ``do`` — DO is a
reserved word in Postgres) and loan_actions timestamps live on
``performed_at`` (there is no created_at column).
"""
from __future__ import annotations

import asyncpg

PATTERN_THRESHOLD = 3


async def detect_patterns(conn: asyncpg.Connection, tenant_id: str) -> int:
    patterns = await conn.fetch("""
        SELECT
            dout.decision_id,
            dout.boundary_rule,
            dout.outcome as accord_outcome,
            la.action_type as human_action,
            la.reason_category,
            COUNT(*) as override_count,
            array_agg(la.reason_text ORDER BY la.performed_at DESC) as reasons
        FROM decision_outputs dout
        JOIN loan_actions la ON la.application_id = dout.application_id
        WHERE dout.tenant_id = $1
          AND la.tenant_id = $1
          AND la.performed_at > NOW() - INTERVAL '30 days'
          AND dout.outcome IN ('block','escalate')
          AND la.action_type IN ('approve','deny')
          AND la.reason_text IS NOT NULL
          AND length(la.reason_text) >= 25
        GROUP BY dout.decision_id, dout.boundary_rule,
                 dout.outcome, la.action_type, la.reason_category
        HAVING COUNT(*) >= $2
        ORDER BY override_count DESC
    """, tenant_id, PATTERN_THRESHOLD)

    created = 0
    for p in patterns:
        existing = await conn.fetchval("""
            SELECT COUNT(*) FROM policy_proposals
            WHERE tenant_id=$1 AND decision_id=$2
              AND boundary_rule=$3 AND status='pending'
              AND created_at > NOW() - INTERVAL '7 days'
        """, tenant_id, p['decision_id'], p['boundary_rule'] or '')

        if existing:
            continue

        reasons = p['reasons'] or []
        example = reasons[0] if reasons else 'compensating factors'
        boundary = p['boundary_rule'] or 'policy boundary'

        summary = (
            f"In the last 30 days, underwriters overrode Accord's "
            f"'{p['accord_outcome']}' on {p['decision_id']} "
            f"{p['override_count']} times (boundary: {boundary}). "
            f"Most common reason: {p['reason_category'] or 'other'}. "
            f"Example: \"{example}\""
        )

        proposed = _suggest_change(
            p['decision_id'], boundary,
            p['reason_category'], example,
            p['override_count'],
        )

        await conn.execute("""
            INSERT INTO policy_proposals (
                tenant_id, decision_id, boundary_rule,
                override_count, pattern_summary,
                proposed_change, status, created_at
            ) VALUES ($1,$2,$3,$4,$5,$6,'pending',NOW())
        """,
            tenant_id, p['decision_id'],
            p['boundary_rule'] or '',
            p['override_count'], summary, proposed,
        )
        created += 1

    return created


def _suggest_change(decision_id, boundary, reason_category, example, count) -> str:
    # Key off the decision_id as well as the boundary text — the boundary is
    # often a generic label ("default escalate") while the decision_id reliably
    # names the rule family (dti_calculation, credit_assessment, …).
    bl = f"{decision_id or ''} {boundary or ''}".lower()
    if 'dti' in bl:
        return (
            f"Consider adding a DTI exception: allow files that exceed "
            f"the DTI cap when credit >= 720 AND reserves >= 6 months. "
            f"This pattern appeared {count} times. Example: \"{example}\""
        )
    elif 'credit' in bl:
        return (
            f"Consider a credit score waiver for borrowers who meet "
            f"other strong criteria. Pattern appeared {count} times. "
            f"Example: \"{example}\""
        )
    elif 'income' in bl:
        return (
            f"Consider raising the income discrepancy threshold for "
            f"certain employment types. Pattern: {count} overrides. "
            f"Example: \"{example}\""
        )
    elif 'fraud' in bl:
        return (
            f"Consider raising the fraud threshold for borrowers with "
            f"documented identity verification. {count} overrides. "
            f"Example: \"{example}\""
        )
    else:
        return (
            f"Underwriters overrode '{boundary}' {count} times with "
            f"'{reason_category}' reasoning. Review whether this "
            f"boundary needs an exception condition. "
            f"Example: \"{example}\""
        )


__all__ = ['detect_patterns', 'PATTERN_THRESHOLD']
