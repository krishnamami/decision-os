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


# Catalogue rule names this resolver/analyzer read through rule_loader.
COLLATERAL_RULE_KEYS = [
    'ineligible_property_types',       # Fannie B2-1.3-01 (list)
    'flood_zones_requiring_insurance', # Fannie B7-3-02 (list)
    'appraisal_gap_major_pct',         # Fannie B4-1.3-09
    'appraisal_gap_minor_pct',         # Fannie B4-1.3-09
]

# STRUCTURAL UI text for ineligible types (not the agency VALUE — the LIST of
# ineligible types comes from agency_guidelines.ineligible_property_types).
INELIGIBLE_REASONS = {
    'vacant_land':  'Fannie Mae does not finance vacant land',
    'commercial':   'Commercial property not eligible for residential financing',
    'cooperative':  'Cooperative — ineligible for conventional financing',
    'coop':         'Cooperative — ineligible for conventional financing',
}

# Property types requiring special treatment — STRUCTURAL workflow conditions
# (condo review, multi-unit rents), not an eligible/ineligible agency value.
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

# STRUCTURAL flood-zone severity (V/VE = coastal high hazard). WHICH zones
# require insurance is the agency value -> agency_guidelines
# .flood_zones_requiring_insurance.
FLOOD_ZONE_SEVERITY = {
    'V':  'major', 'VE': 'major',
    'A':  'moderate', 'AE': 'moderate',
    'AH': 'moderate', 'AO': 'moderate',
}


async def load_collateral_rules(conn, tenant_id: str, agency: str = 'fannie') -> dict:
    """Resolve collateral rules from the catalogue via rule_loader. Returns
    {'values': {key: applied}, 'trace': {key: {applied, governed_by, layers}}}.
    Called on the ASYNC snapshot path (runner) — never inside the sync persona —
    and injected into PropertyEligibilityResolver / AppraisalAnalyzer."""
    from core.catalogue.rule_loader import get_rule
    values, trace = {}, {}
    for key in COLLATERAL_RULE_KEYS:
        r = await get_rule(conn, key, tenant_id, agency=agency)
        values[key] = r.get('applied')
        trace[key] = {
            'applied':     r.get('applied'),
            'governed_by': r.get('governed_by'),
            'layers':      r.get('layers', {}),
        }
    return {'values': values, 'trace': trace}


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

    def __init__(self, rules: Optional[dict] = None):
        """`rules` is the catalogue-resolved {key: value} map (from
        load_collateral_rules, injected via the bundle). Falls back to
        rule_loader.SAFE_DEFAULTS — the single sanctioned fallback; no
        resolver-local hardcoded lending values."""
        from core.catalogue.rule_loader import SAFE_DEFAULTS
        self._rules = dict(SAFE_DEFAULTS)
        if rules:
            self._rules.update(
                {k: v for k, v in rules.items() if v is not None}
            )

    @property
    def _ineligible_types(self) -> set:
        v = self._rules.get('ineligible_property_types') or []
        return {str(t).lower() for t in v}

    @property
    def _flood_zones(self) -> set:
        v = self._rules.get('flood_zones_requiring_insurance') or []
        return {str(z).upper() for z in v}

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

        # ── Check ineligible types (catalogue) ──
        if str(property_type).lower() in self._ineligible_types:
            fannie_eligible = False
            fha_eligible    = False
            ineligible_reasons.append(
                INELIGIBLE_REASONS.get(
                    str(property_type).lower(),
                    f'{property_type} ineligible for conventional financing',
                )
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

        # ── Flood zone check (catalogue list) ──
        in_flood_zone       = False
        requires_flood_ins  = False
        zone = (flood_zone or 'X').upper()
        insurance_required = zone in self._flood_zones
        flood_rules = {
            'insurance_required': insurance_required,
            'severity': FLOOD_ZONE_SEVERITY.get(zone, 'clear'),
        }

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
    "load_collateral_rules",
    "FANNIE_SPECIAL_TYPES",
    "COLLATERAL_RULE_KEYS",
]
