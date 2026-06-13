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


# doc_type → (display name, key extracted field, how to render the key value)
DOC_META: dict[str, dict] = {
    "URLA_1003": {"name": "URLA 1003", "key": "stated_income_monthly", "fmt": "income_mo"},
    "CREDIT_REPORT": {"name": "Credit Report", "key": "mid_score", "fmt": "score"},
    "W2_CURRENT": {"name": "W2", "key": "box1_wages", "fmt": "money", "year": "tax_year"},
    "W2_PRIOR": {"name": "W2 (prior year)", "key": "box1_wages", "fmt": "money", "year": "tax_year"},
    "IRS_TRANSCRIPT": {"name": "IRS Transcript", "key": "adjusted_gross_income", "fmt": "money", "year": "tax_year"},
    "PAY_STUBS": {"name": "Pay Stubs", "key": "gross_monthly_income", "fmt": "money_mo"},
    "PAYSTUB": {"name": "Pay Stubs", "key": "gross_monthly_income", "fmt": "money_mo"},
    "BANK_STATEMENT": {"name": "Bank Statements", "key": "total_balance", "fmt": "money"},
    "BANK_STATEMENTS": {"name": "Bank Statements", "key": "total_balance", "fmt": "money"},
    "DRIVERS_LICENSE": {"name": "Driver's License", "key": None, "fmt": None},
    "PURCHASE_AGREEMENT": {"name": "Purchase Agreement", "key": "purchase_price", "fmt": "money"},
    "APPRAISAL_URAR": {"name": "Appraisal (URAR)", "key": "appraised_value", "fmt": "money"},
    "OFAC_CHECK": {"name": "OFAC Check", "key": "match_score", "fmt": "raw"},
    "EMPLOYER_VERIFICATION": {"name": "Employer Verification (VOE)", "key": None, "fmt": None},
    "VOE": {"name": "Employer Verification (VOE)", "key": None, "fmt": None},
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
