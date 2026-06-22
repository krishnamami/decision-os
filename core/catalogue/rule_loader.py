# core/catalogue/rule_loader.py
"""
Shared rule loader for all resolvers.

Reads from three catalogue layers:
  regulatory_rules  → federal floor (reference)
  agency_guidelines → agency guideline (reference)
  overlay_rules     → lender config (APPLIED)

TYPE 2 SCD:
  agency_guidelines queries use point-in-time logic:
    WHERE valid_from <= as_of
    AND (valid_to IS NULL OR valid_to >= as_of)
  Default as_of = today (current rules).
  Pass historical date for loan replay.

RESOLUTION:
  Lender overlay always applied.
  Risk communicated vs regulatory + agency.
  GREEN / AMBER / RED per layer.

COALESCE:
  If row missing → SAFE_DEFAULT + WARNING.
  WARNING tells ops which row to add.
  Run refresh_fannie_guidelines.py to populate.

SCHEMA NOTES (verified against live RDS):
  overlay_rules keys on `rule_type` (NOT rule_name) and uses lender-era
  names (credit_floor, ltv_max_purchase) that predate the canonical
  vocabulary — OVERLAY_ALIASES bridges canonical guideline_name -> rule_type.
  overlay_value is NUMERIC (asyncpg returns Decimal) — _parse handles it.
"""

import json
import logging
from datetime import date
from decimal import Decimal
from typing import Optional, Any

logger = logging.getLogger(__name__)


SAFE_DEFAULTS = {
    # Asset (Fannie B3-4.3-04)
    'qualifying_factor_checking':      1.00,
    'qualifying_factor_savings':       1.00,
    'qualifying_factor_cd':            1.00,
    'qualifying_factor_retirement':    0.60,
    'qualifying_factor_stocks_bonds':  0.70,
    'qualifying_factor_crypto':        0.00,
    'minimum_reserves_months':         2,
    'large_deposit_threshold_pct':     50,
    'seasoning_days_required':         60,
    # Credit (Fannie B3-5.3-07 worst case)
    'bankruptcy_ch7_waiting_years':    4,
    'bankruptcy_ch13_waiting_years':   2,
    'foreclosure_waiting_years':       7,
    'short_sale_waiting_years':        4,
    'deed_in_lieu_waiting_years':      4,
    'min_credit_score':                620,
    # Income
    'dti_back_max':                    50,
    'student_loan_deferred_rate_pct':  1.0,
    'medical_collection_excluded':     True,
    'rental_vacancy_factor_pct':       25,
    'se_income_years_required':        2,
    'se_declining_use_lower_year':     True,
    # Property
    'ltv_purchase_max':                97,
    'ltv_cashout_max':                 80,
    'ltv_refi_max':                    95,
    'max_units_conventional':          4,
    'appraisal_gap_major_pct':         10,
    'appraisal_gap_minor_pct':         3,
    'mi_required_ltv_threshold':       80,
    # Risk thresholds (Accord model)
    'income_mismatch_medium_pct':      10,
    'income_mismatch_high_pct':        25,
    'income_mismatch_critical_pct':    50,
    'undisclosed_debt_medium_mo':      200,
    'undisclosed_debt_high_mo':        500,
    'undisclosed_debt_critical_mo':    1000,
    # Title lien treatments (Fannie B8-1-01/02) — string values.
    'lien_solar_panel_treatment':      'acceptable_if_leased_or_owned',
    'lien_irs_tax_treatment':          'blocks_closing',
    'lien_hoa_treatment':              'requires_payoff_if_superior',
    'lien_mechanics_treatment':        'blocks_closing',
}


# Lender overlays predate the canonical vocabulary and key on overlay_rules
# .rule_type with their own names. Map canonical guideline_name -> rule_type
# so "overlay always applied" actually resolves for these.
OVERLAY_ALIASES = {
    'min_credit_score':  'credit_floor',
    'ltv_purchase_max':  'ltv_max_purchase',
    'ltv_cashout_max':   'ltv_max_cashout',
    'ltv_refi_max':      'ltv_max_refi',
}


async def _db_today(conn) -> date:
    """The DB server's CURRENT_DATE. Catalogue rows are stamped with the
    server-side CURRENT_DATE (UTC on RDS); using the local process clock for
    point-in-time as_of can be a day behind and exclude every current row."""
    return await conn.fetchval('SELECT CURRENT_DATE')


