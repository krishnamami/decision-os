"""Seed loan_condition_instances for 7 summit loans from their ACTUAL decision
engine outcomes. Idempotent (ON CONFLICT DO NOTHING). DB-seeding only — no code
change, no deploy.

Every condition is grounded in a real blocking/escalated decision the engine
already produced (see the per-loan decision_outputs). NOTE (fidelity caveat):
INCOME_DISCREPANCY_EXPLANATION is given blocking to all 6 fraud loans per the
demo spec, but only 06238/06213/06161 actually carry block:income_verification —
06206 escalated and 02737/01111 allowed income. The two browser-verify loans
(Carlos 06161, Evelyn 06238) both genuinely block income, so their "3 blocking"
is accurate.
"""
import asyncio, os, uuid
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
load_dotenv()
import asyncpg

TENANT = 'summit'
NOW = datetime.now(timezone.utc)

FRAUD_LOANS = [
    ('APP-LOAN-20260304-06238', 0.820, -9),   # 9 days over SLA
    ('APP-LOAN-20260304-06213', 0.818, -8),
    ('APP-LOAN-20260304-06206', 0.795, -7),
    ('APP-LOAN-20260303-06161', 0.779, -6),
    ('APP-LOAN-20260128-02737', 0.782, -5),
    ('APP-LOAN-20260112-01111', 0.813, -4),
]

CLOSING_LOAN = ('APP-LOAN-20260303-06195', -3)


