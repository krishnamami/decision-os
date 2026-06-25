"""
Income Mismatch Detector — FR-B

Detects income discrepancies across documents.
Writes fraud signals to fraud_signals table.

Sources compared:
  W2 box1_wages (verified — tax document)
  URLA stated income (self-reported)
  Paystub YTD annualized (verified — employer)
  1040 AGI (verified — IRS)

Thresholds:
  >10% difference: income_mismatch (medium)
  >25% difference: income_inflation (high)
  >50% difference: income_inflation (critical)
                   → auto_block

Already detected by EV-C as evidence nodes.
FR-B: reads evidence_nodes, writes fraud_signals.
Avoids duplication — checks existing signals first.
"""

import re

from core.fraud.fraud_rules import load_fraud_rules


# Severity tiers, MOST severe first. The (signal_type, severity, auto_block)
# mapping is STRUCTURAL classifier logic and stays in Python (RA-4F); only the
# numeric variance cutoff per tier comes from the catalogue, keyed below. The
# catalogue stores the cutoff as a PERCENT (10/25/50) — converted to a fraction
# at compare time.
MISMATCH_TIERS = [
    ('income_mismatch_critical_pct', 'income_inflation', 'critical', True),
    ('income_mismatch_high_pct',     'income_inflation', 'high',     False),
    ('income_mismatch_medium_pct',   'income_mismatch',  'medium',   False),
]


