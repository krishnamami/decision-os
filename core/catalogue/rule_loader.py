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
    # SE business-asset tiers (Gap c — Fannie B3-3.4-02). Raw catalogue percents;
    # asset_resolver divides the two *Asset Credit* factors by 100 (1.00 / 0.50).
    'Self-Employed Business Ownership Sole Threshold':     100,
    'Self-Employed Business Ownership Majority Threshold':  50,
    'Self-Employed Full Business Asset Credit':            100,
    'Self-Employed Partial Business Asset Credit':          50,
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
    'months_remaining_exclusion':      10,
    'rental_vacancy_factor_pct':       25,
    'se_income_years_required':        2,
    'se_declining_use_lower_year':     True,
    'employment_history_months_required': 24,   # INC-B (Fannie B3-3.1-01)
    # Documentation-evidence confidence thresholds (Fannie B3-3.1-01). Also seeded
    # in agency_guidelines; kept here as the RULE 9 fallback so get_rule returns
    # them (and the enricher populates income_confidence_min / _floor) even if the
    # catalogue row is ever deactivated — making the 12 personas' 0.75 fallbacks
    # fully redundant in the DB path.
    'income_documentation_confidence_min':   0.75,
    'income_documentation_confidence_floor': 0.5,
    # INC-E — retirement / SS / asset-depletion / investment (Fannie B3-3.1-09)
    'ss_non_taxable_gross_up_factor':            1.25,
    'ss_continuance_months_required':            36,
    'retirement_continuance_months_required':    36,
    'asset_depletion_divisor_months':            360,
    'asset_depletion_retirement_haircut_pct':    70,
    'asset_depletion_cash_haircut_pct':          100,
    'asset_depletion_equity_haircut_pct':        70,
    'dividend_interest_history_months_required': 24,
    # INC-F — alimony / child support (Fannie B3-3.1-09 / B3-6-05)
    'alimony_continuance_months_required':       36,
    'child_support_continuance_months_required': 36,
    'alimony_paid_dti_treatment':                'monthly_debt',
    # OB-A — obligation payment factors (Fannie B3-6-02)
    'revolving_payment_factor_pct':              5,
    'heloc_payment_factor_pct':                  1,
    # OB-B — business-debt exclusion (Fannie B3-6-05 / B3-3.4-02)
    'business_debt_exclusion_months':            12,
    # EX-A — exception framework (Fannie B3-2-02)
    'exception_requires_compensating_factors':   True,
    'exception_max_dti_overlay_breach_pct':      5,
    'exception_max_ltv_overlay_breach_pct':      5,
    'exception_cannot_breach_agency_floor':      True,
    # EX-B — compensating-factor bar thresholds (Fannie B3-2-02)
    'substantial_reserves_months':               6,
    'exceptional_reserves_months':               12,
    'low_ltv_factor_max_pct':                    75,
    'excellent_credit_delta_pts':                60,
    'long_employment_months':                    60,
    'minimal_debt_obligations_max_pct':          10,
    # EX-C — exception score -> approval-level thresholds (Fannie B3-2-02)
    'exception_score_senior_min':                9,
    'exception_score_manager_min':               5,
    'exception_score_uw_min':                    2,
    # EV-G — document staleness / recency (Fannie B3-2-10 / B3-4.3-05 / B3-5.3-01 /
    # B3-3.1-01/02 / B7-2-03; FHA HUD 4000.1)
    'appraisal_validity_days_conventional':      120,
    'appraisal_validity_days_fha':               180,
    'paystub_max_age_days':                      30,
    'bank_statement_max_age_days':               60,
    'credit_report_validity_days':               120,
    'w2_tax_year_lookback_years':                2,
    'tax_return_lookback_years':                 2,
    # CO-D — ADU + multi-unit rental income (Fannie B3-3.1-08 / B5-6-01)
    'market_rent_qualifying_factor_pct':         75,
    'subject_2_4_unit_rental_factor':            75,
    'adu_rental_income_allowed':                 True,
    'adu_owner_occupancy_required':              True,
    'adu_max_units':                             1,
    # CM-D — fair-lending thresholds (EEOC 29 CFR 1607.4(D) / CFPB)
    'fair_lending_four_fifths_ratio':            0.80,
    'fair_lending_min_sample_size':              30,
    # CM-F — overlay-attributable disparity screen (INTERNAL, not a federal
    # standard): a >20 percentage-point gap in overlay-fail rate between a
    # protected class and the reference flags the overlay for review.
    'fair_lending_overlay_disparity_pct':        20,
    # CM-G — proxy-discrimination risk heuristics (INTERNAL, informed by CFPB
    # supervisory research; NOT regulatory determinations). Per-criterion proxy
    # correlation weights + the elevated/high composite-score bands.
    'credit_floor_proxy_risk_weight':            0.70,
    'dti_proxy_risk_weight':                     0.45,
    'ltv_proxy_risk_weight':                     0.35,
    'overlay_bias_elevated_threshold':           0.55,
    'overlay_bias_high_threshold':               0.75,
    # MI-E — non-occupant co-borrower (Fannie B2-2-04)
    'non_occupant_co_borrower_max_ltv_pct':          95,
    'non_occupant_co_borrower_occupant_must_qualify': True,
    # CR-F — collections + mortgage-late (Fannie B3-5.3-09 / B3-5.3-01)
    'medical_collection_ignore_amt':                 2000,
    'non_medical_collection_loe_threshold':          250,
    'non_medical_collection_aggregate_payoff':       1000,
    'mortgage_late_30day_12mo_conventional_blocks':  True,
    # FR-F — VA residual income estimate scalars (VA Pamphlet 26-7 Ch.4)
    'va_residual_maintenance_per_sqft_monthly':      0.14,
    'va_residual_tax_estimate_pct':                  25,
    'va_residual_min_loan_amount':                   80000,
    # PL-B — overlay guardrail hard bounds (seeded into regulatory_rules; these
    # are the RULE 9 fallback when the catalogue row is absent). credit floors:
    # FHA HUD 4000.1 (580 @ 3.5% down, 500 absolute @ 10% down); dti/ltv hard
    # ceilings: Fannie B3-6-02 / B2-1.2-01.
    'credit_floor_fha_standard_min':                 580,
    'credit_floor_fha_absolute_min':                 500,
    'dti_back_hard_max':                             57,
    'ltv_hard_max':                                  97,
    # CF-C — CRA tier cutoffs (federal, 12 CFR 25/228) + internal self-assessment
    # benchmark thresholds (NOT regulatory; official CRA ratings are examiner-set).
    'cra_lmi_low_max_pct':                           50,
    'cra_moderate_max_pct':                          80,
    'cra_middle_max_pct':                            120,
    'cra_lmi_ratio_outstanding_pct':                 40,
    'cra_lmi_ratio_satisfactory_pct':                25,
    'cra_lmi_ratio_needs_improvement_pct':           10,
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
    # RA-SEED-C: 5 more lien treatments (Fannie B8-1-02), all blocks_closing.
    'lien_tax_property_treatment':     'blocks_closing',
    'lien_state_tax_treatment':        'blocks_closing',
    'lien_judgment_treatment':         'blocks_closing',
    'lien_child_support_treatment':    'blocks_closing',
    'lien_lis_pendens_treatment':      'blocks_closing',
    # Compliance boundary suite (RA-4E) — agency/regulatory floors & ceilings
    # the rule_validator self-test asserts against. Canonical keys; the live
    # catalogue rows are human-named (see VALIDATOR_RULE_SPECS in
    # core/compliance/rule_validator.py for the name mapping). 'fha_abs_min_score'
    # is NOT yet in the catalogue under any name (HUD 4000.1, 500 @ 10% down) —
    # it resolves via this default and is flagged using_default until seeded.
    'fha_min_score_3_5':               580,
    'fha_abs_min_score':               500,
    'conv_min_score':                  620,
    'du_dti_max':                      50,
    'qm_dti_max':                      43,
    'conv_ltv_max':                    97,
    'fha_ltv_max':                     96.5,
    'va_ltv_max':                      100,
    'tx_cashout_ltv_max':              80,
    'ny_usury_cap':                    16,
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


