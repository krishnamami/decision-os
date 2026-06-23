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


# Derogatory event -> catalogue guideline_name for the BASE waiting period.
# Years are read per agency (key + '_' + agency) from agency_guidelines via
# rule_loader, injected through the bundle (RA-4B). Events not listed here have
# no agency waiting period (0) — LOE-only / structural.
EVENT_RULE_KEY = {
    'bankruptcy_ch7':  'bankruptcy_ch7_waiting_years',
    'bankruptcy_ch13': 'bankruptcy_ch13_waiting_years',
    'foreclosure':     'foreclosure_waiting_years',
    'short_sale':      'short_sale_waiting_years',
    'deed_in_lieu':    'deed_in_lieu_waiting_years',
}

# Structural metadata per event — NO catalogued waiting years (those come from
# the catalogue). Keeps per-agency notes + loe_required / blocks_if_active /
# severity / condition_code / fannie_hard_block. (extenuating reductions were
# dead data — never read by resolve_finding — and were dropped.)
# NOTE: 'judgment' is an agency waiting period (Fannie B3-5.3-07) NOT yet in the
# catalogue — its years stay here under `years` as a flagged follow-up.
WAITING_META = {
    'bankruptcy_ch7': {
        'loe_required': True, 'blocks_if_active': True,
        'severity': 'fatal', 'condition_code': 'CREDIT_LOE_BANKRUPTCY',
    },
    'bankruptcy_ch13': {
        'fha': {'note': 'satisfactory payments'},
        'va':  {'note': 'satisfactory payments'},
        'loe_required': True, 'blocks_if_active': True,
        'severity': 'major', 'condition_code': 'CREDIT_LOE_BANKRUPTCY',
    },
    'foreclosure': {
        'loe_required': True, 'blocks_if_active': True,
        'severity': 'fatal', 'condition_code': 'CREDIT_LOE_FORECLOSURE',
    },
    'short_sale': {
        'loe_required': True, 'blocks_if_active': False,
        'severity': 'major', 'condition_code': 'CREDIT_LOE_SHORT_SALE',
    },
    'deed_in_lieu': {
        'loe_required': True, 'blocks_if_active': False,
        'severity': 'major', 'condition_code': 'CREDIT_LOE_DEED_IN_LIEU',
    },
    'collection_non_medical': {
        'fannie': {'note': 'LOE if >$250'},
        'fha': {'note': 'pay if >$2K cumulative'},
        'loe_required': True, 'blocks_if_active': False,
        'severity': 'moderate', 'condition_code': 'CREDIT_LOE_COLLECTION',
    },
    'collection_medical': {
        'fannie': {'note': 'ignore (post-2023)'},
        'fha': {'note': 'ignore'}, 'va': {'note': 'ignore'},
        'loe_required': False, 'blocks_if_active': False,
        'severity': 'informational', 'condition_code': None,
    },
    'charge_off': {
        'fannie': {'note': 'LOE required'},
        'fha': {'note': 'pay off or LOE'},
        'loe_required': True, 'blocks_if_active': False,
        'severity': 'moderate', 'condition_code': 'CREDIT_LOE_CHARGE_OFF',
    },
    'mortgage_late_12mo': {
        'fannie': {'note': 'hard block most products'},
        'fha': {'note': 'LOE required'}, 'va': {'note': 'LOE required'},
        'loe_required': True, 'blocks_if_active': True,
        'fannie_hard_block': True, 'severity': 'major',
        'condition_code': 'CREDIT_LOE_MORTGAGE_LATE',
    },
    'mortgage_late_24mo': {
        'fannie': {'note': 'LOE required'}, 'fha': {'note': 'LOE required'},
        'va': {'note': 'LOE required'},
        'loe_required': True, 'blocks_if_active': False,
        'severity': 'minor', 'condition_code': 'CREDIT_LOE_MORTGAGE_LATE',
    },
    'judgment': {
        # UNCATALOGUED agency waiting period (Fannie B3-5.3-07) — TODO seed.
        'years': {'fannie': 7, 'fha': 3, 'va': 2},
        'loe_required': True, 'blocks_if_active': True,
        'severity': 'major', 'condition_code': 'CREDIT_LOE_JUDGMENT',
    },
    'thin_file': {
        'fannie': {'note': 'nontraditional credit'},
        'fha': {'note': 'nontraditional credit'},
        'va': {'note': 'nontraditional credit'},
        'loe_required': False, 'blocks_if_active': False,
        'severity': 'minor', 'condition_code': 'CREDIT_NONTRADITIONAL',
    },
    'disputed_account': {
        'fannie': {'note': 'remove dispute before closing'},
        'fha': {'note': 'remove dispute before closing'},
        'loe_required': False, 'blocks_if_active': True,
        'severity': 'moderate', 'condition_code': 'CREDIT_DISPUTED_ACCOUNT',
    },
}


