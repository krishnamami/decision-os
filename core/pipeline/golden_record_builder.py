"""
Golden Record Builder — RA-2B

Production-correct derivations from document_index extracted_fields. These are
the primitives the ingestion path must use to populate entity_states so that
LTV, the governing credit score, flood zone, property type, and purchase price
are computed the way an underwriter (and Fannie Mae) expect.

Pure functions only — no DB writes here. The live meridian fixtures are seeded
(intentionally tuned for scenario outcomes); applying these to real production
ingestion is correct, but blanket-recomputing the demo fixtures would rewrite
deliberately-set values, so fixture corrections are done separately and
conservatively (see scripts/fixes/apply_safe_fixes.py).

Run unit tests:  python core/pipeline/golden_record_builder.py
"""

import json
from typing import Optional


# ── Shared helpers ───────────────────────────
def parse_amount(val) -> float:
    if val is None:
        return 0.0
    try:
        return float(
            str(val)
            .replace(',', '')
            .replace('$', '')
            .replace('%', '')
            .strip()
        )
    except (ValueError, TypeError):
        return 0.0


def get_fields(doc) -> dict:
    """Extract the extracted_fields dict from a document record/dict."""
    fields = doc.get('extracted_fields', {}) \
        if isinstance(doc, dict) \
        else doc['extracted_fields']
    if isinstance(fields, str):
        try:
            return json.loads(fields)
        except Exception:
            return {}
    return fields or {}


def first_val(fields: dict, keys: list):
    for k in keys:
        v = fields.get(k)
        if v is not None and v != '':
            return v
    return None


# ── FIX 1 — LTV: lesser-of rule ──────────────
def compute_ltv(
    loan_amount: float,
    appraised_value: float,
    purchase_price: float = None,
) -> Optional[float]:
    """
    LTV = loan_amount / lesser_of(
        appraised_value, purchase_price
    )
    If no purchase_price (refi): use appraised.
    Citation: Fannie Mae B4-1.1-01
    """
    if not loan_amount or loan_amount <= 0:
        return None
    if purchase_price and purchase_price > 0:
        lesser = min(appraised_value,
                     purchase_price)
    else:
        lesser = appraised_value
    if not lesser or lesser <= 0:
        return None
    return round(loan_amount / lesser * 100, 3)


# ── FIX 2 — Mid credit score: 3-bureau middle ─
def compute_mid_score(
    equifax: float = None,
    experian: float = None,
    transunion: float = None,
) -> Optional[float]:
    """
    Mid score = middle of 3 bureau scores.
    2 bureaus: use lower.
    1 bureau: use that score.
    NOT average. NOT highest.
    Citation: Fannie Mae B3-5.1-01
    """
    scores = sorted([
        s for s in [equifax, experian,
                    transunion]
        if s and s > 0
    ])
    if len(scores) == 3:
        return scores[1]   # middle
    elif len(scores) == 2:
        return scores[0]   # lower of two
    elif len(scores) == 1:
        return scores[0]
    return None


# ── FIX 3 — flood_zone from documents ────────
def extract_flood_zone(doc_map: dict) -> Optional[str]:
    """
    Extract flood zone designation.
    FLOOD_CERT is authoritative.
    Fall back to APPRAISAL_URAR.
    Citation: Fannie Mae B7-3-02
    """
    # FLOOD_CERT is authoritative
    if 'FLOOD_CERT' in doc_map:
        fz = first_val(
            get_fields(doc_map['FLOOD_CERT']),
            ['flood_zone_designation',
             'flood_zone', 'zone_designation',
             'sfha_indicator']
        )
        if fz:
            return str(fz).upper().strip()

    # Fall back to appraisal
    if 'APPRAISAL_URAR' in doc_map:
        fz = first_val(
            get_fields(doc_map['APPRAISAL_URAR']),
            ['flood_zone', 'flood_zone_designation',
             'fema_flood_zone',
             'special_flood_hazard_area']
        )
        if fz:
            return str(fz).upper().strip()

    return None


