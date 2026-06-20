"""
Employment & Occupancy Fraud Detector — FR-C

DETECTOR 1: Employment mismatch
  Employer name must be consistent across:
  W2, paystub, URLA, VOE
  Uses employment evidence_nodes from EV-B4.
  Inconsistency → employer_inconsistency signal.

DETECTOR 2: Occupancy risk
  Checks for investment-as-primary fraud.
  Signals from entity_states + URLA data.
  → occupancy_risk signal if flagged.

Both write to fraud_signals (idempotent).
"""

import json
import re


# Employer name stop words (ignore in matching)
EMPLOYER_STOP_WORDS = {
    'LLC', 'INC', 'CORP', 'CO', 'LTD',
    'THE', 'AND', 'OF', 'DBA', 'GROUP',
    'HOLDINGS', 'SERVICES', 'SOLUTIONS',
}


def normalize_employer(name: str) -> set:
    """Extract key words from employer name."""
    if not name:
        return set()
    words = re.sub(
        r'[^a-zA-Z0-9\s]', ' ', name.upper()
    ).split()
    return {
        w for w in words
        if len(w) > 2
        and w not in EMPLOYER_STOP_WORDS
    }


class EmploymentFraudDetector:

    def __init__(self, conn):
        self.conn = conn

    async def detect_employer_mismatch(
        self,
        application_id: str,
        tenant_id: str,
    ) -> list:
        """
        Compare employer names across
        employment evidence nodes.
        """
        # Get employer evidence nodes
        nodes = await self.conn.fetch('''
            SELECT field_name, raw_value,
                   source_document_type
            FROM evidence_nodes
            WHERE application_id = $1
            AND tenant_id = $2
            AND evidence_category = 'employment'
            AND field_name LIKE '%employer_name%'
            ORDER BY source_document_type
        ''', application_id, tenant_id)

        if len(nodes) < 2:
            return []  # Need 2+ sources to compare

        # Check existing signals
        existing = await self.conn.fetchval('''
            SELECT COUNT(*) FROM fraud_signals
            WHERE application_id = $1
            AND tenant_id = $2
            AND signal_type = 'employer_inconsistency'
        ''', application_id, tenant_id)
        if existing and int(existing) > 0:
            return []

        # Build employer dict per source
        employers = {}
        for node in nodes:
            doc_type = node['source_document_type']
            name     = node['raw_value'] or ''
            employers[doc_type] = name

        # Check for mismatch using normalized names
        normalized = {
            doc: normalize_employer(name)
            for doc, name in employers.items()
        }

        # Find common key words across all sources
        all_words = list(normalized.values())
        if not all_words:
            return []

        common = all_words[0]
        for words in all_words[1:]:
            common = common & words

        signals = []
        if not common and len(employers) >= 2:
            # No common words — mismatch
            signal_id = await self.conn.fetchval('''
                INSERT INTO fraud_signals (
                    application_id, tenant_id,
                    signal_type, severity,
                    description,
                    detected_value, expected_value,
                    source_docs,
                    auto_block, requires_review,
                    condition_code
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11
                ) RETURNING id
            ''',
                application_id, tenant_id,
                'employer_inconsistency', 'medium',
                (
                    f'Employer name inconsistency: '
                    f'{employers}. '
                    f'Names do not share key words.'
                ),
                str(list(employers.values())),
                'Consistent employer across all docs',
                list(employers.keys()),
                False, True,
                'FRAUD_EMPLOYER_MISMATCH',
            )
            signals.append({
                'signal_type': 'employer_inconsistency',
                'severity':    'medium',
                'employers':   employers,
            })

        return signals

    async def detect_occupancy_risk(
        self,
        application_id: str,
        tenant_id: str,
    ) -> list:
        """
        Detect investment-as-primary fraud.
        Reads entity_states + URLA fields.
        """
        # Check existing
        existing = await self.conn.fetchval('''
            SELECT COUNT(*) FROM fraud_signals
            WHERE application_id = $1
            AND tenant_id = $2
            AND signal_type = 'occupancy_risk'
        ''', application_id, tenant_id)
        if existing and int(existing) > 0:
            return []

        # Get loan and property data
        row = await self.conn.fetchrow('''
            SELECT
                es.loan_terms->'urla'
                    ->>'property_usage_type'
                        AS usage_type,
                es.loan_terms->'urla'
                    ->>'property_state'
                        AS prop_state,
                es.loan_terms->'urla'
                    ->>'loan_purpose'
                        AS loan_purpose,
                es.borrower->'identity'
                    ->>'fraud_score' AS fraud_score
            FROM entity_states es
            WHERE es.application_id = $1
            AND es.tenant_id = $2
        ''', application_id, tenant_id)

        if not row:
            return []

        # Get URLA occupancy fields
        urla_row = await self.conn.fetchrow('''
            SELECT extracted_fields
            FROM document_index
            WHERE application_id = $1
            AND tenant_id = $2
            AND document_type = 'URLA_1003'
            AND is_current = true
            LIMIT 1
        ''', application_id, tenant_id)

        signals  = []
        risk_factors = []

        if urla_row:
            fields = urla_row['extracted_fields']
            if isinstance(fields, str):
                fields = json.loads(fields)

            # Check occupancy type
            occupancy = fields.get(
                'occupancy_type', ''
            ) or fields.get(
                'property_usage', ''
            ) or ''

            stated_primary = (
                'primary' in occupancy.lower()
                if occupancy else True
            )

            # Check for investment indicators
            prop_state  = row['prop_state'] or ''
            loan_purpose = row['loan_purpose'] or ''

            # High-risk vacation/resort states
            vacation_states = {
                'HI', 'FL', 'NV', 'AZ', 'CO'
            }
            is_vacation_market = (
                prop_state.upper()
                in vacation_states
            )

            # Rental income claimed on purchase
            # = investor not primary
            rental_income = fields.get(
                'rental_income', 0
            ) or 0
            has_rental_income = (
                float(rental_income) > 0
            )

            if is_vacation_market \
                    and stated_primary:
                risk_factors.append(
                    f'Property in {prop_state} '
                    f'(vacation/resort market) '
                    f'stated as primary residence'
                )

            if has_rental_income \
                    and loan_purpose == 'purchase' \
                    and stated_primary:
                risk_factors.append(
                    f'Rental income claimed on '
                    f'purchase stated as primary '
                    f'(indicates investment intent)'
                )

        if risk_factors:
            await self.conn.execute('''
                INSERT INTO fraud_signals (
                    application_id, tenant_id,
                    signal_type, severity,
                    description,
                    source_docs,
                    auto_block, requires_review,
                    condition_code
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9
                )
            ''',
                application_id, tenant_id,
                'occupancy_risk', 'medium',
                'Occupancy risk indicators: '
                + '; '.join(risk_factors),
                ['URLA_1003'],
                False, True,
                'FRAUD_OCCUPANCY_RISK',
            )
            signals.append({
                'signal_type':  'occupancy_risk',
                'severity':     'medium',
                'risk_factors': risk_factors,
            })

        return signals

    async def run_all_meridian(self) -> dict:
        """Run both detectors across all apps."""
        rows = await self.conn.fetch('''
            SELECT DISTINCT application_id
            FROM entity_states
            WHERE tenant_id = 'meridian'
            ORDER BY application_id
        ''')
        results = {}
        for r in rows:
            app_id = r['application_id']
            signals = []
            signals += await \
                self.detect_employer_mismatch(
                    app_id, 'meridian'
                )
            signals += await \
                self.detect_occupancy_risk(
                    app_id, 'meridian'
                )
            if signals:
                results[app_id] = signals
        return results


__all__ = [
    "EmploymentFraudDetector",
    "normalize_employer",
    "EMPLOYER_STOP_WORDS",
]
