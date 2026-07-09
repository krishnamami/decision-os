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


# ── FIX 5 — purchase_price (RA-EX-C: purchase agreement first) ──
_PRICE_KEYS = ['purchase_price', 'sales_price', 'contract_price',
              'property_value', 'subject_property_value',
              'purchase_contract_price', 'contract_sale_price']


def extract_purchase_price(
    doc_map: dict
) -> Optional[float]:
    """
    Extract purchase price — the contract price the borrower agreed to pay.
    NOT derived from appraised value. The PURCHASE_AGREEMENT is authoritative
    (RA-EX-C); the URLA is the fallback. The live URLA has no purchase_price
    field (RA-EX-A), so this is None until the purchase agreement is extracted.
    Citation: Fannie Mae B4-1.1-01
    """
    for dt in ('PURCHASE_AGREEMENT', 'URLA_1003'):
        if dt not in doc_map:
            continue
        raw = first_val(get_fields(doc_map[dt]), _PRICE_KEYS)
        if raw is not None:
            val = parse_amount(raw)
            if val > 0:
                return val
    return None


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


# ── RA-EX-C — bank statement: large deposits / NSF / statement date ──
# Doc types that carry bank-statement transactions.
_BANK_DOC_TYPES = (
    'BANK_STATEMENT_M1', 'BANK_STATEMENT_M2', 'BANK_STATEMENT_M3',
    'BANK_STATEMENT',
)
# Flag any single credit >= this for UW review. The ACTUAL sourcing threshold
# (large_deposit_threshold_pct of qualifying income) is applied later by the
# asset_verification persona from the catalogue rule — this is only a capture
# flag, not a decision.
LARGE_DEPOSIT_FLAG_USD = 1000.0
_NSF_KEYWORDS = ('nsf', 'overdraft', 'insufficient', 'returned item',
                 'returned check', 'od fee')


def _bank_txns(fields: dict) -> list:
    txns = fields.get('transactions') or fields.get('deposits') or []
    return txns if isinstance(txns, list) else []


def extract_large_deposits(
    doc_map: dict, *, flag_threshold: float = LARGE_DEPOSIT_FLAG_USD
) -> list:
    """Large credit transactions (>= flag_threshold) across bank statements.
    Returns [{date, amount, description}]. Empty when no transaction detail is
    available (the live BANK_STATEMENT_M1 carries balances only — RA-EX-A)."""
    out: list = []
    for dt in _BANK_DOC_TYPES:
        if dt not in doc_map:
            continue
        f = get_fields(doc_map[dt])
        # Pre-extracted list, if the extractor already produced one.
        pre = f.get('large_deposits')
        if isinstance(pre, list):
            out.extend(d for d in pre if isinstance(d, dict))
        for t in _bank_txns(f):
            if not isinstance(t, dict):
                continue
            amt = parse_amount(t.get('amount'))
            is_credit = (str(t.get('type', '')).lower() in ('credit', 'deposit')
                         if t.get('type') is not None else amt > 0)
            if is_credit and amt >= flag_threshold:
                out.append({'date': t.get('date'),
                            'amount': round(amt, 2),
                            'description': t.get('description', '')})
    return out


def extract_nsf_count(doc_map: dict) -> int:
    """Count of NSF / overdraft events across bank statements. 0 when no
    transaction detail (or an explicit nsf_count field) is available."""
    count = 0
    for dt in _BANK_DOC_TYPES:
        if dt not in doc_map:
            continue
        f = get_fields(doc_map[dt])
        explicit = f.get('nsf_count')
        if explicit is not None:
            count += int(parse_amount(explicit))
            continue
        for t in _bank_txns(f):
            desc = str(t.get('description', '') if isinstance(t, dict) else t).lower()
            if any(k in desc for k in _NSF_KEYWORDS):
                count += 1
    return count


def extract_statement_date(doc_map: dict) -> Optional[str]:
    """Most recent bank-statement end date (ISO YYYY-MM-DD) for staleness
    checks. None when unavailable."""
    dates: list = []
    for dt in _BANK_DOC_TYPES:
        if dt not in doc_map:
            continue
        d = first_val(get_fields(doc_map[dt]),
                      ['statement_date', 'statement_end_date', 'period_end',
                       'ending_date', 'as_of_date', 'statement_period_end'])
        if d:
            dates.append(str(d)[:10])
    return max(dates) if dates else None


