"""CF-A — CFPB HMDA edit-check engine (FFIEC FIG Syntactical / Validity / Quality / Macro).

Runs a focused, named subset of CFPB edits over the generated LAR records so a lender
knows what blocks submission BEFORE uploading to the CFPB HMDA Platform. Pure +
DB-less. RULE 11: a missing/invalid field is surfaced, never auto-passed.

Severity: error (S/V — blocks submission) · warning (Q + soft-V — review) ·
info (M — aggregate). submission_ready == no error-level edits failed.
"""
from __future__ import annotations

from core.compliance.hmda_lar_file import (
    VALID_ACTION_TAKEN, VALID_LIEN_STATUS, VALID_LOAN_PURPOSES, VALID_LOAN_TYPES,
    VALID_OCCUPANCY,
)

EDIT_CHECKS = [
    {"id": "S010", "cat": "S", "sev": "error", "field": "lei",
     "desc": "LEI must be present and 20 characters"},
    {"id": "S020", "cat": "S", "sev": "error", "field": "uli",
     "desc": "ULI must be present"},
    {"id": "S030", "cat": "S", "sev": "error", "field": "action_taken_date",
     "desc": "Action taken date must be present and a valid YYYYMMDD"},
    {"id": "V210", "cat": "V", "sev": "error", "field": "loan_type",
     "desc": "Loan type must be 1-4 (Conventional/FHA/VA/USDA)"},
    {"id": "V225", "cat": "V", "sev": "error", "field": "loan_purpose",
     "desc": "Loan purpose must be 1, 2, 31, 32, 4, or 5"},
    {"id": "V272", "cat": "V", "sev": "error", "field": "action_taken",
     "desc": "Action taken must be 1-8"},
    {"id": "V290", "cat": "V", "sev": "error", "field": "occupancy_type",
     "desc": "Occupancy type must be 1-3"},
    {"id": "V310", "cat": "V", "sev": "error", "field": "lien_status",
     "desc": "Lien status must be 1 or 2"},
    {"id": "V350", "cat": "V", "sev": "error", "field": "denial_reason_1",
     "desc": "Denial reason required when action taken = 3 (denied)"},
    {"id": "V380", "cat": "V", "sev": "warning", "field": "census_tract",
     "desc": "Census tract should be present for a reportable loan"},
    {"id": "V395", "cat": "V", "sev": "warning", "field": "applicant_ethnicity_1",
     "desc": "Applicant ethnicity should be reported"},
    {"id": "Q614", "cat": "Q", "sev": "warning", "field": "loan_amount",
     "desc": "Loan amount > $10M is unusual — verify"},
    {"id": "Q629", "cat": "Q", "sev": "warning", "field": "rate_spread",
     "desc": "Rate spread > 10% is unusual — verify"},
    {"id": "Q640", "cat": "Q", "sev": "warning", "field": "income",
     "desc": "Annual income > $10M is unusual — verify"},
    {"id": "M001", "cat": "M", "sev": "info", "field": "action_taken",
     "desc": "Denial rate > 50% — review for fair lending"},
]


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def run_edit_checks(records: list, lar_rows: list) -> dict:
    """records = raw hmda_lar dicts; lar_rows = parsed FIG field dicts (same order).
    Returns the structured edit report."""
    records = records or []
    lar_rows = lar_rows or []
    res = {e["id"]: {**e, "applications_affected": [], "pass": True} for e in EDIT_CHECKS}

    def fail(eid, app_id):
        res[eid]["applications_affected"].append(app_id)
        res[eid]["pass"] = False

    denial_count = 0
    total = len(records)

    for rec, row in zip(records, lar_rows):
        app = rec.get("application_id", "?")
        action = str(row.get("action_taken", ""))
        if action == "3":
            denial_count += 1

        # Syntactical
        lei = str(row.get("lei", ""))
        if len(lei) != 20:
            fail("S010", app)
        if not str(row.get("uli", "")):
            fail("S020", app)
        adate = str(row.get("action_taken_date", ""))
        if len(adate) != 8 or not adate.isdigit():
            fail("S030", app)

        # Validity (errors)
        if str(row.get("loan_type", "")) not in VALID_LOAN_TYPES:
            fail("V210", app)
        if str(row.get("loan_purpose", "")) not in VALID_LOAN_PURPOSES:
            fail("V225", app)
        if action not in VALID_ACTION_TAKEN:
            fail("V272", app)
        if str(row.get("occupancy_type", "")) not in VALID_OCCUPANCY:
            fail("V290", app)
        if str(row.get("lien_status", "")) not in VALID_LIEN_STATUS:
            fail("V310", app)
        if action == "3" and not str(row.get("denial_reason_1", "")):
            fail("V350", app)

        # Validity (warnings)
        if not str(row.get("census_tract", "")):
            fail("V380", app)
        eth = str(row.get("applicant_ethnicity_1", ""))
        if eth in ("", "0"):
            fail("V395", app)

        # Quality (warnings)
        if _f(rec.get("loan_amount")) > 10_000_000:
            fail("Q614", app)
        if rec.get("rate_spread") is not None and _f(rec.get("rate_spread")) > 10.0:
            fail("Q629", app)
        if _f(rec.get("applicant_income")) > 10_000_000:
            fail("Q640", app)

    # Macro
    if total and denial_count / total > 0.50:
        res["M001"]["applications_affected"] = ["aggregate"]
        res["M001"]["pass"] = False

    failed = [r for r in res.values() if r["applications_affected"]]
    errors = [r for r in failed if r["sev"] == "error"]
    warnings = [r for r in failed if r["sev"] == "warning"]
    infos = [r for r in failed if r["sev"] == "info"]

    return {
        "total_records": total,
        "edit_checks_run": len(EDIT_CHECKS),
        "errors": errors, "warnings": warnings, "infos": infos,
        "error_count": len(errors), "warning_count": len(warnings),
        "submission_ready": len(errors) == 0,
        "note": ("submission_ready = no syntactical/validity errors. Quality/info edits "
                 "should be reviewed but do not block. The CFPB HMDA Platform upload is a "
                 "manual external step — this engine does not auto-submit."),
        "data_source": "hmda_lar + generate_lar_row FIG mapping",
        "missing_inputs": ([f"{len(errors)} error-level edit(s) failed — fix before submission"]
                           if errors else []),
    }


__all__ = ["run_edit_checks", "EDIT_CHECKS"]
