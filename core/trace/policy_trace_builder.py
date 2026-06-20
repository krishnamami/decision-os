"""
Policy Trace Builder — TR-B

Populates the policy_trace JSONB in decision_trace (left empty by TR-A).

Captures:
  1. Agency guidelines evaluated (agency_guidelines)
  2. Tenant overlay rules applied (overlay_rules)
  3. Platform guardrails (platform_guardrails)
  4. Per-loan threshold evaluations (dti / ltv / credit_score), evaluated
     against the EFFECTIVE limit — the stricter of agency baseline and tenant
     overlay — so the trace shows what actually governed the loan.
  5. Policy version

Schema notes (the live tables differ from the TR-B spec draft):
  overlay_rules:        rule_type / loan_type / overlay_value / direction
                        (no rule_name / rule_value / is_overlay / effective_date)
  platform_guardrails:  product_type / parameter / agency_floor / platform_ceiling
                        (no guardrail_name / min_value / max_value)
  entity_states:        loan_type lives in loan_terms.urla (no column)
"""

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any


# Fannie baseline floors/caps used when no agency_guidelines match is found.
AGENCY_DTI_MAX = 50.0     # DU max DTI
AGENCY_LTV_MAX = 97.0     # primary 1-unit max LTV
AGENCY_CREDIT_FLOOR = 620.0


def _num(v: Any):
    if isinstance(v, Decimal):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _jsonb(v: Any):
    if isinstance(v, (dict, list)) or v is None:
        return v
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (ValueError, TypeError):
            return v
    return v