# ── FIX 4 — property_type from appraisal ─────
PROPERTY_TYPE_MAP = {
    'single family':     'sfr',
    'single-family':     'sfr',
    '1 unit':            'sfr',
    'one unit':          'sfr',
    'sfr':               'sfr',
    'detached':          'sfr',
    'condominium':       'condo',
    'condo':             'condo',
    'pud':               'pud',
    'planned unit':      'pud',
    '2 unit':            '2_unit',
    'two unit':          '2_unit',
    'duplex':            '2_unit',
    '3 unit':            '3_unit',
    'three unit':        '3_unit',
    'triplex':           '3_unit',
    '4 unit':            '4_unit',
    'four unit':         '4_unit',
    'quadplex':          '4_unit',
    'manufactured':      'manufactured',
    'mobile':            'manufactured',
    'cooperative':       'cooperative',
    'co-op':             'cooperative',
    'vacant land':       'vacant_land',
    'commercial':        'commercial',
}


def extract_property_type(
    doc_map: dict
) -> Optional[str]:
    """
    Extract and normalize property type
    from appraisal.
    Citation: Fannie Mae B2-1.3-01
    """
    if 'APPRAISAL_URAR' not in doc_map:
        return None
    raw = first_val(
        get_fields(doc_map['APPRAISAL_URAR']),
        ['property_type', 'prop_type',
         'subject_property_type',
         'improvement_type', 'property_use',
         'property_form_type']
    )
    if not raw:
        return None
    normalized = str(raw).lower().strip()
    # Try exact match first
    if normalized in PROPERTY_TYPE_MAP:
        return PROPERTY_TYPE_MAP[normalized]
    # Try partial match
    for key, val in PROPERTY_TYPE_MAP.items():
        if key in normalized:
            return val
    # Return cleaned raw if no match
    return normalized


# ── FIX 5 — purchase_price from URLA ─────────
def extract_purchase_price(
    doc_map: dict
) -> Optional[float]:
    """
    Extract purchase price from loan application.
    This is what the borrower agreed to pay.
    NOT derived from appraised value.
    Citation: Fannie Mae B4-1.1-01
    """
    if 'URLA_1003' not in doc_map:
        return None
    raw = first_val(
        get_fields(doc_map['URLA_1003']),
        ['purchase_price', 'sales_price',
         'contract_price', 'property_value',
         'subject_property_value',
         'purchase_contract_price']
    )
    if raw is None:
        return None
    val = parse_amount(raw)
    return val if val > 0 else None


# ── ADD 1 — occupancy_type from URLA ─────────
def extract_occupancy_type(
    doc_map: dict
) -> Optional[str]:
    """
    Extract occupancy type from URLA.
    Normalizes to canonical form.
    primary / second_home / investment
    Citation: Fannie Mae B2-1.1-01
    """
    if 'URLA_1003' not in doc_map:
        return None
    raw = first_val(
        get_fields(doc_map['URLA_1003']),
        ['occupancy_type', 'occupancy',
         'property_use', 'intended_occupancy',
         'subject_property_occupancy']
    )
    if not raw:
        return None
    normalized = str(raw).lower().strip()
    return {
        'primary':            'primary',
        'primary residence':  'primary',
        'owner occupied':     'primary',
        'owner-occupied':     'primary',
        'second home':        'second_home',
        'second':             'second_home',
        'vacation':           'second_home',
        'investment':         'investment',
        'investment property': 'investment',
        'non-owner':          'investment',
        'rental':             'investment',
    }.get(normalized, normalized)


# ── ADD 2 — loan_purpose from URLA ───────────
def extract_loan_purpose(
    doc_map: dict
) -> Optional[str]:
    """
    Extract loan purpose from URLA.
    purchase / refinance / cash_out
    Citation: Fannie Mae B2-1.3-02
    """
    if 'URLA_1003' not in doc_map:
        return None
    raw = first_val(
        get_fields(doc_map['URLA_1003']),
        ['loan_purpose', 'purpose',
         'transaction_type',
         'purpose_of_loan']
    )
    if not raw:
        return None
    normalized = str(raw).lower().strip()
    return {
        'purchase':       'purchase',
        'refinance':      'refinance',
        'refi':           'refinance',
        'rate/term':      'refinance',
        'rate and term':  'refinance',
        'cash-out':       'cash_out',
        'cash out':       'cash_out',
        'cashout':        'cash_out',
    }.get(normalized, normalized)


