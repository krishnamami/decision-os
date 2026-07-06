"""
Condition Engine — CN-A

Creates and manages condition instances from
resolver outputs.

Flow:
  1. Resolver generates condition dict
     {code, text, blocks, prior_to}
  2. ConditionEngine.create_condition()
     looks up template in conditions_library
     fills variables from resolver data
     writes to loan_condition_instances
  3. UW reviews, documents submitted
  4. ConditionEngine.satisfy_condition()
     marks condition approved
     links satisfying document

Idempotent: UNIQUE(app, tenant, code)
  ON CONFLICT DO NOTHING
  Conditions won't duplicate across re-runs

NB: the live table is loan_condition_instances (not loan_conditions —
that name belongs to the underwriter workbench's own conditions table).
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, List
from uuid import UUID


class ConditionEngine:

    def __init__(self, conn):
        self.conn = conn

    async def create_condition(
        self,
        application_id: str,
        tenant_id: str,
        condition_code: str,
        condition_text: str,
        category: str = 'other',
        prior_to: str = 'docs',
        blocks_closing: Optional[bool] = None,
        generated_by: str = '',
        decision_id: Optional[str] = None,
        template_vars: dict = None,
    ) -> Optional[str]:
        """
        Create a loan condition.
        Looks up template from conditions_library.
        Fills variables if template_vars provided.
        Returns condition ID or None if duplicate.
        """
        # Get template from library
        template = await self.conn.fetchrow('''
            SELECT template_text, category,
                   prior_to, sla_hours,
                   assignee, edms_document_type,
                   agency_citation, auto_satisfy
            FROM conditions_library
            WHERE code = $1
            AND is_active = true
        ''', condition_code)

        # Use template if found, else use provided
        if template:
            text = template['template_text']
            # Fill template variables
            if template_vars:
                for k, v in template_vars.items():
                    text = text.replace(
                        f'${{{k}}}', str(v)
                    )
            cat       = template['category']
            prior     = template['prior_to']
            sla       = template['sla_hours']
            assignee  = template['assignee']
            doc_type  = template['edms_document_type']
            citation  = template['agency_citation']
            auto_sat  = template['auto_satisfy']
        else:
            text     = condition_text
            cat      = category
            prior    = prior_to
            sla      = 48
            assignee = 'borrower'
            doc_type = None
            citation = None
            auto_sat = False

        # blocks_closing unspecified -> derive from the template: a condition that
        # must clear before closing (prior_to='closing') blocks closing.
        if blocks_closing is None:
            blocks_closing = (prior == 'closing')

        # Compute due date
        due_date = datetime.now(timezone.utc) + \
            timedelta(hours=sla)

        # Insert (idempotent)
        result = await self.conn.fetchval('''
            INSERT INTO loan_condition_instances (
                application_id, tenant_id,
                condition_code, category,
                condition_text, agency_citation,
                status, prior_to, sla_hours,
                due_date, assignee,
                edms_document_type,
                blocks_closing, auto_satisfy,
                generated_by, decision_id
            ) VALUES (
                $1,$2,$3,$4,$5,$6,
                'open',$7,$8,$9,$10,
                $11,$12,$13,$14,$15
            )
            ON CONFLICT (application_id,
                         tenant_id,
                         condition_code)
            DO NOTHING
            RETURNING id
        ''',
            application_id, tenant_id,
            condition_code, cat,
            text, citation,
            prior, sla, due_date,
            assignee, doc_type,
            blocks_closing, auto_sat,
            generated_by,
            UUID(decision_id)
                if decision_id else None,
        )
        return str(result) if result else None

    async def auto_generate_conditions(
        self,
        application_id: str,
        tenant_id: str,
        decision_id: str,
        outcome: str,
        boundary_rule: Optional[str] = None,
        signals: Optional[dict] = None,
        decision_uuid: Optional[str] = None,
        generated_by: str = 'auto_block',
    ) -> list:
        """When a persona BLOCKs/ESCALATEs, create the actionable condition instance.
        Maps persona + signals -> conditions_library code (persona_map), then
        create_condition() (idempotent; template-driven; blocks_closing derived from
        the template's prior_to). Returns created code(s); [] if excluded persona,
        no code, or the row already exists. `decision_uuid` links the condition to the
        decision_outputs row. Never raises -- must not fail the decision write."""
        if outcome not in ('block', 'escalate'):
            return []
        from core.conditions.persona_map import select_condition_code
        code = select_condition_code(decision_id, boundary_rule, signals)
        if not code:
            return []
        cid = await self.create_condition(
            application_id=application_id,
            tenant_id=tenant_id,
            condition_code=code,
            condition_text='',        # filled from the library template
            blocks_closing=None,      # derived from template.prior_to
            generated_by=generated_by,
            decision_id=decision_uuid,   # decision_outputs.id (UUID) or None
        )
        return [code] if cid else []

    async def create_from_resolver_output(
        self,
        application_id: str,
        tenant_id: str,
        conditions: List[dict],
        generated_by: str = '',
        decision_id: Optional[str] = None,
    ) -> dict:
        """
        Bulk create conditions from resolver output.
        conditions: list of dicts with
          {code, text, blocks, prior_to}
        Returns: created count, skipped count
        """
        created = 0
        skipped = 0

        for cond in conditions:
            code = cond.get('code', '')
            if not code:
                continue

            result = await self.create_condition(
                application_id=application_id,
                tenant_id=tenant_id,
                condition_code=code,
                condition_text=cond.get('text',''),
                blocks_closing=cond.get('blocks',False),
                prior_to=cond.get('prior_to','docs'),
                generated_by=generated_by,
                decision_id=decision_id,
            )
            if result:
                created += 1
            else:
                skipped += 1

        return {
            'created': created,
            'skipped': skipped,
            'total':   len(conditions),
        }

    async def get_open_conditions(
        self,
        application_id: str,
        tenant_id: str,
        prior_to: Optional[str] = None,
    ) -> List[dict]:
        """Get all open conditions for a loan."""
        query = '''
            SELECT lc.id, lc.condition_code,
                   lc.category, lc.condition_text,
                   lc.status, lc.prior_to,
                   lc.sla_hours, lc.due_date,
                   lc.assignee, lc.blocks_closing,
                   lc.edms_document_type,
                   lc.agency_citation,
                   lc.generated_by,
                   lc.opened_at
            FROM loan_condition_instances lc
            WHERE lc.application_id = $1
            AND lc.tenant_id = $2
            AND lc.status IN (
                'open','submitted','in_review'
            )
        '''
        params = [application_id, tenant_id]
        if prior_to:
            query += ' AND lc.prior_to = $3'
            params.append(prior_to)
        query += ' ORDER BY lc.blocks_closing DESC,'\
                 ' lc.due_date ASC'

        rows = await self.conn.fetch(
            query, *params
        )
        return [dict(r) for r in rows]

    async def satisfy_condition(
        self,
        condition_id: str,
        document_id: str,
        reviewed_by: str,
        review_notes: str = '',
    ) -> bool:
        """Mark a condition as satisfied."""
        async with self.conn.transaction():
            # Update condition status
            await self.conn.execute('''
                UPDATE loan_condition_instances
                SET status = 'approved',
                    cleared_at = NOW(),
                    satisfying_doc_id = $2,
                    updated_at = NOW()
                WHERE id = $1
            ''', UUID(condition_id), document_id)

            # Record the document
            await self.conn.execute('''
                INSERT INTO condition_documents (
                    condition_id, application_id,
                    tenant_id, document_id,
                    reviewed_by, review_notes,
                    satisfies
                )
                SELECT $1, application_id,
                       tenant_id, $2, $3, $4, true
                FROM loan_condition_instances
                WHERE id = $1
            ''',
                UUID(condition_id),
                document_id, reviewed_by,
                review_notes,
            )
        return True

    async def get_condition_summary(
        self,
        application_id: str,
        tenant_id: str,
    ) -> dict:
        """Summary of conditions for a loan."""
        rows = await self.conn.fetch('''
            SELECT status,
                   prior_to,
                   blocks_closing,
                   COUNT(*) as cnt
            FROM loan_condition_instances
            WHERE application_id = $1
            AND tenant_id = $2
            GROUP BY status, prior_to,
                     blocks_closing
            ORDER BY status
        ''', application_id, tenant_id)

        total      = 0
        open_count = 0
        blocking   = 0

        for r in rows:
            total += r['cnt']
            if r['status'] in (
                'open','submitted','in_review'
            ):
                open_count += r['cnt']
                if r['blocks_closing']:
                    blocking += r['cnt']

        return {
            'total':         total,
            'open':          open_count,
            'blocking_open': blocking,
            'cleared': total - open_count,
            'by_status':  [dict(r) for r in rows],
        }


__all__ = ["ConditionEngine"]
