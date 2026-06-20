"""
Decision Trace Builder — TR-A

Assembles a complete, immutable decision trace from:
  decision_outputs   (per-decision rows: outcome / reasoning / confidence /
                      context_snapshot payload — there is NO context_snapshot
                      table and NO persona_outputs column)
  entity_states      (loan snapshot)
  fact_nodes         (evidence facts)
  loan_condition_instances (conditions)
  fraud_signals      (fraud findings)

Writes to decision_trace + a first decision_audit_log entry.

The trace is the permanent record. It answers:
  What did the borrower submit?  (input_snapshot)
  What did each persona conclude? (persona_traces — one entry per decision_id)
  What evidence supported it?     (evidence_trace from fact_nodes)
  What was the final outcome?     (underwriting_decision headline)
  What conditions were generated? (conditions_snapshot)
  Who decided it?                 (decided_by + audit log)
"""

import json
from datetime import datetime, timezone
from typing import Any, Optional


# decision outcome -> regulator-facing final_outcome (decision_trace CHECK).
OUTCOME_MAP = {
    'allow':     'approve',
    'approve':   'approve',
    'recommend': 'approve_with_conditions',
    'escalate':  'escalate',
    'block':     'block',
    'refer':     'refer',
}


def _decode(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, (bytes, bytearray)):
        val = val.decode('utf-8')
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (ValueError, TypeError):
            return val
    return val


def _f(val: Any) -> Optional[float]:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


