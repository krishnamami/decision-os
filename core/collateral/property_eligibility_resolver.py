"""
Property Eligibility Resolver — CO-A

Determines if a property is eligible for
financing per Fannie Mae, FHA, VA guidelines.

Ineligible property types (Fannie Mae):
  - Co-ops (in most states)
  - Manufactured homes (special requirements)
  - Mixed-use with >20% commercial
  - Vacant land
  - Working farms
  - Properties with deed restrictions
    that impair marketability

FHA additional rules:
  - Minimum property standards (MPS)
  - No deferred maintenance
  - No safety hazards
  - Lead paint disclosure on pre-1978 homes

Condo warrantability (Fannie Mae B4-2):
  Must be: owner-occupied >51%
           no pending litigation
           no single entity owns >10%
           HOA financially stable
           not condo-hotel

Flood zone:
  Zone A/AE: flood insurance required
  Zone V/VE: coastal high hazard (special reqs)
  Zone X: no requirement
"""

from dataclasses import dataclass, field
from typing import List, Optional


# Property types ineligible for conventional
FANNIE_INELIGIBLE_TYPES = {
    'vacant_land':  'Fannie Mae does not finance '
                    'vacant land',
    'commercial':   'Commercial property not '
                    'eligible for residential financing',
}

# Property types requiring special treatment
FANNIE_SPECIAL_TYPES = {
    'condo':        'Condo warrantability review required',
    'coop':         'Co-op — limited Fannie eligibility',
    'manufactured': 'Manufactured home — '
                    'additional requirements apply',
    '2_unit':       'Multi-unit — rental income '
                    'documentation required',
    '3_unit':       'Multi-unit — rental income '
                    'documentation required',
    '4_unit':       'Multi-unit — rental income '
                    'documentation required',
    'mixed_use':    'Mixed-use — commercial '
                    'space must be ≤20%',
}

# Flood zone rules
FLOOD_ZONE_RULES = {
    'A':   {'insurance_required': True,
            'severity': 'moderate'},
    'AE':  {'insurance_required': True,
            'severity': 'moderate'},
    'AH':  {'insurance_required': True,
            'severity': 'moderate'},
    'AO':  {'insurance_required': True,
            'severity': 'moderate'},
    'V':   {'insurance_required': True,
            'severity': 'major',
            'note': 'Coastal high hazard'},
    'VE':  {'insurance_required': True,
            'severity': 'major',
            'note': 'Coastal high hazard'},
    'X':   {'insurance_required': False,
            'severity': 'clear'},
    'X500':{'insurance_required': False,
            'severity': 'informational'},
}


@dataclass
class PropertyEligibilityResult:
    property_type:       str
    usage_type:          str
    fannie_eligible:     bool
    fha_eligible:        bool
    va_eligible:         bool
    is_warrantable:      Optional[bool]
    in_flood_zone:       bool
    requires_flood_ins:  bool
    ineligibility_reasons: List[str] = field(
                             default_factory=list
                         )
    conditions:          List[dict] = field(
                             default_factory=list
                         )
    overall_status:      str = 'eligible'
    notes:               str = ''


