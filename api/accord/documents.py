"""Accord — document viewer API (checklist → extraction detail → source match).

Connects the existing EDMS ``document_index`` (real indexed documents with
``extracted_fields``) to the Accord UI so an underwriter can trace every AI data
point back to its source document. Documents are matched by application_id (the
EDMS rows live under tenant_id='default'); the loan itself is tenant-checked via
entity_states.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException

from api.accord.auth import get_tenant_id
from api.accord.pipeline import _get_pool, _require_db

router = APIRouter(prefix="/api/accord/documents", tags=["accord-documents"])


def _jsonb(v: Any) -> Any:
    if isinstance(v, (dict, list)) or v is None:
        return v
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return {}


def _iso(v: Any) -> Optional[str]:
    return v.isoformat() if hasattr(v, "isoformat") else v


def _money(v: Any) -> Optional[str]:
    try:
        return f"${float(v):,.0f}"
    except (TypeError, ValueError):
        return None


# doc_type → (display name, key extracted field, how to render the key value).
# Reconciled against all 53 live document_type values in document_index. Each
# `key` is verified to exist in that type's extracted_fields; `fmt` is one of
# money | money_mo | income_mo | score | bool | raw. `year` (optional) appends a
# tax/effective year to the display name. Grouped by document_category.
DOC_META: dict[str, dict] = {
    # ── income ──
    "W2_CURRENT": {"name": "W-2", "key": "box1_wages", "fmt": "money", "year": "tax_year"},
    "W2_PRIOR": {"name": "W-2 (Prior Year)", "key": "box1_wages", "fmt": "money", "year": "tax_year"},
    "PAYSTUB_CURRENT": {"name": "Pay Stub", "key": "gross_pay", "fmt": "money"},
    "IRS_TRANSCRIPT": {"name": "IRS Transcript", "key": "agi", "fmt": "money", "year": "tax_year"},
    "TAX_RETURN_1040": {"name": "1040 Tax Return", "key": "agi", "fmt": "money", "year": "tax_year"},
    "1099_NEC": {"name": "1099-NEC", "key": "nonemployee_compensation", "fmt": "money", "year": "tax_year"},
    "SCHEDULE_C": {"name": "Schedule C", "key": "net_profit", "fmt": "money", "year": "tax_year"},
    "SCHEDULE_E": {"name": "Schedule E", "key": "net_rental_income", "fmt": "money"},
    "COMMISSION_HISTORY": {"name": "Commission History", "key": "two_year_average", "fmt": "money", "year": "tax_year"},
    "OFFER_LETTER": {"name": "Offer Letter", "key": "salary", "fmt": "money"},
    "EMPLOYMENT_GAP_LETTER": {"name": "Employment Gap Letter", "key": None, "fmt": None},
    "PENSION_LETTER": {"name": "Pension Letter", "key": "monthly_benefit", "fmt": "money_mo"},
    "SSA_AWARD_LETTER": {"name": "SSA Award Letter", "key": "monthly_benefit", "fmt": "money_mo"},
    "RENTAL_LEASE": {"name": "Rental Lease", "key": "monthly_rent", "fmt": "money_mo"},
    "FOREIGN_INCOME_DOCS": {"name": "Foreign Income Docs", "key": "annual_income", "fmt": "money"},
    "FLOOD_INSURANCE": {"name": "Flood Insurance", "key": "coverage_amount", "fmt": "money"},
    # ── employment ──
    "VOE_TWN": {"name": "Employment Verification (TWN)", "key": "income_amount", "fmt": "money"},
    "VOE": {"name": "Employer Verification (VOE)", "key": "current_salary", "fmt": "money"},
    # ── credit ──
    "CREDIT_REPORT": {"name": "Credit Report", "key": "mid_score", "fmt": "score"},
    # ── asset ──
    "BANK_STATEMENT_M1": {"name": "Bank Statement (Month 1)", "key": "ending_balance", "fmt": "money"},
    "BANK_STATEMENT_M2": {"name": "Bank Statement (Month 2)", "key": "ending_balance", "fmt": "money"},
    "BANK_STATEMENT_M3": {"name": "Bank Statement (Month 3)", "key": "ending_balance", "fmt": "money"},
    "GIFT_LETTER": {"name": "Gift Letter", "key": "gift_amount", "fmt": "money"},
    "GIFT_DONOR_BANK_STATEMENT": {"name": "Gift Donor Bank Statement", "key": "withdrawal_amount", "fmt": "money"},
    # ── property ──
    "APPRAISAL_URAR": {"name": "Appraisal (URAR)", "key": "appraised_value", "fmt": "money"},
    "PURCHASE_AGREEMENT": {"name": "Purchase Agreement", "key": "purchase_price", "fmt": "money"},
    "BUILDER_CONTRACT": {"name": "Builder Contract", "key": "contract_price", "fmt": "money"},
    "CONDO_QUESTIONNAIRE": {"name": "Condo Questionnaire", "key": "fannie_approved", "fmt": "bool"},
    "PROPERTY_TAX_BILL": {"name": "Property Tax Bill", "key": "annual_tax", "fmt": "money", "year": "tax_year"},
    "FLOOD_CERT": {"name": "Flood Certification", "key": "flood_zone", "fmt": "raw"},
    "TITLE_COMMITMENT": {"name": "Title Commitment", "key": "policy_amount", "fmt": "money"},
    "TITLE_INSURANCE": {"name": "Title Insurance", "key": "coverage_amount", "fmt": "money"},
    "HOI_BINDER": {"name": "Homeowner's Insurance Binder", "key": "coverage_dwelling", "fmt": "money"},
    # ── identity ──
    "DRIVERS_LICENSE": {"name": "Driver's License", "key": None, "fmt": None},
    "PASSPORT": {"name": "Passport", "key": None, "fmt": None},
    "SSN_VALIDATION": {"name": "SSN Validation", "key": None, "fmt": None},
    "OFAC_CHECK": {"name": "OFAC Check", "key": None, "fmt": None},
    "EAD_CARD": {"name": "EAD Card", "key": None, "fmt": None},
    "I94": {"name": "Form I-94", "key": None, "fmt": None},
    "VISA_H1B": {"name": "H-1B Visa", "key": None, "fmt": None},
    # ── legal ──
    "DIVORCE_DECREE": {"name": "Divorce Decree", "key": "alimony_amount", "fmt": "money"},
    "ALIMONY_RECEIPT_HISTORY": {"name": "Alimony Receipt History", "key": "monthly_amount", "fmt": "money_mo"},
    # ── loan / loan_terms ──
    "URLA_1003": {"name": "URLA 1003", "key": "loan_amount", "fmt": "money"},
    "CLOSING_DISCLOSURE": {"name": "Closing Disclosure", "key": "section_a_total", "fmt": "money"},
    "LOAN_ESTIMATE": {"name": "Loan Estimate", "key": "section_a_total", "fmt": "money"},
    "RATE_LOCK": {"name": "Rate Lock", "key": "loan_amount", "fmt": "money"},
    "ESCROW_ANALYSIS": {"name": "Escrow Analysis", "key": "monthly_escrow", "fmt": "money_mo"},
    "MORTGAGE_PAYOFF": {"name": "Mortgage Payoff", "key": "current_balance", "fmt": "money"},
    "PAYMENT_HISTORY_24MO": {"name": "Payment History (24mo)", "key": "late_payments", "fmt": "raw"},
    # ── vendor ──
    "AUS_DU_FINDINGS": {"name": "AUS Findings (DU)", "key": "recommendation", "fmt": "raw"},
    "MI_CERTIFICATE": {"name": "MI Certificate", "key": "monthly_premium", "fmt": "money_mo"},
    "USDA_ELIGIBILITY": {"name": "USDA Eligibility", "key": "income_eligible", "fmt": "bool"},
    "VA_COE": {"name": "VA Certificate of Eligibility", "key": "entitlement_amount", "fmt": "money"},
}


def _display_name(doc_type: str, fields: dict) -> str:
    meta = DOC_META.get(doc_type, {})
    name = meta.get("name", doc_type.replace("_", " ").title())
    year = meta.get("year")
    if year and fields.get(year):
        return f"{name} ({fields[year]})"
    return name


def _key_value(doc_type: str, fields: dict) -> tuple[Optional[str], Optional[str]]:
    meta = DOC_META.get(doc_type, {})
    key = meta.get("key")
    if not key or fields.get(key) is None:
        return None, None
    val = fields[key]
    fmt = meta.get("fmt")
    if fmt == "money":
        return _money(val), key
    if fmt == "money_mo":
        return (f"{_money(val)}/mo" if _money(val) else None), key
    if fmt == "income_mo":  # monthly → annualized display
        return (f"{_money(float(val) * 12)}/yr" if _money(float(val) * 12) else None), key
    if fmt == "score":
        return f"Score {val}", key
    if fmt == "bool":
        return ("Yes" if val else "No"), key
    return str(val), key


# Required documents by loan profile.
BASE_REQUIRED = [
    ("URLA_1003", "URLA 1003", "Required application form"),
    ("CREDIT_REPORT", "Credit Report", "Required for credit assessment"),
    ("W2_CURRENT", "W2 (current year)", "Required for income verification"),
    ("DRIVERS_LICENSE", "Driver's License", "Required for identity"),
    ("PAY_STUBS", "Pay Stubs (30 days)", "Required for income verification"),
    ("BANK_STATEMENT", "Bank Statements (2 mo)", "Required for reserves"),
]
PURCHASE_REQUIRED = [
    ("PURCHASE_AGREEMENT", "Purchase Agreement", "Required for purchase transactions"),
    ("APPRAISAL_URAR", "Appraisal (URAR)", "Required to establish value"),
]
CLOSING_REQUIRED = [
    ("EMPLOYER_VERIFICATION", "Employer Verification (VOE)", "Required before closing (Fannie)"),
]
SELF_EMPLOYED_REQUIRED = [
    ("TAX_RETURN_1040", "1040 Tax Return", "Required for self-employed income"),
    ("PROFIT_LOSS", "P&L Statement", "Required for self-employed income"),
]


def _required_for(loan_type: str, loan_purpose: str, self_employed: bool) -> list[tuple]:
    req = list(BASE_REQUIRED)
    if (loan_purpose or "").lower() == "purchase":
        req += PURCHASE_REQUIRED
    else:
        req += [("APPRAISAL_URAR", "Appraisal (URAR)", "Required to establish value")]
    req += CLOSING_REQUIRED
    if self_employed:
        req += SELF_EMPLOYED_REQUIRED
    return req


async def _loan_or_404(conn, application_id: str, tenant_id: str):
    es = await conn.fetchrow(
        "SELECT * FROM entity_states WHERE application_id=$1 AND tenant_id=$2", application_id, tenant_id)
    if es is None:
        raise HTTPException(404, f"Unknown application {application_id}")
    return es


async def _docs(conn, application_id: str):
    return await conn.fetch(
        "SELECT document_id, document_type, document_category, status, confidence_score, extraction_method, "
        " extracted_fields, s3_key, received_at FROM document_index WHERE application_id=$1 ORDER BY document_type",
        application_id)


# ── 1. Document checklist (on file + missing) ───────────────────────
@router.get("/{application_id}")
async def get_documents(application_id: str, tenant_id: str = Depends(get_tenant_id)) -> dict:
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        es = await _loan_or_404(conn, application_id, tenant_id)
        rows = await _docs(conn, application_id)
    lt = _jsonb(es["loan_terms"]) or {}
    loan_type = lt.get("loan_type", "conventional")
    loan_purpose = (_jsonb(es["borrower"]) or {}).get("loan_purpose") or lt.get("loan_purpose") or "purchase"
    # self-employed hint from borrower.employment
    emp = (_jsonb(es["borrower"]) or {}).get("employment") or {}
    self_employed = bool(emp.get("self_employed")) if isinstance(emp, dict) else False

    documents = []
    on_file_types: set[str] = set()
    for r in rows:
        fields = _jsonb(r["extracted_fields"]) or {}
        kv, kf = _key_value(r["document_type"], fields)
        on_file_types.add(r["document_type"])
        documents.append({
            "document_id": r["document_id"],
            "document_type": r["document_type"],
            "document_category": r["document_category"],
            "display_name": _display_name(r["document_type"], fields),
            "status": r["status"],
            "indexed_at": _iso(r["received_at"]),
            "extraction_method": r["extraction_method"],
            "confidence": r["confidence_score"],
            "key_value": kv,
            "key_field": kf,
            "extracted_data": fields,
            "file_path": r["s3_key"],
        })

    missing = []
    for dtype, name, reason in _required_for(loan_type, loan_purpose, self_employed):
        if dtype not in on_file_types:
            missing.append({"document_type": dtype, "display_name": name, "required": True, "reason": reason})

    return {
        "application_id": application_id,
        "documents": documents,
        "missing_documents": missing,
        "summary": {
            "total_on_file": len(documents),
            "total_missing": len(missing),
            "total_required_missing": sum(1 for m in missing if m["required"]),
        },
    }


# ── 2. Source-match: every entity_state value traced to its document ──
def _find_doc(docmap: dict, *types: str):
    for t in types:
        if t in docmap:
            return docmap[t]
    return None


def _field(name, value, display, doc, source_field, status="verified"):
    return {
        "field_name": name, "value": value, "display_value": display,
        "source_document": doc["display_name"] if doc else None,
        "source_field": source_field,
        "document_id": doc["document_id"] if doc else None,
        "confidence": doc["confidence"] if doc else None,
        "status": status if doc else "missing",
    }


@router.get("/{application_id}/source-match")
async def source_match(application_id: str, tenant_id: str = Depends(get_tenant_id)) -> dict:
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        es = await _loan_or_404(conn, application_id, tenant_id)
        rows = await _docs(conn, application_id)

    # index docs by type, with extracted fields + display name
    docmap: dict[str, dict] = {}
    for r in rows:
        fields = _jsonb(r["extracted_fields"]) or {}
        docmap[r["document_type"]] = {
            "document_id": r["document_id"], "confidence": r["confidence_score"],
            "display_name": _display_name(r["document_type"], fields), "fields": fields,
        }

    prop = _jsonb(es["property"]) or {}
    verifications: list[dict] = []

    # ── INCOME ──
    urla = _find_doc(docmap, "URLA_1003")
    w2 = _find_doc(docmap, "W2_CURRENT")
    irs = _find_doc(docmap, "IRS_TRANSCRIPT")
    inc_fields = []
    stated = None
    if urla and urla["fields"].get("stated_income_monthly") is not None:
        stated = float(urla["fields"]["stated_income_monthly"]) * 12
        inc_fields.append(_field("Stated income", stated, f"{_money(stated)}/yr", urla, "stated_monthly_income × 12"))
    w2_inc = None
    if w2 and w2["fields"].get("box1_wages") is not None:
        w2_inc = float(w2["fields"]["box1_wages"])
        inc_fields.append(_field("W2 income", w2_inc, f"{_money(w2_inc)}/yr", w2, "Box 1 wages"))
    if irs and irs["fields"].get("adjusted_gross_income") is not None:
        irs_inc = float(irs["fields"]["adjusted_gross_income"])
        inc_fields.append(_field("IRS income", irs_inc, f"{_money(irs_inc)}/yr", irs, "Adjusted Gross Income"))
    inc_disc = {"exists": False}
    if stated and w2_inc:
        gap = abs(stated - w2_inc) / stated
        if gap > 0.25:
            inc_disc = {
                "exists": True,
                "description": f"Stated {_money(stated)} vs documented {_money(w2_inc)} ({gap * 100:.0f}% gap)",
                "severity": "high" if gap > 0.35 else "medium",
                "ai_used": f"{_money(w2_inc)} (verified from W2{', confirmed by IRS' if irs else ''})",
            }
        else:
            inc_disc = {"exists": False, "description": f"Stated and documented income agree within {gap * 100:.0f}%"}
    if inc_fields:
        verifications.append({"category": "income", "fields": inc_fields, "discrepancy": inc_disc})

    # ── CREDIT ──
    cr = _find_doc(docmap, "CREDIT_REPORT")
    if cr:
        cf = cr["fields"]
        fields = [_field("Credit score (mid)", cf.get("mid_score"), str(cf.get("mid_score")), cr, "Mid FICO score")]
        obligs = cf.get("monthly_obligations")
        if isinstance(obligs, list):
            fields.append(_field("Tradelines", len(obligs), f"{len(obligs)} accounts", cr, "Open tradelines"))
        fields.append(_field("Bankruptcies", cf.get("active_bankruptcy"), "None" if not cf.get("active_bankruptcy") else "Active", cr, "Public records"))
        verifications.append({"category": "credit", "fields": fields, "discrepancy": {"exists": False}})

    # ── PROPERTY ──
    apr = _find_doc(docmap, "APPRAISAL_URAR")
    pa = _find_doc(docmap, "PURCHASE_AGREEMENT")
    prop_fields = []
    appraised = purchase = None
    if apr and apr["fields"].get("appraised_value") is not None:
        appraised = float(apr["fields"]["appraised_value"])
        prop_fields.append(_field("Appraised value", appraised, _money(appraised), apr, "Opinion of value"))
    if pa and pa["fields"].get("purchase_price") is not None:
        purchase = float(pa["fields"]["purchase_price"])
        prop_fields.append(_field("Purchase price", purchase, _money(purchase), pa, "Contract price"))
    if es["ltv"] is not None:
        prop_fields.append({"field_name": "LTV", "value": float(es["ltv"]), "display_value": f"{float(es['ltv']):.1f}%",
                            "source_document": "Calculated", "source_field": "loan ÷ value", "document_id": None,
                            "confidence": None, "status": "computed"})
    prop_disc = {"exists": False}
    if appraised is not None and purchase is not None:
        if appraised < purchase:
            prop_disc = {"exists": True, "description": f"Appraised {_money(appraised)} < purchase {_money(purchase)} — value shortfall", "severity": "high"}
        else:
            prop_disc = {"exists": False, "description": f"Appraised {_money(appraised)} ≥ purchase {_money(purchase)} — adequate equity"}
    if prop_fields:
        verifications.append({"category": "property", "fields": prop_fields, "discrepancy": prop_disc})

    # ── LOAN TERMS ──
    lt_fields = []
    if urla and urla["fields"].get("loan_amount") is not None:
        la = float(urla["fields"]["loan_amount"])
        lt_fields.append(_field("Loan amount", la, _money(la), urla, "Requested amount"))
    if es["interest_rate"] is not None:
        lt_fields.append({"field_name": "Rate", "value": float(es["interest_rate"]), "display_value": f"{float(es['interest_rate']):.2f}%",
                          "source_document": "Rate Lock", "source_field": "Locked rate", "document_id": None, "confidence": None, "status": "verified"})
    loan_terms = _jsonb(es["loan_terms"]) or {}
    if loan_terms.get("loan_type"):
        lt_fields.append(_field("Type", loan_terms["loan_type"], str(loan_terms["loan_type"]).title(), urla, "Loan program"))
    if lt_fields:
        verifications.append({"category": "loan_terms", "fields": lt_fields, "discrepancy": {"exists": False}})

    # ── IDENTITY ──
    dl = _find_doc(docmap, "DRIVERS_LICENSE")
    id_fields = []
    name = (w2 and w2["fields"].get("employee_name")) or (dl and dl["fields"].get("name"))
    if name:
        id_fields.append(_field("Name", name, name, w2 or dl, "Employee / licensee name"))
    dl_state = dl["fields"].get("dl_state") if dl else None
    prop_state = prop.get("state") or (urla and urla["fields"].get("address_state"))
    if dl_state:
        id_fields.append(_field("License state", dl_state, dl_state, dl, "DL issuing state"))
    id_disc = {"exists": False}
    if dl_state and prop_state and dl_state != prop_state:
        id_disc = {"exists": True, "description": f"DL state ({dl_state}) does not match property state ({prop_state})", "severity": "medium"}
    if dl and dl["fields"].get("expired"):
        id_disc = {"exists": True, "description": "Driver's license is expired", "severity": "medium"}
    if id_fields:
        verifications.append({"category": "identity", "fields": id_fields, "discrepancy": id_disc})

    # ── EMPLOYMENT ──
    if w2 and (w2["fields"].get("employer_name") or w2["fields"].get("employer_ein")):
        emp_fields = []
        if w2["fields"].get("employer_name"):
            emp_fields.append(_field("Employer", w2["fields"]["employer_name"], w2["fields"]["employer_name"], w2, "Employer name"))
        if w2["fields"].get("employer_ein"):
            emp_fields.append(_field("Employer EIN", w2["fields"]["employer_ein"], w2["fields"]["employer_ein"], w2, "Employer EIN"))
        verifications.append({"category": "employment", "fields": emp_fields, "discrepancy": {"exists": False}})

    return {"application_id": application_id, "verifications": verifications}
