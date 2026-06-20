"""
Credit Findings Resolver — CR-C

Applies agency waiting period rules to each
derogatory credit finding.

For each finding determines:
  1. Which agencies are affected
  2. Waiting period per agency
  3. Is borrower currently eligible?
  4. When will they be eligible?
  5. What conditions/LOE required?

Agency waiting periods (Fannie Mae Selling Guide
+ FHA 4000.1 + VA Lenders Handbook):

  BANKRUPTCY Ch7:
    Fannie: 4yr from discharge
    FHA:    2yr from discharge
    VA:     2yr from discharge
    With extenuating: Fannie 2yr, FHA 1yr

  BANKRUPTCY Ch13:
    Fannie: 2yr from discharge OR
            4yr from dismissal
    FHA:    1yr satisfactory payments
    VA:     1yr satisfactory payments

  FORECLOSURE:
    Fannie: 7yr from completion
    FHA:    3yr from completion
    VA:     2yr from completion
    With extenuating: Fannie 3yr

  SHORT SALE / DEED IN LIEU:
    Fannie: 4yr from completion
    FHA:    3yr from completion
    VA:     2yr from completion

  COLLECTION (non-medical):
    Fannie: no waiting period
            (pay off or LOE if >$250)
    FHA:    no waiting period
            (pay off if >$2,000 cumulative)
    VA:     no waiting period

  COLLECTION (medical):
    Fannie: ignore (post-2023 guidance)
    FHA:    ignore
    VA:     ignore

  CHARGE-OFF:
    Fannie: no waiting period
            (LOE required)
    FHA:    no waiting period
            (pay off or LOE)
    VA:     no waiting period

  MORTGAGE LATE (30-day in last 12mo):
    Fannie/Freddie: hard block on most products
    FHA: acceptable with LOE
    VA:  acceptable with LOE
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional


WAITING_PERIODS = {

    'bankruptcy_ch7': {
        'fannie': {'years': 4, 'from': 'discharge'},
        'fha':    {'years': 2, 'from': 'discharge'},
        'va':     {'years': 2, 'from': 'discharge'},
        'extenuating': {
            'fannie': {'years': 2},
            'fha':    {'years': 1},
        },
        'loe_required':    True,
        'blocks_if_active': True,
        'severity':        'fatal',
        'condition_code':  'CREDIT_LOE_BANKRUPTCY',
    },

    'bankruptcy_ch13': {
        'fannie': {'years': 2, 'from': 'discharge'},
        'fha':    {'years': 1, 'from': 'filing',
                   'note': 'satisfactory payments'},
        'va':     {'years': 1, 'from': 'filing',
                   'note': 'satisfactory payments'},
        'loe_required':    True,
        'blocks_if_active': True,
        'severity':        'major',
        'condition_code':  'CREDIT_LOE_BANKRUPTCY',
    },

    'foreclosure': {
        'fannie': {'years': 7, 'from': 'completion'},
        'fha':    {'years': 3, 'from': 'completion'},
        'va':     {'years': 2, 'from': 'completion'},
        'extenuating': {
            'fannie': {'years': 3},
        },
        'loe_required':    True,
        'blocks_if_active': True,
        'severity':        'fatal',
        'condition_code':  'CREDIT_LOE_FORECLOSURE',
    },

    'short_sale': {
        'fannie': {'years': 4, 'from': 'completion'},
        'fha':    {'years': 3, 'from': 'completion'},
        'va':     {'years': 2, 'from': 'completion'},
        'loe_required':    True,
        'blocks_if_active': False,
        'severity':        'major',
        'condition_code':  'CREDIT_LOE_SHORT_SALE',
    },

    'deed_in_lieu': {
        'fannie': {'years': 4, 'from': 'completion'},
        'fha':    {'years': 3, 'from': 'completion'},
        'va':     {'years': 2, 'from': 'completion'},
        'loe_required':    True,
        'blocks_if_active': False,
        'severity':        'major',
        'condition_code':  'CREDIT_LOE_DEED_IN_LIEU',
    },

    'collection_non_medical': {
        'fannie': {'years': 0,
                   'note': 'LOE if >$250'},
        'fha':    {'years': 0,
                   'note': 'pay if >$2K cumulative'},
        'va':     {'years': 0},
        'loe_required':    True,
        'blocks_if_active': False,
        'severity':        'moderate',
        'condition_code':  'CREDIT_LOE_COLLECTION',
    },

    'collection_medical': {
        'fannie': {'years': 0,
                   'note': 'ignore (post-2023)'},
        'fha':    {'years': 0,
                   'note': 'ignore'},
        'va':     {'years': 0,
                   'note': 'ignore'},
        'loe_required':    False,
        'blocks_if_active': False,
        'severity':        'informational',
        'condition_code':  None,
    },

    'charge_off': {
        'fannie': {'years': 0, 'note': 'LOE required'},
        'fha':    {'years': 0,
                   'note': 'pay off or LOE'},
        'va':     {'years': 0},
        'loe_required':    True,
        'blocks_if_active': False,
        'severity':        'moderate',
        'condition_code':  'CREDIT_LOE_CHARGE_OFF',
    },

    'mortgage_late_12mo': {
        'fannie': {'years': 0,
                   'note': 'hard block most products'},
        'fha':    {'years': 0, 'note': 'LOE required'},
        'va':     {'years': 0, 'note': 'LOE required'},
        'loe_required':    True,
        'blocks_if_active': True,
        'fannie_hard_block': True,
        'severity':        'major',
        'condition_code':  'CREDIT_LOE_MORTGAGE_LATE',
    },

    'mortgage_late_24mo': {
        'fannie': {'years': 0, 'note': 'LOE required'},
        'fha':    {'years': 0, 'note': 'LOE required'},
        'va':     {'years': 0, 'note': 'LOE required'},
        'loe_required':    True,
        'blocks_if_active': False,
        'severity':        'minor',
        'condition_code':  'CREDIT_LOE_MORTGAGE_LATE',
    },

    'judgment': {
        'fannie': {'years': 7, 'from': 'filed'},
        'fha':    {'years': 3, 'from': 'filed'},
        'va':     {'years': 2, 'from': 'filed'},
        'loe_required':    True,
        'blocks_if_active': True,
        'severity':        'major',
        'condition_code':  'CREDIT_LOE_JUDGMENT',
    },

    'thin_file': {
        'fannie': {'years': 0,
                   'note': 'nontraditional credit'},
        'fha':    {'years': 0,
                   'note': 'nontraditional credit'},
        'va':     {'years': 0,
                   'note': 'nontraditional credit'},
        'loe_required':    False,
        'blocks_if_active': False,
        'severity':        'minor',
        'condition_code':  'CREDIT_NONTRADITIONAL',
    },

    'disputed_account': {
        'fannie': {'years': 0,
                   'note': 'remove dispute before closing'},
        'fha':    {'years': 0,
                   'note': 'remove dispute before closing'},
        'va':     {'years': 0},
        'loe_required':    False,
        'blocks_if_active': True,
        'severity':        'moderate',
        'condition_code':  'CREDIT_DISPUTED_ACCOUNT',
    },
}


def _add_years(ref_date: date, years: int) -> date:
    """Add whole years to a date, clamping Feb-29 to Feb-28 in non-leap
    target years so a leap-day reference date never raises ValueError."""
    try:
        return date(ref_date.year + int(years),
                    ref_date.month, ref_date.day)
    except ValueError:
        # Only Feb 29 -> non-leap year reaches here.
        return date(ref_date.year + int(years), ref_date.month, 28)


@dataclass
class FindingResolution:
    finding_type:      str
    severity:          str
    event_date:        Optional[date]
    discharge_date:    Optional[date]
    amount:            float
    fannie_eligible:   bool
    fha_eligible:      bool
    va_eligible:       bool
    fannie_eligible_date: Optional[date]
    fha_eligible_date:    Optional[date]
    va_eligible_date:     Optional[date]
    blocks_approval:   bool
    requires_loe:      bool
    condition_code:    Optional[str]
    notes:             str
    fannie_hard_block: bool = False


class CreditFindingsResolver:

    def resolve_finding(
        self,
        finding_type: str,
        event_date: Optional[date] = None,
        discharge_date: Optional[date] = None,
        amount: float = 0,
        loan_type: str = 'conventional',
    ) -> FindingResolution:
        """
        Resolve a single credit finding.
        Determines eligibility per agency.
        """
        rules = WAITING_PERIODS.get(
            finding_type, {}
        )
        today = date.today()

        def calc_eligible(
            agency_rules: dict,
            ref_date: Optional[date],
        ):
            years = agency_rules.get('years', 0)
            if years == 0:
                return True, None
            if not ref_date:
                return False, None
            eligible_date = _add_years(ref_date, years)
            return today >= eligible_date, \
                   eligible_date

        # Use discharge_date if available
        # else event_date
        ref_date = discharge_date or event_date

        fannie_elig, fannie_date = calc_eligible(
            rules.get('fannie', {}), ref_date
        )
        fha_elig, fha_date = calc_eligible(
            rules.get('fha', {}), ref_date
        )
        va_elig, va_date = calc_eligible(
            rules.get('va', {}), ref_date
        )

        blocks = (
            rules.get('blocks_if_active', False)
            and not fannie_elig
        )

        fannie_hard = rules.get(
            'fannie_hard_block', False
        )
        if fannie_hard and \
                loan_type == 'conventional':
            blocks = True

        notes_parts = []
        if not fannie_elig and fannie_date:
            notes_parts.append(
                f'Fannie eligible: {fannie_date}'
            )
        if not fha_elig and fha_date:
            notes_parts.append(
                f'FHA eligible: {fha_date}'
            )
        if rules.get('fannie', {}).get('note'):
            notes_parts.append(
                f'Fannie note: '
                f'{rules["fannie"]["note"]}'
            )

        return FindingResolution(
            finding_type=finding_type,
            severity=rules.get(
                'severity', 'moderate'
            ),
            event_date=event_date,
            discharge_date=discharge_date,
            amount=amount,
            fannie_eligible=fannie_elig,
            fha_eligible=fha_elig,
            va_eligible=va_elig,
            fannie_eligible_date=fannie_date,
            fha_eligible_date=fha_date,
            va_eligible_date=va_date,
            blocks_approval=blocks,
            requires_loe=rules.get(
                'loe_required', True
            ),
            condition_code=rules.get(
                'condition_code'
            ),
            notes='\n'.join(notes_parts),
            fannie_hard_block=fannie_hard,
        )

    def resolve_all(
        self,
        findings: list,
        loan_type: str = 'conventional',
    ) -> dict:
        """
        Resolve all credit findings.
        Returns summary with eligibility per agency.
        """
        resolutions = []
        blocks_fannie = False
        blocks_fha    = False
        blocks_va     = False
        conditions    = []

        for f in findings:
            res = self.resolve_finding(
                f.get('finding_type', ''),
                f.get('event_date'),
                f.get('discharge_date'),
                float(f.get('amount') or 0),
                loan_type,
            )
            resolutions.append(res)

            if not res.fannie_eligible:
                blocks_fannie = True
            if not res.fha_eligible:
                blocks_fha = True
            if not res.va_eligible:
                blocks_va = True

            if res.condition_code:
                conditions.append({
                    'code':     res.condition_code,
                    'type':     res.finding_type,
                    'severity': res.severity,
                    'blocks':   res.blocks_approval,
                    'loe':      res.requires_loe,
                })

        overall = 'clear'
        if blocks_fannie and \
                loan_type == 'conventional':
            overall = 'block'
        elif any(r.blocks_approval
                 for r in resolutions):
            overall = 'block'
        elif resolutions:
            overall = 'conditions'

        return {
            'resolutions':    resolutions,
            'overall_status': overall,
            'fannie_eligible': not blocks_fannie,
            'fha_eligible':    not blocks_fha,
            'va_eligible':     not blocks_va,
            'conditions':      conditions,
            'finding_count':   len(resolutions),
            'blocking_count': sum(
                1 for r in resolutions
                if r.blocks_approval
            ),
        }


__all__ = ["CreditFindingsResolver", "FindingResolution", "WAITING_PERIODS"]
