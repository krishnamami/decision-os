#!/usr/bin/env python3
"""
Senior Underwriter Critical Audit — RA-2A

Audit question: Can I defend every loan decision
to Fannie Mae if this loan defaults?

Nine phases:
  1. File assembly — do we have everything?
  2. Income — verified correctly?
  3. Assets — qualified correctly?
  4. Liabilities — all obligations counted?
  5. Ratios — DTI and LTV math correct?
  6. Credit — score and waiting periods?
  7. Property — type, flood, condition?
  8. Evidence chain — can we prove it?
  9. Decision quality — rules from catalogue?

Persona: Senior UW with 20 years experience.
Has seen every Fannie repurchase demand.
Trusts nothing. Verifies everything.

SCHEMA ADAPTATIONS (vs the drafted script — verified against live RDS):
  - BANK_STATEMENT -> BANK_STATEMENT_M1 (real document_type)
  - entity_states has no property_type column -> derived from
    loan_terms->'urla'->>'property_type'; rate/term read from urla too
  - document_index.uploaded_at -> received_at
  - overlay_rules keys on rule_type (not rule_name)
  - decision_outputs: output_data/output_type -> evidence_trace /
    context_snapshot / decision_id
  - evidence_nodes: node_type/raw_value/confidence (not evidence_type/
    extracted_value/confidence_score)
  - fact_nodes: confidence/conflicts_found/evidence_ids (not confidence_score/
    conflicts_detected/source_documents)
  - phase 9 hardcode scan uses a Python file walk (portable; no `grep` dep)
The audit LOGIC (checks, severities, citations, thresholds) is unchanged.
"""

import asyncio
import json
import os
import re
import pathlib
import sys
from datetime import date, datetime, timedelta
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

# Windows console is cp1252 — the emoji severity icons would crash on encode.
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

TENANT = 'meridian'
TODAY  = date.today()

# ─── FINDINGS ────────────────────────────────
FINDINGS = []

SEV_ORDER = [
    'CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO'
]
SEV_ICON = {
    'CRITICAL': '🔴',
    'HIGH':     '🟠',
    'MEDIUM':   '🟡',
    'LOW':      '🟢',
    'INFO':     'ℹ️ ',
}


def finding(
    severity: str,
    phase: str,
    app_id: str,
    issue: str,
    detail: str = '',
    citation: str = '',
    fix: str = '',
):
    FINDINGS.append({
        'severity': severity,
        'phase':    phase,
        'app_id':   app_id,
        'issue':    issue,
        'detail':   detail,
        'citation': citation,
        'fix':      fix,
    })
    icon = SEV_ICON.get(severity, '?')
    print(f'    {icon} [{severity}][{phase}] '
          f'{app_id}: {issue}')
    if detail:
        print(f'       detail:   {detail}')
    if citation:
        print(f'       citation: {citation}')
    if fix:
        print(f'       fix:      {fix}')


# ─── HELPERS ─────────────────────────────────
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
        if v is not None and v != '' \
                and v != 0:
            return v
    return None


def as_json(val):
    if val is None:
        return {}
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return {}
    return val


async def get_catalogue(conn, name: str):
    row = await conn.fetchrow('''
        SELECT guideline_value
        FROM agency_guidelines
        WHERE guideline_name = $1
        AND is_active = true
        AND valid_to IS NULL
        ORDER BY valid_from DESC
        LIMIT 1
    ''', name)
    if not row:
        return None
    gv = row['guideline_value']
    if isinstance(gv, str):
        try:
            gv = json.loads(gv)
        except Exception:
            return gv
    if isinstance(gv, dict):
        return gv.get('value', gv)
    return gv


def section(title: str):
    print(f'\n  ── {title} ──')


# ═══════════════════════════════════════════
# PHASE 1: FILE ASSEMBLY
# ═══════════════════════════════════════════
async def phase1_file_assembly(conn, app_id, docs):
    """
    Do I have everything I need
    to underwrite this loan?
    """
    section('PHASE 1: File Assembly')

    doc_types = {d['document_type'] for d in docs}

    # Required documents
    required = {
        'URLA_1003':         'Loan application',
        'W2_CURRENT':        'Current year W2',
        'PAYSTUB_CURRENT':   'Recent paystub',
        'BANK_STATEMENT_M1': 'Bank statement',
        'APPRAISAL_URAR':    'Appraisal report',
    }
    for doc_type, label in required.items():
        if doc_type not in doc_types:
            finding(
                'CRITICAL', 'P1-DOCS', app_id,
                f'Missing: {label} ({doc_type})',
                'Cannot underwrite without '
                'this document',
                'Fannie B3-3.1-01',
                f'Upload {doc_type}',
            )
        else:
            print(f'    ✅ {doc_type}')

    # Recommended documents
    recommended = {
        'W2_PRIOR':         'Prior year W2',
        'TAX_RETURN_1040':  'Tax return',
        'CREDIT_REPORT':    'Credit report',
        'VOE':              'Employment verification',
    }
    for doc_type, label in recommended.items():
        if doc_type not in doc_types:
            finding(
                'HIGH', 'P1-DOCS', app_id,
                f'Recommended missing: '
                f'{label} ({doc_type})',
                'Needed for complete '
                'income/credit analysis',
            )

    # Check extraction completeness
    # per document type
    CRITICAL_FIELDS = {
        'W2_CURRENT': [
            'box1_wages', 'wages',
            'gross_wages', 'total_wages',
        ],
        'URLA_1003': [
            'base_income', 'monthly_income',
            'gross_monthly_income',
            'purchase_price', 'loan_amount',
        ],
        'APPRAISAL_URAR': [
            'appraised_value',
            'estimated_value',
            'market_value',
        ],
        'BANK_STATEMENT_M1': [
            'closing_balance',
            'checking_balance',
            'account_balance',
            'ending_balance',
            'available_balance',
            'gift_funds',
        ],
        'PAYSTUB_CURRENT': [
            'ytd_gross', 'ytd_income',
            'gross_ytd',
            'year_to_date_gross',
        ],
    }

    print()
    for doc in docs:
        dt = doc['document_type']
        if dt not in CRITICAL_FIELDS:
            continue
        fields = get_fields(doc)
        found = first_val(
            fields, CRITICAL_FIELDS[dt]
        )
        if found is None:
            finding(
                'CRITICAL', 'P1-EXTRACT',
                app_id,
                f'{dt}: critical fields '
                f'not extracted',
                f'Looked for: '
                f'{CRITICAL_FIELDS[dt]}. '
                f'Got: {list(fields.keys())[:5]}',
                '',
                'Fix extraction prompt '
                'or re-upload document',
            )
        else:
            print(f'    ✅ {dt}: '
                  f'key field = {found}')

    # Check entity_states is populated.
    # property_type is derived from loan_terms->urla (no column exists).
    es = await conn.fetchrow('''
        SELECT application_id,
               appraised_value,
               purchase_price,
               loan_amount,
               interest_rate,
               qualifying_monthly,
               mid_credit_score,
               dti_back, ltv,
               loan_terms,
               property,
               loan_terms->'urla'->>'property_type'
                   AS property_type
        FROM entity_states
        WHERE application_id = $1
        AND tenant_id = $2
    ''', app_id, TENANT)

    if not es:
        finding(
            'CRITICAL', 'P1-ENTITY',
            app_id,
            'No entity_states record',
            'golden_record_builder '
            'may not have run',
            '',
            'Run golden_record_builder',
        )
        return None

    # Check critical fields not NULL
    null_checks = {
        'appraised_value':    es['appraised_value'],
        'loan_amount':        es['loan_amount'],
        'qualifying_monthly': es['qualifying_monthly'],
        'mid_credit_score':   es['mid_credit_score'],
        'dti_back':           es['dti_back'],
        'ltv':                es['ltv'],
    }
    for field, val in null_checks.items():
        if val is None or parse_amount(val) == 0:
            finding(
                'CRITICAL', 'P1-NULL',
                app_id,
                f'entity_states.{field} is NULL',
                'Field not populated from '
                'document extraction',
                '',
                f'Fix golden_record_builder '
                f'mapping for {field}',
            )

    # purchase_price specifically
    if es['purchase_price'] is None:
        finding(
            'HIGH', 'P1-NULL',
            app_id,
            'purchase_price is NULL',
            'LTV may be wrong. '
            'Lesser-of rule cannot be applied.',
            'Fannie B4-1.1-01',
            'Extract purchase_price '
            'from URLA_1003',
        )

    # property_type
    if es['property_type'] is None:
        finding(
            'HIGH', 'P1-NULL',
            app_id,
            'property_type is NULL',
            'Cannot determine eligibility '
            'without property type',
            'Fannie B2-1.3-01',
            'Extract from APPRAISAL_URAR',
        )
    else:
        # Check if appraisal corroborates the URLA-stated type
        appr = next(
            (d for d in docs
             if d['document_type']
             == 'APPRAISAL_URAR'), None
        )
        if appr:
            af = get_fields(appr)
            appr_type = first_val(af, [
                'property_type', 'prop_type',
                'subject_property_type',
                'improvement_type',
            ])
            if appr_type is None:
                finding(
                    'MEDIUM', 'P1-EXTRACT',
                    app_id,
                    'property_type not in '
                    'appraisal extracted_fields',
                    'Cannot corroborate URLA-'
                    'stated property_type',
                    '',
                    'Add property_type to '
                    'appraisal extraction prompt',
                )

    return es


