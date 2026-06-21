"""
Safe fixture corrections — RA-2B Step 2

Applies only additive or non-breaking
corrections to live meridian data.
Does not touch intentionally tuned values.
"""

import asyncio, os, json, sys
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, '.')

TENANT = 'meridian'


def parse_amount(val) -> float:
    if val is None:
        return 0.0
    try:
        return float(
            str(val).replace(',', '')
                    .replace('$', '')
                    .replace('%', '')
        )
    except Exception:
        return 0.0


def first_val(fields, keys):
    for k in keys:
        v = fields.get(k)
        if v is not None and v != '':
            return v
    return None


async def fix_flood_zone(conn, app_id):
    """Additive: populate flood_zone if missing."""
    row = await conn.fetchrow('''
        SELECT loan_terms
        FROM entity_states
        WHERE application_id = $1
        AND tenant_id = $2
    ''', app_id, TENANT)

    if not row:
        return 'no_entity_states'

    lt = row['loan_terms'] or {}
    if isinstance(lt, str):
        try:
            lt = json.loads(lt)
        except Exception:
            lt = {}

    # Already set? Skip.
    existing = lt.get('urla', {}).get(
        'flood_zone'
    )
    if existing:
        return f'already_set:{existing}'

    # Try FLOOD_CERT first, then appraisal
    flood_zone = None
    for doc_type in [
        'FLOOD_CERT', 'APPRAISAL_URAR'
    ]:
        doc = await conn.fetchrow('''
            SELECT extracted_fields
            FROM document_index
            WHERE application_id = $1
            AND tenant_id = $2
            AND document_type = $3
            AND is_current = true
            LIMIT 1
        ''', app_id, TENANT, doc_type)

        if not doc:
            continue

        fields = doc['extracted_fields']
        if isinstance(fields, str):
            try:
                fields = json.loads(fields)
            except Exception:
                fields = {}

        keys = ['flood_zone_designation',
                'flood_zone', 'zone_designation',
                'fema_flood_zone']
        fz = first_val(fields, keys)
        if fz:
            flood_zone = str(fz).upper().strip()
            break

    if not flood_zone:
        return 'not_in_docs'

    # Write flood_zone to loan_terms.urla
    if 'urla' not in lt:
        lt['urla'] = {}
    lt['urla']['flood_zone'] = flood_zone

    await conn.execute('''
        UPDATE entity_states
        SET loan_terms = $1
        WHERE application_id = $2
        AND tenant_id = $3
    ''', json.dumps(lt), app_id, TENANT)

    return f'set:{flood_zone}'


async def fix_ltv_lesser_of(conn, app_id):
    """
    Correct LTV to use lesser-of rule.
    ONLY if correction does not change
    the loan decision outcome.
    """
    row = await conn.fetchrow('''
        SELECT ltv, loan_amount,
               appraised_value, purchase_price,
               dti_back, mid_credit_score
        FROM entity_states
        WHERE application_id = $1
        AND tenant_id = $2
    ''', app_id, TENANT)

    if not row:
        return 'no_entity_states'

    appraised = parse_amount(
        row['appraised_value']
    )
    purchase  = parse_amount(
        row['purchase_price']
    )
    loan_amt  = parse_amount(row['loan_amount'])
    ltv_stored = parse_amount(row['ltv'])

    # No purchase price: cannot apply
    if not purchase or purchase <= 0:
        return 'no_purchase_price'

    # Purchase >= appraised: no change needed
    # (lesser = appraised = current calc)
    if purchase >= appraised:
        return 'purchase_gte_appraised_no_change'

    # Compute correct LTV
    lesser = min(appraised, purchase)
    ltv_correct = round(
        loan_amt / lesser * 100, 3
    ) if lesser > 0 else 0

    # No meaningful change
    if abs(ltv_correct - ltv_stored) < 0.01:
        return 'no_change_needed'

    # Check overlay LTV limit
    overlay = await conn.fetchrow('''
        SELECT overlay_value
        FROM overlay_rules
        WHERE tenant_id = $1
        AND rule_type ILIKE $2
        AND (loan_type = 'conventional'
             OR loan_type IS NULL)
        ORDER BY loan_type NULLS LAST
        LIMIT 1
    ''', TENANT, '%ltv%')
    ltv_limit = parse_amount(
        overlay['overlay_value']
        if overlay else 97
    )

    # Would correction cross the LTV limit?
    was_over  = ltv_stored  > ltv_limit
    will_over = ltv_correct > ltv_limit

    if was_over != will_over:
        # This would flip the decision
        return (
            f'SKIP:would_flip_decision:'
            f'stored={ltv_stored:.3f}'
            f'_correct={ltv_correct:.3f}'
            f'_limit={ltv_limit}'
        )

    # Safe to apply
    await conn.execute('''
        UPDATE entity_states
        SET ltv = $1
        WHERE application_id = $2
        AND tenant_id = $3
    ''', ltv_correct, app_id, TENANT)

    return (
        f'corrected:'
        f'{ltv_stored:.3f}->{ltv_correct:.3f}'
    )


async def main():
    import asyncpg
    url = os.environ['DATABASE_URL']\
        .replace('+asyncpg', '')\
        .replace('postgresql+psycopg2', 'postgresql')
    conn = await asyncpg.connect(url)

    try:
        apps = await conn.fetch('''
            SELECT DISTINCT application_id
            FROM entity_states
            WHERE tenant_id = $1
            ORDER BY application_id
        ''', TENANT)

        print(f'Applying safe fixes to '
              f'{len(apps)} apps\n')

        print('-- FIX A: flood_zone --')
        for r in apps:
            app_id = r['application_id']
            result = await fix_flood_zone(
                conn, app_id
            )
            print(f'  {app_id}: {result}')

        print('\n-- FIX B: LTV lesser-of --')
        for r in apps:
            app_id = r['application_id']
            result = await fix_ltv_lesser_of(
                conn, app_id
            )
            print(f'  {app_id}: {result}')

        # Verify after fixes
        print('\n-- Verification --')
        sample = await conn.fetch('''
            SELECT application_id, ltv,
                   loan_terms
            FROM entity_states
            WHERE tenant_id = $1
            ORDER BY application_id
        ''', TENANT)

        for r in sample:
            lt = r['loan_terms'] or {}
            if isinstance(lt, str):
                try:
                    lt = json.loads(lt)
                except Exception:
                    lt = {}
            flood = lt.get(
                'urla', {}
            ).get('flood_zone', '-')
            print(
                f'  {r["application_id"]}: '
                f'ltv={r["ltv"]} '
                f'flood={flood}'
            )

    finally:
        await conn.close()


if __name__ == '__main__':
    asyncio.run(main())