# ── RA-EX-C — credit report: full tradelines array ──
def extract_tradelines(doc_map: dict) -> list:
    """Per-line tradeline detail from the credit report (the array the RA-4B
    TradelineAnalyzer needs). Empty when only a count is extracted (the live
    CREDIT_REPORT carries tradeline_count, not the array — RA-EX-A)."""
    if 'CREDIT_REPORT' not in doc_map:
        return []
    tl = get_fields(doc_map['CREDIT_REPORT']).get('tradelines')
    return tl if isinstance(tl, list) else []


# ── v4.9 — amortization / lien position / HMDA lien status ──
_AMORT_MAP = {
    'fixed': 'fixed', 'fixed rate': 'fixed', 'fixed-rate': 'fixed',
    'arm': 'arm', 'adjustable': 'arm', 'adjustable rate': 'arm', 'adjustable-rate': 'arm',
    'balloon': 'balloon',
    'interest only': 'interest_only', 'interest-only': 'interest_only', 'io': 'interest_only',
}
_LIEN_MAP = {
    'first': 'first', '1': 'first', 'first lien': 'first', 'primary': 'first',
    'second': 'second', '2': 'second', 'second lien': 'second', 'subordinate': 'second',
    'third': 'third', '3': 'third',
}
# HMDA LAR lien status — NO default: unknown lien_position -> None (the HMDA
# reporter fills it in), never a false 'not_secured_by_lien' on a mortgage.
_LIEN_HMDA = {
    'first':  'secured_by_first_lien',
    'second': 'secured_by_subordinate_lien',
    'third':  'secured_by_subordinate_lien',
}


def extract_amortization_type(doc_map: dict) -> Optional[str]:
    """Amortization type from the URLA — fixed / arm / balloon / interest_only.
    Source: URLA_1003 extracted_fields (MISMO LoanAmortizationType). Encompass 1041."""
    if 'URLA_1003' not in doc_map:
        return None
    raw = first_val(get_fields(doc_map['URLA_1003']),
                    ['amortization_type', 'loan_amortization_type',
                     'amortization', 'LoanAmortizationType'])
    if not raw:
        return None
    n = str(raw).lower().strip()
    return _AMORT_MAP.get(n, next((v for k, v in _AMORT_MAP.items() if k in n), n))


def extract_lien_position(doc_map: dict) -> Optional[str]:
    """Lien position from the URLA — first / second / third. Encompass 420."""
    if 'URLA_1003' not in doc_map:
        return None
    raw = first_val(get_fields(doc_map['URLA_1003']),
                    ['lien_position', 'lien', 'lien_priority'])
    if raw is None or str(raw).strip() == '':
        return None
    n = str(raw).lower().strip()
    return _LIEN_MAP.get(n, next((v for k, v in _LIEN_MAP.items() if k in n), n))


def hmda_lien_status(lien_position: Optional[str]) -> Optional[str]:
    """HMDA LAR lien status derived from lien_position. Returns None when the
    position is unknown (NOT 'not_secured_by_lien' — see _LIEN_HMDA)."""
    return _LIEN_HMDA.get((lien_position or '').lower())


# ── Aggregator — RA-EX-B ─────────────────────
# Property-type can come from the appraisal OR the URLA; the appraisal extractor
# (extract_property_type) only reads APPRAISAL_URAR, so the aggregator falls
# back to the URLA's property_type (the live APPRAISAL_URAR has no property_type
# field — RA-EX-A).
def _property_type(doc_map: dict) -> Optional[str]:
    pt = extract_property_type(doc_map)
    if pt:
        return pt
    if 'URLA_1003' in doc_map:
        raw = first_val(get_fields(doc_map['URLA_1003']),
                        ['property_type', 'prop_type', 'property_use'])
        if raw:
            n = str(raw).lower().strip()
            return PROPERTY_TYPE_MAP.get(n, next(
                (v for k, v in PROPERTY_TYPE_MAP.items() if k in n), n))
    return None


