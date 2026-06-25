"""EV-H — the required-fields manifest (the verified input contract).

A declared, auditable contract for the critical fields personas depend on: for
each field, where it comes from (source doc -> extracted key -> golden-record key
-> entity_states location), which personas consume it, which decisions require it,
and whether any consumer SILENTLY DEFAULTS when it is absent (a RULE 11 violation
EV-H surfaces but does not fix).

Pure data — no DB, no engine. The verifier (field_manifest_verifier.py) checks a
real entity_states row against this contract.

Scope (v1): the 10 fields with a clean, verified entity_states location. Honest
notes:
  - dti_back / qualifying_monthly / piti_monthly / total_liquid_assets are NOT
    build_golden_record outputs — they are derived/seeded downstream; `note` says so.
  - property_type / loan_purpose live nested in loan_terms.urla (not a clean
    top-level contract point) and are deferred to a manifest expansion rather than
    pointed at a path that would false-flag them missing.
  - The three silent-default fields (mid_credit_score / ltv / dti_back) are read by
    rate_pricing from the UPSTREAM PAYLOAD; when that upstream value is absent
    rate_pricing assumes 700 / 0.80 / 0.36 (rate_pricing.py:49-51).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ManifestField:
    """One critical field in the verified input contract."""
    field_name: str
    entity_column: str                       # entity_states column (or JSONB col)
    source_doc_type: str                     # originating document (or 'DERIVED')
    extracted_key: str                       # extracted_fields key (or computation)
    golden_record_key: str                   # build_golden_record key (or 'derived')
    consumers: list                          # personas that read it
    required_for: list                       # decisions that need it
    required: bool
    silent_default: Optional[str] = None     # set if a consumer assumes when NULL
    json_path: Optional[tuple] = None        # for JSONB-nested fields
    note: Optional[str] = None               # provenance caveat (derived/seeded/etc)


FIELD_MANIFEST = [
    ManifestField(
        field_name="mid_credit_score", entity_column="mid_credit_score",
        source_doc_type="CREDIT_REPORT",
        extracted_key="equifax/experian/transunion_score (3-bureau middle) else mid_score",
        golden_record_key="mid_credit_score",
        consumers=["credit_assessment", "rate_pricing", "product_eligibility"],
        required_for=["credit_assessment", "underwriting_decision"], required=True,
        silent_default="rate_pricing assumes 700 when credit_assessment emits no credit_score "
                       "(rate_pricing.py:49)"),
    ManifestField(
        field_name="ltv", entity_column="ltv",
        source_doc_type="APPRAISAL_URAR + URLA_1003",
        extracted_key="appraised_value + loan_amount (lesser-of rule)",
        golden_record_key="ltv",
        consumers=["ltv_assessment", "rate_pricing", "product_eligibility"],
        required_for=["ltv_assessment", "underwriting_decision"], required=True,
        silent_default="rate_pricing assumes 0.80 when ltv_assessment emits no ltv "
                       "(rate_pricing.py:51)"),
    ManifestField(
        field_name="dti_back", entity_column="dti_back",
        source_doc_type="DERIVED",
        extracted_key="qualifying_monthly + monthly_obligations + proposed PITI (computed)",
        golden_record_key="derived",
        consumers=["dti_calculation", "rate_pricing", "product_eligibility"],
        required_for=["dti_calculation", "underwriting_decision"], required=True,
        silent_default="rate_pricing assumes 0.36 when dti_calculation emits no dti "
                       "(rate_pricing.py:50)",
        note="Computed downstream (not a build_golden_record output)."),
    ManifestField(
        field_name="qualifying_monthly", entity_column="qualifying_monthly",
        source_doc_type="W2_CURRENT / PAYSTUB_CURRENT",
        extracted_key="box1_wages/12 or gross*freq/12",
        golden_record_key="derived",
        consumers=["income_verification", "dti_calculation"],
        required_for=["income_verification", "dti_calculation"], required=True,
        note="Derived via the income path / seeded (not a build_golden_record output)."),
    ManifestField(
        field_name="total_liquid_assets", entity_column="total_liquid_assets",
        source_doc_type="BANK_STATEMENT_M1",
        extracted_key="ending_balance (summed)",
        golden_record_key="derived",
        consumers=["asset_verification", "closing_readiness"],
        required_for=["asset_verification"], required=True,
        note="Derived from bank statements / seeded (not a build_golden_record output)."),
    ManifestField(
        field_name="piti_monthly", entity_column="piti_monthly",
        source_doc_type="DERIVED",
        extracted_key="principal+interest+taxes+insurance (computed from loan terms)",
        golden_record_key="derived",
        consumers=["dti_calculation", "asset_verification", "closing_readiness"],
        required_for=["dti_calculation"], required=True,
        note="Computed from loan terms (not a build_golden_record output)."),
    ManifestField(
        field_name="loan_amount", entity_column="loan_amount",
        source_doc_type="URLA_1003", extracted_key="loan_amount",
        golden_record_key="loan_amount",
        consumers=["ltv_assessment", "product_eligibility", "rate_pricing"],
        required_for=["ltv_assessment"], required=True),
    ManifestField(
        field_name="appraised_value", entity_column="appraised_value",
        source_doc_type="APPRAISAL_URAR", extracted_key="appraised_value",
        golden_record_key="appraised_value",
        consumers=["ltv_assessment"], required_for=["ltv_assessment"], required=True),
    ManifestField(
        field_name="monthly_obligations", entity_column="monthly_obligations",
        source_doc_type="CREDIT_REPORT", extracted_key="total_monthly_obligations",
        golden_record_key="monthly_obligations",
        consumers=["dti_calculation", "asset_verification"],
        required_for=["dti_calculation"], required=True),
    ManifestField(
        field_name="loan_type", entity_column="loan_terms",
        source_doc_type="URLA_1003", extracted_key="loan_type",
        golden_record_key="loan_type", json_path=("loan_terms", "loan_type"),
        consumers=["product_eligibility", "compliance_check"],
        required_for=["product_eligibility"], required=True,
        note="Stored in the loan_terms JSONB column (loan_terms.loan_type)."),
]

MANIFEST_BY_FIELD = {f.field_name: f for f in FIELD_MANIFEST}
REQUIRED_FIELDS = [f for f in FIELD_MANIFEST if f.required]
OPTIONAL_FIELDS = [f for f in FIELD_MANIFEST if not f.required]
FIELDS_WITH_SILENT_DEFAULTS = [f for f in FIELD_MANIFEST if f.silent_default]

__all__ = [
    "ManifestField", "FIELD_MANIFEST", "MANIFEST_BY_FIELD",
    "REQUIRED_FIELDS", "OPTIONAL_FIELDS", "FIELDS_WITH_SILENT_DEFAULTS",
]