# ── ADD 3 — verified monthly obligations ─────
def extract_monthly_obligations(
    doc_map: dict,
    student_loan_rate_pct: float = 1.0,
    exclude_medical: bool = True,
) -> dict:
    """
    Extract verified monthly obligations
    from credit report.
    Applies Fannie rules:
      Student loan deferred: 1% of balance
      Medical collections: excluded
    Returns dict with breakdown.
    Citation: Fannie B3-6-02, B3-6-05,
              LL-2023-02
    """
    result = {
        'total_monthly_obligations': 0.0,
        'credit_report_obligations': 0.0,
        'student_loan_1pct':        0.0,
        'medical_excluded':         0.0,
        'source': 'none',
    }

    if 'CREDIT_REPORT' not in doc_map:
        # Fall back to URLA stated
        if 'URLA_1003' in doc_map:
            uf = get_fields(doc_map['URLA_1003'])
            stated = parse_amount(
                first_val(uf, [
                    'monthly_obligations',
                    'total_monthly_payments',
                    'monthly_debts',
                ])
            )
            result['total_monthly_obligations']\
                = stated
            result['source'] = 'urla_stated'
        return result

    cf = get_fields(doc_map['CREDIT_REPORT'])

    # Total from credit report. NOTE: the live
    # CREDIT_REPORT stores this as
    # total_monthly_obligations (checked first).
    cr_total = parse_amount(
        first_val(cf, [
            'total_monthly_obligations',
            'total_monthly_payments',
            'monthly_obligations',
            'minimum_payments',
            'total_minimum_payments',
        ])
    )

    # Student loan 1% rule
    sl_balance = parse_amount(
        first_val(cf, [
            'student_loan_balance',
            'deferred_student_loans',
            'student_loan_outstanding',
        ])
    )
    sl_1pct = round(
        sl_balance * student_loan_rate_pct / 100,
        2
    ) if sl_balance > 0 else 0.0

    # Medical collections excluded
    medical = parse_amount(
        first_val(cf, [
            'medical_collection_balance',
            'medical_collections',
        ])
    ) if exclude_medical else 0.0

    result['credit_report_obligations'] = cr_total
    result['student_loan_1pct']         = sl_1pct
    result['medical_excluded']          = medical
    result['total_monthly_obligations'] = round(
        cr_total + sl_1pct, 2
    )
    result['source'] = 'credit_report'

    return result