class DecisionTraceBuilder:

    def __init__(self, conn):
        self.conn = conn

    async def build_and_save(
        self,
        application_id: str,
        tenant_id: str,
        decision_id: Optional[str] = None,
    ) -> Optional[str]:
        """Build + persist the trace for an application. Returns trace_id
        (existing id if already traced for this decision generation)."""

        # Latest version of every decision row for this loan.
        decisions = await self.conn.fetch('''
            SELECT DISTINCT ON (decision_id)
                   id, decision_id, outcome, reasoning,
                   confidence, context_snapshot,
                   evidence_trace, created_at
            FROM decision_outputs
            WHERE application_id = $1
            AND tenant_id = $2
            ORDER BY decision_id, version DESC
        ''', application_id, tenant_id)

        if not decisions:
            return None

        # Persona traces, one per decision_id. Pick the headline (final)
        # decision: underwriting_decision if present, else most recent.
        persona_traces: dict[str, Any] = {}
        headline = None
        most_recent = None
        for d in decisions:
            reasoning = _decode(d['reasoning']) or {}
            persona_traces[d['decision_id']] = {
                'outcome': d['outcome'],
                'summary': (reasoning.get('summary')
                            if isinstance(reasoning, dict) else None),
                'conclusion': (reasoning.get('conclusion')
                               if isinstance(reasoning, dict) else None),
                'confidence': _f(d['confidence']) or 0.0,
                'payload': _decode(d['context_snapshot']) or {},
            }
            if d['decision_id'] == 'underwriting_decision':
                headline = d
            if most_recent is None or d['created_at'] > most_recent['created_at']:
                most_recent = d
        if headline is None:
            headline = most_recent

        headline_id = headline['id']
        headline_reasoning = _decode(headline['reasoning']) or {}

        # Idempotent: one trace per decision generation (headline row id).
        existing = await self.conn.fetchval(
            'SELECT id FROM decision_trace WHERE decision_id = $1',
            headline_id,
        )
        if existing:
            return str(existing)

        # Loan snapshot (property_type/state live in loan_terms.urla JSON).
        es = await self.conn.fetchrow('''
            SELECT loan_amount, ltv, dti_back, piti_monthly,
                   qualifying_monthly, purchase_price, appraised_value,
                   mid_credit_score,
                   COALESCE((loan_terms->'urla'->>'loan_type'),
                            loan_terms->>'loan_type') AS loan_type,
                   (loan_terms->'urla'->>'property_type') AS property_type,
                   (loan_terms->'urla'->>'property_state') AS property_state
            FROM entity_states
            WHERE application_id = $1 AND tenant_id = $2
        ''', application_id, tenant_id)

        # Evidence facts.
        facts = await self.conn.fetch('''
            SELECT fact_type, fact_value, fact_text, confidence,
                   resolution_method, conflicts_found, resolution_notes
            FROM fact_nodes
            WHERE application_id = $1 AND tenant_id = $2
            AND superseded_by IS NULL
            ORDER BY fact_type
        ''', application_id, tenant_id)
        evidence_trace = {
            f['fact_type']: {
                'value': _f(f['fact_value']),
                'text': f['fact_text'],
                'confidence': _f(f['confidence']) or 0.0,
                'method': f['resolution_method'],
                'conflicts': f['conflicts_found'],
                'notes': f['resolution_notes'],
            }
            for f in facts
        }

        # Conditions snapshot.
        conditions = await self.conn.fetch('''
            SELECT condition_code, category, status, prior_to,
                   blocks_closing, assignee
            FROM loan_condition_instances
            WHERE application_id = $1 AND tenant_id = $2
            ORDER BY blocks_closing DESC, condition_code
        ''', application_id, tenant_id)
        conditions_snapshot = [
            {
                'code': c['condition_code'],
                'category': c['category'],
                'status': c['status'],
                'prior_to': c['prior_to'],
                'blocks': c['blocks_closing'],
                'assignee': c['assignee'],
            }
            for c in conditions
        ]

        # Fraud signals.
        fraud = await self.conn.fetch('''
            SELECT signal_type, severity, auto_block, variance_pct
            FROM fraud_signals
            WHERE application_id = $1 AND tenant_id = $2
            AND resolved = false
        ''', application_id, tenant_id)
        fraud_summary = [
            {
                'type': f['signal_type'],
                'severity': f['severity'],
                'auto_block': f['auto_block'],
                'variance': _f(f['variance_pct']) or 0.0,
            }
            for f in fraud
        ]

        input_snapshot = {
            'application_id': application_id,
            'tenant_id': tenant_id,
            'snapshot_at': datetime.now(timezone.utc).isoformat(),
            'loan': {
                'loan_amount': _f(es['loan_amount']) if es else 0,
                'ltv': _f(es['ltv']) if es else 0,
                'dti': _f(es['dti_back']) if es else 0,
                'loan_type': es['loan_type'] if es else None,
                'property_type': es['property_type'] if es else None,
                'property_state': es['property_state'] if es else None,
                'purchase_price': _f(es['purchase_price']) if es else 0,
                'appraised_value': _f(es['appraised_value']) if es else 0,
            },
            'fraud_signals': fraud_summary,
        }

        final_outcome = OUTCOME_MAP.get(
            str(headline['outcome'] or 'refer').lower(), 'refer'
        )

        trace_id = await self.conn.fetchval('''
            INSERT INTO decision_trace (
                application_id, tenant_id, decision_id,
                input_snapshot, persona_traces, policy_trace, evidence_trace,
                final_outcome, outcome_reason, confidence_score,
                conditions_snapshot,
                loan_amount, ltv, dti, credit_score, loan_type, property_type,
                decided_by
            ) VALUES (
                $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18
            )
            RETURNING id
        ''',
            application_id, tenant_id, headline_id,
            json.dumps(input_snapshot),
            json.dumps(persona_traces),
            json.dumps({}),               # policy_trace -> TR-B
            json.dumps(evidence_trace),
            final_outcome,
            (headline_reasoning.get('summary')
             if isinstance(headline_reasoning, dict) else None),
            _f(headline['confidence']) or 0.0,
            json.dumps(conditions_snapshot),
            _f(es['loan_amount']) if es else None,
            _f(es['ltv']) if es else None,
            _f(es['dti_back']) if es else None,
            int(es['mid_credit_score']) if es and es['mid_credit_score'] else None,
            es['loan_type'] if es else None,
            es['property_type'] if es else None,
            'accord_engine',
        )

        if trace_id:
            await self.conn.execute('''
                INSERT INTO decision_audit_log (
                    application_id, tenant_id, trace_id,
                    action, actor, actor_role, details
                ) VALUES ($1,$2,$3,$4,$5,$6,$7)
            ''',
                application_id, tenant_id, trace_id,
                'decision_created', 'accord_engine', 'system',
                json.dumps({
                    'outcome': final_outcome,
                    'persona_count': len(persona_traces),
                    'fact_count': len(evidence_trace),
                    'condition_count': len(conditions_snapshot),
                    'fraud_signals': len(fraud_summary),
                }),
            )

        return str(trace_id) if trace_id else None

    async def build_all_meridian(self) -> dict:
        """Build traces for all 16 scenarios."""
        rows = await self.conn.fetch('''
            SELECT DISTINCT application_id
            FROM entity_states
            WHERE tenant_id = 'meridian'
            ORDER BY application_id
        ''')
        results = {}
        for r in rows:
            app_id = r['application_id']
            trace_id = await self.build_and_save(app_id, 'meridian')
            if trace_id:
                results[app_id] = trace_id
        return results


__all__ = ["DecisionTraceBuilder", "OUTCOME_MAP"]
