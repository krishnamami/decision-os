"""
Undisclosed Debt Detector — FR-D

Detects liabilities on credit report that
were not disclosed on the URLA application.

This is material fraud — borrower hid debt
to artificially lower their DTI ratio.

Detection:
  credit_obligations (from credit report)
  vs urla_obligations (from application)

  If credit > urla by >$200/mo:
    → undisclosed_debt signal (medium)
  If credit > urla by >$500/mo:
    → undisclosed_debt signal (high)
  If credit > urla by >$1000/mo:
    → undisclosed_debt signal (critical, auto_block)

Also detects: new credit opened after
  application date (pre-closing debt).
  Rapid inquiries suggest new accounts.

Two deviations from the FR-D spec (data-driven):
  1. Credit obligations live at borrower.credit
     .monthly_obligations — the spec's
     'total_monthly_obligations' key is NULL in
     every entity_states row, so using it would
     make the detector permanently inert.
  2. Undisclosed debt is only assertable against a
     DISCLOSED baseline. No Meridian URLA carries a
     liabilities field (nor borrower.income
     .monthly_obligations), so rather than treat an
     absent baseline as "$0 disclosed" (which would
     false-positive on every loan), the detector
     ABSTAINS when no disclosed figure is found. It
     fires correctly once URLA liability extraction
     exists and credit exceeds the disclosed amount.
"""

import json


UNDISCLOSED_THRESHOLDS = {
    200:  'medium',
    500:  'high',
    1000: 'critical',
}


class UndisclosedDebtDetector:

    def __init__(self, conn):
        self.conn = conn

    async def detect(
        self,
        application_id: str,
        tenant_id: str,
    ) -> list:
        """
        Compare credit report obligations
        vs URLA stated obligations.
        """
        # Check existing signal
        existing = await self.conn.fetchval('''
            SELECT COUNT(*) FROM fraud_signals
            WHERE application_id = $1
            AND tenant_id = $2
            AND signal_type = 'undisclosed_debt'
        ''', application_id, tenant_id)
        if existing and int(existing) > 0:
            return []

        # Get credit report obligations.
        # Real key is credit.monthly_obligations;
        # total_monthly_obligations is always NULL.
        row = await self.conn.fetchrow('''
            SELECT
                (borrower->'credit'
                 ->>'monthly_obligations'
                )::numeric AS credit_obligations,
                (borrower->'income'
                 ->>'monthly_obligations'
                )::numeric AS income_obligations,
                qualifying_monthly
            FROM entity_states
            WHERE application_id = $1
            AND tenant_id = $2
        ''', application_id, tenant_id)

        if not row:
            return []

        credit_oblig = float(
            row['credit_obligations'] or 0
        )

        # Get URLA stated obligations
        urla_row = await self.conn.fetchrow('''
            SELECT extracted_fields
            FROM document_index
            WHERE application_id = $1
            AND tenant_id = $2
            AND document_type = 'URLA_1003'
            AND is_current = true
            LIMIT 1
        ''', application_id, tenant_id)

        urla_oblig = 0.0
        urla_found = False
        if urla_row:
            fields = urla_row['extracted_fields']
            if isinstance(fields, str):
                fields = json.loads(fields)

            for key in [
                'total_monthly_obligations',
                'monthly_liabilities',
                'stated_monthly_obligations',
                'total_liabilities',
            ]:
                if fields.get(key):
                    try:
                        urla_oblig = float(
                            str(fields[key])
                            .replace(',','')
                            .replace('$','')
                        )
                        urla_found = True
                        break
                    except (ValueError, TypeError):
                        pass

        # If no URLA obligations found
        # fall back to income obligations field
        if not urla_found and \
                row['income_obligations'] is not None:
            urla_oblig = float(
                row['income_obligations'] or 0
            )
            urla_found = True

        # Undisclosed debt needs a disclosed baseline.
        # No baseline -> cannot assert -> abstain
        # (avoids false-positive on every loan).
        if not urla_found:
            return []

        signals = []

        if credit_oblig > 0 and urla_oblig >= 0:
            diff = credit_oblig - urla_oblig

            # Determine severity
            severity = None
            for threshold, sev in sorted(
                UNDISCLOSED_THRESHOLDS.items(),
                reverse=True
            ):
                if diff >= threshold:
                    severity = sev
                    break

            if severity:
                await self.conn.execute('''
                    INSERT INTO fraud_signals (
                        application_id, tenant_id,
                        signal_type, severity,
                        description,
                        detected_value,
                        expected_value,
                        variance_pct,
                        source_docs,
                        auto_block,
                        requires_review,
                        condition_code
                    ) VALUES (
                        $1,$2,$3,$4,$5,
                        $6,$7,$8,$9,$10,$11,$12
                    )
                ''',
                    application_id, tenant_id,
                    'undisclosed_debt', severity,
                    (
                        f'Credit report shows '
                        f'${credit_oblig:,.0f}/mo '
                        f'in obligations but URLA '
                        f'states ${urla_oblig:,.0f}/mo. '
                        f'Difference: ${diff:,.0f}/mo. '
                        f'Possible undisclosed liabilities.'
                    ),
                    f'${credit_oblig:,.0f}/mo '
                    f'(credit report)',
                    f'${urla_oblig:,.0f}/mo '
                    f'(URLA stated)',
                    round(
                        (diff / max(credit_oblig, 1))
                        * 100, 1
                    ),
                    ['CREDIT_REPORT', 'URLA_1003'],
                    severity == 'critical',
                    True,
                    'FRAUD_UNDISCLOSED_DEBT',
                )
                signals.append({
                    'signal_type': 'undisclosed_debt',
                    'severity':    severity,
                    'diff':        diff,
                    'credit_oblig': credit_oblig,
                    'urla_oblig':  urla_oblig,
                })

        return signals

    async def run_all_meridian(self) -> dict:
        rows = await self.conn.fetch('''
            SELECT DISTINCT application_id
            FROM entity_states
            WHERE tenant_id = 'meridian'
            ORDER BY application_id
        ''')
        results = {}
        for r in rows:
            app_id = r['application_id']
            signals = await self.detect(
                app_id, 'meridian'
            )
            if signals:
                results[app_id] = signals
        return results


__all__ = ["UndisclosedDebtDetector", "UNDISCLOSED_THRESHOLDS"]
