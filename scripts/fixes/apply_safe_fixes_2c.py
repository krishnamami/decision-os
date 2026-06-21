"""
RA-2C safe fixture corrections.
Adds occupancy_type, loan_purpose
to entity_states.loan_terms.urla
and verified obligations to
entity_states.loan_terms.obligations
for all 16 Meridian scenarios.
Additive only — does not change
any existing values.
"""

import asyncio, os, json, sys
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, '.')

TENANT = 'meridian'

from core.pipeline.golden_record_builder import (
    extract_occupancy_type,
    extract_loan_purpose,
    extract_monthly_obligations,
    get_fields,
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

        print(f'Applying RA-2C fixes to '
              f'{len(apps)} apps\n')

        for app in apps:
            app_id = app['application_id']

            docs = await conn.fetch('''
                SELECT document_type,
                       extracted_fields
                FROM document_index
                WHERE application_id = $1
                AND tenant_id = $2
                AND is_current = true
            ''', app_id, TENANT)

            # Wrap as {'extracted_fields': ...} so the builder's get_fields()
            # (which expects that shape, as in its unit tests) reads correctly.
            doc_map = {}
            for d in docs:
                fields = d['extracted_fields']
                if isinstance(fields, str):
                    try:
                        fields = json.loads(fields)
                    except Exception:
                        fields = {}
                doc_map[d['document_type']] = \
                    {'extracted_fields': fields or {}}

            row = await conn.fetchrow('''
                SELECT loan_terms, dti_back,
                       qualifying_monthly
                FROM entity_states
                WHERE application_id = $1
                AND tenant_id = $2
            ''', app_id, TENANT)

            if not row:
                continue

            lt = row['loan_terms'] or {}
            if isinstance(lt, str):
                try:
                    lt = json.loads(lt)
                except Exception:
                    lt = {}
            lt = lt or {}

            if 'urla' not in lt:
                lt['urla'] = {}

            changes = []

            # ADD: occupancy_type
            if not lt['urla'].get('occupancy_type'):
                occ = extract_occupancy_type(doc_map)
                if occ:
                    lt['urla']['occupancy_type'] = occ
                    changes.append(
                        f'occupancy_type={occ}'
                    )

            # ADD: loan_purpose
            if not lt['urla'].get('loan_purpose'):
                purpose = extract_loan_purpose(
                    doc_map
                )
                if purpose:
                    lt['urla']['loan_purpose'] = \
                        purpose
                    changes.append(
                        f'loan_purpose={purpose}'
                    )

            # ADD: verified obligations
            # (additive — stored in loan_terms
            #  for resolver use)
            oblig = extract_monthly_obligations(
                doc_map
            )
            if oblig['source'] != 'none':
                lt['obligations'] = oblig
                changes.append(
                    f'obligations='
                    f'${oblig["total_monthly_obligations"]:,.0f}/mo'
                    f' ({oblig["source"]})'
                )

            if changes:
                await conn.execute('''
                    UPDATE entity_states
                    SET loan_terms = $1
                    WHERE application_id = $2
                    AND tenant_id = $3
                ''', json.dumps(lt),
                    app_id, TENANT)
                print(f'  + {app_id}: '
                      f'{", ".join(changes)}')
            else:
                print(f'  - {app_id}: no changes')

        # Verify
        print('\n-- Verification --')
        rows = await conn.fetch('''
            SELECT application_id, loan_terms
            FROM entity_states
            WHERE tenant_id = $1
            ORDER BY application_id
        ''', TENANT)

        for r in rows:
            lt = r['loan_terms'] or {}
            if isinstance(lt, str):
                try:
                    lt = json.loads(lt)
                except Exception:
                    lt = {}
            urla = lt.get('urla', {})
            oblig = lt.get('obligations', {})
            print(
                f'  {r["application_id"]}: '
                f'occ={urla.get("occupancy_type","-")} '
                f'purpose={urla.get("loan_purpose","-")} '
                f'oblig=${oblig.get("total_monthly_obligations",0):,.0f}/mo'
                f'({oblig.get("source","-")})'
            )

    finally:
        await conn.close()


if __name__ == '__main__':
    asyncio.run(main())
