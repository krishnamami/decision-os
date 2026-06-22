"""
Rental Income Resolver — INC-B

Resolves rental income from Schedule E.

Fannie Mae B3-3.1-08:
  Primary method: Schedule E (tax return)
    Net rental income + depreciation add-back
    2-year average required
    Cannot use lease amount alone

  If < 2 years rental history:
    Use lower of: lease amount OR
                  appraised market rent
    Apply 25% vacancy factor

  Departure residence rules:
    Borrower moving, renting prior home
    Must have 30% equity OR
    rental income covers full PITIA

  Note: rental income from Schedule E
  is a SEPARATE income stream from W2.
  It adds to qualifying income.
  Loss from Schedule E may REDUCE income.
"""

import json
from typing import Optional


class RentalIncomeResolver:

    def __init__(self, conn):
        self.conn = conn
        # Catalogue-resolved vacancy fraction (RA-4G). Loaded async before the
        # sync _calculate_qualifying runs; never hardcoded.
        self._vacancy_frac: Optional[float] = None
        self.rule_trace: Optional[dict] = None

    async def load_rules(self, tenant_id: str) -> None:
        """Resolve rental thresholds from the catalogue. The resolver is async
        and holds a conn, so it self-loads (RA-4F-style) — no bundle injection.
        rental_vacancy_factor_pct is a PERCENT (25) → stored as a fraction."""
        from core.catalogue.rule_loader import get_rule, SAFE_DEFAULTS
        r = await get_rule(self.conn, "rental_vacancy_factor_pct", tenant_id)
        pct = r.get("applied")
        if pct is None:
            pct = SAFE_DEFAULTS.get("rental_vacancy_factor_pct", 25)
        self._vacancy_frac = float(pct) / 100.0
        self.rule_trace = {
            "rental_vacancy_factor_pct": {
                "applied": r.get("applied"),
                "governed_by": r.get("governed_by"),
                "layers": sorted((r.get("layers") or {}).keys()),
            }
        }

    async def resolve(
        self,
        application_id: str,
        tenant_id: str,
    ) -> Optional[dict]:
        """
        Resolve rental income for application.
        Returns monthly rental income to add
        to qualifying income (or loss to subtract).
        """
        if self._vacancy_frac is None:
            await self.load_rules(tenant_id)

        docs = await self._load_rental_docs(
            application_id, tenant_id
        )
        if not docs:
            return None

        rental_data = self._extract_rental_fields(docs)
        if not rental_data:
            return None

        return self._calculate_qualifying(rental_data)

    async def _load_rental_docs(
        self, application_id, tenant_id
    ) -> list:
        """Load Schedule E and related docs."""
        rows = await self.conn.fetch('''
            SELECT document_type,
                   extracted_fields,
                   confidence_score
            FROM document_index
            WHERE application_id = $1
            AND tenant_id = $2
            AND document_type IN (
                'TAX_RETURN_1040',
                'SCHEDULE_E',
                'SCHEDULE_E_CURRENT',
                'SCHEDULE_E_PRIOR',
                'RENTAL_AGREEMENT',
                'LEASE_AGREEMENT',
                'W2_CURRENT',
                'W2_PRIOR'
            )
            AND is_current = true
            ORDER BY document_type
        ''', application_id, tenant_id)

        docs = []
        for r in rows:
            fields = r['extracted_fields']
            if isinstance(fields, str):
                fields = json.loads(fields)
            docs.append({
                'document_type': r['document_type'],
                'fields':        fields,
                'confidence':    float(
                    r['confidence_score'] or 0
                ),
            })
        return docs

    @staticmethod
    def _num(fields: dict, keys: list):
        for key in keys:
            if fields.get(key) is not None:
                try:
                    return float(
                        str(fields[key])
                        .replace(',', '')
                        .replace('$', '')
                    )
                except (ValueError, TypeError):
                    continue
        return None

    def _extract_rental_fields(
        self, docs: list
    ) -> Optional[dict]:
        """Extract rental income fields from docs."""
        rental_data = {
            'lease_amount':        None,
            'rental_income_gross': None,
            'rental_expenses':     None,
            'depreciation':        None,
            'net_rental_income':   None,
            'has_schedule_e':      False,
        }

        for doc in docs:
            fields = doc['fields']
            doc_type = doc['document_type']

            if 'SCHEDULE_E' in doc_type or '1040' in doc_type:
                gross = self._num(fields, [
                    'rental_income', 'gross_rental_income',
                    'total_rental_income', 'schedule_e_income',
                ])
                if gross is not None:
                    rental_data['rental_income_gross'] = gross
                    rental_data['has_schedule_e'] = True
                exp = self._num(fields, [
                    'rental_expenses', 'total_expenses',
                    'schedule_e_expenses',
                ])
                if exp is not None:
                    rental_data['rental_expenses'] = exp
                dep = self._num(fields, [
                    'depreciation', 'depreciation_depletion',
                    'schedule_e_depreciation',
                ])
                if dep is not None:
                    rental_data['depreciation'] = dep
                net = self._num(fields, [
                    'net_rental_income', 'rental_net_income',
                    'schedule_e_net',
                ])
                if net is not None:
                    rental_data['net_rental_income'] = net

            if 'LEASE' in doc_type or 'RENTAL_AGREEMENT' in doc_type:
                lease = self._num(fields, [
                    'monthly_rent', 'lease_amount', 'rent_amount',
                ])
                if lease is not None:
                    rental_data['lease_amount'] = lease

        has_data = (
            rental_data['rental_income_gross']
            or rental_data['net_rental_income']
            or rental_data['lease_amount']
        )
        return rental_data if has_data else None

    def _calculate_qualifying(self, data: dict) -> dict:
        """
        Calculate qualifying monthly rental income.

        Fannie Mae B3-3.1-08:
          Primary: (gross - expenses + depreciation) / 12
          Fallback: lease * (1 - vacancy) / 12, vacancy from catalogue
                    (rental_vacancy_factor_pct, Fannie B3-3.1-08)
        """
        monthly_qualifying = 0.0
        method = ''
        notes = []

        if data['has_schedule_e'] and data['rental_income_gross']:
            gross = data['rental_income_gross']
            expenses = data['rental_expenses'] or 0
            depreciation = data['depreciation'] or 0

            net = gross - expenses
            qualifying_annual = net + depreciation

            if qualifying_annual < 0:
                notes.append(
                    f'Rental LOSS: ${qualifying_annual:,.0f}/yr '
                    f'reduces qualifying income'
                )
            else:
                notes.append(
                    f'Rental income: gross ${gross:,.0f} - '
                    f'expenses ${expenses:,.0f} + depreciation '
                    f'${depreciation:,.0f} = '
                    f'${qualifying_annual:,.0f}/yr'
                )

            monthly_qualifying = round(qualifying_annual / 12, 2)
            method = (
                'Schedule E: (gross - expenses + depreciation) / 12 '
                '(Fannie Mae B3-3.1-08)'
            )

        elif data['lease_amount']:
            lease = data['lease_amount']
            # Vacancy factor from the catalogue (rental_vacancy_factor_pct,
            # Fannie B3-3.1-08), loaded by load_rules before resolve calls this.
            # occupancy = 1 - vacancy. No Python-hardcoded value.
            vacancy_frac = self._vacancy_frac
            occupancy = 1.0 - vacancy_frac
            monthly_qualifying = round(lease * occupancy, 2)
            method = (
                f'Lease ${lease:,.0f}/mo x {occupancy:.0%} occupancy '
                f'({vacancy_frac:.0%} vacancy factor, Fannie Mae B3-3.1-08)'
            )
            notes.append(
                f'No Schedule E - using lease amount with {vacancy_frac:.0%} '
                'vacancy deduction. Request Schedule E for full analysis.'
            )

        return {
            'monthly_qualifying_rental': monthly_qualifying,
            'method':            method,
            'notes':             '\n'.join(notes),
            'has_schedule_e':    data['has_schedule_e'],
            'is_loss':           monthly_qualifying < 0,
            'annual_qualifying': monthly_qualifying * 12,
        }


async def add_rental_to_qualifying(
    conn,
    application_id: str,
    tenant_id: str,
) -> Optional[float]:
    """Resolve rental income and add it to entity_states
    qualifying_monthly. Returns the updated value or None."""
    resolver = RentalIncomeResolver(conn)
    result = await resolver.resolve(application_id, tenant_id)
    if not result:
        return None
    rental_monthly = result['monthly_qualifying_rental']
    if rental_monthly == 0:
        return None

    row = await conn.fetchrow('''
        SELECT qualifying_monthly FROM entity_states
        WHERE application_id = $1 AND tenant_id = $2
    ''', application_id, tenant_id)
    if not row:
        return None

    current = float(row['qualifying_monthly'] or 0)
    updated = round(current + rental_monthly, 2)
    await conn.execute('''
        UPDATE entity_states SET qualifying_monthly = $1
        WHERE application_id = $2 AND tenant_id = $3
    ''', updated, application_id, tenant_id)
    return updated


__all__ = ["RentalIncomeResolver", "add_rental_to_qualifying"]