class PropertyEligibilityResolver:

    def resolve(
        self,
        property_type: str,
        usage_type: str = 'primary',
        flood_zone: str = 'X',
        property_state: str = '',
        hoa_fee: float = 0,
        loan_type: str = 'conventional',
        appraised_value: float = 0,
        loan_amount: float = 0,
    ) -> PropertyEligibilityResult:
        """
        Resolve property eligibility.
        """
        fannie_eligible = True
        fha_eligible    = True
        va_eligible     = True
        is_warrantable  = True
        ineligible_reasons = []
        conditions      = []
        notes_parts     = []

        # ── Check ineligible types ─────────────
        if property_type in FANNIE_INELIGIBLE_TYPES:
            fannie_eligible = False
            fha_eligible    = False
            ineligible_reasons.append(
                FANNIE_INELIGIBLE_TYPES[property_type]
            )

        # ── Check special types ────────────────
        elif property_type in FANNIE_SPECIAL_TYPES:
            notes_parts.append(
                FANNIE_SPECIAL_TYPES[property_type]
            )
            conditions.append({
                'code': f'COLLATERAL_'
                        f'{property_type.upper()}',
                'text': FANNIE_SPECIAL_TYPES[
                    property_type
                ],
                'blocks': False,
                'prior_to': 'docs',
            })

            # Condo: needs warrantability review
            if property_type == 'condo':
                is_warrantable = None  # Unknown
                conditions.append({
                    'code': 'COLLATERAL_CONDO_REVIEW',
                    'text': (
                        'Condo project warrantability '
                        'review required. Provide: '
                        '(1) HOA cert/questionnaire, '
                        '(2) budget showing <15% '
                        'delinquencies, '
                        '(3) confirm no pending '
                        'litigation, '
                        '(4) owner-occupancy >51%.'
                    ),
                    'blocks': False,
                    'prior_to': 'docs',
                })

            # Multi-unit: rental income required
            if property_type in (
                '2_unit', '3_unit', '4_unit'
            ):
                conditions.append({
                    'code': 'COLLATERAL_MULTIUNIT_RENTS',
                    'text': (
                        'Multi-unit property: '
                        'provide current leases '
                        'or market rent appraisal '
                        'for all units.'
                    ),
                    'blocks': False,
                    'prior_to': 'docs',
                })

        # ── Investment property checks ─────────
        if usage_type == 'investment':
            # VA does not finance investment
            va_eligible = False
            notes_parts.append(
                'Investment property: '
                'VA not eligible'
            )
            # Higher down payment required
            conditions.append({
                'code': 'COLLATERAL_INVESTMENT',
                'text': (
                    'Investment property: '
                    'minimum 15% down payment '
                    'required (Fannie Mae). '
                    'Rental income may be used '
                    'with 2yr history.'
                ),
                'blocks': False,
                'prior_to': 'docs',
            })

        # ── Flood zone check ───────────────────
        in_flood_zone       = False
        requires_flood_ins  = False
        flood_rules = FLOOD_ZONE_RULES.get(
            flood_zone.upper() if flood_zone
            else 'X',
            FLOOD_ZONE_RULES['X']
        )

        if flood_rules['insurance_required']:
            in_flood_zone      = True
            requires_flood_ins = True
            conditions.append({
                'code': 'COLLATERAL_FLOOD_INSURANCE',
                'text': (
                    f'Property in flood zone '
                    f'{flood_zone}. '
                    f'Flood insurance required '
                    f'before closing. Obtain NFIP '
                    f'or private flood policy '
                    f'with coverage ≥ loan amount.'
                ),
                'blocks': False,
                'prior_to': 'closing',
            })
            if flood_rules.get('severity') \
                    == 'major':
                notes_parts.append(
                    f'Coastal high hazard zone '
                    f'{flood_zone} — additional '
                    f'review required'
                )

        # ── HOA fee check ──────────────────────
        if hoa_fee > 0:
            notes_parts.append(
                f'HOA fee: ${hoa_fee:,.0f}/mo '
                f'included in DTI'
            )

        # ── Overall status ─────────────────────
        if not fannie_eligible and \
                not fha_eligible:
            overall = 'ineligible'
        elif ineligible_reasons \
                or conditions:
            overall = 'eligible_with_conditions'
        else:
            overall = 'eligible'

        return PropertyEligibilityResult(
            property_type=property_type,
            usage_type=usage_type,
            fannie_eligible=fannie_eligible,
            fha_eligible=fha_eligible,
            va_eligible=va_eligible,
            is_warrantable=is_warrantable,
            in_flood_zone=in_flood_zone,
            requires_flood_ins=requires_flood_ins,
            ineligibility_reasons=ineligible_reasons,
            conditions=conditions,
            overall_status=overall,
            notes='\n'.join(notes_parts),
        )


__all__ = [
    "PropertyEligibilityResolver",
    "PropertyEligibilityResult",
    "FANNIE_INELIGIBLE_TYPES",
    "FANNIE_SPECIAL_TYPES",
    "FLOOD_ZONE_RULES",
]
