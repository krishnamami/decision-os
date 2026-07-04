"""LoanImporter — CSV (any LOS export) → entity_states / applications / applicants.

Validates a CSV, maps each row to the Accord entity model, derives LTV/DTI when
not provided, assigns to the team by status, and inserts. Uses the stdlib csv
module (no pandas dependency). Column auto-mapping handles non-template headers.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import date, datetime
from typing import Any, Optional

# Canonical template columns (order matters for the downloadable template).
TEMPLATE_COLUMNS = [
    "loan_number", "application_date", "loan_purpose", "loan_type", "channel",
    "borrower_first_name", "borrower_last_name", "borrower_email", "borrower_phone", "borrower_dob",
    "borrower_ssn_last4", "borrower_citizenship", "employer_name", "employment_type", "employment_years",
    "employer_phone", "stated_annual_income", "verified_annual_income", "monthly_income", "other_income",
    "income_source", "credit_score_experian", "credit_score_transunion", "credit_score_equifax", "mid_credit_score",
    "monthly_debt_payments", "monthly_housing_payment", "property_address", "property_type", "property_state",
    "property_county", "property_zip", "occupancy", "purchase_price", "appraised_value", "estimated_value",
    "loan_amount", "interest_rate", "loan_term_months", "amortization_type", "ltv", "dti_front", "dti_back",
    "coborrower_first_name", "coborrower_last_name", "coborrower_income", "coborrower_credit_score",
    "loan_status", "assigned_to_email",
]
REQUIRED = [
    "loan_number", "application_date", "loan_purpose", "loan_type", "borrower_first_name", "borrower_last_name",
    "employer_name", "employment_type", "stated_annual_income", "mid_credit_score", "monthly_debt_payments",
    "property_address", "property_type", "property_state", "property_zip", "occupancy", "loan_amount",
    "interest_rate", "loan_term_months",
]
VALID = {
    "loan_purpose": {"purchase", "refinance", "cash_out"},
    "loan_type": {"conventional", "fha", "va", "usda", "jumbo"},
    "employment_type": {"salaried", "self_employed", "retired", "other"},
    "property_type": {"sfr", "condo", "townhouse", "multi_2_4", "manufactured"},
    "occupancy": {"primary", "secondary", "investment"},
}
# CSV value → the constrained value the applications table accepts.
PURPOSE_MAP = {"purchase": "purchase", "refinance": "refinance_rate_term", "cash_out": "refinance_cash_out"}
OCCUPANCY_MAP = {"primary": "primary_residence", "secondary": "second_home", "investment": "investment_property"}

US_STATES = {"AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS",
             "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY",
             "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC"}


# ── Column auto-mapping (fuzzy + keyword) ───────────────────────────
_KEYWORDS = {
    "loan_number": ["loan num", "loan no", "loan id", "loan #", "loannumber"],
    "mid_credit_score": ["fico", "mid score", "credit score", "mid fico", "representative score"],
    "loan_amount": ["base loan", "loan amount", "loan amt", "base amt"],
    "borrower_first_name": ["first name", "borrower first", "first"],
    "borrower_last_name": ["last name", "borrower last", "surname", "last"],
    "stated_annual_income": ["stated income", "gross income", "annual income"],
    "property_address": ["property street", "subject address", "property addr", "address"],
    "interest_rate": ["note rate", "rate", "interest"],
    "loan_term_months": ["term", "loan term", "amort term"],
    "purchase_price": ["purchase price", "sales price", "contract price"],
    "appraised_value": ["appraised", "appraisal value", "opinion of value"],
}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def auto_map(headers: list[str]) -> dict[str, Optional[str]]:
    """Map source headers → Accord template fields. Returns {source: field|None}."""
    out: dict[str, Optional[str]] = {}
    used: set[str] = set()
    canon = {_slug(c): c for c in TEMPLATE_COLUMNS}
    for h in headers:
        s = _slug(h)
        if s in canon and canon[s] not in used:  # exact (slug) match
            out[h] = canon[s]; used.add(canon[s]); continue
        match = None
        for field, kws in _KEYWORDS.items():
            if field in used:
                continue
            if any(_slug(k) in s or s in _slug(k) for k in kws):
                match = field; break
        if match is None:  # loose contains against template field names
            for c in TEMPLATE_COLUMNS:
                if c in used:
                    continue
                if _slug(c) and (_slug(c) in s or s in _slug(c)):
                    match = c; break
        out[h] = match
        if match:
            used.add(match)
    return out


def parse_csv(text: str) -> tuple[list[str], list[dict]]:
    text = text.lstrip("﻿")
    delimiter = "\t" if (text[:2000].count("\t") > text[:2000].count(",")) else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    headers = reader.fieldnames or []
    rows = [dict(r) for r in reader]
    return headers, rows


def _num(v: Any) -> Optional[float]:
    if v is None:
        return None
    s = str(v).strip().replace("$", "").replace(",", "").replace("%", "")
    if s == "" or s.lower() in ("na", "n/a", "none"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _apply_mapping(row: dict, mapping: Optional[dict]) -> dict:
    if not mapping:
        return row
    out: dict = {}
    for src, field in mapping.items():
        if field and field != "__skip__":
            out[field] = row.get(src)
    return out


def _rule_matches(loan_data: dict, rule: dict) -> bool:
    """AND logic across all set conditions. A condition on a field that isn't
    available for this loan (e.g. fraud_score at import time) fails to match —
    so fraud/non-QM rules stay inert until those signals exist at ingestion."""
    amt = loan_data.get("loan_amount")
    lt = str(loan_data.get("loan_type") or "").upper()
    ltv = loan_data.get("ltv")
    fs = loan_data.get("fraud_score")
    if rule.get("min_loan_amount") is not None and (amt is None or amt < float(rule["min_loan_amount"])):
        return False
    if rule.get("max_loan_amount") is not None and (amt is None or amt > float(rule["max_loan_amount"])):
        return False
    if rule.get("loan_type") is not None and lt != str(rule["loan_type"]).upper():
        return False
    if rule.get("min_fraud_score") is not None and (fs is None or fs < float(rule["min_fraud_score"])):
        return False
    if rule.get("min_ltv") is not None and (ltv is None or ltv < float(rule["min_ltv"])):
        return False
    return True


def get_assigned_role(loan_data: dict, rules: list[dict]) -> tuple[str, Any]:
    """First matching rule wins (rules pre-sorted by priority DESC). Falls back
    to the default underwriter role when nothing matches."""
    for rule in rules:
        if _rule_matches(loan_data, rule):
            return rule["assign_to_role"], rule.get("assign_to_user_id")
    return "underwriter", None


class LoanImporter:
    def __init__(self, tenant_id: str, uploaded_by: Optional[str] = None):
        self.tenant_id = tenant_id
        self.uploaded_by = uploaded_by
        self.errors: list[dict] = []
        self.warnings: list[str] = []
        self.imported = 0
        self.skipped = 0

    # ── validation ──────────────────────────────────────────────────
    def validate(self, rows: list[dict], mapping: Optional[dict] = None) -> dict:
        errors: list[dict] = []
        warnings: list[str] = []
        preview: list[dict] = []
        seen: set[str] = set()
        valid_count = 0
        for i, raw in enumerate(rows, start=1):
            r = _apply_mapping(raw, mapping)
            row_errs = []
            for col in REQUIRED:
                if not str(r.get(col) or "").strip():
                    row_errs.append(f"{col} is required but missing")
            ln = str(r.get("loan_number") or "").strip()
            if ln and ln in seen:
                row_errs.append(f"duplicate loan_number {ln}")
            if ln:
                seen.add(ln)
            for col, allowed in VALID.items():
                v = str(r.get(col) or "").strip().lower()
                if v and v not in allowed:
                    row_errs.append(f"{col} '{v}' is not recognized")
            st = str(r.get("property_state") or "").strip().upper()
            if st and st not in US_STATES:
                row_errs.append(f"property_state '{st}' is not a valid state code")
            if r.get("loan_purpose") == "purchase" and not str(r.get("purchase_price") or "").strip():
                row_errs.append("purchase_price is required for purchase loans")
            # warnings (non-blocking)
            if not str(r.get("appraised_value") or "").strip():
                warnings.append(f"Row {i}: appraised_value missing — LTV estimated from purchase_price")
            if not str(r.get("credit_score_experian") or "").strip():
                warnings.append(f"Row {i}: credit_score_experian missing — mid_score used")
            if not str(r.get("employer_phone") or "").strip():
                warnings.append(f"Row {i}: employer_phone missing — VOE may be incomplete")

            if row_errs:
                for e in row_errs:
                    errors.append({"row": i, "error": e})
                preview.append({"loan_number": ln or "—", "borrower": "Error row", "amount": None, "status": "error", "error": row_errs[0]})
            else:
                valid_count += 1
                preview.append({
                    "loan_number": ln, "borrower": f"{r.get('borrower_first_name', '')} {r.get('borrower_last_name', '')}".strip(),
                    "amount": _num(r.get("loan_amount")), "type": r.get("loan_type"), "status": "ok"})
        return {
            "valid": len(errors) == 0, "row_count": len(rows), "valid_count": valid_count,
            "errors": errors[:50], "warnings": warnings[:50], "preview": preview[:10],
        }

    # ── mapping a row → entity_states JSONB shape ───────────────────
    def map_row(self, r: dict) -> dict:
        return {
            "borrower": {
                "first_name": r.get("borrower_first_name"), "last_name": r.get("borrower_last_name"),
                "email": r.get("borrower_email"), "dob": r.get("borrower_dob"), "employer": r.get("employer_name"),
                "employment_type": r.get("employment_type"), "employment_years": _num(r.get("employment_years")),
                "stated_income": _num(r.get("stated_annual_income")), "verified_income": _num(r.get("verified_annual_income")),
                "monthly_income": _num(r.get("monthly_income")), "citizenship": r.get("borrower_citizenship") or "us_citizen",
            },
            "property": {
                "address": r.get("property_address"), "type": r.get("property_type"), "state": (r.get("property_state") or "").upper(),
                "county": r.get("property_county"), "zip": r.get("property_zip"), "occupancy": r.get("occupancy"),
                "purchase_price": _num(r.get("purchase_price")), "appraised_value": _num(r.get("appraised_value")),
                "estimated_value": _num(r.get("estimated_value")),
            },
            "loan_terms": {
                "loan_amount": _num(r.get("loan_amount")), "interest_rate": _num(r.get("interest_rate")),
                "term_months": int(_num(r.get("loan_term_months")) or 360), "loan_type": r.get("loan_type"),
                "loan_purpose": r.get("loan_purpose"), "amortization_type": r.get("amortization_type") or "fixed",
                "channel": r.get("channel"),
            },
            "credit": {
                "mid_score": int(_num(r.get("mid_credit_score")) or 0), "experian": _num(r.get("credit_score_experian")),
                "transunion": _num(r.get("credit_score_transunion")), "equifax": _num(r.get("credit_score_equifax")),
            },
            "liabilities": {"monthly_debt": _num(r.get("monthly_debt_payments")) or 0, "current_housing": _num(r.get("monthly_housing_payment")) or 0},
        }

    # ── derived fields ──────────────────────────────────────────────
    def ltv(self, r: dict) -> Optional[float]:
        if _num(r.get("ltv")):
            return round(_num(r.get("ltv")), 1)
        value = _num(r.get("appraised_value")) or _num(r.get("purchase_price")) or _num(r.get("estimated_value"))
        la = _num(r.get("loan_amount"))
        if not value or not la:
            return None
        return round(la / value * 100, 1)

    def _monthly_income(self, r: dict) -> Optional[float]:
        m = _num(r.get("monthly_income"))
        if m:
            return m + (_num(r.get("other_income")) or 0) / 12
        annual = _num(r.get("stated_annual_income"))
        return (annual / 12 + (_num(r.get("other_income")) or 0) / 12) if annual else None

    def _piti(self, r: dict) -> Optional[float]:
        la, rate, n = _num(r.get("loan_amount")), _num(r.get("interest_rate")), _num(r.get("loan_term_months"))
        value = _num(r.get("appraised_value")) or _num(r.get("purchase_price")) or la
        if not la or rate is None or not n:
            return None
        mr = rate / 100 / 12
        pi = la * mr * (1 + mr) ** n / ((1 + mr) ** n - 1) if mr > 0 else la / n
        ti = (value or la) * 0.0125 / 12  # taxes + insurance ~1.25%/yr
        mi = la * 0.005 / 12 if (self.ltv(r) or 0) > 80 else 0  # MI when LTV > 80
        return round(pi + ti + mi, 2)

    def front_dti(self, r: dict) -> Optional[float]:
        if _num(r.get("dti_front")):
            return round(_num(r.get("dti_front")), 1)
        mi, piti = self._monthly_income(r), self._piti(r)
        return round(piti / mi * 100, 1) if mi and piti else None

    def back_dti(self, r: dict) -> Optional[float]:
        if _num(r.get("dti_back")):
            return round(_num(r.get("dti_back")), 1)
        mi, piti = self._monthly_income(r), self._piti(r)
        debt = _num(r.get("monthly_debt_payments")) or 0
        return round((piti + debt) / mi * 100, 1) if mi and piti else None

    # ── insert ──────────────────────────────────────────────────────
    async def import_rows(self, conn, rows: list[dict], mapping: Optional[dict] = None, run_evaluation: bool = False) -> dict:
        # team for round-robin assignment
        users = await conn.fetch("SELECT user_id, email, role FROM users WHERE tenant_id=$1 AND is_active IS NOT false", self.tenant_id)
        by_role: dict[str, list] = {}
        by_email: dict[str, Any] = {}
        for u in users:
            by_role.setdefault(u["role"], []).append(u["user_id"])
            by_email[u["email"].lower()] = u["user_id"]
        rr = {"processor": 0, "underwriter": 0, "closer": 0, "senior_uw": 0}
        # Active assignment rules (priority DESC) — route matching loans directly
        # to a senior role, bypassing the default UW queue.
        rule_rows = await conn.fetch(
            "SELECT rule_name, priority, min_loan_amount, max_loan_amount, loan_type, "
            "min_fraud_score, min_ltv, assign_to_role, assign_to_user_id "
            "FROM assignment_rules WHERE tenant_id=$1 AND is_active=true ORDER BY priority DESC",
            self.tenant_id)
        assignment_rules = [dict(r) for r in rule_rows]
        user_ids = {u["user_id"] for u in users}

        def pick(role: str):
            lst = by_role.get(role) or []
            if not lst:
                return None
            uid = lst[rr[role] % len(lst)]
            rr[role] += 1
            return uid

        summary = {"by_type": {}, "by_status": {}, "amounts": [], "scores": [], "assignments": {}}
        imported_ids: list[str] = []

        for i, raw in enumerate(rows, start=1):
            r = _apply_mapping(raw, mapping)
            errs = [c for c in REQUIRED if not str(r.get(c) or "").strip()]
            if errs:
                self.errors.append({"row": i, "error": f"{errs[0]} is required but missing"})
                self.skipped += 1
                continue
            lt = str(r.get("loan_type") or "").lower()
            if lt and lt not in VALID["loan_type"]:
                self.errors.append({"row": i, "error": f"loan_type '{lt}' is not recognized"})
                self.skipped += 1
                continue

            ln = str(r["loan_number"]).strip()
            app_id = f"APP-IMP-{self.tenant_id}-{ln}"
            apl_id = f"APL-IMP-{self.tenant_id}-{ln}"
            exists = await conn.fetchval("SELECT 1 FROM entity_states WHERE application_id=$1", app_id)
            if exists:
                self.warnings.append(f"Row {i}: loan {ln} already imported — skipped")
                self.skipped += 1
                continue

            es = self.map_row(r)
            ltv, fdti, bdti = self.ltv(r), self.front_dti(r), self.back_dti(r)
            status = str(r.get("loan_status") or "active").lower()
            stage = {"approved": "close", "funded": "close", "denied": "decide"}.get(status, "verify")

            # assignment — explicit email wins; else rule-based direct assignment
            # (active loans only); else the default round-robin.
            email = str(r.get("assigned_to_email") or "").strip().lower()
            assignment_type = None
            assign_stage = stage
            assignee = by_email.get(email) if email else None
            if assignee is None and status == "active" and assignment_rules:
                loan_data = {"loan_amount": _num(r.get("loan_amount")), "loan_type": r.get("loan_type"),
                             "ltv": ltv, "fraud_score": None}
                role, target_uid = get_assigned_role(loan_data, assignment_rules)
                if role and role != "underwriter":
                    picked = target_uid if (target_uid and target_uid in user_ids) else pick(role)
                    if picked:
                        assignee = picked
                        assignment_type = "direct_assignment"
                        assign_stage = "decide"  # straight to the decision queue
            if assignee is None:
                assignee = (pick("processor") if status == "active"
                            else pick("closer") if status in ("approved", "funded")
                            else pick("underwriter"))

            import json
            from uuid import UUID
            dob = r.get("borrower_dob") or "1980-01-01"
            # ssn_hash is a placeholder (we never store the SSN); make it unique
            # per loan so the UNIQUE(ssn_hash) constraint never collides on last-4.
            ssn_hash = hashlib.sha256(f"{self.tenant_id}:{ln}:{r.get('borrower_ssn_last4') or ''}".encode()).hexdigest()[:40]
            name = f"{r['borrower_first_name']} {r['borrower_last_name']}".strip()

            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO applicants (applicant_id, full_name, first_name, last_name, dob, ssn_hash, ssn_last4, "
                    " email, phone, status, identity_xrefs, application_ids, created_at, updated_at, external_ids, tenant_id) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'active','{}'::jsonb,$10::jsonb,NOW(),NOW(),'{}'::jsonb,$11) "
                    "ON CONFLICT (applicant_id) DO NOTHING",
                    apl_id, name, r["borrower_first_name"], r["borrower_last_name"], _date(dob), ssn_hash,
                    str(r.get("borrower_ssn_last4") or "")[:4], r.get("borrower_email"), r.get("borrower_phone"),
                    json.dumps([app_id]), self.tenant_id)
                await conn.execute(
                    "INSERT INTO applications (application_id, applicant_id, los_id, status, created_at, tenant_id, "
                    " loan_type, loan_purpose, occupancy, loan_amount, interest_rate, loan_term_months, stated_income, "
                    " verified_income, stated_employer) "
                    "VALUES ($1,$2,$3,$4,NOW(),$5,$6,$7,$8,$9,$10,$11,$12,$13,$14) ON CONFLICT (application_id) DO NOTHING",
                    app_id, apl_id, ln, status, self.tenant_id, r.get("loan_type"),
                    PURPOSE_MAP.get(str(r.get("loan_purpose") or "").lower(), "other"),
                    OCCUPANCY_MAP.get(str(r.get("occupancy") or "").lower(), "primary_residence"),
                    _num(r.get("loan_amount")), _num(r.get("interest_rate")),
                    int(_num(r.get("loan_term_months")) or 360), _num(r.get("stated_annual_income")),
                    _num(r.get("verified_annual_income")), r.get("employer_name"))
                await conn.execute(
                    "INSERT INTO entity_states (application_id, tenant_id, borrower, property, loan_terms, "
                    " mid_credit_score, appraised_value, purchase_price, loan_amount, interest_rate, ltv, dti_front, "
                    " dti_back, loan_status, current_stage, status, assigned_to, application_date, created_at, last_updated) "
                    "VALUES ($1,$2,$3::jsonb,$4::jsonb,$5::jsonb,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,'active',$16,$17,NOW(),NOW())",
                    app_id, self.tenant_id, json.dumps(es["borrower"]), json.dumps(es["property"]), json.dumps(es["loan_terms"]),
                    es["credit"]["mid_score"], _num(r.get("appraised_value")), _num(r.get("purchase_price")),
                    _num(r.get("loan_amount")), _num(r.get("interest_rate")), ltv, fdti, bdti, status, assign_stage, assignee,
                    _date(r.get("application_date")))
                if assignee:
                    await conn.execute(
                        "INSERT INTO loan_assignments (application_id, tenant_id, assigned_to, assigned_by, stage, status, assigned_at, assignment_type) "
                        "VALUES ($1,$2,$3,$4,$5,'active',NOW(),$6)",
                        app_id, self.tenant_id, assignee, _uuid(self.uploaded_by), assign_stage, assignment_type)

            self.imported += 1
            imported_ids.append(app_id)
            summary["by_type"][lt] = summary["by_type"].get(lt, 0) + 1
            summary["by_status"][status] = summary["by_status"].get(status, 0) + 1
            if _num(r.get("loan_amount")):
                summary["amounts"].append(_num(r.get("loan_amount")))
            if es["credit"]["mid_score"]:
                summary["scores"].append(es["credit"]["mid_score"])
            akey = next((e for e, uid in by_email.items() if uid == assignee), "unassigned") if assignee else "unassigned"
            summary["assignments"][akey] = summary["assignments"].get(akey, 0) + 1

        avg_amount = round(sum(summary["amounts"]) / len(summary["amounts"])) if summary["amounts"] else 0
        avg_score = round(sum(summary["scores"]) / len(summary["scores"])) if summary["scores"] else 0
        return {
            "imported": self.imported, "skipped": self.skipped, "errors": self.errors[:50], "warnings": self.warnings[:50],
            "application_ids": imported_ids,
            "summary": {
                "total_loans": self.imported, "by_type": summary["by_type"], "by_status": summary["by_status"],
                "avg_amount": avg_amount, "avg_score": avg_score, "assignments": summary["assignments"],
            },
        }


async def evaluate_imported(conn, tenant_id: str, app_ids: list[str], rules: dict, programs: list[str]) -> dict:
    """Run a lightweight rule evaluation on imported loans and write one
    underwriting decision per loan so they appear evaluated in the pipeline."""
    from core.compliance.rule_validator import resolve, evaluate, load_validator_rules
    # RA-4E: agency/regulatory floors & ceilings come from the catalogue, not
    # Python constants. The conn is in hand, so resolve them here.
    catalogue = await load_validator_rules(conn, tenant_id)
    R = resolve(rules, programs, catalogue)
    counts = {"allow": 0, "review": 0, "block": 0, "escalate": 0}
    # Active rule version for this tenant right now — stamped on every decision
    # written here. NULL when the tenant has no rules. Never blocks the import.
    try:
        rule_version_id = await conn.fetchval(
            "SELECT rule_version_id FROM tenant_rules "
            "WHERE tenant_id=$1 AND status='active' "
            "AND effective_from <= NOW() AND (effective_to IS NULL OR effective_to > NOW()) "
            "ORDER BY version DESC LIMIT 1",
            tenant_id,
        )
    except Exception:
        rule_version_id = None
    for app in app_ids:
        es = await conn.fetchrow(
            "SELECT mid_credit_score, dti_back, ltv, loan_terms FROM entity_states WHERE application_id=$1", app)
        if es is None:
            continue
        import json
        lt = es["loan_terms"]
        lt = json.loads(lt) if isinstance(lt, str) else (lt or {})
        loan_type = lt.get("loan_type", "conventional")
        # strictest of the three field checks
        results = []
        if es["mid_credit_score"]:
            results.append(evaluate({"credit_score": es["mid_credit_score"], "loan_type": loan_type}, R)[0])
        if es["dti_back"] is not None:
            results.append(evaluate({"dti": float(es["dti_back"]), "credit_score": es["mid_credit_score"] or 0}, R)[0])
        if es["ltv"] is not None:
            results.append(evaluate({"ltv": float(es["ltv"]), "loan_type": loan_type}, R)[0])
        if "block" in results:
            outcome, mode = "block", "recommend"
        elif any(r in ("review", "allow_if") for r in results):
            outcome, mode = "recommend", "recommend"
        else:
            outcome, mode = "allow", "auto_execute"
        counts["allow" if outcome == "allow" else "review" if outcome == "recommend" else "block"] += 1
        await conn.execute(
            "INSERT INTO decision_outputs (application_id, decision_id, wave, outcome, mode, confidence, tenant_id, decided_at, rule_version_id) "
            "VALUES ($1,'underwriting_decision',4,$2,$3,$4,$5,NOW(),$6)",
            app, outcome, mode, 0.9, tenant_id, rule_version_id)
    return counts


def _date(v) -> Optional[date]:
    if isinstance(v, date):
        return v
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except (ValueError, TypeError):
        return None


def _uuid(v):
    from uuid import UUID
    try:
        return UUID(str(v)) if v else None
    except (ValueError, TypeError):
        return None