# ═══════════════════════════════════════════
# PHASE 2: INCOME ANALYSIS
# ═══════════════════════════════════════════
async def phase2_income(
    conn, app_id, docs, es
):
    """
    How much does this borrower earn?
    Can I prove it from documents?
    Is what we have in entity_states correct?
    """
    if not es:
        return

    section('PHASE 2: Income Analysis')

    doc_map = {}
    for d in docs:
        doc_map[d['document_type']] = \
            get_fields(d)

    qualifying = parse_amount(
        es['qualifying_monthly']
    )

    # ── W2 base income ────────────────────────
    w2_annual  = 0.0
    w2_monthly = 0.0
    if 'W2_CURRENT' in doc_map:
        wf = doc_map['W2_CURRENT']
        raw = first_val(wf, [
            'box1_wages', 'wages',
            'gross_wages', 'total_wages',
        ])
        if raw:
            w2_annual  = parse_amount(raw)
            w2_monthly = round(w2_annual / 12, 2)

    # ── Prior year W2 (2yr trend) ─────────────
    w2_prior_annual  = 0.0
    w2_prior_monthly = 0.0
    if 'W2_PRIOR' in doc_map:
        wp = doc_map['W2_PRIOR']
        raw = first_val(wp, [
            'box1_wages', 'wages',
            'gross_wages', 'total_wages',
        ])
        if raw:
            w2_prior_annual  = parse_amount(raw)
            w2_prior_monthly = round(
                w2_prior_annual / 12, 2
            )

    # ── Paystub YTD corroboration ─────────────
    paystub_monthly = 0.0
    if 'PAYSTUB_CURRENT' in doc_map:
        pf = doc_map['PAYSTUB_CURRENT']
        ytd = first_val(pf, [
            'ytd_gross', 'ytd_income',
            'gross_ytd',
            'year_to_date_gross',
        ])
        if ytd:
            ytd_amt = parse_amount(ytd)
            # Annualize YTD
            days = (
                TODAY - date(TODAY.year, 1, 1)
            ).days or 1
            paystub_monthly = round(
                ytd_amt / days * 365 / 12, 2
            )

    # ── URLA stated income ────────────────────
    urla_stated = 0.0
    if 'URLA_1003' in doc_map:
        uf = doc_map['URLA_1003']
        raw = first_val(uf, [
            'base_income',
            'monthly_income',
            'gross_monthly_income',
            'total_income',
            'base_employment_income',
            'stated_monthly_income',
            'monthly_income_stated',
        ])
        if raw:
            urla_stated = parse_amount(raw)

    # ── SE income (Schedule C) ────────────────
    se_monthly = 0.0
    if 'SCHEDULE_C' in doc_map:
        cf = doc_map['SCHEDULE_C']
        net  = parse_amount(
            first_val(cf, [
                'net_profit',
                'schedule_c_net',
                'business_net_income',
            ]) or 0
        )
        depr = parse_amount(
            first_val(cf, [
                'depreciation',
                'schedule_c_depreciation',
            ]) or 0
        )
        # 2yr average check
        prior_net = 0.0
        if 'SCHEDULE_C_PRIOR' in doc_map:
            cp = doc_map['SCHEDULE_C_PRIOR']
            prior_net = parse_amount(
                first_val(cp, [
                    'net_profit',
                    'schedule_c_net',
                ]) or 0
            )
            prior_depr = parse_amount(
                first_val(cp, [
                    'depreciation'
                ]) or 0
            )
            curr = net + depr
            prev = prior_net + prior_depr
            if curr < prev:
                # Declining — use lower
                se_monthly = round(curr / 12, 2)
                finding(
                    'HIGH', 'P2-INCOME',
                    app_id,
                    f'SE income declining: '
                    f'${prev:,.0f} -> ${curr:,.0f}',
                    'Using lower year only. '
                    f'${se_monthly:,.0f}/mo',
                    'Fannie B3-3.4-01',
                )
            else:
                se_monthly = round(
                    (curr + prev) / 2 / 12, 2
                )
        else:
            se_monthly = round(
                (net + depr) / 12, 2
            )
            if se_monthly > 0:
                finding(
                    'MEDIUM', 'P2-INCOME',
                    app_id,
                    'SE income: only 1 year '
                    'Schedule C available',
                    '2-year history required. '
                    'Request prior year Schedule C.',
                    'Fannie B3-3.4-01',
                )

    # ── Rental income (Schedule E) ────────────
    rental_monthly = 0.0
    if 'SCHEDULE_E' in doc_map:
        ef = doc_map['SCHEDULE_E']
        gross = parse_amount(
            first_val(ef, [
                'rental_income',
                'gross_rental_income',
            ]) or 0
        )
        expenses = parse_amount(
            first_val(ef, [
                'rental_expenses',
                'total_expenses',
            ]) or 0
        )
        depr = parse_amount(
            first_val(ef, [
                'depreciation'
            ]) or 0
        )
        # Get vacancy factor from catalogue
        vf = await get_catalogue(
            conn, 'rental_vacancy_factor_pct'
        ) or 25
        vacancy = float(vf) / 100
        rental_monthly = round(
            (gross - expenses + depr) / 12, 2
        )
        if rental_monthly < 0:
            finding(
                'MEDIUM', 'P2-INCOME',
                app_id,
                f'Rental LOSS: '
                f'${rental_monthly:,.0f}/mo '
                f'reduces qualifying income',
                'Schedule E shows net loss',
                'Fannie B3-3.1-08',
            )

    # ── Total verified ────────────────────────
    total_verified = round(
        w2_monthly + se_monthly +
        rental_monthly, 2
    )

    print(f'    URLA stated:        '
          f'${urla_stated:>10,.2f}/mo')
    print(f'    W2 current:         '
          f'${w2_monthly:>10,.2f}/mo')
    print(f'    W2 prior:           '
          f'${w2_prior_monthly:>10,.2f}/mo')
    print(f'    Paystub YTD:        '
          f'${paystub_monthly:>10,.2f}/mo')
    print(f'    SE (Schedule C):    '
          f'${se_monthly:>10,.2f}/mo')
    print(f'    Rental (Schedule E):'
          f'${rental_monthly:>10,.2f}/mo')
    print(f'    ─────────────────────────────')
    print(f'    Total verified:     '
          f'${total_verified:>10,.2f}/mo')
    print(f'    entity_states:      '
          f'${qualifying:>10,.2f}/mo')

    # ── Stated vs verified mismatch ───────────
    if urla_stated > 0 and w2_monthly > 0:
        mismatch_pct = abs(
            urla_stated - w2_monthly
        ) / max(urla_stated, w2_monthly) * 100

        print(f'    Stated vs W2:       '
              f'{mismatch_pct:>10.1f}%')

        if mismatch_pct > 50:
            finding(
                'CRITICAL', 'P2-FRAUD',
                app_id,
                f'INCOME INFLATION: '
                f'URLA ${urla_stated:,.0f} vs '
                f'W2 ${w2_monthly:,.0f} '
                f'({mismatch_pct:.1f}%)',
                'Potential fraud. '
                'Repurchase risk.',
                'Fannie B3-3.1-01 / '
                'SEL-2023-08',
                'Escalate to senior UW. '
                'Do not approve.',
            )
        elif mismatch_pct > 25:
            finding(
                'HIGH', 'P2-FRAUD',
                app_id,
                f'Income discrepancy '
                f'{mismatch_pct:.1f}%: '
                f'URLA ${urla_stated:,.0f} vs '
                f'W2 ${w2_monthly:,.0f}',
                'Exceeds 25% threshold. '
                'UW review required.',
                'Fannie B3-3.1-01',
            )
        elif mismatch_pct > 10:
            finding(
                'MEDIUM', 'P2-FRAUD',
                app_id,
                f'Income variance '
                f'{mismatch_pct:.1f}%',
                f'Minor. Note in file.',
            )

    # ── entity_states vs verified ─────────────
    if total_verified > 0 and qualifying > 0:
        delta_pct = abs(
            qualifying - total_verified
        ) / total_verified * 100
        if delta_pct > 5:
            finding(
                'HIGH', 'P2-INCOME',
                app_id,
                f'entity_states qualifying '
                f'${qualifying:,.0f} vs '
                f'verified ${total_verified:,.0f} '
                f'({delta_pct:.1f}% delta)',
                'golden_record_builder may '
                'not sum all income sources',
                '',
                'Fix income aggregation '
                'in golden_record_builder',
            )

    # ── Income trend ──────────────────────────
    if w2_prior_monthly > 0 and w2_monthly > 0:
        trend = (
            (w2_monthly - w2_prior_monthly)
            / w2_prior_monthly * 100
        )
        if trend < -10:
            finding(
                'HIGH', 'P2-INCOME',
                app_id,
                f'Income declining: '
                f'{trend:.1f}% YoY',
                f'${w2_prior_monthly:,.0f} -> '
                f'${w2_monthly:,.0f}/mo',
                'Fannie B3-3.1-01',
                'Use lower year for '
                'qualifying income',
            )
        else:
            print(f'    Income trend:       '
                  f'{trend:>+10.1f}% YoY ✅')

    # ── Paystub corroboration ─────────────────
    if paystub_monthly > 0 and w2_monthly > 0:
        ytd_delta = abs(
            paystub_monthly - w2_monthly
        ) / w2_monthly * 100
        if ytd_delta > 15:
            finding(
                'MEDIUM', 'P2-INCOME',
                app_id,
                f'Paystub YTD vs W2: '
                f'{ytd_delta:.1f}% variance',
                f'Paystub ${paystub_monthly:,.0f} '
                f'vs W2 ${w2_monthly:,.0f}/mo',
                '',
                'Request explanation or '
                'updated paystub',
            )
        else:
            print(f'    Paystub corroboration:'
                  f'{ytd_delta:>9.1f}% ✅')

    return total_verified