def _parse(raw: Any) -> Any:
    """Parse a catalogue value (JSONB scalar/dict, NUMERIC, or string)
    into a plain scalar/list."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, Decimal):
        return float(raw)
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            return _parse(json.loads(raw))
        except Exception:
            try:
                return float(
                    raw.replace(',', '')
                       .replace('%', '')
                       .replace('$', '')
                )
            except Exception:
                return raw
    if isinstance(raw, dict):
        for k in ['value', 'threshold',
                  'max', 'min', 'limit']:
            if k in raw:
                return _parse(raw[k])
        return raw
    return None


def _risk_level(
    applied: Any,
    reference: Any,
    is_ceiling: bool,
) -> str:
    """GREEN / AMBER / RED vs reference."""
    if reference is None:
        return 'GREEN'
    try:
        a = float(applied)
        r = float(reference)
    except (TypeError, ValueError):
        return 'GREEN'
    if is_ceiling:
        if a <= r:          return 'GREEN'
        elif a <= r * 1.10: return 'AMBER'
        else:               return 'RED'
    else:
        if a >= r:          return 'GREEN'
        elif a >= r * 0.90: return 'AMBER'
        else:               return 'RED'


async def get_rule(
    conn,
    guideline_name: str,
    tenant_id: str,
    agency: str = 'fannie',
    loan_type: str = 'conventional',
    is_ceiling: bool = True,
    as_of: Optional[date] = None,
) -> dict:
    """
    Get effective rule after resolving
    all three catalogue layers.

    as_of: date for point-in-time lookup.
           Default = today.
           Pass loan decision date for replay.

    Returns:
      applied:       value to use
      governed_by:   overlay/agency/regulatory/safe_default
      layers:        all three with version info
      risk:          GREEN/AMBER/RED per layer
      using_default: True if fell back
    """
    as_of = as_of or await _db_today(conn)
    layers = {}

    # ── Layer 1: Regulatory (federal) ─────────
    reg = await conn.fetchrow('''
        SELECT rule_value, authority, citation
        FROM regulatory_rules
        WHERE rule_name = $1
        AND is_active = true
        LIMIT 1
    ''', guideline_name)

    if reg:
        val = _parse(reg['rule_value'])
        if val is not None:
            layers['regulatory'] = {
                'value':     val,
                'authority': reg['authority'],
                'citation':  reg['citation'],
            }

    # ── Layer 2: Agency (Type 2 point-in-time) ─
    ag = await conn.fetchrow('''
        SELECT guideline_value,
               citation, source_url,
               version_id, category,
               valid_from, valid_to,
               downloaded_at
        FROM agency_guidelines
        WHERE agency = $1
        AND guideline_name = $2
        AND valid_from <= $3
        AND (valid_to IS NULL
             OR valid_to >= $3)
        AND is_active = true
        ORDER BY valid_from DESC
        LIMIT 1
    ''', agency, guideline_name, as_of)

    if not ag and agency != 'fannie':
        # Fallback: try fannie
        ag = await conn.fetchrow('''
            SELECT guideline_value,
                   citation, source_url,
                   version_id, category,
                   valid_from, valid_to,
                   downloaded_at
            FROM agency_guidelines
            WHERE agency = 'fannie'
            AND guideline_name = $1
            AND valid_from <= $2
            AND (valid_to IS NULL
                 OR valid_to >= $2)
            AND is_active = true
            ORDER BY valid_from DESC
            LIMIT 1
        ''', guideline_name, as_of)

    if ag:
        val = _parse(ag['guideline_value'])
        if val is not None:
            layers['agency'] = {
                'value':      val,
                'agency':     agency,
                'citation':   ag['citation'],
                'source_url': ag['source_url'],
                'version_id': str(ag['version_id'])
                              if ag['version_id']
                              else None,
                'valid_from': str(ag['valid_from']),
                'valid_to':   str(ag['valid_to'])
                              if ag['valid_to']
                              else None,
            }

    # ── Layer 3: Lender overlay ────────────────
    # overlay_rules keys on rule_type (lender-era names) — bridge via alias.
    overlay_key = OVERLAY_ALIASES.get(guideline_name, guideline_name)
    ov = await conn.fetchrow('''
        SELECT overlay_value, direction
        FROM overlay_rules
        WHERE tenant_id = $1
        AND rule_type = $2
        AND (loan_type = $3
             OR loan_type IS NULL)
        AND is_active = true
        ORDER BY loan_type NULLS LAST
        LIMIT 1
    ''', tenant_id, overlay_key, loan_type)

    if ov:
        val = _parse(ov['overlay_value'])
        if val is not None:
            layers['overlay'] = {
                'value':     val,
                'tenant':    tenant_id,
                'direction': ov['direction'],
            }

    # ── Resolve applied value ──────────────────
    using_default = False

    if 'overlay' in layers:
        applied     = layers['overlay']['value']
        governed_by = 'overlay'
    elif 'agency' in layers:
        applied     = layers['agency']['value']
        governed_by = 'agency'
    elif 'regulatory' in layers:
        applied     = layers['regulatory']['value']
        governed_by = 'regulatory'
    else:
        default = SAFE_DEFAULTS.get(guideline_name)
        logger.warning(
            f'CATALOGUE MISSING: '
            f'{agency}/{guideline_name} '
            f'as_of={as_of} — '
            f'using safe default: {default}. '
            f'Run: python scripts/catalogue/'
            f'refresh_fannie_guidelines.py'
        )
        return {
            'applied':       default,
            'governed_by':   'safe_default',
            'layers':        {},
            'risk':          {},
            'using_default': True,
            'as_of':         str(as_of),
        }

    # ── Risk communication ─────────────────────
    risk = {}
    for layer_name in ['regulatory', 'agency']:
        if layer_name not in layers:
            continue
        ref = layers[layer_name]['value']
        try:
            a = float(applied)
            r = float(ref)
            delta = round(a - r, 2)
            level = _risk_level(a, r, is_ceiling)
            if is_ceiling:
                direction = (
                    'stricter' if a < r
                    else 'looser' if a > r
                    else 'matches'
                )
            else:
                direction = (
                    'stricter' if a > r
                    else 'looser' if a < r
                    else 'matches'
                )
            risk[f'vs_{layer_name}'] = {
                'delta':     delta,
                'direction': direction,
                'level':     level,
                'reference': ref,
            }
        except (TypeError, ValueError):
            pass

    return {
        'applied':       applied,
        'governed_by':   governed_by,
        'tenant':        tenant_id,
        'agency':        agency,
        'loan_type':     loan_type,
        'layers':        layers,
        'risk':          risk,
        'using_default': using_default,
        'as_of':         str(as_of),
    }


async def get_catalogue_value(
    conn,
    agency: str,
    guideline_name: str,
    as_of: Optional[date] = None,
    default: Any = None,
) -> Any:
    """
    Simple single value lookup.
    Point-in-time. Coalesces with default.
    """
    as_of = as_of or await _db_today(conn)
    row = await conn.fetchrow('''
        SELECT guideline_value
        FROM agency_guidelines
        WHERE agency = $1
        AND guideline_name = $2
        AND valid_from <= $3
        AND (valid_to IS NULL
             OR valid_to >= $3)
        AND is_active = true
        ORDER BY valid_from DESC
        LIMIT 1
    ''', agency, guideline_name, as_of)

    if row:
        val = _parse(row['guideline_value'])
        if val is not None:
            return val

    fallback = (
        default
        if default is not None
        else SAFE_DEFAULTS.get(guideline_name)
    )
    logger.warning(
        f'CATALOGUE MISSING: '
        f'{agency}/{guideline_name} '
        f'as_of={as_of} — '
        f'using default: {fallback}. '
        f'Run refresh_fannie_guidelines.py'
    )
    return fallback


async def load_rules(
    conn,
    agency: str,
    category: str,
    as_of: Optional[date] = None,
) -> dict:
    """
    Load all rules for agency + category
    at a point in time.
    Returns flat dict name → value.
    Coalesces missing keys with SAFE_DEFAULTS.
    """
    as_of = as_of or await _db_today(conn)
    rows = await conn.fetch('''
        SELECT DISTINCT ON (guideline_name)
            guideline_name,
            guideline_value
        FROM agency_guidelines
        WHERE agency = $1
        AND category = $2
        AND valid_from <= $3
        AND (valid_to IS NULL
             OR valid_to >= $3)
        AND is_active = true
        ORDER BY guideline_name,
                 valid_from DESC
    ''', agency, category, as_of)

    result = {}
    for r in rows:
        val = _parse(r['guideline_value'])
        if val is not None:
            result[r['guideline_name']] = val

    # Coalesce missing with SAFE_DEFAULTS
    for key, default in SAFE_DEFAULTS.items():
        if key not in result:
            result[key] = default
            logger.warning(
                f'CATALOGUE MISSING: '
                f'{agency}/{category}/{key} '
                f'as_of={as_of} — '
                f'using safe default: {default}'
            )

    return result


__all__ = [
    'SAFE_DEFAULTS',
    'OVERLAY_ALIASES',
    'get_rule',
    'get_catalogue_value',
    'load_rules',
]
