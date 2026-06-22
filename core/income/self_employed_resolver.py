"""
Self-Employed Income Resolver — INC-A

Fannie Mae B3-3.4-01 / B3-3.4-02:
  Sole proprietor (Schedule C):
    Net profit + depreciation + depletion
    + business use of home (add back)
    + mileage (add back non-business portion)
    = adjusted income
    / 24 months = qualifying monthly

  S-Corp / Partnership (Schedule K-1):
    Ordinary income + W2 wages from entity
    + depreciation + depletion / 24

  2-year requirement:
    Must show 2 years SE history; if < 2 years,
    ineligible unless same line of work as prior W2.

  Declining income:
    If year 2 < year 1: use year 2 only (don't average).
"""

import json
from typing import Optional


class SelfEmployedResolver:

    def __init__(self, conn):
        self.conn = conn
        # Catalogue-resolved SE rules (RA-4G). Loaded async before the sync
        # _calculate_qualifying runs; never hardcoded.
        self._depreciation_addback: Optional[bool] = None
        self._use_lower_year: Optional[bool] = None
        self._years_required: Optional[float] = None
        self.rule_trace: Optional[dict] = None

    async def load_rules(self, tenant_id: str) -> None:
        """Resolve SE income rules from the catalogue (Fannie B3-3.4-01/02).
        Async self-load (resolver holds a conn) — no bundle injection."""
        from core.catalogue.rule_loader import get_rule, SAFE_DEFAULTS
        trace = {}
        for key, attr, default in (
            ("se_depreciation_addback", "_depreciation_addback", True),
            ("se_declining_use_lower_year", "_use_lower_year", True),
            ("se_income_years_required", "_years_required", 2),
        ):
            r = await get_rule(self.conn, key, tenant_id)
            val = r.get("applied")
            if val is None:
                val = SAFE_DEFAULTS.get(key, default)
            setattr(self, attr, val)
            trace[key] = {
                "applied": r.get("applied"),
                "governed_by": r.get("governed_by"),
                "layers": sorted((r.get("layers") or {}).keys()),
            }
        self.rule_trace = trace

    async def resolve(
        self,
        application_id: str,
        tenant_id: str,
    ) -> Optional[dict]:
        """Resolve SE income from Schedule C / K-1."""
        if self._depreciation_addback is None:
            await self.load_rules(tenant_id)
        docs = await self._load_se_docs(application_id, tenant_id)
        if not docs:
            return None
        data = self._extract_se_fields(docs)
        if not data:
            return None
        return self._calculate_qualifying(data)

    async def _load_se_docs(self, application_id, tenant_id) -> list:
        rows = await self.conn.fetch('''
            SELECT document_type, extracted_fields, confidence_score
            FROM document_index
            WHERE application_id = $1
            AND tenant_id = $2
            AND document_type IN (
                'SCHEDULE_C', 'SCHEDULE_C_CURRENT', 'SCHEDULE_C_PRIOR',
                'TAX_RETURN_1040', 'SCHEDULE_K1', 'BUSINESS_TAX_RETURN',
                'PROFIT_LOSS_STATEMENT'
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
                'fields': fields,
                'confidence': float(r['confidence_score'] or 0),
            })
        return docs

    @staticmethod
    def _num(fields: dict, keys: list):
        for key in keys:
            if fields.get(key) is not None:
                try:
                    return float(
                        str(fields[key]).replace(',', '').replace('$', '')
                    )
                except (ValueError, TypeError):
                    continue
        return None

    def _extract_se_fields(self, docs: list) -> Optional[dict]:
        data = {
            'net_profit_current': None,
            'net_profit_prior': None,
            'depreciation_current': None,
            'depreciation_prior': None,
            'mileage_addback': None,
            'home_office_addback': None,
            'has_schedule_c': False,
            'business_type': 'sole_proprietor',
        }

        for doc in docs:
            fields = doc['fields']
            doc_type = doc['document_type']
            is_prior = 'PRIOR' in doc_type

            if 'SCHEDULE_C' in doc_type or '1040' in doc_type:
                profit_key = (
                    'net_profit_prior' if is_prior else 'net_profit_current'
                )
                depr_key = (
                    'depreciation_prior' if is_prior
                    else 'depreciation_current'
                )
                profit = self._num(fields, [
                    'net_profit', 'schedule_c_net',
                    'business_net_income', 'net_income',
                ])
                if profit is not None:
                    data[profit_key] = profit
                    data['has_schedule_c'] = True
                depr = self._num(fields, [
                    'depreciation', 'schedule_c_depreciation', 'depletion',
                ])
                if depr is not None:
                    data[depr_key] = depr

        return data if data['has_schedule_c'] else None

    def _calculate_qualifying(self, data: dict) -> dict:
        """N-year average unless declining; depreciation add-back and the
        declining→use-lower-year rule both come from the catalogue (RA-4G)."""
        # Catalogue-resolved flags, set by load_rules before resolve calls this
        # (no Python-hardcoded lending values).
        addback = self._depreciation_addback
        use_lower = self._use_lower_year
        years_required = int(self._years_required)

        current = data['net_profit_current'] or 0
        prior = data['net_profit_prior'] or 0
        depr_c = (data['depreciation_current'] or 0) if addback else 0
        depr_p = (data['depreciation_prior'] or 0) if addback else 0

        adjusted_current = current + depr_c
        adjusted_prior = prior + depr_p

        notes = []
        if adjusted_prior > 0 and adjusted_current > 0:
            if use_lower and adjusted_current < adjusted_prior:
                qualifying_annual = adjusted_current
                method = (
                    'Schedule C: current year only (declining income — '
                    'Fannie B3-3.4-01)'
                )
                notes.append(
                    f'Income declining: ${adjusted_prior:,.0f} -> '
                    f'${adjusted_current:,.0f}. Using lower year.'
                )
            else:
                qualifying_annual = (adjusted_current + adjusted_prior) / 2
                method = f'Schedule C: {years_required}-year average (Fannie B3-3.4-01)'
                notes.append(
                    f'{years_required}-year average: (${adjusted_current:,.0f} + '
                    f'${adjusted_prior:,.0f}) / 2 = ${qualifying_annual:,.0f}'
                )
        elif adjusted_current > 0:
            qualifying_annual = adjusted_current
            method = 'Schedule C: current year only (prior year unavailable)'
            notes.append(
                f'Only one year available; {years_required} years required '
                '(Fannie B3-3.4-01). Request prior-year Schedule C.'
            )
        else:
            qualifying_annual = 0
            method = 'No qualifying SE income found'

        years_available = 2 if adjusted_prior > 0 else 1
        return {
            'monthly_qualifying_se': round(qualifying_annual / 12, 2),
            'annual_qualifying': qualifying_annual,
            'method': method,
            'notes': '\n'.join(notes),
            'is_declining': (
                adjusted_current < adjusted_prior
                if adjusted_prior > 0 else False
            ),
            'years_available': years_available,
            'years_required': years_required,
            'meets_years_requirement': years_available >= years_required,
        }


__all__ = ["SelfEmployedResolver"]