async def load_credit_rules(conn, tenant_id: str) -> dict:
    """Resolve credit rules from the catalogue via rule_loader. Waiting periods
    differ per agency, so each is loaded per agency as
    '{key}_{agency}'. Single-agency rules (student loan, medical) are loaded
    once. Returns {key: {value, governed_by, layers}}. Called on the ASYNC
    snapshot path (runner) — never in the sync persona — and injected into
    CreditFindingsResolver / TradelineAnalyzer."""
    from core.catalogue.rule_loader import get_rule
    rules: dict = {}
    for agency in ('fannie', 'fha', 'va'):
        for key in EVENT_RULE_KEY.values():
            r = await get_rule(conn, key, tenant_id, agency=agency)
            rules[f'{key}_{agency}'] = {
                'value':       r.get('applied'),
                'governed_by': r.get('governed_by'),
                'layers':      r.get('layers', {}),
            }
    for key in ('student_loan_deferred_rate_pct', 'medical_collection_excluded'):
        r = await get_rule(conn, key, tenant_id, agency='fannie')
        rules[key] = {
            'value':       r.get('applied'),
            'governed_by': r.get('governed_by'),
            'layers':      r.get('layers', {}),
        }
    # RA-4J: installment-debt months-remaining DTI exclusion (Fannie B3-6-05).
    # The catalogue row is human-named (RA-SEED-C); map it to the canonical key
    # the TradelineAnalyzer reads.
    r = await get_rule(
        conn, 'Installment Debt Months Remaining Exclusion', tenant_id,
        agency='fannie',
    )
    rules['months_remaining_exclusion'] = {
        'value':       r.get('applied'),
        'governed_by': r.get('governed_by'),
        'layers':      r.get('layers', {}),
    }
    return rules


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

    def __init__(self, rules: Optional[dict] = None):
        """`rules` is the catalogue-resolved {f'{key}_{agency}': value} map of
        base waiting years (from load_credit_rules, injected via the bundle).
        Falls back to rule_loader.SAFE_DEFAULTS (the single sanctioned fallback;
        per-agency variation collapses to the conservative agency default in
        degraded mode). No resolver-local hardcoded waiting years."""
        from core.catalogue.rule_loader import SAFE_DEFAULTS
        self._defaults = SAFE_DEFAULTS
        self._rules = {}
        if rules:
            self._rules = {
                k: v.get('value') if isinstance(v, dict) else v
                for k, v in rules.items()
            }

    def _years(self, finding_type: str, agency: str) -> int:
        """Base waiting years for an event+agency: catalogue (injected) for the
        catalogued events; structural WAITING_META years for the uncatalogued
        'judgment'; 0 (no waiting period) for everything else."""
        key = EVENT_RULE_KEY.get(finding_type)
        if key:
            val = self._rules.get(f'{key}_{agency}')
            if val is None:
                val = self._rules.get(key, self._defaults.get(key, 0))
            return int(float(val or 0))
        meta_years = WAITING_META.get(finding_type, {}).get('years', {})
        return int(meta_years.get(agency, 0))

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
        rules = WAITING_META.get(
            finding_type, {}
        )
        today = date.today()

        def calc_eligible(
            agency: str,
            ref_date: Optional[date],
        ):
            years = self._years(finding_type, agency)
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
            'fannie', ref_date
        )
        fha_elig, fha_date = calc_eligible(
            'fha', ref_date
        )
        va_elig, va_date = calc_eligible(
            'va', ref_date
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


__all__ = [
    "CreditFindingsResolver", "FindingResolution",
    "EVENT_RULE_KEY", "WAITING_META",
]
