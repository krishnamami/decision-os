"""
Tradeline Analyzer — CR-D

Analyzes individual tradelines for:
  1. Authorized user accounts
     (possible score inflation)
  2. Disputed derogatory accounts
     (must be removed before closing)
  3. Student loan deferred/IBR treatment
     (1% rule — most commonly wrong)
  4. Obligation calculation
     (correct per agency rules)

Feeds: credit_assessment persona
       dti_calculation (correct obligations)
       conditions generated
"""

from dataclasses import dataclass, field
from typing import List, Optional


DEROGATORY_STATUSES = {
    'collection', 'charge_off',
    'late_30', 'late_60', 'late_90',
    'late_120', 'foreclosure', 'bankruptcy',
}


@dataclass
class TradelineAnalysis:
    tradeline_id:     str
    creditor_name:    str
    account_type:     str
    current_balance:  float
    monthly_payment:  float
    included_in_dti:  bool
    exclusion_reason: Optional[str]
    computed_payment: float
    flags:            List[str] = field(
                          default_factory=list
                      )
    conditions:       List[dict] = field(
                          default_factory=list
                      )


class TradelineAnalyzer:

    def __init__(self, rules: dict = None):
        """`rules` is the catalogue-resolved {key: value} map
        (student_loan_deferred_rate_pct, medical_collection_excluded), injected
        via the bundle. Falls back to rule_loader.SAFE_DEFAULTS — the single
        sanctioned fallback; no resolver-local hardcoded lending values."""
        from core.catalogue.rule_loader import SAFE_DEFAULTS
        self._rules = dict(SAFE_DEFAULTS)
        if rules:
            self._rules.update({
                k: (v.get('value') if isinstance(v, dict) else v)
                for k, v in rules.items()
                if (v.get('value') if isinstance(v, dict) else v) is not None
            })

    @property
    def _student_loan_rate(self) -> float:
        # catalogue stores percent (1.0); the math wants the fraction.
        return float(
            self._rules.get('student_loan_deferred_rate_pct', 1.0)
        ) / 100.0

    @property
    def _medical_excluded(self) -> bool:
        return bool(self._rules.get('medical_collection_excluded', True))

    def analyze_tradeline(
        self,
        tradeline: dict,
        qualifying_monthly: float = 0,
        agency: str = 'fannie',
    ) -> TradelineAnalysis:
        """
        Analyze a single tradeline.
        Returns: included in DTI, computed payment,
                 flags, conditions.
        """
        creditor    = tradeline.get(
            'creditor_name', ''
        )
        acct_type   = tradeline.get(
            'account_type', 'other'
        )
        balance     = float(
            tradeline.get('current_balance') or 0
        )
        payment     = float(
            tradeline.get('monthly_payment') or 0
        )
        status      = tradeline.get(
            'payment_status', 'current'
        )
        is_auth     = tradeline.get(
            'is_authorized_user', False
        )
        is_disputed = tradeline.get(
            'is_disputed', False
        )
        is_medical  = tradeline.get(
            'is_medical', False
        )
        sl_type     = tradeline.get(
            'student_loan_type'
        )
        ibr_payment = float(
            tradeline.get('ibr_payment') or 0
        )
        months_rem  = tradeline.get(
            'months_remaining'
        )

        included         = True
        exclusion_reason = None
        computed_payment = payment
        flags            = []
        conditions       = []

        # ── RULE 1: Authorized user ────────────
        if is_auth:
            flags.append('authorized_user')
            # Flag for UW review — may need
            # to exclude if related party
            conditions.append({
                'code': 'CREDIT_AUTHORIZED_USER',
                'text': (
                    f'Authorized user account: '
                    f'{creditor}. Verify primary '
                    f'account holder is not a '
                    f'related party. If related '
                    f'party, exclude from analysis.'
                ),
                'blocks': False,
                'loe':    False,
            })

        # ── RULE 2: Disputed derogatory ────────
        if is_disputed and \
                status in DEROGATORY_STATUSES:
            flags.append('disputed_derogatory')
            included = False
            exclusion_reason = (
                'Disputed derogatory — '
                'cannot include until '
                'dispute resolved'
            )
            conditions.append({
                'code': 'CREDIT_DISPUTED_ACCOUNT',
                'text': (
                    f'Disputed derogatory account: '
                    f'{creditor} (status: {status}). '
                    f'Per Fannie Mae B3-5.3-09, '
                    f'dispute must be removed '
                    f'before closing. Contact '
                    f'credit bureau to remove '
                    f'dispute notation.'
                ),
                'blocks': True,
                'loe':    False,
            })

        # ── RULE 3: Student loan treatment ─────
        elif acct_type == 'student_loan':
            if sl_type == 'deferred':
                # Fannie: 1% of balance per month
                # Cannot use $0 payment
                computed_payment = round(
                    balance * self._student_loan_rate, 2
                )
                flags.append(
                    f'student_loan_deferred_'
                    f'1pct_rule'
                )
                if payment == 0:
                    conditions.append({
                        'code': 'CREDIT_STUDENT_DEFERRED',
                        'text': (
                            f'Student loan deferred: '
                            f'{creditor} balance '
                            f'${balance:,.0f}. '
                            f'Per Fannie Mae B3-6-05, '
                            f'1% of balance '
                            f'(${computed_payment:,.0f}/mo) '
                            f'used for DTI calculation. '
                            f'Cannot use $0 payment.'
                        ),
                        'blocks': False,
                        'loe':    False,
                    })

            elif sl_type in ('ibr', 'paye', 'save'):
                # IBR/PAYE/SAVE: the documented income-driven payment IS the
                # obligation, even when $0 (Fannie B3-6-05) — use the actual
                # ibr_payment, never 1% of balance. The 1% proxy applies only to
                # DEFERRED loans with no payment plan (handled above via the
                # catalogue rate); substituting it here would overstate DTI.
                computed_payment = ibr_payment
                flags.append('student_loan_ibr_actual')
                if ibr_payment == 0:
                    conditions.append({
                        'code': 'CREDIT_STUDENT_IBR_ZERO',
                        'text': (
                            f'Student loan on income-driven plan ({sl_type}) '
                            f'with documented $0 payment: {creditor}. Per Fannie '
                            f'Mae B3-6-05 the actual $0 payment is used for DTI '
                            f'(not 1% of balance). Verify the IDR documentation.'
                        ),
                        'blocks': False,
                        'loe':    False,
                    })

            elif sl_type == 'pslf':
                # PSLF: use the actual payment; a documented $0 PSLF payment is
                # excluded from DTI entirely (Fannie B3-6-05).
                computed_payment = payment
                if payment == 0:
                    included = False
                    exclusion_reason = (
                        'PSLF with documented $0 payment — excluded from DTI '
                        'per Fannie Mae B3-6-05'
                    )
                    flags.append('student_loan_pslf_excluded')
                else:
                    flags.append('student_loan_pslf_actual')

        # ── RULE 4: Months remaining ───────────
        elif months_rem is not None \
                and months_rem <= 10 \
                and acct_type not in (
                    'mortgage', 'heloc'
                ):
            # Fannie: can exclude if
            # ≤10 months remaining
            # AND excluding doesn't
            # significantly affect DTI
            included = False
            exclusion_reason = (
                f'{months_rem} months remaining '
                f'— excludable per Fannie B3-6-05'
            )
            computed_payment = 0
            flags.append('near_payoff_excludable')

        # ── RULE 5: Medical collection ─────────
        if is_medical and \
                acct_type == 'collection' and \
                self._medical_excluded:
            included = False
            exclusion_reason = (
                'Medical collection — '
                'excluded per Fannie/FHA/VA '
                'post-2023 guidance'
            )
            computed_payment = 0
            flags.append('medical_collection_excluded')

        return TradelineAnalysis(
            tradeline_id=tradeline.get('id', ''),
            creditor_name=creditor,
            account_type=acct_type,
            current_balance=balance,
            monthly_payment=payment,
            included_in_dti=included,
            exclusion_reason=exclusion_reason,
            computed_payment=computed_payment,
            flags=flags,
            conditions=conditions,
        )

    def analyze_all(
        self,
        tradelines: list,
        qualifying_monthly: float = 0,
        agency: str = 'fannie',
    ) -> dict:
        """
        Analyze all tradelines.
        Returns corrected obligations total.
        """
        analyses   = []
        total_oblig = 0.0
        all_flags   = []
        all_conditions = []
        excluded   = []
        disputed_derogatory = []

        for tl in tradelines:
            analysis = self.analyze_tradeline(
                tl, qualifying_monthly, agency
            )
            analyses.append(analysis)
            all_flags.extend(analysis.flags)
            all_conditions.extend(
                analysis.conditions
            )

            if analysis.included_in_dti:
                total_oblig += \
                    analysis.computed_payment
            else:
                excluded.append(analysis)

            if 'disputed_derogatory' \
                    in analysis.flags:
                disputed_derogatory.append(
                    analysis
                )

        has_disputed_block = len(
            disputed_derogatory
        ) > 0

        return {
            'analyses':         analyses,
            'total_obligations': round(
                total_oblig, 2
            ),
            'excluded_count':   len(excluded),
            'all_flags':        list(set(all_flags)),
            'all_conditions':   all_conditions,
            'has_disputed_derogatory': (
                has_disputed_block
            ),
            'disputed_accounts': [
                a.creditor_name
                for a in disputed_derogatory
            ],
        }


__all__ = ["TradelineAnalyzer", "TradelineAnalysis", "DEROGATORY_STATUSES"]