# ═══════════════════════════════════════════
# PHASE 3: ASSET ANALYSIS
# ═══════════════════════════════════════════
async def phase3_assets(
    conn, app_id, docs, es
):
    if not es:
        return

    section('PHASE 3: Asset Analysis')

    doc_map = {}
    for d in docs:
        doc_map[d['document_type']] = \
            get_fields(d)

    # Get qualifying factors from catalogue
    chk_f = float(
        await get_catalogue(
            conn,
            'qualifying_factor_checking'
        ) or 1.00
    )
    sav_f = float(
        await get_catalogue(
            conn,
            'qualifying_factor_savings'
        ) or 1.00
    )
    ret_f = float(
        await get_catalogue(
            conn,
            'qualifying_factor_retirement'
        ) or 0.60
    )
    stk_f = float(
        await get_catalogue(
            conn,
            'qualifying_factor_stocks_bonds'
        ) or 0.70
    )
    min_res = int(
        await get_catalogue(
            conn,
            'minimum_reserves_months'
        ) or 2
    )
    ld_pct = float(
        await get_catalogue(
            conn,
            'large_deposit_threshold_pct'
        ) or 50
    )

    # Extract balances from docs
    checking   = 0.0
    savings    = 0.0
    retirement = 0.0
    stocks     = 0.0

    if 'BANK_STATEMENT_M1' in doc_map:
        bf = doc_map['BANK_STATEMENT_M1']
        checking = parse_amount(
            first_val(bf, [
                'closing_balance',
                'checking_balance',
                'account_balance',
                'ending_balance',
                'available_balance',
                'current_balance',
                'ledger_balance',
                'gift_funds',
            ]) or 0
        )
        savings = parse_amount(
            first_val(bf, [
                'savings_balance',
                'savings_account_balance',
            ]) or 0
        )

    if 'RETIREMENT_STATEMENT' in doc_map:
        rf = doc_map['RETIREMENT_STATEMENT']
        retirement = parse_amount(
            first_val(rf, [
                'vested_balance',
                'account_balance',
                'total_balance',
            ]) or 0
        )

    if 'BROKERAGE_STATEMENT' in doc_map:
        bf2 = doc_map['BROKERAGE_STATEMENT']
        stocks = parse_amount(
            first_val(bf2, [
                'market_value',
                'account_balance',
                'portfolio_value',
            ]) or 0
        )

    # Apply qualifying factors
    q_checking   = round(checking   * chk_f, 2)
    q_savings    = round(savings    * sav_f, 2)
    q_retirement = round(retirement * ret_f, 2)
    q_stocks     = round(stocks     * stk_f, 2)
    total_qualifying = round(
        q_checking + q_savings +
        q_retirement + q_stocks, 2
    )

    print(f'    Checking:  ${checking:>10,.0f}'
          f' × {chk_f:.0%} = '
          f'${q_checking:>10,.0f}')
    print(f'    Savings:   ${savings:>10,.0f}'
          f' × {sav_f:.0%} = '
          f'${q_savings:>10,.0f}')
    print(f'    Retirement:${retirement:>10,.0f}'
          f' × {ret_f:.0%} = '
          f'${q_retirement:>10,.0f}')
    print(f'    Stocks:    ${stocks:>10,.0f}'
          f' × {stk_f:.0%} = '
          f'${q_stocks:>10,.0f}')
    print(f'    ─────────────────────────────')
    print(f'    Qualifying:{total_qualifying:>11,.0f}')

    # Estimate PITI (rate/term live in loan_terms->urla)
    loan_amt = parse_amount(es['loan_amount'])
    lt = as_json(es['loan_terms'])
    urla = lt.get('urla') or {}

    rate = parse_amount(
        urla.get('interest_rate')
        or es['interest_rate'] or 7.0
    ) / 100 / 12
    term = int(
        urla.get('loan_term_months') or 360
    )
    piti = 0.0
    if rate > 0 and loan_amt > 0:
        pi = loan_amt * rate / (
            1 - (1 + rate) ** (-term)
        )
        piti = round(
            pi + loan_amt * 0.015 / 12, 2
        )

    required_reserves = round(
        piti * min_res, 2
    )

    # Cash to close estimate
    appraised = parse_amount(
        es['appraised_value']
    )
    purchase = parse_amount(
        es['purchase_price']
    )
    lesser = min(appraised, purchase) \
        if purchase > 0 else appraised
    down_payment = round(
        lesser - loan_amt, 2
    ) if lesser > loan_amt else 0
    closing_costs = round(loan_amt * 0.03, 2)
    prepaids = round(piti * 2, 2)
    cash_to_close = round(
        down_payment + closing_costs +
        prepaids, 2
    )

    print(f'    PITI est:  ${piti:>10,.0f}/mo')
    print(f'    Req res:   ${required_reserves:>10,.0f}'
          f' ({min_res}mo PITI)')
    print(f'    Down pmt:  ${down_payment:>10,.0f}')
    print(f'    Closing:   ${closing_costs:>10,.0f}')
    print(f'    Prepaids:  ${prepaids:>10,.0f}')
    print(f'    Cash-to-close:${cash_to_close:>8,.0f}')

    reserves_after = round(
        total_qualifying - cash_to_close, 2
    )
    print(f'    After close:${reserves_after:>9,.0f}')
    print(f'    Need:      ${required_reserves:>10,.0f}')

    if total_qualifying < cash_to_close:
        finding(
            'CRITICAL', 'P3-ASSETS',
            app_id,
            f'Insufficient funds to close: '
            f'${total_qualifying:,.0f} available '
            f'vs ${cash_to_close:,.0f} needed',
            'Borrower cannot close this loan',
            'Fannie B3-4.3-01',
            'Request additional asset '
            'documentation',
        )
    elif reserves_after < required_reserves:
        finding(
            'CRITICAL', 'P3-ASSETS',
            app_id,
            f'Insufficient reserves after '
            f'closing: ${reserves_after:,.0f} '
            f'vs ${required_reserves:,.0f} needed',
            f'{min_res} months PITI required',
            'Fannie B3-4.3-04',
            'Request gift funds or '
            'additional assets',
        )
    else:
        print(f'    ✅ Assets sufficient to close')
        print(f'    ✅ Reserves met after close')

    # Large deposit check
    qualifying_monthly = parse_amount(
        es['qualifying_monthly']
    )
    if qualifying_monthly > 0 \
            and checking > 0:
        ld_threshold = round(
            qualifying_monthly *
            ld_pct / 100, 2
        )
        # We can't check actual deposits without
        # transaction-level bank data
        # Flag for manual review
        finding(
            'INFO', 'P3-ASSETS',
            app_id,
            f'Large deposit threshold: '
            f'${ld_threshold:,.0f} '
            f'({ld_pct:.0f}% of '
            f'${qualifying_monthly:,.0f}/mo)',
            'Manual review: check bank '
            'statements for deposits '
            f'> ${ld_threshold:,.0f}',
            'Fannie B3-4.3-04',
        )

    return total_qualifying, cash_to_close