def build_golden_record(
    doc_map: dict,
    *,
    student_loan_rate_pct: float = 1.0,
    exclude_medical: bool = True,
) -> dict:
    """Aggregate the per-document primitives into ONE golden-record field set
    derived purely from document_index extracted_fields (keyed by document_type
    in ``doc_map``). Pure — NO DB writes.

    This is the canonical document -> entity_states derivation the ingestion path
    should use. Field names map to the LIVE extracted_fields (RA-EX-A): the
    governing mid score is the 3-bureau middle of CREDIT_REPORT
    equifax/experian/transunion_score (falling back to its mid_score); LTV is the
    lesser-of rule over URLA loan_amount, APPRAISAL_URAR appraised_value, and the
    URLA purchase_price. Returns None for any field with no source document, so
    the caller never invents a value."""
    cr = get_fields(doc_map['CREDIT_REPORT']) if 'CREDIT_REPORT' in doc_map else {}
    urla = get_fields(doc_map['URLA_1003']) if 'URLA_1003' in doc_map else {}
    appr = get_fields(doc_map['APPRAISAL_URAR']) if 'APPRAISAL_URAR' in doc_map else {}

    def _n(v):
        v = parse_amount(v)
        return v if v else None

    mid = compute_mid_score(
        _n(cr.get('equifax_score')),
        _n(cr.get('experian_score')),
        _n(cr.get('transunion_score')),
    )
    if mid is None:
        mid = _n(first_val(cr, ['mid_score', 'mid_credit_score']))

    loan_amount = _n(first_val(urla, ['loan_amount']))
    appraised = _n(first_val(appr, ['appraised_value'])
                   or first_val(urla, ['appraised_value']))
    purchase_price = extract_purchase_price(doc_map)
    ltv = compute_ltv(loan_amount or 0, appraised or 0, purchase_price)

    obligations = extract_monthly_obligations(
        doc_map, student_loan_rate_pct=student_loan_rate_pct,
        exclude_medical=exclude_medical,
    )

    # Purchase-agreement detail (RA-EX-C) — None until the doc is extracted.
    pa = get_fields(doc_map['PURCHASE_AGREEMENT']) \
        if 'PURCHASE_AGREEMENT' in doc_map else {}

    return {
        'mid_credit_score':   mid,
        'appraised_value':    appraised,
        'purchase_price':     purchase_price,
        'loan_amount':        loan_amount,
        'ltv':                ltv,
        'flood_zone':         extract_flood_zone(doc_map),
        'property_type':      _property_type(doc_map),
        'occupancy_type':     extract_occupancy_type(doc_map),
        'loan_purpose':       extract_loan_purpose(doc_map),
        'loan_type':          first_val(urla, ['loan_type']),
        # v4.9 — doc-derived canonical columns (Capital Loans onboarding).
        'amortization_type':  extract_amortization_type(doc_map),
        'lien_position':      (_lien := extract_lien_position(doc_map)),
        'lien_status_hmda':   hmda_lien_status(_lien),
        'monthly_obligations': obligations['total_monthly_obligations'] or None,
        'obligations_breakdown': obligations,
        # RA-EX-C — the three closed gaps (empty/None until extraction provides
        # the inputs; the live meridian fixtures don't carry them).
        'large_deposits':     extract_large_deposits(doc_map),
        'nsf_count':          extract_nsf_count(doc_map),
        'statement_date':     extract_statement_date(doc_map),
        'tradelines':         extract_tradelines(doc_map),
        'close_date':         (first_val(pa, ['close_date', 'closing_date',
                                              'expected_closing_date']) or None),
        'seller_concessions_pct': _n(first_val(pa, ['seller_concessions_pct',
                                                    'seller_concession_pct'])),
        'seller_concessions_amt': _n(first_val(pa, ['seller_concessions_amt',
                                                    'seller_concessions', 'seller_credits'])),
        'earnest_money':      _n(first_val(pa, ['earnest_money',
                                                'earnest_money_deposit'])),
    }


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

    # Test 16: purchase_price from PURCHASE_AGREEMENT (authoritative)
    doc_pa = {
        'PURCHASE_AGREEMENT': {'extracted_fields': {
            'purchase_price': '$612,500', 'close_date': '2026-07-15',
            'seller_concessions_pct': 3.0, 'earnest_money': 12000}},
        'URLA_1003': {'extracted_fields': {'purchase_price': '$600,000'}},
    }
    assert extract_purchase_price(doc_pa) == 612500.0, 'PA price wins'
    print(f'  ✅ Purchase price (PA wins over URLA): $612,500')

    # Test 17: large_deposits flag (> $1,000 credits)
    doc_bank = {'BANK_STATEMENT_M1': {'extracted_fields': {
        'statement_period_end': '2026-06-30',
        'transactions': [
            {'date': '2026-06-03', 'amount': 1500, 'type': 'credit', 'description': 'Wire in'},
            {'date': '2026-06-10', 'amount': 200, 'type': 'credit', 'description': 'Refund'},
            {'date': '2026-06-12', 'amount': 3000, 'type': 'debit', 'description': 'Rent'},
            {'date': '2026-06-20', 'amount': 90, 'type': 'debit', 'description': 'NSF FEE returned item'},
        ]}}}
    ld = extract_large_deposits(doc_bank)
    assert len(ld) == 1 and ld[0]['amount'] == 1500, f'large_deposits: {ld}'
    print(f'  ✅ Large deposits (>$1k credit): {len(ld)}')

    # Test 18: nsf_count from transaction descriptions
    assert extract_nsf_count(doc_bank) == 1, 'nsf_count'
    print(f'  ✅ NSF count: {extract_nsf_count(doc_bank)}')

    # Test 19: statement_date (ISO end date)
    assert extract_statement_date(doc_bank) == '2026-06-30', 'statement_date'
    print(f'  ✅ Statement date: {extract_statement_date(doc_bank)}')

    # Test 20: tradelines array passthrough
    doc_cr2 = {'CREDIT_REPORT': {'extracted_fields': {'tradelines': [
        {'creditor_name': 'Chase', 'account_type': 'revolving', 'current_balance': 1200}]}}}
    tl = extract_tradelines(doc_cr2)
    assert len(tl) == 1 and tl[0]['creditor_name'] == 'Chase', 'tradelines'
    print(f'  ✅ Tradelines array: {len(tl)} line(s)')

    # Test 21: build_golden_record surfaces the RA-EX-C fields
    gr = build_golden_record({**doc_pa, **doc_bank, **doc_cr2})
    assert gr['purchase_price'] == 612500.0
    assert gr['nsf_count'] == 1 and len(gr['large_deposits']) == 1
    assert gr['statement_date'] == '2026-06-30' and len(gr['tradelines']) == 1
    assert gr['close_date'] == '2026-07-15' and gr['earnest_money'] == 12000.0
    print(f'  ✅ build_golden_record RA-EX-C fields present')

    # Test 22: amortization_type normalization (v4.9)
    doc_arm = {'URLA_1003': {'extracted_fields': {'amortization_type': 'Adjustable Rate'}}}
    assert extract_amortization_type(doc_arm) == 'arm', 'amortization_type'
    assert extract_amortization_type({}) is None, 'amortization_type no-doc -> None'
    print(f'  ✅ Amortization type: arm')

    # Test 23: lien_position normalization (v4.9)
    doc_lien = {'URLA_1003': {'extracted_fields': {'lien_position': 'First'}}}
    assert extract_lien_position(doc_lien) == 'first', 'lien_position'
    print(f'  ✅ Lien position: first')

    # Test 24: hmda_lien_status maps from lien_position; unknown -> None (v4.9)
    assert hmda_lien_status('first') == 'secured_by_first_lien'
    assert hmda_lien_status('second') == 'secured_by_subordinate_lien'
    assert hmda_lien_status(None) is None, 'unknown lien -> None (not not_secured)'
    gr49 = build_golden_record(doc_arm)
    assert gr49['amortization_type'] == 'arm' and gr49['lien_status_hmda'] is None
    print(f'  ✅ HMDA lien status (unknown -> None)')

    print(f'\n✅ All unit tests passed.')
    print(f'   24/24 assertions correct.')
    return True


if __name__ == '__main__':
    _unit_test()
