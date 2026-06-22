"""
Asset Resolver — AV-B

Answers three questions for every loan:

Q1: SUFFICIENT?
  Total qualifying assets ≥ funds needed?
  funds_needed = down_payment
               + closing_costs (est 3% of loan)
               + prepaids (est 2 months PITI)
               + reserves (2 months PITI min)

Q2: SEASONED?
  Each asset account must show 60 days
  of history (statements).
  Business accounts: 60 days + CPA letter.
  Gift funds: gift letter + donor statement
              + transfer proof.

Q3: SOURCED?
  Large deposits (>50% of qualifying monthly)
  must be documented.
  Gift funds: full gift chain required.

Qualifying factors per asset type:
  checking/savings/money_market: 1.00
  cd:                            1.00 (if liquid)
  brokerage/stocks_bonds:        0.70
  ira/401k/403b/pension/annuity: 0.60
  business_account:              varies by pct
  crypto:                        0.00 (excluded)
  gift_funds:                    1.00 if documented
  proceeds_sale:                 1.00 if verified
  bridge_loan:                   0.00 (not counted)
"""

from dataclasses import dataclass, field
from typing import List, Optional


# Asset-type -> canonical catalogue factor key. STRUCTURAL classifier (not a
# lending value): the factor VALUES come from agency_guidelines via rule_loader
# (Fannie B3-4.3-04). Liquid-equivalent types map to the checking factor.
ACCT_TYPE_TO_FACTOR_KEY = {
    'checking':       'qualifying_factor_checking',
    'savings':        'qualifying_factor_savings',
    'money_market':   'qualifying_factor_checking',
    'cd':             'qualifying_factor_cd',
    'gift_funds':     'qualifying_factor_checking',   # liquid once documented
    'proceeds_sale':  'qualifying_factor_checking',   # liquid once verified
    'other':          'qualifying_factor_checking',
    'brokerage':      'qualifying_factor_stocks_bonds',
    'stocks_bonds':   'qualifying_factor_stocks_bonds',
    'ira':            'qualifying_factor_retirement',
    '401k':           'qualifying_factor_retirement',
    '403b':           'qualifying_factor_retirement',
    'pension':        'qualifying_factor_retirement',
    'annuity':        'qualifying_factor_retirement',
    'crypto':         'qualifying_factor_crypto',
}
# Excluded from qualifying assets (factor 0) unless special-case logic
# (business ownership tiers) applies — structural eligibility, not a value.
EXCLUDED_ACCT_TYPES = {'business_account', 'bridge_loan'}

# Catalogue rule names this resolver reads through rule_loader.
ASSET_RULE_KEYS = [
    'qualifying_factor_checking', 'qualifying_factor_savings',
    'qualifying_factor_cd', 'qualifying_factor_retirement',
    'qualifying_factor_stocks_bonds', 'qualifying_factor_crypto',
    'minimum_reserves_months', 'large_deposit_threshold_pct',
    'seasoning_days_required',
]


async def load_asset_rules(conn, tenant_id: str, agency: str = 'fannie') -> dict:
    """Resolve every asset rule from the catalogue via rule_loader. Returns
    {'values': {key: applied}, 'trace': {key: {applied, governed_by, layers}}}.
    Called on the ASYNC snapshot path (runner) — never inside the sync persona —
    and injected into AssetResolver / DepositAnalyzer."""
    from core.catalogue.rule_loader import get_rule
    values, trace = {}, {}
    for key in ASSET_RULE_KEYS:
        r = await get_rule(conn, key, tenant_id, agency=agency)
        values[key] = r.get('applied')
        trace[key] = {
            'applied':     r.get('applied'),
            'governed_by': r.get('governed_by'),
            'layers':      r.get('layers', {}),
        }
    return {'values': values, 'trace': trace}


@dataclass
class AccountAnalysis:
    account_id:        str
    institution:       str
    account_type:      str
    current_balance:   float
    qualifying_factor: float
    qualifying_amount: float
    is_seasoned:       bool
    seasoned_days:     int
    has_large_deposit: bool
    large_deposit_sourced: bool
    large_deposit_amount: float
    included:          bool
    exclusion_reason:  Optional[str]
    flags:             List[str] = field(
                           default_factory=list
                       )
    conditions:        List[dict] = field(
                           default_factory=list
                       )