class IncomeMismatchDetector:

    def __init__(self, conn, rules: dict | None = None):
        """`rules` is an optional pre-loaded load_fraud_rules() result
        ({'values','trace'}). When omitted the detector self-loads from the
        catalogue on first detect() and caches (per-app loop hits the DB once)."""
        self.conn = conn
        self._injected = rules
        self._values = None
        self.rule_trace = None

    async def _thresholds(self, tenant_id: str) -> dict:
        """Catalogue variance cutoffs as FRACTIONS, keyed by catalogue key.
        Loaded once and cached."""
        if self._values is None:
            loaded = self._injected or await load_fraud_rules(self.conn, tenant_id)
            self._values = loaded.get("values", {})
            self.rule_trace = loaded.get("trace", {})
        return self._values

    async def detect(
        self,
        application_id: str,
        tenant_id: str,
    ) -> list:
        """
        Read income evidence nodes.
        Compare sources.
        Write fraud signals if mismatch found.
        Returns list of signals written.
        """
        # Get income evidence nodes
        nodes = await self.conn.fetch('''
            SELECT field_name, raw_value,
                   numeric_value,
                   source_document_type
            FROM evidence_nodes
            WHERE application_id = $1
            AND tenant_id = $2
            AND evidence_category = 'income'
            AND node_type = 'document_field'
            ORDER BY source_document_type
        ''', application_id, tenant_id)

        # Get cross-validation findings
        cross_nodes = await self.conn.fetch('''
            SELECT field_name, raw_value,
                   numeric_value
            FROM evidence_nodes
            WHERE application_id = $1
            AND tenant_id = $2
            AND node_type IN (
                'cross_validation', 'conflict'
            )
            AND evidence_category = 'income'
        ''', application_id, tenant_id)

        signals_written = []

        # Catalogue variance cutoffs (percent -> fraction), loaded once.
        values = await self._thresholds(tenant_id)

        # Extract income values by source
        w2_income    = None
        urla_income  = None
        paystub_ytd  = None

        for node in nodes:
            fname = node['field_name']
            val   = node['numeric_value']
            if val is None:
                continue
            val = float(val)

            if 'box1_wages_w2' in fname:
                w2_income = val
            elif 'ytd_gross_paystub' in fname:
                paystub_ytd = val

        # Get URLA income from cross-validation
        # EV-C stored the variance in numeric_value
        variance_pct = 0.0
        for node in cross_nodes:
            if 'income_w2_vs_urla' in \
                    node['field_name']:
                # raw_value has the full description
                # Parse URLA value from description
                raw = node['raw_value'] or ''
                # Extract "URLA $X" from description
                match = re.search(
                    r'URLA \$([0-9,]+)',
                    raw
                )
                if match:
                    urla_income = float(
                        match.group(1).replace(',','')
                    )
                variance_pct = float(
                    node['numeric_value'] or 0
                ) * 100

        # Check existing signals to avoid dup
        existing = await self.conn.fetchval('''
            SELECT COUNT(*) FROM fraud_signals
            WHERE application_id = $1
            AND tenant_id = $2
            AND signal_type IN (
                'income_mismatch',
                'income_inflation'
            )
        ''', application_id, tenant_id)

        if existing and int(existing) > 0:
            return []  # Already detected

        # Compare W2 vs URLA
        if w2_income and urla_income \
                and w2_income > 0:
            diff = abs(
                urla_income - w2_income
            ) / w2_income

            # Find applicable threshold — tiers are most-severe first; each
            # cutoff comes from the catalogue (percent -> fraction).
            signal_type = None
            severity    = None
            auto_block  = False

            for key, stype, sev, block in MISMATCH_TIERS:
                cutoff = values.get(key)
                if cutoff is None:
                    continue
                if diff >= float(cutoff) / 100.0:
                    signal_type = stype
                    severity    = sev
                    auto_block  = block
                    break

            if signal_type:
                direction = 'overstated' \
                    if urla_income > w2_income \
                    else 'understated'

                signal_id = await self.conn.fetchval(
                    '''
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
                        $6,$7,$8,$9,$10,
                        $11,$12
                    ) RETURNING id
                    ''',
                    application_id, tenant_id,
                    signal_type, severity,
                    (
                        f'URLA stated income '
                        f'${urla_income:,.0f}/yr '
                        f'{direction} vs W2 '
                        f'${w2_income:,.0f}/yr '
                        f'by {diff:.1%}. '
                        f'{"AUTO-BLOCK: " if auto_block else ""}'
                        f'Income may be falsified.'
                    ),
                    f'${urla_income:,.0f}/yr '
                    f'(URLA stated)',
                    f'${w2_income:,.0f}/yr '
                    f'(W2 verified)',
                    round(diff * 100, 1),
                    ['W2_CURRENT', 'URLA_1003'],
                    auto_block,
                    True,
                    'FRAUD_INCOME_MISMATCH',
                )
                signals_written.append({
                    'id':          str(signal_id),
                    'signal_type': signal_type,
                    'severity':    severity,
                    'variance_pct': round(diff*100,1),
                    'auto_block':  auto_block,
                })

        return signals_written

    async def detect_transcript_mismatch(
        self,
        application_id: str,
        tenant_id: str,
    ) -> list:
        """FR-G — cross-check borrower-submitted income against the 4506-C IRS
        transcript (the authoritative IRS-reported figures). Transcript-GATED: if
        no IRS_TRANSCRIPT exists for the app this returns [] immediately and writes
        nothing — so meridian (0 transcripts) is a pure no-op and 16/16 is
        unaffected. Separate from detect() so the verified W2-vs-URLA path is
        untouched. Writes a fraud_signal on a confirmed mismatch (dedup-guarded)."""
        rows = await self.conn.fetch('''
            SELECT document_type, extracted_fields
            FROM document_index
            WHERE application_id = $1 AND tenant_id = $2 AND is_current = true
            AND document_type IN ('IRS_TRANSCRIPT', 'W2_CURRENT', 'SCHEDULE_C')
        ''', application_id, tenant_id)
        fields_by_type: dict = {}
        for r in rows:
            f = r['extracted_fields']
            if isinstance(f, str):
                f = json.loads(f) if f else {}
            fields_by_type[r['document_type']] = f or {}

        transcript = fields_by_type.get('IRS_TRANSCRIPT')
        if not transcript:
            return []  # no transcript -> nothing to cross-check (meridian path)

        qm = await self.conn.fetchval(
            "SELECT qualifying_monthly FROM entity_states "
            "WHERE application_id=$1 AND tenant_id=$2", application_id, tenant_id)

        from core.fraud.transcript_income_verifier import TranscriptIncomeVerifier
        verifier = TranscriptIncomeVerifier(rules=self._injected)
        result = verifier.run_all_checks(
            w2_fields=fields_by_type.get('W2_CURRENT') or None,
            schedule_c_fields=fields_by_type.get('SCHEDULE_C') or None,
            transcript_fields=transcript,
            qualifying_monthly=float(qm) if qm else None,
        )
        if result.get("status") != "fraud_detected":
            return []

        existing = await self.conn.fetchval('''
            SELECT COUNT(*) FROM fraud_signals
            WHERE application_id=$1 AND tenant_id=$2
            AND signal_type='transcript_income_mismatch'
        ''', application_id, tenant_id)
        if existing and int(existing) > 0:
            return []  # already detected

        worst = next((c for c in result["checks"]
                      if c.get("severity") == result["highest_severity"]), result["checks"][0])
        signal_id = await self.conn.fetchval('''
            INSERT INTO fraud_signals (
                application_id, tenant_id, signal_type, severity, description,
                detected_value, expected_value, variance_pct, source_docs,
                auto_block, requires_review, condition_code
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12) RETURNING id
        ''', application_id, tenant_id, 'transcript_income_mismatch',
            result["highest_severity"] or 'medium',
            (f"Borrower income disagrees with IRS 4506-C transcript by "
             f"{worst.get('variance_pct')}% ({worst.get('check_type')}). "
             f"{'AUTO-BLOCK: ' if result['auto_block'] else ''}IRS-reported income is authoritative."),
            f"${worst.get('submitted', 0):,.0f} (submitted)",
            f"${worst.get('irs_reported', 0):,.0f} (IRS transcript)",
            worst.get("variance_pct", 0), ['IRS_TRANSCRIPT', 'W2_CURRENT'],
            result["auto_block"], True, 'FRAUD_TRANSCRIPT_INCOME_MISMATCH')
        return [{
            "id": str(signal_id), "signal_type": "transcript_income_mismatch",
            "severity": result["highest_severity"], "auto_block": result["auto_block"],
            "variance_pct": worst.get("variance_pct"),
        }]

    async def run_all_meridian(self) -> dict:
        """Run detector across all meridian apps."""
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
            # FR-G: transcript cross-check (no-op on meridian — 0 transcripts).
            signals = list(signals or []) + await self.detect_transcript_mismatch(
                app_id, 'meridian')
            if signals:
                results[app_id] = signals
        # RA-4F: catalogue provenance for the variance cutoffs used this run.
        if self.rule_trace:
            results['_fraud_rule_trace'] = self.rule_trace
        return results


__all__ = ["IncomeMismatchDetector", "MISMATCH_TIERS"]