# ─────────────────────────────────────────────────────────────────────
# RA-5A — policy transparency. Flatten a resolved-rule entry's three
# layers into the workbench disclosure shape (Architecture Rule 3:
# Federal | Agency | Overlay | Applied | Citation). PURE — no DB.
# ─────────────────────────────────────────────────────────────────────


def _num(x: Any) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def expand_rule_trace(rule_name: str, entry: dict) -> dict:
    """Flatten one ``load_*_rules`` entry ({applied|value, governed_by, layers})
    into the workbench three-layer view. Pure — uses only the layers dict the
    loader already resolved via get_rule.

    overlay_rules carries no citation column, so the overlay layer exposes its
    ``direction`` (stricter / looser vs the agency floor) instead of a citation.
    risk_level is the policy posture of the APPLIED value vs the agency floor:
    at-or-stricter-than agency = GREEN; a lender overlay LOOSER than the agency
    floor (or a safe_default fallback) = AMBER — the workbench's review flag."""
    layers = (entry or {}).get("layers") or {}
    reg = layers.get("regulatory") or {}
    ag = layers.get("agency") or {}
    ov = layers.get("overlay") or {}
    applied = entry.get("applied", entry.get("value"))
    governed_by = entry.get("governed_by")

    out = {
        "rule_name":        rule_name,
        "applied_value":    applied,
        "governed_by":      governed_by,
        "federal_value":    reg.get("value"),
        "federal_citation": reg.get("citation") or reg.get("authority"),
        "agency_value":     ag.get("value"),
        "agency_citation":  ag.get("citation"),
        "overlay_value":    ov.get("value"),
        "overlay_direction": ov.get("direction"),  # stricter / looser vs agency
    }
    a, f, g = _num(applied), _num(reg.get("value")), _num(ag.get("value"))
    if a is not None and f is not None:
        out["delta_applied_vs_federal"] = round(a - f, 2)
    if a is not None and g is not None:
        out["delta_applied_vs_agency"] = round(a - g, 2)

    # Policy posture of the applied value vs the agency floor.
    if governed_by == "overlay" and ov.get("direction") == "looser":
        out["risk_level"] = "AMBER"      # lender looser than agency — review
    elif governed_by in ("safe_default", "SAFE_DEFAULT") or entry.get("using_default"):
        out["risk_level"] = "AMBER"      # not catalogued — fallback in use
    else:
        out["risk_level"] = "GREEN"      # at / stricter-than the agency floor
    return out


def expand_rule_traces(traces: Optional[dict]) -> dict:
    """Map expand_rule_trace over a ``{rule_name: entry}`` trace dict (the shape
    load_*_rules / its 'trace' returns). Returns {} for an empty/None input."""
    if not traces:
        return {}
    return {
        name: expand_rule_trace(name, entry)
        for name, entry in traces.items()
        if isinstance(entry, dict)
    }


__all__ = [
    'SAFE_DEFAULTS',
    'OVERLAY_ALIASES',
    'get_rule',
    'get_catalogue_value',
    'load_rules',
    'expand_rule_trace',
    'expand_rule_traces',
]
