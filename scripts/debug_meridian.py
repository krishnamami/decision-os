"""Read-only debug: real entity_states values + actual vs expected outcomes
for all 16 meridian scenarios. Makes NO changes.

  python scripts/debug_meridian.py

Adapted to the real schema: property_state / loan_purpose / state are not
columns — loan_purpose lives in loan_terms.urla, fraud_score in
borrower.identity, co-score in co_borrowers[0].credit. decision_outputs is
deduped to the latest version per (application, decision).
"""
import asyncio
import json
import os

from dotenv import load_dotenv

load_dotenv()

EXPECTED = {
    'APP-MRID-SC01': ('fraud_screening',          'block'),
    'APP-MRID-SC02': ('dti_calculation',          'block'),
    'APP-MRID-SC03': ('income_verification',      'escalate'),
    'APP-MRID-SC04': ('employment_reconciliation', 'escalate'),
    'APP-MRID-SC05': ('compliance_check',         'block'),
    'APP-MRID-SC06': ('credit_assessment',        'allow'),
    'APP-MRID-SC07': ('dti_calculation',          'allow'),
    'APP-MRID-SC08': ('credit_assessment',        'block'),
    'APP-MRID-SC09': ('income_verification',      'block'),
    'APP-MRID-SC10': ('closing_readiness',        'block'),
    'APP-MRID-SC11': ('dti_calculation',          'block'),
    'APP-MRID-SC12': ('income_verification',      'block'),
    'APP-MRID-SC13': ('product_eligibility',      'block'),
    'APP-MRID-SC14': ('product_eligibility',      'escalate'),
    'APP-MRID-SC15': (None,                       None),
    'APP-MRID-SC16': ('closing_readiness',        'escalate'),
}


def _J(v):
    return (json.loads(v) if isinstance(v, str) else v) or {}


async def main():
    import asyncpg
    url = os.environ['DATABASE_URL'].replace('+asyncpg', '').replace('postgresql+psycopg2', 'postgresql')
    conn = await asyncpg.connect(url)

    es = await conn.fetch("""
        SELECT application_id, mid_credit_score, dti_back, loan_amount, ltv,
               borrower, co_borrowers, loan_terms, property
        FROM entity_states WHERE tenant_id='meridian' ORDER BY application_id
    """)
    # latest decision_outputs per (app, decision)
    dout = await conn.fetch("""
        SELECT DISTINCT ON (application_id, decision_id)
               application_id, decision_id, outcome
        FROM decision_outputs WHERE tenant_id='meridian'
        ORDER BY application_id, decision_id, version DESC
    """)
    await conn.close()

    decisions = {}
    for r in dout:
        decisions.setdefault(r['application_id'], {})[r['decision_id']] = r['outcome']

    hdr = (f"{'APP_ID':<16}{'credit':>7}{'dti':>7}{'ltv':>7}{'fraud':>7}{'co_sc':>7}"
           f"{'ftb':>6}  {'key_decision':<26}{'actual':<11}{'expected':<11}status")
    print(hdr)
    print("-" * len(hdr))
    npass = 0
    for r in es:
        app = r['application_id']
        bor = _J(r['borrower'])
        co = _J(r['co_borrowers']) if r['co_borrowers'] else []
        lt = _J(r['loan_terms'])
        fraud = (bor.get('identity', {}) or {}).get('fraud_score')
        ftb = bor.get('first_time_homebuyer')
        if ftb is None:
            ftb = (bor.get('income', {}) or {}).get('first_time_homebuyer')
        co_score = None
        if isinstance(co, list) and co:
            co0 = co[0] if isinstance(co[0], dict) else {}
            co_score = co0.get('mid_credit_score') or (co0.get('credit', {}) or {}).get('mid_score')
        dec_id, exp = EXPECTED.get(app, (None, None))
        actual = (decisions.get(app, {}).get(dec_id, 'NOT_RUN') if dec_id else 'NO_PERSONA')
        ok = (actual == exp)
        if dec_id and ok:
            npass += 1
        status = 'PASS' if ok else ('FLAG' if dec_id is None else 'FAIL')
        print(
            f"{app:<16}"
            f"{str(r['mid_credit_score'] or '?'):>7}"
            f"{str(round(float(r['dti_back']), 2) if r['dti_back'] is not None else 'None'):>7}"
            f"{str(round(float(r['ltv']), 1) if r['ltv'] is not None else '?'):>7}"
            f"{str(fraud if fraud is not None else '?'):>7}"
            f"{str(co_score if co_score is not None else '-'):>7}"
            f"{str(ftb if ftb is not None else '-'):>6}  "
            f"{str(dec_id):<26}{str(actual):<11}{str(exp):<11}{status}"
        )
    total = sum(1 for v in EXPECTED.values() if v[0] is not None)
    print(f"\n{npass}/{total} mapped scenarios match expected "
          f"(1 no-persona: SC15 asset_verification)")


asyncio.run(main())