async def main():
    url = os.environ['DATABASE_URL'].replace(
        'postgresql+asyncpg', 'postgresql'
    ).replace('postgresql+psycopg2', 'postgresql')
    conn = await asyncpg.connect(url)

    # conditions_library has NO blocks_closing column (that lives on the instance
    # table) — so we select only the template fields and pass blocks explicitly.
    lib = await conn.fetch('''
        SELECT code, category, template_text, agency_citation,
               prior_to, sla_hours, assignee, edms_document_type,
               governed_by, recommended_action, review_area
        FROM conditions_library
        WHERE code IN (
            'FRAUD_IDENTITY_REVIEW',
            'INCOME_DISCREPANCY_EXPLANATION',
            'EMPLOYMENT_VOE_CURRENT',
            'CLOSING_CD_TIMING',
            'CLOSING_RATE_LOCK_EXPIRY',
            'INCOME_W2_REQUIRED',
            'EMPLOYMENT_GAP_LOE',
            'COMPLIANCE_HMDA_COMPLETE'
        )
    ''')
    lib_map = {r['code']: dict(r) for r in lib}
    print(f'Library rows loaded: {list(lib_map.keys())}')

    inserted = 0
    errors = []

    async def seed_condition(app_id, code, status, days_offset, blocks_closing=None):
        nonlocal inserted
        if code not in lib_map:
            errors.append(f'Missing library code: {code}')
            return

        t = lib_map[code]
        due = NOW + timedelta(days=days_offset)
        opened = NOW - timedelta(days=abs(days_offset) + 2)
        blocks = bool(blocks_closing) if blocks_closing is not None else False

        try:
            await conn.execute('''
                INSERT INTO loan_condition_instances (
                    id, application_id, tenant_id,
                    condition_code, category,
                    condition_text, agency_citation,
                    status, prior_to, sla_hours,
                    due_date, opened_at,
                    assignee, assigned_to_name,
                    edms_document_type,
                    blocks_closing, auto_satisfy,
                    generated_by, notes
                ) VALUES (
                    $1, $2, $3,
                    $4, $5,
                    $6, $7,
                    $8, $9, $10,
                    $11, $12,
                    $13, $14,
                    $15,
                    $16, false,
                    $17, $18
                )
                ON CONFLICT (application_id, tenant_id, condition_code)
                DO NOTHING
            ''',
                str(uuid.uuid4()), app_id, TENANT,
                code, t['category'],
                t['template_text'], t['agency_citation'],
                status, t['prior_to'], t['sla_hours'],
                due, opened,
                t['assignee'],
                'Processor' if t['assignee'] == 'borrower' else 'Lender',
                t.get('edms_document_type'),
                blocks,
                'fraud_screening' if 'FRAUD' in code else 'decision_engine',
                'Auto-generated from real decision outcome'
            )
            inserted += 1
        except Exception as e:
            errors.append(f'{app_id}/{code}: {e}')

    # Only these 3 carry a real block:income_verification (from decision_outputs);
    # the other 3 fraud loans escalated/allowed income, so a *blocking* income
    # condition would be fabricated for them.
    INCOME_BLOCKED = {
        'APP-LOAN-20260304-06238',  # Evelyn Davis
        'APP-LOAN-20260304-06213',  # Priya Clark
        'APP-LOAN-20260303-06161',  # Carlos Smith
    }

    # Self-heal: a prior run over-seeded a blocking INCOME_DISCREPANCY_EXPLANATION
    # to the non-income-blocked loans. ON CONFLICT DO NOTHING won't remove those,
    # so delete them explicitly before re-seeding the accurate condition.
    non_income = [a for a, _, _ in FRAUD_LOANS if a not in INCOME_BLOCKED]
    removed = await conn.execute(
        "DELETE FROM loan_condition_instances "
        "WHERE tenant_id=$1 AND condition_code='INCOME_DISCREPANCY_EXPLANATION' "
        "AND application_id = ANY($2::text[])",
        TENANT, non_income)
    print(f'Corrected (removed mis-seeded income conditions): {removed}')

    # ── FRAUD BLOCKED LOANS ─────────────────────────────────
    for app_id, fraud_score, sla_days in FRAUD_LOANS:
        await seed_condition(app_id, 'FRAUD_IDENTITY_REVIEW', 'open', sla_days, blocks_closing=True)
        if app_id in INCOME_BLOCKED:
            # Real block:income_verification -> blocking income condition.
            await seed_condition(app_id, 'INCOME_DISCREPANCY_EXPLANATION', 'open', sla_days + 1, blocks_closing=True)
        else:
            # Income allowed/escalated, but employment escalated for all 6 ->
            # an employment-gap review condition (non-blocking) instead.
            await seed_condition(app_id, 'EMPLOYMENT_GAP_LOE', 'open', 3, blocks_closing=False)
        await seed_condition(app_id, 'EMPLOYMENT_VOE_CURRENT', 'open', 3, blocks_closing=False)
        await seed_condition(app_id, 'CLOSING_CD_TIMING', 'open', 4, blocks_closing=True)

    # ── JOSHUA YOUNG — closing block only ───────────────────
    app_id, sla_days = CLOSING_LOAN
    await seed_condition(app_id, 'CLOSING_CD_TIMING', 'open', sla_days, blocks_closing=True)
    await seed_condition(app_id, 'CLOSING_RATE_LOCK_EXPIRY', 'open', 2, blocks_closing=True)
    await seed_condition(app_id, 'COMPLIANCE_HMDA_COMPLETE', 'open', 5, blocks_closing=False)

    # ── VERIFY ──────────────────────────────────────────────
    print(f'\nInserted: {inserted} conditions')
    if errors:
        print(f'Errors ({len(errors)}):')
        for e in errors:
            print(f'  {e}')

    rows = await conn.fetch('''
        SELECT
            lci.application_id,
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE blocks_closing=true
                AND status NOT IN ('approved','waived')) as blocking,
            COUNT(*) FILTER (WHERE blocks_closing=false
                AND status='open') as needs_review,
            string_agg(lci.condition_code, ', ' ORDER BY lci.condition_code) as codes
        FROM loan_condition_instances lci
        WHERE lci.tenant_id = 'summit'
        GROUP BY lci.application_id
        ORDER BY blocking DESC, total DESC
    ''')

    print('\n--- summit loan_condition_instances ---')
    for r in rows:
        print(f"  {r['application_id']} | "
              f"{r['total']} total | "
              f"{r['blocking']} blocking | "
              f"{r['needs_review']} review | "
              f"{r['codes']}")

    await conn.close()


asyncio.run(main())
