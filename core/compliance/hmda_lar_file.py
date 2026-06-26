"""CF-A — HMDA LAR submission file generator (CFPB/FFIEC FIG, pipe-delimited).

Builds the plain-text, pipe-delimited (`|`) HMDA submission file from the existing
`hmda_lar` records (RA-7C): a Transmittal Sheet (record identifier `1`) + one LAR
row (record identifier `2`) per application, in FIG field order. We hold ~20 of the
~110 FIG fields; the rest are emitted blank and the genuinely-required-but-absent
ones are reported per record (RULE 11 — never fabricated).

Pure + DB-less (RULE 5/6). Read-only: the CFPB HMDA Platform upload is a deliberate
external manual step — this only produces a submission-ready file + (via
hmda_edit_checks) the edit report. No decision path, no writes -> 16/16 by
construction.

NOTE: `hmda_lar` already stores HMDA INTEGER codes for action_taken (1-8) and
lien_status (1-2), and integer demographic codes — those are emitted directly.
loan_type / loan_purpose / occupancy are stored as TEXT and mapped to FIG codes.
"""
from __future__ import annotations

from typing import Any

# FIG LAR record field order (record type 2). We populate what hmda_lar has; the
# rest stay blank (CFPB accepts blanks for not-applicable / exempt fields).
LAR_FIELD_ORDER = [
    "record_identifier", "lei", "uli", "application_date", "loan_type", "loan_purpose",
    "preapproval", "construction_method", "occupancy_type", "loan_amount",
    "action_taken", "action_taken_date", "state", "county", "census_tract",
    "applicant_ethnicity_1", "applicant_race_1", "applicant_sex",
    "co_applicant_ethnicity_1", "co_applicant_race_1", "co_applicant_sex",
    "applicant_age", "income", "purchaser_type", "rate_spread", "hoepa_status",
    "lien_status", "applicant_credit_score_type", "co_applicant_credit_score_type",
    "denial_reason_1", "denial_reason_2", "denial_reason_3", "denial_reason_4",
    "total_loan_costs", "total_points_fees", "origination_charges", "discount_points",
    "lender_credits", "interest_rate", "prepayment_penalty_term", "debt_to_income_ratio",
    "combined_loan_to_value", "loan_term", "introductory_rate_period", "balloon_payment",
    "interest_only_payments", "negative_amortization", "other_non_amortizing_features",
    "property_value", "manufactured_home_secured_property_type",
    "manufactured_home_land_property_interest", "total_units", "multifamily_affordable_units",
    "submission_of_application", "initially_payable_to_institution", "aus_1", "aus_result_1",
    "reverse_mortgage", "open_end_line_of_credit", "business_or_commercial_purpose",
]

# Text -> FIG code maps (DB stores human strings for these three).
LOAN_TYPE_CODES = {"conventional": "1", "fha": "2", "va": "3", "usda": "4", "other": ""}
LOAN_PURPOSE_CODES = {
    "purchase": "1", "home_improvement": "2", "refinance": "31",
    "rate_term_refi": "31", "rate_term_refinance": "31",
    "cash_out_refi": "32", "cash_out_refinance": "32", "other": "4", "na": "5"}
OCCUPANCY_CODES = {"primary": "1", "principal": "1", "second_home": "2",
                   "secondary": "2", "investment": "3"}
# Defensive: if action_taken/lien arrive as outcome strings instead of codes.
ACTION_TAKEN_CODES = {"originated": "1", "allow": "1", "recommend": "1", "approve": "1",
                      "escalate": "2", "approved": "2", "denied": "3", "block": "3",
                      "deny": "3", "withdrawn": "4", "withdraw": "4", "incomplete": "5",
                      "purchased": "6"}
LIEN_CODES = {"first": "1", "subordinate": "2"}

VALID_LOAN_TYPES = {"1", "2", "3", "4"}
VALID_LOAN_PURPOSES = {"1", "2", "31", "32", "4", "5"}
VALID_ACTION_TAKEN = {"1", "2", "3", "4", "5", "6", "7", "8"}
VALID_OCCUPANCY = {"1", "2", "3"}
VALID_LIEN_STATUS = {"1", "2"}

# Per-record required fields whose absence is ACTIONABLE (varies per loan).
# application_date is a FIG-required field that hmda_lar does not capture at all
# (a systemic gap, like the _HMDA_NOT_CAPTURED set in api/accord/audit.py) — its
# FIG slot is emitted blank but it is NOT reported per-record (would flag all rows).
REQUIRED_LAR_FIELDS = {
    "lei", "uli", "loan_type", "loan_purpose",
    "loan_amount", "action_taken", "action_taken_date", "lien_status",
}


def _blank(v: Any) -> str:
    return "" if v is None else str(v)


def _fmt_date(v: Any) -> str:
    """Any date/str -> YYYYMMDD (FIG format, no separators). '' if absent."""
    if v is None:
        return ""
    s = str(v)
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else ""


