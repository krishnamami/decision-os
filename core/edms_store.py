"""EDMS-backed context store.

Reads decision context from EDMS's persona views (one view per decision)
plus the global ``decision_outputs`` table for upstream dependencies.

This is a sibling to ``core.context_store.LendingContextStore`` — the
local-first one composes Redis + Postgres. EDMS replaces that with a
single Postgres connection pool against the EDMS schema:

  vw_<decision>_context  → bundle.objects
  decision_outputs       → bundle.upstream_outputs

The cron runner consumes ``EdmsSnapshot`` directly to build a
ContextBundle for ``persona._compute_offline``. ContextBuilder's
projection / read-perm filtering is intentionally bypassed — the EDMS
views are already the authoritative per-decision projection (one view
per decision_id).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────
# Snapshot shape — the runner reads ``.context`` + ``.upstream_outputs``
# and passes them into ContextBundle.
# ─────────────────────────────────────────────────────────────────────


class EdmsSnapshot(BaseModel):
    """Frozen EDMS read for one (application_id, decision_id)."""

    id: UUID = Field(default_factory=uuid4)
    application_id: str
    decision_id: str
    snapshot_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    context: dict[str, Any] = Field(default_factory=dict)
    upstream_outputs: dict[str, Any] = Field(default_factory=dict)
    upstream_decision_ids: list[str] = Field(default_factory=list)


class EdmsContextStore:
    """Reads context from EDMS PostgreSQL views.

    One asyncpg pool per process. Pool is created on first use so
    construction is cheap and side-effect free."""

    # decision_id → (view, ObjectType, field map, id field in view)
    #
    # field_map maps view column name → bundle field name. When the two
    # match, the entry is "passthrough". When the view returns a wider
    # row (the underwriting decision rolls up multiple JSONB columns)
    # the special object_type "FULL_ROW" is used and _parse_full_row
    # explodes the columns into ObjectType buckets.
    VIEW_MAPPINGS: dict[str, dict[str, Any]] = {
        "credit_assessment": {
            "view": "vw_credit_assessment_context",
            "object_type": "CreditProfile",
            "field_map": {
                "credit_score": "credit_score",
                "credit_band": "credit_band",
                "equifax_score": "equifax_score",
                "experian_score": "experian_score",
                "transunion_score": "transunion_score",
                "active_bankruptcy": "active_bankruptcy",
                "foreclosure_last_36_months": "foreclosure_last_36_months",
                "thin_file": "thin_file",
                "no_derogatory_last_24_months": "no_derogatory_last_24_months",
                "derogatory_marks": "derogatory_marks",
                "open_tradelines": "open_tradelines",
                "credit_utilization": "credit_utilization",
                "monthly_obligations": "monthly_obligations",
                "governing_credit_score": "governing_credit_score",
            },
            "id_field": "applicant_id",
        },
        "fraud_screening": {
            "view": "vw_fraud_screening_context",
            "object_type": "FraudProfile",
            "field_map": {
                "fraud_score": "fraud_score",
                "identity_match_confidence": "identity_match_confidence",
                "document_authenticity_score": "document_authenticity_score",
                "watchlist_match": "watchlist_match",
                "synthetic_identity_flag": "synthetic_identity_flag",
            },
            "id_field": "applicant_id",
        },
        "compliance_check": {
            "view": "vw_compliance_check_context",
            "object_type": "ComplianceRecord",
            "field_map": {
                "all_hmda_fields_complete": "all_hmda_fields_complete",
                "no_fair_lending_flags": "no_fair_lending_flags",
                "state_rules_passed": "state_rules_passed",
                "fair_lending_violation": "fair_lending_violation",
                "missing_required_disclosures": "missing_required_disclosures",
                "regulatory_ambiguity": "regulatory_ambiguity",
                "mixed_jurisdiction": "mixed_jurisdiction",
                "minor_data_gap": "minor_data_gap",
                # State-specific inputs for the TX cash-out LTV rule.
                "property_state": "property_state",
                "loan_purpose": "loan_purpose",
                "ltv": "ltv",
                "tx_cashout_ltv_violation": "tx_cashout_ltv_violation",
            },
            "id_field": "application_id",
        },
        "employment_reconciliation": {
            "view": "vw_employment_reconciliation_context",
            "object_type": "VerificationAttempt",
            "field_map": {
                "reconciliation_status": "reconciliation_status",
                "continuity_coverage_pct": "continuity_coverage_pct",
                "max_gap_days": "max_gap_days",
                "employer_name_match_confidence": "employer_name_match_confidence",
                "stated_vs_verified_drift_pct": "stated_vs_verified_drift_pct",
                "employer_on_watchlist": "employer_on_watchlist",
                "employer_name": "employer_name",
                "period_start": "period_start",
                "period_end": "period_end",
                "employment_status": "employment_status",
                "gross_amount": "gross_amount",
                "stated_employer": "stated_employer",
                "stated_income": "stated_income",
            },
            "id_field": "applicant_id",
        },
        "income_verification": {
            "view": "vw_income_verification_context",
            "object_type": "IncomeProfile",
            "field_map": {
                "income_confidence_score": "income_confidence_score",
                "employment_type": "employment_type",
                "payroll_verified": "payroll_verified",
                "reconciliation_status": "reconciliation_status",
                "income_discrepancy_pct": "income_discrepancy_pct",
                "stated_income": "stated_income",
                "verified_income": "verified_income",
                "multiple_income_sources": "multiple_income_sources",
                "income_stability": "income_stability",
                "income_trending": "income_trending",
                "overall_confidence": "overall_confidence",
            },
            "id_field": "applicant_id",
        },
        "dti_calculation": {
            "view": "vw_dti_calculation_context",
            "object_type": "Application",
            "field_map": {
                "dti": "dti",
                "dti_front": "dti_front",
                "existing_debt_obligations": "existing_debt_obligations",
                "proposed_payment": "proposed_payment",
                "qualifying_monthly": "qualifying_monthly",
                "combined_monthly_income": "combined_monthly_income",
                "income_confidence": "income_confidence",
                "loan_amount": "loan_amount",
                "interest_rate": "interest_rate",
            },
            "id_field": "application_id",
        },
        "ltv_assessment": {
            "view": "vw_ltv_assessment_context",
            "object_type": "Property",
            "field_map": {
                "ltv": "ltv",
                "appraised_value": "appraised_value",
                "purchase_price": "purchase_price",
                "loan_amount": "loan_amount",
                "down_payment": "down_payment",
                "appraisal_disputed": "appraisal_disputed",
                "title_status": "title_status",
                "lien_dispute": "lien_dispute",
                "credit_band": "credit_band",
            },
            "id_field": "application_id",
        },
        "product_eligibility": {
            "view": "vw_product_eligibility_context",
            "object_type": "Application",
            "field_map": {
                "dti_ratio": "dti_ratio",
                "ltv_ratio": "ltv_ratio",
                "credit_band": "credit_band",
                "credit_score": "credit_score",
                "loan_type": "loan_type",
                "loan_amount": "loan_amount",
                "loan_purpose": "loan_purpose",
                "va_entitlement_used": "va_entitlement_used",
                "va_entitlement_remaining": "va_entitlement_remaining",
            },
            "id_field": "application_id",
        },
        "rate_pricing": {
            "view": "vw_rate_pricing_context",
            "object_type": "Loan",
            "field_map": {
                "credit_score": "credit_score",
                "dti_ratio": "dti_ratio",
                "ltv_ratio": "ltv_ratio",
                "interest_rate": "interest_rate",
                "loan_type": "loan_type",
                "rate_within_normal_band": "rate_within_normal_band",
                "no_manual_adjustments_required": "no_manual_adjustments_required",
                "rate_exceeds_usury_limit": "rate_exceeds_usury_limit",
                "concurrent_rate_lock_conflict": "concurrent_rate_lock_conflict",
                "llpa_adjustment": "llpa_adjustment",
                "loan_program": "loan_program",
            },
            "id_field": "application_id",
        },
        "underwriting_decision": {
            "view": "vw_underwriting_decision_context",
            "object_type": "FULL_ROW",
            "id_field": "application_id",
        },
        "approval_routing": {
            "view": "vw_approval_routing_context",
            "object_type": "Application",
            "field_map": {
                "applicant_id": "applicant_id",
                "status": "status",
                "completeness_pct": "completeness_pct",
            },
            "id_field": "application_id",
        },
        "closing_readiness": {
            "view": "vw_closing_readiness_context",
            "object_type": "ComplianceRecord",
            "field_map": {
                "all_conditions_cleared": "all_conditions_cleared",
                "cd_timing_compliant": "cd_timing_compliant",
                "title_clear": "title_clear",
                "cd_timing_violation": "cd_timing_violation",
                "title_defect": "title_defect",
                "lien_dispute": "lien_dispute",
                "insurance_gap": "insurance_gap",
                "insurance_binder": "insurance_binder",
                "closing_disclosure_sent_at": "closing_disclosure_sent_at",
                "days_until_rate_lock_expiry": "days_until_rate_lock_expiry",
            },
            "id_field": "application_id",
        },
    }

    def __init__(self, database_url: str):
        self._database_url = database_url
        self._pool: Optional[Any] = None  # asyncpg pool, lazy

    async def _get_pool(self) -> Any:
        if self._pool is None:
            import asyncpg  # type: ignore
            # Tuned for long-running batch processing:
            #   command_timeout caps any single statement so a hung
            #     view read can't stall the runner;
            #   max_inactive_connection_lifetime cycles idle conns so
            #     they don't get killed mid-batch by the RDS idle reaper;
            #   statement_cache_size=0 sidesteps "prepared statement
            #     does not exist" errors that show up when pgbouncer or
            #     a server-side timeout invalidates a cached plan.
            self._pool = await asyncpg.create_pool(
                self._database_url,
                min_size=2,
                max_size=10,
                command_timeout=60,
                max_inactive_connection_lifetime=300,
                statement_cache_size=0,
            )
        return self._pool

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    # ── Snapshot ─────────────────────────────────────────────────────

    async def snapshot(
        self,
        application_id: str,
        decision_id: str,
        entity_keys: Optional[list[tuple[str, str]]] = None,
        upstream_decision_ids: Optional[list[str]] = None,
    ) -> EdmsSnapshot:
        """Read the persona view for this decision + upstream outputs.

        Returns an EdmsSnapshot the cron runner converts into a
        ContextBundle. ``entity_keys`` is accepted for parity with the
        LendingContextStore signature but ignored — the view already
        returns the projection."""

        pool = await self._get_pool()
        mapping = self.VIEW_MAPPINGS.get(decision_id)
        if mapping is None:
            raise ValueError(f"No EDMS view mapping for decision_id: {decision_id}")

        view = mapping["view"]
        id_field = mapping["id_field"]

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT * FROM {view} WHERE application_id = $1",
                application_id,
            )

        if row is None:
            context: dict[str, Any] = {}
        elif mapping["object_type"] == "FULL_ROW":
            context = self._parse_full_row(row)
        else:
            ot = mapping["object_type"]
            entity_id = str(row[id_field]) if row.get(id_field) is not None else application_id
            fields: dict[str, Any] = {}
            for view_col, field_name in mapping.get("field_map", {}).items():
                val = row.get(view_col)
                if val is not None:
                    fields[field_name] = _coerce(val)
            context = {ot: {entity_id: fields}}

        upstream_outputs: dict[str, Any] = {}
        if upstream_decision_ids:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT decision_id, outcome, context_snapshot, reasoning, confidence
                    FROM decision_outputs
                    WHERE application_id = $1
                      AND decision_id = ANY($2)
                      AND version = (
                        SELECT MAX(version) FROM decision_outputs d2
                        WHERE d2.application_id = decision_outputs.application_id
                          AND d2.decision_id = decision_outputs.decision_id
                      )
                    """,
                    application_id,
                    list(upstream_decision_ids),
                )
            for r in rows:
                upstream_outputs[r["decision_id"]] = {
                    "outcome": r["outcome"],
                    "payload": _decode_json(r["context_snapshot"]) or {},
                    "confidence": r["confidence"],
                }

        return EdmsSnapshot(
            application_id=application_id,
            decision_id=decision_id,
            context=context,
            upstream_outputs=upstream_outputs,
            upstream_decision_ids=list(upstream_decision_ids or []),
        )

    # ── FULL_ROW (underwriting) parser ───────────────────────────────

    def _parse_full_row(self, row: Any) -> dict[str, Any]:
        """Underwriting view returns full JSONB columns. Explode them
        into the ObjectType buckets the persona expects."""
        context: dict[str, Any] = {}
        application_id = row["application_id"]

        borrower = _decode_json(row.get("borrower"))
        if borrower:
            app_id = borrower.get("applicant_id", application_id)
            if borrower.get("credit"):
                context["CreditProfile"] = {app_id: dict(borrower["credit"])}
            if borrower.get("income"):
                context["IncomeProfile"] = {app_id: dict(borrower["income"])}
            if borrower.get("identity"):
                context["FraudProfile"] = {app_id: dict(borrower["identity"])}
            if borrower.get("employment"):
                context["VerificationAttempt"] = {app_id: dict(borrower["employment"])}

        prop = _decode_json(row.get("property"))
        if prop:
            context["Property"] = {application_id: dict(prop)}

        loan = _decode_json(row.get("loan_terms"))
        if loan:
            context["Loan"] = {application_id: dict(loan)}

        verif = _decode_json(row.get("verifications"))
        if verif:
            context["ComplianceRecord"] = {application_id: dict(verif)}

        # Flat indexed columns roll up as Application.
        flat = {
            "mid_credit_score": row.get("mid_credit_score"),
            "ltv": row.get("ltv"),
            "dti_back": row.get("dti_back"),
            "dti_front": row.get("dti_front"),
            "piti_monthly": row.get("piti_monthly"),
            "qualifying_monthly": row.get("qualifying_monthly"),
            "combined_monthly_income": row.get("combined_monthly_income"),
            "total_liquid_assets": row.get("total_liquid_assets"),
            "loan_amount": row.get("loan_amount"),
            "interest_rate": row.get("interest_rate"),
            "appraised_value": row.get("appraised_value"),
            "purchase_price": row.get("purchase_price"),
            "completeness_pct": row.get("completeness_pct"),
            "status": row.get("status"),
        }
        context["Application"] = {
            application_id: {k: _coerce(v) for k, v in flat.items() if v is not None}
        }
        return context


def _decode_json(val: Any) -> Optional[dict[str, Any]]:
    """asyncpg returns JSONB as Python dict by default, but when type
    codecs aren't registered (or the column was inserted as text) it
    can come back as str. Handle both."""
    if val is None:
        return None
    if isinstance(val, dict):
        return val
    if isinstance(val, (bytes, bytearray)):
        val = val.decode("utf-8")
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def _coerce(val: Any) -> Any:
    """Make values JSON-safe for downstream serialization. Pass through
    primitives; stringify datetime / Decimal / UUID."""
    from datetime import date
    from decimal import Decimal

    if val is None or isinstance(val, (str, int, float, bool, list, dict)):
        return val
    if isinstance(val, Decimal):
        # Preserve precision but be JSON-safe.
        return float(val)
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    return str(val)


__all__ = ["EdmsContextStore", "EdmsSnapshot"]