# ── Unit tests ───────────────────────────────
def _unit_test():
    """
    Verify fixes compute correctly.
    Run: python core/pipeline/golden_record_builder.py
    """
    print('Running unit tests...')

    # Test 1: LTV lesser-of
    ltv = compute_ltv(
        loan_amount=508250,
        appraised_value=535000,
        purchase_price=549000,
    )
    expected = round(508250/535000*100, 3)
    assert abs(ltv - expected) < 0.01, \
        f'LTV: got {ltv} expected {expected}'
    print(f'  ✅ LTV lesser-of: {ltv:.3f}%')

    # Test 2: LTV no purchase price (refi)
    ltv_refi = compute_ltv(
        loan_amount=400000,
        appraised_value=500000,
    )
    expected_refi = round(400000/500000*100, 3)
    assert abs(ltv_refi - expected_refi) < 0.01
    print(f'  ✅ LTV refi: {ltv_refi:.3f}%')

    # Test 3: LTV purchase > appraised (gap)
    ltv_gap = compute_ltv(
        loan_amount=500000,
        appraised_value=490000,
        purchase_price=520000,
    )
    expected_gap = round(500000/490000*100, 3)
    assert abs(ltv_gap - expected_gap) < 0.01
    print(f'  ✅ LTV gap: {ltv_gap:.3f}%')

    # Test 4: Mid score 3 bureaus
    mid = compute_mid_score(742, 728, 751)
    assert mid == 742, \
        f'Mid score: got {mid} expected 742'
    print(f'  ✅ Mid score (3): {mid}')

    # Test 5: Mid score 2 bureaus
    mid2 = compute_mid_score(742, 728, None)
    assert mid2 == 728, \
        f'Mid 2 bureau: got {mid2} expected 728'
    print(f'  ✅ Mid score (2): {mid2}')

    # Test 6: Mid score 1 bureau
    mid1 = compute_mid_score(742, None, None)
    assert mid1 == 742
    print(f'  ✅ Mid score (1): {mid1}')

    # Test 7: Mid score SC08 scenario
    # Bureaus 758/760/763 -> middle = 760
    sc08 = compute_mid_score(758, 760, 763)
    assert sc08 == 760, \
        f'SC08: got {sc08} expected 760'
    print(f'  ✅ Mid score SC08: {sc08}')

    # Test 8: Flood zone priority
    doc_map_flood = {
        'FLOOD_CERT': {
            'extracted_fields': {
                'flood_zone_designation': 'X'
            }
        },
        'APPRAISAL_URAR': {
            'extracted_fields': {
                'flood_zone': 'A'
            }
        }
    }
    fz = extract_flood_zone(doc_map_flood)
    assert fz == 'X', \
        f'Flood zone: got {fz} expected X'
    print(f'  ✅ Flood zone (cert wins): {fz}')

    # Test 9: Flood zone fallback
    doc_map_appr = {
        'APPRAISAL_URAR': {
            'extracted_fields': {
                'flood_zone': 'AE'
            }
        }
    }
    fz2 = extract_flood_zone(doc_map_appr)
    assert fz2 == 'AE'
    print(f'  ✅ Flood zone (appr fallback): {fz2}')

    # Test 10: Property type normalization
    doc_map_pt = {
        'APPRAISAL_URAR': {
            'extracted_fields': {
                'property_type': 'Single Family'
            }
        }
    }
    pt = extract_property_type(doc_map_pt)
    assert pt == 'sfr', \
        f'Property type: got {pt} expected sfr'
    print(f'  ✅ Property type: {pt}')

    # Test 11: Property type condo
    doc_map_condo = {
        'APPRAISAL_URAR': {
            'extracted_fields': {
                'property_type': 'Condominium'
            }
        }
    }
    pt2 = extract_property_type(doc_map_condo)
    assert pt2 == 'condo'
    print(f'  ✅ Property type condo: {pt2}')

    # Test 12: Purchase price extraction
    doc_map_pp = {
        'URLA_1003': {
            'extracted_fields': {
                'purchase_price': '$549,000'
            }
        }
    }
    pp = extract_purchase_price(doc_map_pp)
    assert abs(pp - 549000) < 0.01
    print(f'  ✅ Purchase price: ${pp:,.0f}')

    # Test 13: occupancy_type
    doc_primary = {
        'URLA_1003': {
            'extracted_fields': {
                'occupancy_type': 'Primary Residence'
            }
        }
    }
    occ = extract_occupancy_type(doc_primary)
    assert occ == 'primary', \
        f'Occupancy: got {occ}'
    print(f'  ✅ Occupancy type: {occ}')

    # Test 14: loan_purpose
    doc_purchase = {
        'URLA_1003': {
            'extracted_fields': {
                'loan_purpose': 'Purchase'
            }
        }
    }
    purpose = extract_loan_purpose(doc_purchase)
    assert purpose == 'purchase'
    print(f'  ✅ Loan purpose: {purpose}')

    # Test 15: monthly obligations
    doc_cr = {
        'CREDIT_REPORT': {
            'extracted_fields': {
                'total_monthly_payments': 575,
                'student_loan_balance': 35000,
            }
        }
    }
    oblig = extract_monthly_obligations(doc_cr)
    assert oblig['credit_report_obligations'] == 575
    assert oblig['student_loan_1pct'] == 350
    assert oblig['total_monthly_obligations'] == 925
    print(f'  ✅ Monthly obligations: '
          f'${oblig["total_monthly_obligations"]:,.0f}/mo')

    print(f'\n✅ All unit tests passed.')
    print(f'   15/15 assertions correct.')
    return True


if __name__ == '__main__':
    _unit_test()