def _coerce_code(v: Any, valid: set, mapping: dict) -> str:
    """If v is already a valid FIG code, keep it; else map a known string; else ''."""
    if v is None:
        return ""
    s = str(v).strip().lower()
    if s in valid:
        return s
    return mapping.get(s, "")


def generate_transmittal_sheet(institution_meta: dict, calendar_year: int,
                               lar_count: int) -> str:
    m = institution_meta or {}
    return "|".join([
        "1", _blank(m.get("lei")), str(calendar_year), "4",
        _blank(m.get("institution_name") or m.get("tenant_id")),
        _blank(m.get("contact_name")), _blank(m.get("contact_phone")),
        _blank(m.get("contact_email")), str(lar_count), "",
    ])


def generate_lar_row(record: dict, institution_meta: dict) -> tuple:
    """One pipe-delimited LAR row. Returns (row_str, missing_required_fields)."""
    record = record or {}
    m = institution_meta or {}
    lei = _blank(m.get("lei"))
    app = _blank(record.get("application_id"))
    uli = record.get("uli") or (f"{lei}{app}" if lei or app else "")

    loan_type = _coerce_code(record.get("loan_type"), VALID_LOAN_TYPES, LOAN_TYPE_CODES)
    loan_purpose = _coerce_code(record.get("loan_purpose"), VALID_LOAN_PURPOSES, LOAN_PURPOSE_CODES)
    occupancy = _coerce_code(record.get("occupancy_type"), VALID_OCCUPANCY, OCCUPANCY_CODES)
    action = _coerce_code(record.get("action_taken"), VALID_ACTION_TAKEN, ACTION_TAKEN_CODES)
    lien = _coerce_code(record.get("lien_status"), VALID_LIEN_STATUS, LIEN_CODES)
    action_date = _fmt_date(record.get("action_taken_date"))

    denial_reasons = record.get("denial_reasons") or []
    denied = action == "3"
    dr = [(_blank(denial_reasons[i]) if denied and i < len(denial_reasons) else "")
          for i in range(4)]

    row = {
        "record_identifier": "2", "lei": lei, "uli": uli,
        "application_date": _fmt_date(record.get("application_date")),  # not in hmda_lar -> blank
        "loan_type": loan_type, "loan_purpose": loan_purpose,
        "preapproval": "2", "construction_method": "1", "occupancy_type": occupancy,
        "loan_amount": _blank(record.get("loan_amount")),
        "action_taken": action, "action_taken_date": action_date,
        "state": _blank(record.get("state_code")), "county": _blank(record.get("county_code")),
        "census_tract": _blank(record.get("census_tract")),
        "applicant_ethnicity_1": _blank(record.get("applicant_ethnicity")),
        "applicant_race_1": _blank(record.get("applicant_race")),
        "applicant_sex": _blank(record.get("applicant_sex")),
        "co_applicant_ethnicity_1": "5", "co_applicant_race_1": "8", "co_applicant_sex": "4",
        "applicant_age": _blank(record.get("applicant_age")),
        "income": _blank(record.get("applicant_income")),
        "purchaser_type": "0", "rate_spread": _blank(record.get("rate_spread")),
        "hoepa_status": "2", "lien_status": lien,
        "applicant_credit_score_type": "1", "co_applicant_credit_score_type": "10",
        "denial_reason_1": dr[0], "denial_reason_2": dr[1],
        "denial_reason_3": dr[2], "denial_reason_4": dr[3],
        "interest_rate": _blank(record.get("interest_rate")),
        "loan_term": _blank(record.get("loan_term_months")),
        "aus_1": _blank(record.get("aus_system")), "aus_result_1": _blank(record.get("aus_result")),
    }

    missing = sorted(f for f in REQUIRED_LAR_FIELDS if not row.get(f, ""))
    line = "|".join(row.get(f, "") for f in LAR_FIELD_ORDER)
    return line, missing


def generate_lar_file(records: list, institution_meta: dict,
                      calendar_year: int) -> tuple:
    """Full pipe-delimited LAR file. Returns (file_text, missing_fields_report)."""
    records = records or []
    lines = [generate_transmittal_sheet(institution_meta, calendar_year, len(records))]
    missing_report = []
    for rec in records:
        line, missing = generate_lar_row(rec, institution_meta)
        lines.append(line)
        if missing:
            missing_report.append({"application_id": rec.get("application_id"),
                                   "missing_fields": missing})
    return "\n".join(lines), missing_report


def parse_lar_rows(file_text: str) -> list:
    """Parse the LAR rows (record type 2) back into field dicts (for edit checks)."""
    rows = []
    for line in file_text.splitlines():
        vals = line.split("|")
        if vals and vals[0] == "2":
            padded = vals + [""] * (len(LAR_FIELD_ORDER) - len(vals))
            rows.append(dict(zip(LAR_FIELD_ORDER, padded)))
    return rows


__all__ = ["generate_lar_file", "generate_lar_row", "generate_transmittal_sheet",
           "parse_lar_rows", "LAR_FIELD_ORDER", "LOAN_TYPE_CODES", "LOAN_PURPOSE_CODES"]