# ═══════════════════════════════════════════
# PHASE 4: LIABILITY ANALYSIS
# ═══════════════════════════════════════════
async def phase4_liabilities(
    conn, app_id, docs, es
):
    if not es:
        return

    section('PHASE 4: Liability Analysis')

    doc_map = {}
    for d in docs:
        doc_map[d['document_type']] = \
            get_fields(d)

    # Get rules from catalogue
    sl_rate = float(
        await get_catalogue(
            conn,
            'student_loan_deferred_rate_pct'
        ) or 1.0
    ) / 100

    med_excl = await get_catalogue(
        conn, 'medical_collection_excluded'
    )
    medical_excluded = bool(med_excl) \
        if med_excl is not None else True

    # URLA stated obligations
    urla_obligations = 0.0
    if 'URLA_1003' in doc_map:
        uf = doc_map['URLA_1003']
        raw = first_val(uf, [
            'monthly_obligations',
            'total_monthly_payments',
            'monthly_debts',
            'total_liabilities_monthly',
        ])
        if raw:
            urla_obligations = parse_amount(raw)

    # Credit report obligations
    cr_obligations   = 0.0
    cr_medical       = 0.0
    cr_student_bal   = 0.0
    cr_student_pmt   = 0.0

    if 'CREDIT_REPORT' in doc_map:
        cf = doc_map['CREDIT_REPORT']

        cr_obligations = parse_amount(
            first_val(cf, [
                'total_monthly_obligations',
                'total_monthly_payments',
                'monthly_obligations',
                'minimum_payments',
                'total_minimum_payments',
            ]) or 0
        )

        # Student loan balance for 1% rule
        cr_student_bal = parse_amount(
            first_val(cf, [
                'student_loan_balance',
                'student_loans',
                'deferred_student_loans',
                'student_loan_outstanding',
            ]) or 0
        )
        if cr_student_bal > 0:
            cr_student_pmt = round(
                cr_student_bal * sl_rate, 2
            )
            finding(
                'INFO', 'P4-LIAB',
                app_id,
                f'Student loan 1% rule: '
                f'${cr_student_bal:,.0f} × '
                f'{sl_rate*100:.0f}% = '
                f'${cr_student_pmt:,.0f}/mo',
                'Added to monthly obligations',
                'Fannie B3-6-05',
            )

        # Medical collections
        cr_medical = parse_amount(
            first_val(cf, [
                'medical_collection_balance',
                'medical_collections',
            ]) or 0
        )
        if cr_medical > 0 and medical_excluded:
            finding(
                'INFO', 'P4-LIAB',
                app_id,
                f'Medical collections excluded: '
                f'${cr_medical:,.0f}',
                'Per Fannie LL-2023-02',
                'Fannie LL-2023-02',
            )

    # Estimate PITI (rate/term live in loan_terms->urla)
    loan_amt = parse_amount(es['loan_amount'])
    lt = as_json(es['loan_terms'])
    urla = lt.get('urla') or {}

    rate = parse_amount(
        urla.get('interest_rate')
        or es['interest_rate'] or 7.0
    ) / 100 / 12
    term = int(
        urla.get('loan_term_months') or 360
    )
    piti = 0.0
    if rate > 0 and loan_amt > 0:
        pi = loan_amt * rate / (
            1 - (1 + rate) ** (-term)
        )
        piti = round(
            pi + loan_amt * 0.015 / 12, 2
        )

    # Total obligations
    base_obligations = (
        cr_obligations
        if cr_obligations > 0
        else urla_obligations
    )
    total_obligations = round(
        base_obligations +
        cr_student_pmt +
        piti, 2
    )

    print(f'    URLA stated:     '
          f'${urla_obligations:>10,.2f}/mo')
    print(f'    Credit report:   '
          f'${cr_obligations:>10,.2f}/mo')
    print(f'    Student loan 1%: '
          f'${cr_student_pmt:>10,.2f}/mo')
    print(f'    Medical excl:    '
          f'${cr_medical:>10,.2f}/mo')
    print(f'    PITI (est):      '
          f'${piti:>10,.2f}/mo')
    print(f'    ─────────────────────────────')
    print(f'    Total oblig:     '
          f'${total_obligations:>10,.2f}/mo')

    # Undisclosed debt
    if urla_obligations > 0 \
            and cr_obligations > 0:
        undisclosed = (
            cr_obligations - urla_obligations
        )
        und_threshold_med = float(
            await get_catalogue(
                conn,
                'undisclosed_debt_medium_mo'
            ) or 200
        )
        und_threshold_high = float(
            await get_catalogue(
                conn,
                'undisclosed_debt_high_mo'
            ) or 500
        )
        if undisclosed > und_threshold_high:
            finding(
                'HIGH', 'P4-FRAUD',
                app_id,
                f'Undisclosed debt: '
                f'${undisclosed:,.0f}/mo',
                f'Credit ${cr_obligations:,.0f} '
                f'vs URLA ${urla_obligations:,.0f}',
                'Fannie B3-2-10',
                'Escalate to UW review',
            )
        elif undisclosed > und_threshold_med:
            finding(
                'MEDIUM', 'P4-FRAUD',
                app_id,
                f'Possible undisclosed debt: '
                f'${undisclosed:,.0f}/mo',
            )

    return total_obligations, piti


