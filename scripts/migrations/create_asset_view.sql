-- scripts/migrations/create_asset_view.sql  (AV-D)
-- Extends vw_asset_verification_context with account/deposit rollups from the
-- AV-A entity tables. All pre-existing columns are preserved verbatim and in
-- their original order (CREATE OR REPLACE VIEW can only APPEND columns), so the
-- asset_verification field_map keeps working; the 4 new columns are appended.

CREATE OR REPLACE VIEW vw_asset_verification_context AS
SELECT
    es.application_id,
    es.tenant_id,
    es.borrower ->> 'applicant_id'                                       AS applicant_id,
    ((es.borrower -> 'assets') ->> 'large_deposit_amount')::double precision    AS large_deposit_amount,
    ((es.borrower -> 'assets') ->> 'large_deposit_documented')::boolean         AS large_deposit_documented,
    ((es.borrower -> 'assets') ->> 'liquid_assets_total')::double precision     AS liquid_assets_total,
    ((es.borrower -> 'assets') ->> 'reserves_months')::double precision         AS reserves_months,
    ((es.borrower -> 'assets') ->> 'checking_savings')::double precision        AS checking_savings,
    ((es.borrower -> 'assets') ->> 'gift_funds')::double precision              AS gift_funds,
    ((es.borrower -> 'assets') ->> 'gift_funds_documented')::boolean            AS gift_funds_documented,
    es.assets_verified,
    es.total_liquid_assets,
    es.status,

    -- ── NEW (AV-D): asset accounts (aggregated) ───────────────────────
    COALESCE((
        SELECT json_agg(json_build_object(
            'id',                    aa.id,
            'institution_name',      aa.institution_name,
            'account_type',          aa.account_type,
            'current_balance',       aa.current_balance,
            'qualifying_factor',     aa.qualifying_factor,
            'qualifying_amount',     aa.qualifying_amount,
            'seasoned_days',         aa.seasoned_days,
            'is_seasoned',           aa.is_seasoned,
            'is_gift',               aa.is_gift,
            'gift_documented',       aa.gift_documented,
            'is_business',           aa.is_business,
            'business_ownership_pct',aa.business_ownership_pct,
            'has_large_deposit',     aa.has_large_deposit,
            'large_deposit_amount',  aa.large_deposit_amount,
            'large_deposit_sourced', aa.large_deposit_sourced,
            'large_deposit_date',    aa.large_deposit_date
        ))
        FROM asset_accounts aa
        WHERE aa.application_id = es.application_id
          AND aa.tenant_id = es.tenant_id
    ), '[]'::json)                                                       AS asset_accounts,

    -- ── NEW (AV-D): unsourced deposits ────────────────────────────────
    COALESCE((
        SELECT json_agg(json_build_object(
            'id',               ad.id,
            'deposit_date',     ad.deposit_date,
            'deposit_amount',   ad.deposit_amount,
            'is_sourced',       ad.is_sourced,
            'is_gift',          ad.is_gift,
            'institution_name', aa2.institution_name,
            'deposit_source',   ad.deposit_source
        ))
        FROM asset_deposits ad
        JOIN asset_accounts aa2 ON ad.account_id = aa2.id
        WHERE ad.application_id = es.application_id
          AND ad.tenant_id = es.tenant_id
          AND ad.is_sourced = false
    ), '[]'::json)                                                       AS unsourced_deposits,

    -- ── NEW (AV-D): total qualifying assets ───────────────────────────
    COALESCE((
        SELECT SUM(aa.qualifying_amount)
        FROM asset_accounts aa
        WHERE aa.application_id = es.application_id
          AND aa.tenant_id = es.tenant_id
    ), 0)                                                                AS total_qualifying_assets,

    -- ── NEW (AV-D): unsourced deposit count ───────────────────────────
    COALESCE((
        SELECT COUNT(*)
        FROM asset_deposits ad
        WHERE ad.application_id = es.application_id
          AND ad.tenant_id = es.tenant_id
          AND ad.is_sourced = false
    ), 0)                                                                AS unsourced_deposit_count

FROM entity_states es;