class PolicyTraceBuilder:

    def __init__(self, conn):
        self.conn = conn

    async def build_policy_trace(
        self,
        application_id: str,
        tenant_id: str,
        loan_type: str = 'conventional',
    ) -> dict:

        agency_rows = await self.conn.fetch('''
            SELECT agency, guideline_name, guideline_value, description
            FROM agency_guidelines
            WHERE is_active = true
            ORDER BY agency, guideline_name
        ''')

        overlay_rows = await self.conn.fetch('''
            SELECT rule_type, loan_type, overlay_value, direction, is_active
            FROM overlay_rules
            WHERE tenant_id = $1 AND is_active = true
            ORDER BY rule_type
        ''', tenant_id)

        guardrail_rows = await self.conn.fetch('''
            SELECT product_type, parameter, agency_floor,
                   platform_ceiling, description
            FROM platform_guardrails
            ORDER BY product_type, parameter
        ''')

        es = await self.conn.fetchrow('''
            SELECT dti_back, ltv, mid_credit_score, loan_amount,
                   COALESCE((loan_terms->'urla'->>'loan_type'),
                            loan_terms->>'loan_type') AS loan_type
            FROM entity_states
            WHERE application_id = $1 AND tenant_id = $2
        ''', application_id, tenant_id)

        # ── Agency guidelines, grouped by agency ──────────────────────────
        agency_trace: dict[str, dict] = {}
        for r in agency_rows:
            gv = _jsonb(r['guideline_value'])
            threshold = gv.get('value') if isinstance(gv, dict) else gv
            agency_trace.setdefault(r['agency'], {})[r['guideline_name']] = {
                'threshold': threshold,
                'description': r['description'],
            }

        # ── Tenant overlays, by rule_type (this loan_type + generic) ──────
        overlay_trace: dict[str, Any] = {}
        overlays_for_loan: dict[str, float] = {}
        for r in overlay_rows:
            val = _num(r['overlay_value'])
            overlay_trace[f"{r['rule_type']}:{r['loan_type']}"] = {
                'rule_type': r['rule_type'],
                'loan_type': r['loan_type'],
                'value': val,
                'direction': r['direction'],
            }
            if r['loan_type'] in (loan_type, None, ''):
                overlays_for_loan[r['rule_type']] = val

        # ── Platform guardrails ───────────────────────────────────────────
        guardrail_trace = [{
            'product_type': r['product_type'],
            'parameter': r['parameter'],
            'agency_floor': _num(r['agency_floor']),
            'platform_ceiling': _num(r['platform_ceiling']),
            'description': r['description'],
        } for r in guardrail_rows]

        # ── Per-loan threshold evaluations (overlay-aware) ────────────────
        evaluations = []
        if es:
            dti = _num(es['dti_back']) or 0.0
            ltv = _num(es['ltv']) or 0.0
            score = int(es['mid_credit_score'] or 0)

            # DTI — max cap; stricter = lower.
            ov_dti = overlays_for_loan.get('dti_back_max')
            eff_dti = min(AGENCY_DTI_MAX, ov_dti) if ov_dti else AGENCY_DTI_MAX
            evaluations.append({
                'check': 'dti_back',
                'actual': dti,
                'agency_limit': AGENCY_DTI_MAX,
                'effective_limit': eff_dti,
                'source': (f'{tenant_id}_overlay'
                           if ov_dti and ov_dti <= AGENCY_DTI_MAX
                           else 'fannie_mae'),
                'result': 'pass' if dti <= eff_dti else 'fail',
            })

            # LTV — max cap; stricter = lower.
            ov_ltv = overlays_for_loan.get('ltv_max_purchase')
            eff_ltv = min(AGENCY_LTV_MAX, ov_ltv) if ov_ltv else AGENCY_LTV_MAX
            evaluations.append({
                'check': 'ltv',
                'actual': ltv,
                'agency_limit': AGENCY_LTV_MAX,
                'effective_limit': eff_ltv,
                'source': (f'{tenant_id}_overlay'
                           if ov_ltv and ov_ltv <= AGENCY_LTV_MAX
                           else 'fannie_mae'),
                'result': 'pass' if ltv <= eff_ltv else 'fail',
            })

            # Credit score — floor; stricter = higher.
            ov_credit = overlays_for_loan.get('credit_floor')
            eff_credit = (max(AGENCY_CREDIT_FLOOR, ov_credit)
                          if ov_credit else AGENCY_CREDIT_FLOOR)
            evaluations.append({
                'check': 'credit_score',
                'actual': score,
                'agency_limit': AGENCY_CREDIT_FLOOR,
                'effective_limit': eff_credit,
                'source': (f'{tenant_id}_overlay'
                           if ov_credit and ov_credit >= AGENCY_CREDIT_FLOOR
                           else 'fannie_mae'),
                'result': 'pass' if score >= eff_credit else 'fail',
            })

        return {
            'policy_version': '2026.01',
            'evaluated_at': datetime.now(timezone.utc).isoformat(),
            'tenant_id': tenant_id,
            'loan_type': loan_type,
            'agency_guidelines': agency_trace,
            'overlay_rules': overlay_trace,
            'platform_guardrails': guardrail_trace,
            'evaluations': evaluations,
            'passes': sum(1 for e in evaluations if e['result'] == 'pass'),
            'fails': sum(1 for e in evaluations if e['result'] == 'fail'),
        }

    async def update_trace_policy(
        self,
        application_id: str,
        tenant_id: str,
    ) -> bool:
        loan_type = await self.conn.fetchval('''
            SELECT COALESCE((loan_terms->'urla'->>'loan_type'),
                            loan_terms->>'loan_type', 'conventional')
            FROM entity_states
            WHERE application_id = $1 AND tenant_id = $2
        ''', application_id, tenant_id) or 'conventional'

        pt = await self.build_policy_trace(
            application_id, tenant_id, str(loan_type).lower()
        )

        result = await self.conn.execute('''
            UPDATE decision_trace
            SET policy_trace = $1
            WHERE application_id = $2
            AND tenant_id = $3
            AND superseded_by IS NULL
        ''', json.dumps(pt), application_id, tenant_id)
        return result != 'UPDATE 0'

    async def update_all_meridian(self) -> dict:
        rows = await self.conn.fetch('''
            SELECT DISTINCT application_id
            FROM entity_states
            WHERE tenant_id = 'meridian'
            ORDER BY application_id
        ''')
        updated = 0
        for r in rows:
            if await self.update_trace_policy(r['application_id'], 'meridian'):
                updated += 1
        return {'updated': updated, 'total': len(rows)}


__all__ = ["PolicyTraceBuilder"]