# ═══════════════════════════════════════════
# PHASE 5: RATIO ANALYSIS
# ═══════════════════════════════════════════
async def phase5_ratios(
    conn, app_id, es,
    total_obligations, piti
):
    if not es:
        return

    section('PHASE 5: Ratio Analysis')

    qualifying = parse_amount(
        es['qualifying_monthly']
    )
    appraised = parse_amount(
        es['appraised_value']
    )
    purchase = parse_amount(
        es['purchase_price']
    )
    loan_amt = parse_amount(
        es['loan_amount']
    )
    dti_stored = parse_amount(es['dti_back'])
    ltv_stored = parse_amount(es['ltv'])

    # ── DTI ───────────────────────────────────
    dti_recomputed = round(
        total_obligations / qualifying * 100, 3
    ) if qualifying > 0 else 0

    front_dti = round(
        piti / qualifying * 100, 3
    ) if qualifying > 0 else 0

    print(f'    Front-end DTI:   {front_dti:>10.3f}%')
    print(f'    Back-end stored: {dti_stored:>10.3f}%')
    print(f'    Back-end recalc: {dti_recomputed:>10.3f}%')

    # DTI delta check
    if dti_stored > 0 and dti_recomputed > 0:
        dti_delta = abs(dti_stored - dti_recomputed)
        if dti_delta > 2:
            finding(
                'HIGH', 'P5-DTI',
                app_id,
                f'DTI mismatch: stored '
                f'{dti_stored:.1f}% vs '
                f'recomputed {dti_recomputed:.1f}%',
                f'Delta: {dti_delta:.1f}%',
                '',
                'Fix DTI calculation in '
                'golden_record_builder',
            )

    # Get overlay DTI limit
    dti_rule = await conn.fetchrow('''
        SELECT overlay_value
        FROM overlay_rules
        WHERE tenant_id = $1
        AND rule_type = $2
        AND (loan_type = 'conventional'
             OR loan_type IS NULL)
        ORDER BY loan_type NULLS LAST
        LIMIT 1
    ''', TENANT, 'dti_back_max')
    dti_limit = parse_amount(
        dti_rule['overlay_value']
        if dti_rule else 50
    )

    if dti_recomputed > dti_limit:
        finding(
            'CRITICAL', 'P5-DTI',
            app_id,
            f'DTI exceeds limit: '
            f'{dti_recomputed:.1f}% > '
            f'{dti_limit:.1f}%',
            f'Meridian overlay max: '
            f'{dti_limit:.1f}%',
            'Overlay: meridian/dti_back_max',
            'Loan does not qualify. '
            'Reduce obligations or '
            'increase income.',
        )
    else:
        print(f'    DTI limit:       {dti_limit:>10.1f}%')
        print(f'    ✅ DTI within limit')

    # ── LTV ───────────────────────────────────
    lesser = min(appraised, purchase) \
        if purchase > 0 else appraised
    ltv_correct = round(
        loan_amt / lesser * 100, 3
    ) if lesser > 0 else 0

    print(f'\n    Appraised:       ${appraised:>10,.0f}')
    print(f'    Purchase:        ${purchase:>10,.0f}')
    print(f'    Lesser of:       ${lesser:>10,.0f}')
    print(f'    Loan amount:     ${loan_amt:>10,.0f}')
    print(f'    LTV stored:      {ltv_stored:>10.3f}%')
    print(f'    LTV correct:     {ltv_correct:>10.3f}%')

    ltv_delta = abs(ltv_stored - ltv_correct)
    if purchase > 0 and ltv_delta > 0.1:
        finding(
            'HIGH', 'P5-LTV',
            app_id,
            f'LTV wrong: stored {ltv_stored:.3f}% '
            f'vs correct {ltv_correct:.3f}%',
            'Lesser-of rule not applied. '
            f'Should use ${lesser:,.0f} '
            f'not ${appraised:,.0f}',
            'Fannie B4-1.1-01',
            'Fix LTV calc: use '
            'min(appraised, purchase)',
        )
    elif ltv_delta <= 0.1:
        print(f'    ✅ LTV correct')

    # Get overlay LTV limit
    ltv_rule = await conn.fetchrow('''
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
        ltv_rule['overlay_value']
        if ltv_rule else 97
    )

    if ltv_correct > ltv_limit:
        finding(
            'CRITICAL', 'P5-LTV',
            app_id,
            f'LTV exceeds limit: '
            f'{ltv_correct:.1f}% > '
            f'{ltv_limit:.1f}%',
            f'Meridian overlay max: {ltv_limit}%',
            'Overlay: meridian/ltv_max',
            'Increase down payment.',
        )
    else:
        print(f'    LTV limit:       {ltv_limit:>10.1f}%')
        print(f'    ✅ LTV within limit')

    # Appraisal gap
    if purchase > 0 and appraised < purchase:
        gap = purchase - appraised
        gap_pct = gap / purchase * 100
        major_pct = float(
            await get_catalogue(
                conn, 'appraisal_gap_major_pct'
            ) or 10
        )
        sev = 'CRITICAL' \
            if gap_pct > major_pct \
            else 'HIGH'
        finding(
            sev, 'P5-LTV',
            app_id,
            f'Appraisal gap: '
            f'${gap:,.0f} ({gap_pct:.1f}%)',
            f'Appraised ${appraised:,.0f} < '
            f'purchase ${purchase:,.0f}. '
            f'Borrower must cover ${gap:,.0f} cash.',
            'Fannie B4-1.1-01',
            'Verify borrower has cash to '
            'cover gap + closing costs.',
        )


# ═══════════════════════════════════════════
# PHASE 6: CREDIT ANALYSIS
# ═══════════════════════════════════════════
async def phase6_credit(conn, app_id, docs, es):
    if not es:
        return

    section('PHASE 6: Credit Analysis')

    doc_map = {}
    for d in docs:
        doc_map[d['document_type']] = \
            get_fields(d)

    stored_score = parse_amount(
        es['mid_credit_score']
    )
    print(f'    Mid score stored: {stored_score:.0f}')

    # Three bureau verification
    if 'CREDIT_REPORT' in doc_map:
        cf = doc_map['CREDIT_REPORT']

        eq  = parse_amount(
            cf.get('equifax_score', 0)
        )
        exp = parse_amount(
            cf.get('experian_score', 0)
        )
        tu  = parse_amount(
            cf.get('transunion_score', 0)
        )
        scores = sorted([
            s for s in [eq, exp, tu] if s > 0
        ])

        if len(scores) == 3:
            mid_correct = scores[1]
            print(
                f'    Bureau scores:    '
                f'EQ={eq:.0f} '
                f'EXP={exp:.0f} '
                f'TU={tu:.0f}'
            )
            print(
                f'    Mid correct:      '
                f'{mid_correct:.0f}'
            )
            if abs(stored_score - mid_correct) > 1:
                finding(
                    'CRITICAL', 'P6-CREDIT',
                    app_id,
                    f'Mid score wrong: '
                    f'stored {stored_score:.0f} '
                    f'vs correct {mid_correct:.0f}',
                    f'Scores: {scores}. '
                    f'Middle = {mid_correct:.0f}',
                    'Fannie B3-5.1-01',
                    'Fix mid score calculation: '
                    'use middle of 3 bureaus',
                )
            else:
                print(
                    f'    ✅ Mid score correct'
                )
        elif len(scores) < 3:
            finding(
                'HIGH', 'P6-CREDIT',
                app_id,
                f'Only {len(scores)} bureau '
                f'score(s) found: {scores}',
                'All 3 bureaus required. '
                'With 2: use lower. '
                'With 1: use only score.',
                'Fannie B3-5.1-01',
            )

        # Derogatory events — check all types
        dero_checks = [
            (
                'bankruptcy_discharge_date',
                'bankruptcy_ch7_waiting_years',
                'Chapter 7 BK',
                'Fannie B3-5.3-07',
            ),
            (
                'bankruptcy_ch13_discharge_date',
                'bankruptcy_ch13_waiting_years',
                'Chapter 13 BK',
                'Fannie B3-5.3-07',
            ),
            (
                'foreclosure_date',
                'foreclosure_waiting_years',
                'Foreclosure',
                'Fannie B3-5.3-07',
            ),
            (
                'short_sale_date',
                'short_sale_waiting_years',
                'Short Sale',
                'Fannie B3-5.3-07',
            ),
            (
                'deed_in_lieu_date',
                'deed_in_lieu_waiting_years',
                'Deed-in-Lieu',
                'Fannie B3-5.3-07',
            ),
        ]

        for date_field, wp_name, label, cite \
                in dero_checks:
            event_date = cf.get(date_field)
            if not event_date:
                continue
            try:
                ev_date = datetime.strptime(
                    str(event_date)[:10],
                    '%Y-%m-%d'
                ).date()
                years_since = (
                    TODAY - ev_date
                ).days / 365.25

                req_years = float(
                    await get_catalogue(
                        conn, wp_name
                    ) or 4
                )

                if years_since < req_years:
                    finding(
                        'CRITICAL', 'P6-CREDIT',
                        app_id,
                        f'{label} waiting period '
                        f'NOT met: '
                        f'{years_since:.1f}yr of '
                        f'{req_years:.0f}yr required',
                        f'Event date: {event_date}',
                        cite,
                        'Loan ineligible until '
                        f'{ev_date.year + int(req_years)}'
                        f'-{ev_date.month:02d}-'
                        f'{ev_date.day:02d}',
                    )
                else:
                    print(
                        f'    ✅ {label} cleared: '
                        f'{years_since:.1f}yr '
                        f'(need {req_years:.0f}yr)'
                    )
            except Exception:
                finding(
                    'MEDIUM', 'P6-CREDIT',
                    app_id,
                    f'Cannot parse {label} '
                    f'date: {event_date}',
                )

    # Credit floor check (overlay keys on rule_type)
    credit_floor = await conn.fetchrow('''
        SELECT overlay_value
        FROM overlay_rules
        WHERE tenant_id = $1
        AND rule_type ILIKE $2
        ORDER BY loan_type NULLS LAST
        LIMIT 1
    ''', TENANT, '%credit%')
    floor = parse_amount(
        credit_floor['overlay_value']
        if credit_floor else 620
    )

    if stored_score > 0 \
            and stored_score < floor:
        finding(
            'CRITICAL', 'P6-CREDIT',
            app_id,
            f'Credit score below floor: '
            f'{stored_score:.0f} < '
            f'{floor:.0f}',
            f'Meridian minimum: {floor:.0f}',
            'Overlay: meridian/credit_floor',
            'Loan does not qualify.',
        )
    elif stored_score >= floor:
        print(f'    ✅ Score {stored_score:.0f} '
              f'>= floor {floor:.0f}')


# ═══════════════════════════════════════════
# PHASE 7: PROPERTY ANALYSIS
# ═══════════════════════════════════════════
async def phase7_property(conn, app_id, docs, es):
    if not es:
        return

    section('PHASE 7: Property Analysis')

    doc_map = {}
    for d in docs:
        doc_map[d['document_type']] = \
            get_fields(d)

    lt = as_json(es['loan_terms'])
    urla = lt.get('urla') or {}

    prop_type  = es['property_type']
    flood_zone = urla.get('flood_zone') \
        or as_json(es['property']).get('flood_zone')
    year_built = as_json(es['property']).get(
        'year_built'
    )

    print(f'    property_type: {prop_type}')
    print(f'    flood_zone:    {flood_zone}')
    print(f'    year_built:    {year_built}')

    # Property type from appraisal?
    if 'APPRAISAL_URAR' in doc_map:
        af = doc_map['APPRAISAL_URAR']
        appr_type = first_val(af, [
            'property_type',
            'prop_type',
            'subject_property_type',
            'improvement_type',
            'property_use',
        ])
        cond = first_val(af, [
            'condition',
            'condition_rating',
            'property_condition',
        ])
        appr_date_raw = first_val(af, [
            'appraisal_date',
            'effective_date',
            'report_date',
        ])

        print(f'    appr property_type: {appr_type}')
        print(f'    appr condition:     {cond}')
        print(f'    appr date:          {appr_date_raw}')

        # Appraisal date check
        if appr_date_raw:
            try:
                appr_date = datetime.strptime(
                    str(appr_date_raw)[:10],
                    '%Y-%m-%d'
                ).date()
                age_days = (TODAY - appr_date).days
                if age_days > 120:
                    finding(
                        'HIGH', 'P7-PROPERTY',
                        app_id,
                        f'Appraisal stale: '
                        f'{age_days} days old',
                        'Fannie requires < 120 days '
                        'at closing',
                        'Fannie B4-1.2-03',
                        'Order new appraisal',
                    )
                else:
                    print(
                        f'    ✅ Appraisal age: '
                        f'{age_days} days'
                    )
            except Exception:
                finding(
                    'MEDIUM', 'P7-PROPERTY',
                    app_id,
                    f'Cannot parse appraisal '
                    f'date: {appr_date_raw}',
                )
        else:
            finding(
                'HIGH', 'P7-PROPERTY',
                app_id,
                'Appraisal date not extracted',
                'Cannot verify appraisal < 120 days',
                'Fannie B4-1.2-03',
            )

        # Condition rating
        if cond and str(cond).upper() \
                in ['C5', 'C6']:
            finding(
                'HIGH', 'P7-PROPERTY',
                app_id,
                f'Poor condition: {cond}',
                'C5/C6 requires repair escrow '
                'or as-repaired appraisal',
                'Fannie B4-1.3-03',
                'Require repair escrow '
                'prior to closing',
            )
        elif cond:
            print(f'    ✅ Condition: {cond}')

        # Property type mismatch
        if appr_type and prop_type:
            if str(appr_type).lower().strip() \
                    != str(prop_type).lower().strip():
                finding(
                    'HIGH', 'P7-PROPERTY',
                    app_id,
                    f'Property type mismatch: '
                    f'entity={prop_type} '
                    f'vs appraisal={appr_type}',
                    'entity_states not updated '
                    'from appraisal extraction',
                    '',
                    'Fix golden_record_builder: '
                    'map APPRAISAL_URAR.'
                    'property_type -> '
                    'entity_states.property_type',
                )
        elif appr_type and not prop_type:
            finding(
                'HIGH', 'P7-PROPERTY',
                app_id,
                f'property_type NULL in '
                f'entity_states but appraisal '
                f'has: {appr_type}',
                'golden_record_builder not '
                'mapping this field',
                '',
                'Fix golden_record_builder mapping',
            )

    # Flood zone
    if not flood_zone:
        finding(
            'HIGH', 'P7-PROPERTY',
            app_id,
            'flood_zone not in entity_states',
            'Cannot determine flood insurance '
            'requirement',
            'Fannie B7-3-02',
            'Extract flood_zone from '
            'APPRAISAL_URAR or FLOOD_CERT',
        )
    else:
        sfha_zones = await get_catalogue(
            conn, 'flood_zones_requiring_insurance'
        ) or ['A', 'AE', 'AH', 'AO', 'V', 'VE']
        if isinstance(sfha_zones, str):
            try:
                sfha_zones = json.loads(sfha_zones)
            except Exception:
                sfha_zones = []
        if flood_zone in sfha_zones:
            finding(
                'HIGH', 'P7-PROPERTY',
                app_id,
                f'SFHA flood zone {flood_zone}: '
                f'flood insurance required',
                'Must have active flood policy '
                'before closing',
                'Fannie B7-3-02',
                'Obtain flood insurance '
                'declaration page',
            )
        else:
            print(f'    ✅ Flood zone {flood_zone}: '
                  f'no flood insurance required')

    # Ineligible property type
    if prop_type:
        inelig = await get_catalogue(
            conn, 'ineligible_property_types'
        ) or []
        if isinstance(inelig, str):
            try:
                inelig = json.loads(inelig)
            except Exception:
                inelig = []
        if isinstance(inelig, dict):
            inelig = inelig.get('types', [])
        if prop_type in inelig:
            finding(
                'CRITICAL', 'P7-PROPERTY',
                app_id,
                f'Ineligible property: {prop_type}',
                'Not eligible for Fannie Mae',
                'Fannie B2-1.3-01',
                'Decline loan.',
            )
        else:
            print(f'    ✅ Property type '
                  f'{prop_type} eligible')


# ═══════════════════════════════════════════
# PHASE 8: EVIDENCE CHAIN
# ═══════════════════════════════════════════
async def phase8_evidence(conn, app_id):
    section('PHASE 8: Evidence Chain')

    ev_nodes = await conn.fetch('''
        SELECT node_type, field_name,
               raw_value, numeric_value,
               source_document_type,
               confidence
        FROM evidence_nodes
        WHERE application_id = $1
        AND tenant_id = $2
        ORDER BY node_type
    ''', app_id, TENANT)

    fn_nodes = await conn.fetch('''
        SELECT fact_type, fact_value,
               confidence,
               conflicts_found,
               resolution_method,
               evidence_ids
        FROM fact_nodes
        WHERE application_id = $1
        AND tenant_id = $2
        ORDER BY fact_type
    ''', app_id, TENANT)

    print(f'    evidence_nodes: {len(ev_nodes)}')
    print(f'    fact_nodes:     {len(fn_nodes)}')

    if not ev_nodes:
        finding(
            'HIGH', 'P8-EVIDENCE',
            app_id,
            'No evidence_nodes populated',
            'Cannot prove values used '
            'in decision',
            '',
            'Run evidence resolvers '
            '(EV-B1 through EV-B4)',
        )

    if not fn_nodes:
        finding(
            'HIGH', 'P8-EVIDENCE',
            app_id,
            'No fact_nodes populated',
            'Personas using raw entity_states '
            'not qualified evidence',
            '',
            'EV-F: wire evidence to personas',
        )
        return

    # Check required fact types
    required_facts = [
        'qualifying_income',
        'verified_assets',
        'governing_credit_score',
        'employment_continuity',
    ]
    fn_types = {f['fact_type'] for f in fn_nodes}
    for ft in required_facts:
        if ft not in fn_types:
            finding(
                'HIGH', 'P8-EVIDENCE',
                app_id,
                f'Missing fact: {ft}',
                'Required fact type '
                'not in fact_nodes',
            )

    # Check confidence levels
    for fn in fn_nodes:
        conf = float(
            fn['confidence'] or 0
        )
        has_conflict = bool(
            fn['conflicts_found']
        )
        print(
            f'    {fn["fact_type"]}: '
            f'conf={conf:.2f} '
            f'conflict={has_conflict}'
        )
        if conf < 0.75:
            finding(
                'MEDIUM', 'P8-EVIDENCE',
                app_id,
                f'Low confidence: '
                f'{fn["fact_type"]} '
                f'({conf:.2f})',
                'Request additional docs '
                'to increase confidence',
            )
        if has_conflict:
            finding(
                'HIGH', 'P8-EVIDENCE',
                app_id,
                f'Conflict detected: '
                f'{fn["fact_type"]}',
                'Multiple sources disagree. '
                'Use conservative value.',
            )

    # Reverse trace check
    # Can we go decision → source doc?
    decision = await conn.fetchrow('''
        SELECT evidence_trace,
               context_snapshot,
               created_at
        FROM decision_outputs
        WHERE application_id = $1
        AND tenant_id = $2
        ORDER BY created_at DESC
        LIMIT 1
    ''', app_id, TENANT)

    if not decision:
        finding(
            'HIGH', 'P8-EVIDENCE',
            app_id,
            'No decision_output found',
            'Cannot verify audit trail',
        )
    else:
        print(f'    ✅ Decision output exists')
        has_trace = bool(
            decision['evidence_trace']
        ) or bool(
            decision['context_snapshot']
        )
        if not has_trace:
            finding(
                'MEDIUM', 'P8-EVIDENCE',
                app_id,
                'Decision output missing '
                'evidence_trace / context_snapshot',
                'Cannot trace decision back '
                'to source documents',
                '',
                'Add trace to decision output',
            )
        else:
            print(f'    ✅ Decision trace exists')


# ═══════════════════════════════════════════
# PHASE 9: DECISION QUALITY
# ═══════════════════════════════════════════
async def phase9_decision(conn, app_id):
    section('PHASE 9: Decision Quality')

    # Check persona context views
    # reference fact_nodes (EV-F)
    views = await conn.fetch('''
        SELECT table_name, view_definition
        FROM information_schema.views
        WHERE table_schema = 'public'
        AND table_name ILIKE '%context%'
        ORDER BY table_name
    ''')

    evf_missing = []
    for v in views:
        defn = v['view_definition'] or ''
        has_facts = 'fact_node' in defn.lower()
        if not has_facts:
            evf_missing.append(v['table_name'])

    if evf_missing:
        finding(
            'HIGH', 'P9-DECISION',
            'ALL',
            f'EV-F missing: {len(evf_missing)} '
            f'context views not using fact_nodes',
            'Personas read raw entity_states. '
            'Decisions not evidence-based.',
            'EV-F',
            'Wire fact_nodes into '
            'vw_*_context views',
        )

    # Check resolver hardcoding (Python file walk —
    # portable equivalent of the original grep)
    pattern = re.compile(
        r'WAITING_PERIODS|QUALIFYING_FACTORS|'
        r'LIEN_RULES|MISMATCH_THRESHOLDS|'
        r'LARGE_DEPOSIT_PCT|MIN_RESERVES'
    )
    hardcoded = []
    core_dir = pathlib.Path('core')
    if core_dir.exists():
        for p in core_dir.rglob('*.py'):
            if '__pycache__' in str(p):
                continue
            try:
                for i, line in enumerate(
                    p.read_text(
                        encoding='utf-8',
                        errors='replace'
                    ).splitlines(), 1
                ):
                    if pattern.search(line):
                        hardcoded.append(
                            f'{p}:{i}: '
                            f'{line.strip()}'
                        )
            except Exception:
                pass
    if hardcoded:
        finding(
            'HIGH', 'P9-DECISION',
            'CODEBASE',
            f'{len(hardcoded)} hardcoded rule '
            f'violations in resolvers',
            '\n'.join(hardcoded[:5]) +
            (f'\n...and '
             f'{len(hardcoded)-5} more'
             if len(hardcoded) > 5 else ''),
            '',
            'Phase RA-4: rewrite resolvers '
            'to use rule_loader',
        )
    else:
        print(f'    ✅ No hardcoded rule dicts '
              f'detected')

    # Check decision outputs exist
    decisions = await conn.fetch('''
        SELECT application_id,
               decision_id, outcome
        FROM decision_outputs
        WHERE tenant_id = $1
        ORDER BY application_id, decision_id
    ''', TENANT)

    if not decisions:
        finding(
            'CRITICAL', 'P9-DECISION',
            'ALL',
            'No decision_outputs found',
            'No decisions recorded for '
            'any application',
        )
    else:
        by_app = {}
        for d in decisions:
            by_app.setdefault(
                d['application_id'], []
            ).append(d['outcome'])

        print(
            f'    Decision outputs: '
            f'{len(decisions)} across '
            f'{len(by_app)} apps'
        )
        for app_id_d, outcomes in \
                sorted(by_app.items()):
            print(
                f'    {app_id_d}: '
                f'{", ".join(sorted(set(outcomes)))}'
            )


# ═══════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════
async def main():
    import asyncpg

    url = os.environ['DATABASE_URL'] \
        .replace('+asyncpg', '') \
        .replace('postgresql+psycopg2',
                 'postgresql')
    conn = await asyncpg.connect(url)

    try:
        print('=' * 60)
        print('SENIOR UNDERWRITER AUDIT')
        print('ACCORD Decision OS — Critical Phase')
        print(f'Tenant: {TENANT}')
        print(f'Date:   {TODAY}')
        print('=' * 60)
        print()
        print('Persona: Senior UW / 20yr experience')
        print('Standard: Fannie Mae Selling Guide')
        print('Purpose: Repurchase defense audit')
        print('=' * 60)

        # All applications
        apps = await conn.fetch('''
            SELECT DISTINCT application_id
            FROM entity_states
            WHERE tenant_id = $1
            ORDER BY application_id
        ''', TENANT)

        print(
            f'\nAuditing {len(apps)} '
            f'applications\n'
        )

        for app in apps:
            app_id = app['application_id']
            print(f'\n{"═"*60}')
            print(f'APPLICATION: {app_id}')
            print(f'{"═"*60}')

            # Get documents
            docs = await conn.fetch('''
                SELECT document_type,
                       extracted_fields,
                       confidence_score,
                       received_at
                FROM document_index
                WHERE application_id = $1
                AND tenant_id = $2
                AND is_current = true
                ORDER BY document_type
            ''', app_id, TENANT)

            # Run all phases
            es = await phase1_file_assembly(
                conn, app_id, docs
            )
            total_verified = await phase2_income(
                conn, app_id, docs, es
            )
            await phase3_assets(
                conn, app_id, docs, es
            )
            liab_result = await phase4_liabilities(
                conn, app_id, docs, es
            )
            total_oblig = liab_result[0] \
                if liab_result else 0
            piti = liab_result[1] \
                if liab_result else 0
            await phase5_ratios(
                conn, app_id, es,
                total_oblig, piti
            )
            await phase6_credit(
                conn, app_id, docs, es
            )
            await phase7_property(
                conn, app_id, docs, es
            )
            await phase8_evidence(
                conn, app_id
            )
            await phase9_decision(
                conn, app_id
            )

        # ── FINDINGS SUMMARY ──────────────────
        print('\n\n' + '=' * 60)
        print('AUDIT FINDINGS SUMMARY')
        print('=' * 60)

        by_sev = {}
        for f in FINDINGS:
            by_sev.setdefault(
                f['severity'], []
            ).append(f)

        total = len(FINDINGS)
        print(f'Total findings: {total}')
        for s in SEV_ORDER:
            n = len(by_sev.get(s, []))
            if n:
                print(
                    f'{SEV_ICON[s]} {s}: {n}'
                )

        for sev in SEV_ORDER:
            items = by_sev.get(sev, [])
            if not items:
                continue
            print(
                f'\n{SEV_ICON[sev]} '
                f'{sev} FINDINGS:'
            )
            for f in items:
                print(
                    f'  [{f["phase"]}] '
                    f'{f["app_id"]}: '
                    f'{f["issue"]}'
                )
                if f['detail']:
                    print(
                        f'    detail: {f["detail"]}'
                    )
                if f['citation']:
                    print(
                        f'    cite:   '
                        f'{f["citation"]}'
                    )
                if f['fix']:
                    print(
                        f'    fix:    {f["fix"]}'
                    )

        # ── CRITICAL PATH SUMMARY ─────────────
        print('\n' + '=' * 60)
        print('CRITICAL PATH — Fix in this order:')
        print('=' * 60)

        critical = by_sev.get('CRITICAL', [])
        high     = by_sev.get('HIGH', [])

        if not critical and not high:
            print('✅ No critical or high findings.')
            print('System ready for production.')
        else:
            # Group by phase
            by_phase = {}
            for f in critical + high:
                by_phase.setdefault(
                    f['phase'], []
                ).append(f)
            for phase, items in \
                    sorted(by_phase.items()):
                print(
                    f'\n{phase} '
                    f'({len(items)} issues):'
                )
                for f in items:
                    print(
                        f'  {SEV_ICON[f["severity"]]}'
                        f' {f["app_id"]}: '
                        f'{f["issue"]}'
                    )
                    if f['fix']:
                        print(
                            f'    → {f["fix"]}'
                        )

        print('\n' + '=' * 60)
        print('END OF AUDIT')
        print('=' * 60)

    finally:
        await conn.close()


if __name__ == '__main__':
    asyncio.run(main())
