"""Create vw_asset_verification_context (asset_verification persona).

Mirrors the existing vw_*_context pattern: projects borrower.assets JSONB
out of entity_states into flat, typed columns the EdmsContextStore maps into
an AssetProfile bundle object. Idempotent (CREATE OR REPLACE).

  python scripts/migrations/add_asset_verification_view.py
"""
import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

DDL = """
CREATE OR REPLACE VIEW vw_asset_verification_context AS
SELECT
    entity_states.application_id,
    entity_states.tenant_id,
    entity_states.borrower ->> 'applicant_id' AS applicant_id,
    ((entity_states.borrower -> 'assets') ->> 'large_deposit_amount')::double precision  AS large_deposit_amount,
    ((entity_states.borrower -> 'assets') ->> 'large_deposit_documented')::boolean        AS large_deposit_documented,
    ((entity_states.borrower -> 'assets') ->> 'liquid_assets_total')::double precision     AS liquid_assets_total,
    ((entity_states.borrower -> 'assets') ->> 'reserves_months')::double precision         AS reserves_months,
    ((entity_states.borrower -> 'assets') ->> 'checking_savings')::double precision        AS checking_savings,
    ((entity_states.borrower -> 'assets') ->> 'gift_funds')::double precision              AS gift_funds,
    ((entity_states.borrower -> 'assets') ->> 'gift_funds_documented')::boolean            AS gift_funds_documented,
    entity_states.assets_verified,
    entity_states.total_liquid_assets,
    entity_states.status
FROM entity_states;
"""

GRANTS = ["GRANT SELECT ON vw_asset_verification_context TO accord_app",
          "GRANT SELECT ON vw_asset_verification_context TO accord_readonly"]


async def main():
    import asyncpg
    url = os.environ['DATABASE_URL'].replace('+asyncpg', '').replace('postgresql+psycopg2', 'postgresql')
    conn = await asyncpg.connect(url)
    try:
        await conn.execute(DDL)
        for g in GRANTS:
            try:
                await conn.execute(g)
            except Exception as e:  # noqa: BLE001
                print(f"  grant warn: {e}")
        cols = await conn.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='vw_asset_verification_context' ORDER BY ordinal_position")
        print("view created:", ", ".join(r["column_name"] for r in cols))
    finally:
        await conn.close()


asyncio.run(main())
