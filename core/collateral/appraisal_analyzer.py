"""
Appraisal Gap Analyzer — CO-B

Analyzes the relationship between:
  Appraised value (what it's worth)
  Purchase price (what they're paying)
  Loan amount (what they're borrowing)

Scenarios:

1. CLEAN: Appraised >= Purchase price
   LTV = Loan / Appraised (normal)
   No action needed.

2. LOW APPRAISAL: Appraised < Purchase price
   LTV recalculates on LOWER value.
   Borrower options:
     a) Cover gap in cash
        (gap = purchase - appraised)
     b) Renegotiate purchase price
     c) Walk away (if contingency in contract)

3. APPRAISAL WAIVER (AW / PIW):
   Fannie DU may waive full appraisal.
   Use AVM value instead.
   Only for low-LTV refinances typically.

4. VALUE ABOVE PURCHASE:
   Appraised > Purchase
   LTV = Loan / Purchase (use lower)
   Instant equity — good for borrower.
   Check: Fannie uses LOWER of value or price.

Agency rule:
  Fannie Mae B4-1.1-01:
  LTV = Loan Amount / LESSER OF
    (a) Appraised value
    (b) Purchase price
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class AppraisalAnalysis:
    appraised_value:    float
    purchase_price:     float
    loan_amount:        float
    ltv_on_appraised:   float
    ltv_on_purchase:    float
    effective_ltv:      float
    has_gap:            bool
    gap_amount:         float
    gap_pct:            float
    borrower_must_cover: float
    effective_down:     float
    status:             str
    conditions:         List[dict] = field(
                            default_factory=list
                        )
    notes:              str = ''


class AppraisalAnalyzer:

    def __init__(self, rules: dict = None):
        """`rules` is the catalogue-resolved {key: value} map
        (appraisal_gap_major_pct, appraisal_gap_minor_pct), injected via the
        bundle. Falls back to rule_loader.SAFE_DEFAULTS — the single sanctioned
        fallback; no resolver-local hardcoded lending values."""
        from core.catalogue.rule_loader import SAFE_DEFAULTS
        self._rules = dict(SAFE_DEFAULTS)
        if rules:
            self._rules.update(
                {k: v for k, v in rules.items() if v is not None}
            )

    @property
    def _gap_major_pct(self) -> float:
        return float(self._rules.get('appraisal_gap_major_pct', 10))

    @property
    def _gap_minor_pct(self) -> float:
        return float(self._rules.get('appraisal_gap_minor_pct', 3))

    def analyze(
        self,
        appraised_value: float,
        purchase_price: float,
        loan_amount: float,
        current_assets: float = 0,
    ) -> AppraisalAnalysis:
        """
        Analyze appraisal vs purchase price.

        Returns gap analysis with:
          effective_ltv (on lesser of value/price)
          gap_amount (if appraised < purchase)
          borrower_must_cover (cash needed)
          conditions to generate
        """
        conditions = []
        notes_parts = []

        # Avoid divide by zero
        if appraised_value <= 0:
            return AppraisalAnalysis(
                appraised_value=0,
                purchase_price=purchase_price,
                loan_amount=loan_amount,
                ltv_on_appraised=0,
                ltv_on_purchase=0,
                effective_ltv=0,
                has_gap=False,
                gap_amount=0,
                gap_pct=0,
                borrower_must_cover=0,
                effective_down=0,
                status='no_appraisal',
                notes='No appraised value available',
            )

        # Fannie rule: use lesser of value or price
        lesser_value = min(
            appraised_value,
            purchase_price
            if purchase_price > 0
            else appraised_value
        )

        ltv_appraised = round(
            loan_amount / appraised_value * 100, 3
        ) if appraised_value > 0 else 0

        ltv_purchase = round(
            loan_amount / purchase_price * 100, 3
        ) if purchase_price > 0 else 0

        effective_ltv = round(
            loan_amount / lesser_value * 100, 3
        ) if lesser_value > 0 else 0

        effective_down = lesser_value - loan_amount

        # Check for appraisal gap
        has_gap = (
            purchase_price > 0
            and appraised_value < purchase_price
        )
        gap_amount = max(
            purchase_price - appraised_value, 0
        ) if purchase_price > 0 else 0

        gap_pct = round(
            gap_amount / purchase_price * 100, 1
        ) if purchase_price > 0 else 0

        # Borrower must cover gap in cash
        # (loan is capped at appraised value × LTV)
        borrower_must_cover = gap_amount

        # Determine status
        if appraised_value <= 0:
            status = 'no_appraisal'
        elif has_gap and gap_pct > self._gap_major_pct:
            status = 'major_gap'
        elif has_gap and gap_pct > self._gap_minor_pct:
            status = 'minor_gap'
        elif not has_gap and \
                purchase_price > 0 and \
                appraised_value > purchase_price:
            status = 'above_purchase'
        else:
            status = 'at_value'

        # Generate conditions
        if has_gap:
            notes_parts.append(
                f'Low appraisal: '
                f'${appraised_value:,.0f} vs '
                f'purchase ${purchase_price:,.0f} '
                f'(gap ${gap_amount:,.0f} = '
                f'{gap_pct:.1f}%)'
            )

            if current_assets > 0:
                can_cover = (
                    current_assets >= gap_amount
                )
                cover_note = (
                    'Borrower assets sufficient'
                    if can_cover
                    else 'Borrower assets insufficient'
                )
                notes_parts.append(cover_note)

            conditions.append({
                'code': 'COLLATERAL_APPRAISAL_GAP',
                'text': (
                    f'Low appraisal: property '
                    f'appraised at '
                    f'${appraised_value:,.0f}, '
                    f'${gap_amount:,.0f} below '
                    f'purchase price. Borrower '
                    f'options: (1) cover gap '
                    f'(${gap_amount:,.0f}) in cash, '
                    f'(2) renegotiate purchase '
                    f'price, (3) exercise '
                    f'appraisal contingency.'
                ),
                'blocks': gap_pct > self._gap_major_pct,
                'prior_to': 'docs',
            })

        elif status == 'above_purchase':
            notes_parts.append(
                f'Appraisal above purchase: '
                f'${appraised_value:,.0f} vs '
                f'${purchase_price:,.0f}. '
                f'LTV uses purchase price '
                f'(Fannie B4-1.1-01).'
            )

        # LTV check
        if effective_ltv > 97:
            conditions.append({
                'code': 'COLLATERAL_HIGH_LTV',
                'text': (
                    f'Effective LTV {effective_ltv:.1f}% '
                    f'exceeds 97% maximum. '
                    f'Additional down payment '
                    f'required.'
                ),
                'blocks': True,
                'prior_to': 'docs',
            })
        elif effective_ltv > 95:
            conditions.append({
                'code': 'COLLATERAL_LTV_REVIEW',
                'text': (
                    f'LTV {effective_ltv:.1f}% '
                    f'requires MI or special '
                    f'product (HomeReady/HomePossible).'
                ),
                'blocks': False,
                'prior_to': 'docs',
            })

        return AppraisalAnalysis(
            appraised_value=appraised_value,
            purchase_price=purchase_price,
            loan_amount=loan_amount,
            ltv_on_appraised=ltv_appraised,
            ltv_on_purchase=ltv_purchase,
            effective_ltv=effective_ltv,
            has_gap=has_gap,
            gap_amount=gap_amount,
            gap_pct=gap_pct,
            borrower_must_cover=borrower_must_cover,
            effective_down=effective_down,
            status=status,
            conditions=conditions,
            notes='\n'.join(notes_parts),
        )


__all__ = ["AppraisalAnalyzer", "AppraisalAnalysis"]