class AssetResolver:

    def __init__(self, rules: Optional[dict] = None):
        """`rules` is the catalogue-resolved {key: value} map (from
        load_asset_rules, attached to the bundle by the runner). When absent
        (tests / non-enriched callers), fall back to rule_loader.SAFE_DEFAULTS —
        the single sanctioned fallback; no resolver-local hardcoded values."""
        from core.catalogue.rule_loader import SAFE_DEFAULTS
        self._rules = dict(SAFE_DEFAULTS)
        if rules:
            self._rules.update(
                {k: v for k, v in rules.items() if v is not None}
            )

    def _factor(self, acct_type: str) -> float:
        if acct_type in EXCLUDED_ACCT_TYPES:
            return 0.0
        key = ACCT_TYPE_TO_FACTOR_KEY.get(
            acct_type, 'qualifying_factor_checking'
        )
        return float(self._rules.get(key, 1.0))

    @property
    def _reserves_months(self) -> float:
        return float(self._rules.get('minimum_reserves_months', 2))

    @property
    def _large_deposit_frac(self) -> float:
        # catalogue stores percent (50); the math wants the fraction.
        return float(
            self._rules.get('large_deposit_threshold_pct', 50)
        ) / 100.0

    @property
    def _seasoning_days(self) -> int:
        return int(self._rules.get('seasoning_days_required', 60))

    def analyze_account(
        self,
        account: dict,
        qualifying_monthly: float = 0,
    ) -> AccountAnalysis:
        """
        Analyze a single asset account.
        """
        acct_type  = account.get(
            'account_type', 'other'
        )
        balance    = float(
            account.get('current_balance') or 0
        )
        factor     = self._factor(acct_type)
        seasoned   = account.get(
            'is_seasoned', True
        )
        seas_days  = int(
            account.get('seasoned_days') or 0
        )
        is_gift    = account.get(
            'is_gift', False
        )
        gift_doc   = account.get(
            'gift_documented', False
        )
        is_biz     = account.get(
            'is_business', False
        )
        biz_pct    = float(
            account.get(
                'business_ownership_pct'
            ) or 0
        )
        has_dep    = account.get(
            'has_large_deposit', False
        )
        dep_sourced = account.get(
            'large_deposit_sourced', False
        )
        dep_amount = float(
            account.get(
                'large_deposit_amount'
            ) or 0
        )
        institution = account.get(
            'institution_name', 'Unknown Bank'
        )

        included         = True
        exclusion_reason = None
        flags            = []
        conditions       = []

        # ── Crypto: always excluded ────────────
        if acct_type == 'crypto':
            included = False
            exclusion_reason = (
                'Crypto assets excluded per '
                'Fannie Mae policy'
            )
            factor = self._factor('crypto')
            flags.append('crypto_excluded')

        # ── Gift funds: need full chain ────────
        elif is_gift and not gift_doc:
            flags.append('gift_undocumented')
            conditions.append({
                'code': 'ASSET_GIFT_LETTER',
                'text': (
                    f'Gift funds of '
                    f'${balance:,.0f} from '
                    f'{institution} require: '
                    f'(1) signed gift letter, '
                    f'(2) donor bank statement '
                    f'showing withdrawal, '
                    f'(3) borrower statement '
                    f'showing deposit. '
                    f'No repayment clause allowed.'
                ),
                'blocks': False,
                'prior_to': 'docs',
            })

        # ── Business account: needs CPA ────────
        elif is_biz:
            if biz_pct >= 100:
                factor = 1.00
            elif biz_pct >= 50:
                factor = 0.50
            else:
                factor = 0.00
                included = False
                exclusion_reason = (
                    f'Business account with '
                    f'{biz_pct}% ownership — '
                    f'need ≥50% to use'
                )
            if included:
                flags.append(
                    f'business_asset_{biz_pct}pct'
                )
                conditions.append({
                    'code': 'ASSET_BUSINESS_CPA',
                    'text': (
                        f'Business account at '
                        f'{institution}: '
                        f'${balance:,.0f}. '
                        f'Provide CPA letter '
                        f'confirming withdrawal '
                        f'will not harm business '
                        f'operations.'
                    ),
                    'blocks': False,
                    'prior_to': 'docs',
                })

        # ── Seasoning check ────────────────────
        if included and not seasoned \
                and seas_days < self._seasoning_days:
            flags.append(
                f'not_seasoned_{seas_days}d'
            )
            conditions.append({
                'code': 'ASSET_SEASONING',
                'text': (
                    f'Account at {institution}: '
                    f'${balance:,.0f} has only '
                    f'{seas_days} days of history '
                    f'({self._seasoning_days} required). Provide '
                    f'additional statements or '
                    f'source of funds.'
                ),
                'blocks': False,
                'prior_to': 'docs',
            })

        # ── Large deposit check ────────────────
        if included and has_dep \
                and not dep_sourced \
                and dep_amount > 0:
            threshold = (
                qualifying_monthly
                * self._large_deposit_frac
                if qualifying_monthly > 0
                else 5000
            )
            if dep_amount > threshold:
                flags.append(
                    f'large_deposit_unsourced_'
                    f'${dep_amount:,.0f}'
                )
                conditions.append({
                    'code': 'ASSET_LARGE_DEPOSIT',
                    'text': (
                        f'Large deposit of '
                        f'${dep_amount:,.0f} '
                        f'in {institution} account '
                        f'requires documentation: '
                        f'(1) written explanation '
                        f'of source, '
                        f'(2) supporting documents '
                        f'(pay stub, tax return, '
                        f'sale proceeds, transfer '
                        f'confirmation). '
                        f'Per Fannie Mae B3-4.3-04.'
                    ),
                    'blocks': False,
                    'prior_to': 'docs',
                })

        # Compute qualifying amount
        qualifying_amount = round(
            balance * factor, 2
        ) if included else 0.0

        return AccountAnalysis(
            account_id=str(
                account.get('id', '')
            ),
            institution=institution,
            account_type=acct_type,
            current_balance=balance,
            qualifying_factor=factor,
            qualifying_amount=qualifying_amount,
            is_seasoned=seasoned,
            seasoned_days=seas_days,
            has_large_deposit=has_dep,
            large_deposit_sourced=dep_sourced,
            large_deposit_amount=dep_amount,
            included=included,
            exclusion_reason=exclusion_reason,
            flags=flags,
            conditions=conditions,
        )

    def resolve_all(
        self,
        accounts: list,
        qualifying_monthly: float = 0,
        piti_monthly: float = 0,
        loan_amount: float = 0,
        down_payment: float = 0,
    ) -> dict:
        """
        Resolve all asset accounts.
        Returns sufficiency check.
        """
        analyses        = []
        total_qualifying = 0.0
        all_conditions  = []
        all_flags       = []

        for acct in accounts:
            analysis = self.analyze_account(
                acct, qualifying_monthly
            )
            analyses.append(analysis)
            all_conditions.extend(
                analysis.conditions
            )
            all_flags.extend(analysis.flags)
            if analysis.included:
                total_qualifying += \
                    analysis.qualifying_amount

        # Funds to close calculation
        closing_costs = round(
            loan_amount * 0.03, 2
        ) if loan_amount else 0
        prepaids = round(
            piti_monthly * 2, 2
        ) if piti_monthly else 0
        reserves = round(
            piti_monthly * self._reserves_months, 2
        ) if piti_monthly else 0

        funds_needed = (
            down_payment
            + closing_costs
            + prepaids
            + reserves
        )

        sufficient = (
            total_qualifying >= funds_needed
            if funds_needed > 0
            else True
        )

        if not sufficient and funds_needed > 0:
            shortfall = funds_needed \
                      - total_qualifying
            all_conditions.append({
                'code': 'ASSET_INSUFFICIENT',
                'text': (
                    f'Insufficient assets for '
                    f'funds to close. '
                    f'Needed: ${funds_needed:,.0f} '
                    f'(down ${down_payment:,.0f} '
                    f'+ costs ${closing_costs:,.0f} '
                    f'+ prepaids ${prepaids:,.0f} '
                    f'+ reserves ${reserves:,.0f}). '
                    f'Available: '
                    f'${total_qualifying:,.0f}. '
                    f'Shortfall: ${shortfall:,.0f}.'
                ),
                'blocks': True,
                'prior_to': 'docs',
            })

        has_unsourced = any(
            'large_deposit_unsourced' in f
            for f in all_flags
        )
        has_gift_undoc = any(
            'gift_undocumented' in f
            for f in all_flags
        )

        overall = (
            'block' if not sufficient
            else 'escalate'
                if (has_unsourced or has_gift_undoc)
            else 'allow'
        )

        return {
            'analyses':          analyses,
            'total_qualifying':  round(
                total_qualifying, 2
            ),
            'funds_needed':      funds_needed,
            'funds_sufficient':  sufficient,
            'closing_costs_est': closing_costs,
            'prepaids_est':      prepaids,
            'reserves_needed':   reserves,
            'overall_status':    overall,
            'all_conditions':    all_conditions,
            'all_flags':         list(
                set(all_flags)
            ),
            'has_unsourced_deposit': has_unsourced,
            'has_undoc_gift':    has_gift_undoc,
            'account_count':     len(analyses),
        }


__all__ = [
    "AssetResolver",
    "AccountAnalysis",
    "load_asset_rules",
    "ACCT_TYPE_TO_FACTOR_KEY",
    "ASSET_RULE_KEYS",
]
