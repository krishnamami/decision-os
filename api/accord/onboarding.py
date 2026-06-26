"""Accord — customer onboarding API (CSV import → entity_states).

Validate a CSV without importing, import it (with optional column mapping for
non-template exports), download the template, and review import history.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile

from api.accord.auth import get_current_user, get_tenant_id
from api.accord.pipeline import _get_pool, _require_db
from core.onboarding.importer import LoanImporter, REQUIRED, TEMPLATE_COLUMNS, auto_map, evaluate_imported, parse_csv

router = APIRouter(prefix="/api/accord/onboarding", tags=["accord-onboarding"])

# PL-E — required columns for a product-matrix activation upload (products table).
REQUIRED_PRODUCT_COLS = ("product_id", "product_name", "loan_type", "loan_purpose",
                         "min_credit_score", "max_dti", "max_ltv", "max_loan_amount",
                         "is_active")

_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "templates" / "accord_import_template.csv"


def _slug(s: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _headers_match_template(headers: list[str]) -> bool:
    have = {_slug(h) for h in headers}
    return all(_slug(c) in have for c in REQUIRED)


async def _read_csv(file: UploadFile) -> tuple[list[str], list[dict]]:
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1", errors="replace")
    if not text.strip():
        raise HTTPException(400, "Uploaded file is empty")
    return parse_csv(text)


def _mapping_from_form(mapping: Optional[str]) -> Optional[dict]:
    if not mapping:
        return None
    try:
        return json.loads(mapping)
    except (TypeError, ValueError):
        raise HTTPException(422, "mapping must be valid JSON")


# ── 1. Validate (no import) ─────────────────────────────────────────
@router.post("/validate")
async def validate(file: UploadFile = File(...), mapping: Optional[str] = Form(None),
                   user: dict = Depends(get_current_user)) -> dict:
    _require_db()
    headers, rows = await _read_csv(file)
    m = _mapping_from_form(mapping)
    needs_mapping = m is None and not _headers_match_template(headers)
    result = LoanImporter(user["tenant_id"], user.get("user_id")).validate(rows, m)
    result["headers"] = headers
    result["needs_mapping"] = needs_mapping
    if needs_mapping:
        am = auto_map(headers)
        result["auto_mapping"] = am
        result["mapping_stats"] = {
            "auto": sum(1 for v in am.values() if v),
            "skipped": sum(1 for v in am.values() if not v),
            "total": len(headers),
        }
    return result


# ── 2. Import ───────────────────────────────────────────────────────
@router.post("/import")
async def import_csv(file: UploadFile = File(...), mapping: Optional[str] = Form(None),
                     user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in ("admin", "manager"):
        raise HTTPException(403, "Admin or manager access required to import loans")
    _require_db()
    headers, rows = await _read_csv(file)
    m = _mapping_from_form(mapping)
    imp = LoanImporter(user["tenant_id"], user.get("user_id"))
    pool = await _get_pool()
    async with pool.acquire() as conn:
        result = await imp.import_rows(conn, rows, m)
        # Evaluate the imported loans so they appear with AI decisions.
        if result.get("application_ids"):
            active = await conn.fetchrow(
                "SELECT rules, programs FROM tenant_rules WHERE tenant_id=$1 AND status='active'", user["tenant_id"])
            if active:
                rules = json.loads(active["rules"]) if isinstance(active["rules"], str) else active["rules"]
                programs = json.loads(active["programs"]) if isinstance(active["programs"], str) else (active["programs"] or ["conventional", "fha"])
                result["evaluation"] = await evaluate_imported(conn, user["tenant_id"], result["application_ids"], rules, programs)
    result["next_steps"] = [
        f"Accord is now evaluating your {result['imported']} loans with AI agents",
        "Results will appear in Pipeline within 2 minutes",
        "Upload documents via SFTP or the document portal (coming soon)",
    ]
    return result


# ── 3. Template download ────────────────────────────────────────────
@router.get("/template")
async def template() -> Response:
    if _TEMPLATE_PATH.exists():
        body = _TEMPLATE_PATH.read_text(encoding="utf-8")
    else:
        body = ",".join(TEMPLATE_COLUMNS) + "\n"
    return Response(
        content=body, media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=accord_import_template.csv"})


# ── 4. Import history ───────────────────────────────────────────────
@router.get("/status")
async def status(tenant_id: str = Depends(get_tenant_id)) -> dict:
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        n = await conn.fetchval("SELECT count(*) FROM entity_states WHERE application_id LIKE $1", f"APP-IMP-{tenant_id}-%")
        recent = await conn.fetch(
            "SELECT application_id, loan_status, created_at FROM entity_states WHERE application_id LIKE $1 ORDER BY created_at DESC LIMIT 10",
            f"APP-IMP-{tenant_id}-%")
    return {"imported_total": n, "recent": [{"application_id": r["application_id"], "loan_status": r["loan_status"],
                                             "created_at": r["created_at"].isoformat() if r["created_at"] else None} for r in recent]}


# ── 5. Saved column mappings ────────────────────────────────────────
@router.get("/mappings")
async def list_mappings(tenant_id: str = Depends(get_tenant_id)) -> dict:
    _require_db()
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT mapping_id, mapping_name, source_system, column_mapping FROM import_mappings WHERE tenant_id=$1 ORDER BY created_at DESC", tenant_id)
    return {"mappings": [{"mapping_id": str(r["mapping_id"]), "mapping_name": r["mapping_name"],
                          "source_system": r["source_system"], "column_mapping": r["column_mapping"]} for r in rows]}


@router.post("/mappings")
async def save_mapping(payload: dict, user: dict = Depends(get_current_user)) -> dict:
    _require_db()
    pool = await _get_pool()
    from uuid import UUID
    try:
        uid = UUID(str(user.get("user_id")))
    except (ValueError, TypeError):
        uid = None
    async with pool.acquire() as conn:
        mid = await conn.fetchval(
            "INSERT INTO import_mappings (tenant_id, mapping_name, source_system, column_mapping, created_by) "
            "VALUES ($1,$2,$3,$4::jsonb,$5) RETURNING mapping_id",
            user["tenant_id"], payload.get("mapping_name", "Custom mapping"), payload.get("source_system", "custom"),
            json.dumps(payload.get("column_mapping") or {}), uid)
    return {"ok": True, "mapping_id": str(mid)}


# ── PL-C — Platform Studio credit-policy PDF extractor (EXTRACT stage only) ──
@router.post("/extract-policy")
async def extract_policy(
    file: UploadFile = File(...),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Extract a lender credit-policy PDF into a DRAFT overlay proposal (rules JSONB
    + the 3 typed overlay_rules) with per-field confidence + source quotes. Writes
    NOTHING — the admin reviews the proposal, then uses the existing rules.py flow
    (validate_overlay -> create version -> activate) to stage + activate it."""
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(400, "empty file")
    from core.extraction.policy_extractor import CreditPolicyExtractor
    proposal = await CreditPolicyExtractor().extract(file_bytes, file.filename or "policy.pdf")
    proposal["tenant_id"] = tenant_id
    return proposal


# ── PL-D — Platform Studio rate-sheet CSV extractor (EXTRACT stage only) ──
@router.post("/extract-rate-sheet")
async def extract_rate_sheet(
    file: UploadFile = File(...),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Extract a lender rate-sheet CSV into a DRAFT proposal — rate_sheet_entry_rows
    (tenant base rates) + llpa_rows (FICO×LTV + adjustment grid) with per-row
    confidence + source provenance (RULE 11). Writes NOTHING — the admin reviews
    the proposal, then activates via the existing rate_sheet_upload endpoint (base
    rates) / refresh_llpa_grid promote path (LLPA grid). Stdlib csv only."""
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(400, "empty file")
    from core.extraction.rate_sheet_extractor import RateSheetExtractor
    proposal = RateSheetExtractor().extract(file_bytes, file.filename or "rates.csv")
    proposal["tenant_id"] = tenant_id
    return proposal


# ── PL-E — Platform Studio product-matrix CSV extractor (EXTRACT stage only) ──
@router.post("/extract-product-matrix")
async def extract_product_matrix(
    file: UploadFile = File(...),
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Extract a lender product-matrix CSV into a DRAFT proposal — `products`-shaped
    rows with per-row confidence + warnings + source provenance (RULE 11). Writes
    NOTHING — the admin reviews the proposal, then activates via /products/upload."""
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(400, "empty file")
    from core.extraction.product_matrix_extractor import ProductMatrixExtractor
    proposal = ProductMatrixExtractor().extract(
        file_bytes, file.filename or "products.csv", tenant_id)
    proposal["tenant_id"] = tenant_id
    return proposal


# ── PL-E — product-matrix ACTIVATE path (upsert into the products table) ──
@router.post("/products/upload")
async def upload_products(file: UploadFile = File(...),
                          user: dict = Depends(get_current_user)) -> dict:
    """Activate a reviewed product-matrix CSV into the tenant's products table.
    Admin/manager only. This is the FIRST programmatic writer of the products
    matrix table (outside the seed script). The products PK is product_id ALONE,
    so the upsert is tenant-guarded: a product_id already owned by ANOTHER tenant
    is rejected (surfaced in errors), never silently overwritten."""
    if user.get("role") not in ("admin", "manager"):
        raise HTTPException(403, "Admin or manager access required to upload products")
    _require_db()
    tenant_id = user["tenant_id"]
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "empty file")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1", errors="replace")
    if not text.strip():
        raise HTTPException(400, "Uploaded file is empty")

    reader = csv.DictReader(io.StringIO(text))
    cols = {(h or "").strip() for h in (reader.fieldnames or [])}
    missing = [c for c in REQUIRED_PRODUCT_COLS if c not in cols]
    if missing:
        raise HTTPException(422, f"CSV missing required columns: {', '.join(missing)}")

    errors: list = []
    uploaded = 0
    skipped_other_tenant = 0
    rows_in_file = 0

    def _int(v):
        v = (v or "").strip()
        return int(float(v)) if v else None

    def _flt(v):
        v = (v or "").strip()
        return float(v) if v else None

    pool = await _get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            for i, r in enumerate(reader, start=2):
                rows_in_file += 1
                try:
                    pid = (r["product_id"] or "").strip()
                    name = (r["product_name"] or "").strip()
                    if not pid or not name:
                        raise ValueError("product_id and product_name are required")
                    is_active = str(r.get("is_active", "")).strip().lower() in (
                        "yes", "y", "true", "1", "active", "offered", "approved")
                    res = await conn.fetchrow(
                        "INSERT INTO products "
                        "(product_id, tenant_id, product_name, loan_type, loan_purpose, "
                        " min_credit_score, max_dti, max_ltv, max_loan_amount, is_active) "
                        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) "
                        "ON CONFLICT (product_id) DO UPDATE SET "
                        "  product_name=EXCLUDED.product_name, loan_type=EXCLUDED.loan_type, "
                        "  loan_purpose=EXCLUDED.loan_purpose, min_credit_score=EXCLUDED.min_credit_score, "
                        "  max_dti=EXCLUDED.max_dti, max_ltv=EXCLUDED.max_ltv, "
                        "  max_loan_amount=EXCLUDED.max_loan_amount, is_active=EXCLUDED.is_active "
                        "WHERE products.tenant_id = EXCLUDED.tenant_id "
                        "RETURNING product_id",
                        pid, tenant_id, name,
                        (r.get("loan_type") or "").strip() or "conventional",
                        (r.get("loan_purpose") or "").strip() or "purchase",
                        _int(r.get("min_credit_score")), _flt(r.get("max_dti")),
                        _flt(r.get("max_ltv")), _int(r.get("max_loan_amount")), is_active)
                    if res is None:
                        # conflict on product_id but owned by another tenant — never clobber
                        skipped_other_tenant += 1
                        errors.append({"row": i, "product_id": pid,
                                       "error": "product_id already owned by another tenant — not overwritten"})
                    else:
                        uploaded += 1
                except (ValueError, TypeError, KeyError) as e:
                    errors.append({"row": i, "error": str(e)})
                if len(errors) > 50:
                    break
            # Best-effort freshness log — never fail the upload over this.
            try:
                await conn.execute(
                    "INSERT INTO data_source_status (source_id, source_name, last_download, last_success, record_count, status, updated_at) "
                    "VALUES ('products','Product Matrix Upload',NOW(),NOW(),$1,'ok',NOW()) "
                    "ON CONFLICT (source_id) DO UPDATE SET last_download=NOW(), last_success=NOW(), "
                    "record_count=$1, status='ok', error_message=NULL, updated_at=NOW()",
                    uploaded)
            except Exception:
                pass

    if uploaded == 0 and rows_in_file > 0:
        raise HTTPException(422, detail={"message": "No valid rows uploaded", "errors": errors[:10]})

    return {"uploaded": uploaded, "rows_in_file": rows_in_file,
            "skipped_other_tenant": skipped_other_tenant, "errors": errors[:10],
            "tenant_id": tenant_id, "uploaded_at": datetime.utcnow().isoformat() + "Z"}


# ══════════════════════════════════════════════════════════════════════
# PL-A — the 4 onboarding-step endpoints that close the 8-step API surface.
#
# All four are CONFIG layer: tenant-scoped, admin/manager-gated, and never
# touch the decision path (no persona wiring, no decision_outputs / entity_states
# writes). 16/16 holds by construction. The validation/normalization logic lives
# in PURE module-level helpers (below) so it is unit-testable without a DB — the
# endpoints are thin wrappers that add the I/O (same posture as the resolvers).
# RULE 11: every response carries data_source + missing_inputs.
# ══════════════════════════════════════════════════════════════════════

_US_STATES = frozenset(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO "
    "MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split())

_COMPANY_TYPES = ("bank", "credit_union", "imc", "broker", "other")


def _require_admin_manager(user: dict) -> None:
    if user.get("role") not in ("admin", "manager"):
        raise HTTPException(403, "Admin or manager access required")


def build_company_update(payload: dict) -> tuple:
    """Pure: (name, settings_patch, errors) for the company step. Required:
    company_name + nmls_id. Optional: contact_email, primary_state, company_type."""
    payload = payload or {}
    errors: list = []
    name = str(payload.get("company_name") or "").strip()
    nmls = str(payload.get("nmls_id") or "").strip()
    if not name:
        errors.append("company_name is required")
    if not nmls:
        errors.append("nmls_id is required")

    patch: dict = {}
    if nmls:
        patch["nmls_id"] = nmls
    email = str(payload.get("contact_email") or "").strip()
    if email:
        if "@" not in email or "." not in email.split("@")[-1]:
            errors.append("contact_email is not a valid email")
        else:
            patch["contact_email"] = email
    state = str(payload.get("primary_state") or "").strip().upper()
    if state:
        if state not in _US_STATES:
            errors.append(f"primary_state {state!r} is not a US state code")
        else:
            patch["primary_state"] = state
    ctype = str(payload.get("company_type") or "").strip().lower()
    if ctype:
        patch["company_type"] = ctype if ctype in _COMPANY_TYPES else "other"
    return name, patch, errors


def validate_licenses(payload: dict) -> tuple:
    """Pure: (licenses, errors, warnings). Each license needs state + license_number.
    An unrecognized state is a WARNING, not a hard error (deduped by state, last wins)."""
    payload = payload or {}
    errors: list = []
    warnings: list = []
    raw = payload.get("licenses")
    if not isinstance(raw, list) or not raw:
        errors.append("licenses must be a non-empty list")
        return [], errors, warnings

    by_state: dict = {}
    for i, lic in enumerate(raw):
        if not isinstance(lic, dict):
            errors.append(f"license[{i}] must be an object")
            continue
        st = str(lic.get("state") or "").strip().upper()
        num = str(lic.get("license_number") or "").strip()
        if not st or not num:
            errors.append(f"license[{i}] requires state + license_number")
            continue
        if st not in _US_STATES:
            warnings.append(f"{st} is not a recognized US state code")
        by_state[st] = {
            "state": st, "license_number": num,
            "license_type": str(lic.get("license_type") or "").strip() or "lender",
            "expiry_date": str(lic.get("expiry_date") or "").strip() or None,
        }
    return list(by_state.values()), errors, warnings


def validate_exception_config(payload: dict) -> tuple:
    """Pure: (config, errors). Bounds: max_exception_level 1-4; auto-escalate DTI
    <= 60 (cannot exceed the agency ceiling); auto-escalate LTV <= 100;
    required_compensating_factors 0-6 (the CompensatingFactorsEngine detects 6)."""
    payload = payload or {}
    errors: list = []
    cfg: dict = {}

    lvl = payload.get("max_exception_level")
    if lvl is None:
        errors.append("max_exception_level is required")
    else:
        try:
            lvl = int(lvl)
            if not 1 <= lvl <= 4:
                errors.append("max_exception_level must be between 1 and 4")
            else:
                cfg["max_exception_level"] = lvl
        except (TypeError, ValueError):
            errors.append("max_exception_level must be an integer")

    def _bounded(key, lo, hi, ceiling_msg):
        v = payload.get(key)
        if v is None:
            return
        try:
            v = float(v)
        except (TypeError, ValueError):
            errors.append(f"{key} must be numeric")
            return
        if v < lo or v > hi:
            errors.append(ceiling_msg)
        else:
            cfg[key] = v

    _bounded("auto_escalate_dti_threshold", 0.0, 60.0,
             "auto_escalate_dti_threshold cannot exceed the agency ceiling of 60%")
    _bounded("auto_escalate_ltv_threshold", 0.0, 100.0,
             "auto_escalate_ltv_threshold cannot exceed 100%")

    cf = payload.get("required_compensating_factors")
    if cf is not None:
        try:
            cf = int(cf)
            if not 0 <= cf <= 6:
                errors.append("required_compensating_factors must be between 0 and 6")
            else:
                cfg["required_compensating_factors"] = cf
        except (TypeError, ValueError):
            errors.append("required_compensating_factors must be an integer")

    roles = payload.get("exception_approval_roles")
    if roles is not None:
        if not isinstance(roles, list) or not all(isinstance(r, str) for r in roles):
            errors.append("exception_approval_roles must be a list of role strings")
        else:
            cfg["exception_approval_roles"] = roles
    return cfg, errors


# Synthetic, well-formed borrower profiles for the test-loan probe (no PII, no DB).
_TEST_PROFILES = {
    "clean_approval": {"mid_credit_score": 760, "dti_back": 32.0, "ltv": 75.0,
                       "loan_amount": 400000, "qualifying_monthly": 12000,
                       "piti_monthly": 2200, "monthly_obligations": 600, "loan_type": "conventional"},
    "borderline": {"mid_credit_score": 648, "dti_back": 46.0, "ltv": 96.0,
                   "loan_amount": 520000, "qualifying_monthly": 8200,
                   "piti_monthly": 2600, "monthly_obligations": 1200, "loan_type": "conventional"},
    "fraud": {"mid_credit_score": 590, "dti_back": 58.0, "ltv": 99.0,
              "loan_amount": 980000, "qualifying_monthly": 6000,
              "piti_monthly": 3400, "monthly_obligations": 2100, "loan_type": "conventional"},
}


def synthetic_test_profile(scenario: str) -> dict:
    return dict(_TEST_PROFILES.get(scenario or "clean_approval", _TEST_PROFILES["clean_approval"]))


def advise_test_loan(profile: dict) -> dict:
    """Pure, no-write advisory probe: runs the existing ProgramRecommender (EX2-B,
    sync + DB-less) over the profile and maps its eligibility to an advisory
    outcome. This is NOT the 14-persona engine (that path WRITES decision_outputs);
    it is a config-coherence probe that proves the product/threshold config is wired,
    without persisting anything. The honest engine label is reported in the result."""
    from core.products.program_recommender import ProgramRecommender
    rec = ProgramRecommender().recommend(profile or {})
    if rec.get("eligible_count"):
        outcome = "recommend"
    elif rec.get("near_miss_count"):
        outcome = "escalate"
    else:
        outcome = "block"
    return {
        "outcome": outcome,
        "engine": "ProgramRecommender (advisory product-eligibility probe)",
        "eligible_products": [p["product_id"] for p in rec.get("eligible_products", [])],
        "top_recommendation": (rec.get("top_recommendation") or {}).get("product_id"),
        "profile_summary": rec.get("profile_summary"),
        "advisory": True,
        "writes_decision_outputs": False,
        "note": ("Advisory config probe only — does NOT run the 14-persona engine and "
                 "writes nothing. The full evaluation (which persists decision_outputs) "
                 "runs when a real loan is imported via POST /onboarding/import."),
        "data_source": "synthetic profile + ProgramRecommender (in memory)",
        "missing_inputs": rec.get("missing_inputs", []),
    }


# ── Step 1 — company identity + NMLS ──────────────────────────────────
@router.post("/company")
async def setup_company(payload: dict, user: dict = Depends(get_current_user)) -> dict:
    """Register company identity + NMLS. Upserts the tenant name + merges the
    company fields into tenants.settings (JSONB). Admin/manager only."""
    _require_admin_manager(user)
    _require_db()
    name, patch, errors = build_company_update(payload)
    if errors:
        raise HTTPException(422, detail={"message": "Invalid company payload", "errors": errors})
    tenant_id = user["tenant_id"]
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE tenants SET name=$2, "
            "settings = COALESCE(settings,'{}'::jsonb) || $3::jsonb, updated_at=NOW() "
            "WHERE tenant_id=$1",
            tenant_id, name, json.dumps(patch))
    return {"tenant_id": tenant_id, "company_name": name, "nmls_id": patch.get("nmls_id"),
            "settings_saved": sorted(patch.keys()), "status": "company_registered",
            "data_source": "tenants table", "missing_inputs": []}


# ── Step 2 — state lending licenses ───────────────────────────────────
@router.post("/licenses")
async def setup_licenses(payload: dict, user: dict = Depends(get_current_user)) -> dict:
    """Register state lending licenses into tenants.settings.licenses[] (deduped by
    state). Unrecognized state codes are warnings, not errors. Admin/manager only."""
    _require_admin_manager(user)
    _require_db()
    licenses, errors, warnings = validate_licenses(payload)
    if errors:
        raise HTTPException(422, detail={"message": "Invalid licenses payload", "errors": errors})
    tenant_id = user["tenant_id"]
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE tenants SET settings = COALESCE(settings,'{}'::jsonb) || "
            "jsonb_build_object('licenses', $2::jsonb), updated_at=NOW() WHERE tenant_id=$1",
            tenant_id, json.dumps(licenses))
    return {"tenant_id": tenant_id, "licenses_registered": len(licenses),
            "states": [l["state"] for l in licenses], "warnings": warnings,
            "status": "licenses_registered", "data_source": "tenants.settings.licenses",
            "missing_inputs": []}


# ── Step 5 — exception-framework configuration ────────────────────────
@router.post("/exception-config")
async def setup_exception_config(payload: dict, user: dict = Depends(get_current_user)) -> dict:
    """Configure the exception framework. Validates bounds (level 1-4, DTI ≤ 60%,
    LTV ≤ 100%, CFs 0-6 — never above agency ceilings). Stored additively under the
    active tenant_rules.rules.exceptions (decision-path-inert — the live personas do
    not read it); falls back to tenants.settings.exception_config if no active rules
    version exists yet. Admin/manager only."""
    _require_admin_manager(user)
    _require_db()
    cfg, errors = validate_exception_config(payload)
    if errors:
        raise HTTPException(422, detail={"message": "Invalid exception config", "errors": errors})
    tenant_id = user["tenant_id"]
    pool = await _get_pool()
    stored_in = "tenants.settings.exception_config"
    rule_version = None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT rule_version_id, version, rules FROM tenant_rules "
            "WHERE tenant_id=$1 AND status='active' ORDER BY version DESC LIMIT 1", tenant_id)
        if row:
            rules = row["rules"]
            if isinstance(rules, str):
                rules = json.loads(rules)
            rules = rules or {}
            rules["exceptions"] = cfg  # additive subkey, not read by the live engine
            await conn.execute("UPDATE tenant_rules SET rules=$2::jsonb WHERE rule_version_id=$1",
                               row["rule_version_id"], json.dumps(rules))
            stored_in = "tenant_rules.rules.exceptions"
            rule_version = row["version"]
        else:
            await conn.execute(
                "UPDATE tenants SET settings = COALESCE(settings,'{}'::jsonb) || "
                "jsonb_build_object('exception_config', $2::jsonb), updated_at=NOW() "
                "WHERE tenant_id=$1", tenant_id, json.dumps(cfg))
    return {"tenant_id": tenant_id, "exception_config": cfg, "rule_version": rule_version,
            "stored_in": stored_in, "status": "exception_config_saved",
            "data_source": stored_in, "missing_inputs": []}


# ── Step 8 — advisory test loan (no decision_outputs write) ───────────
@router.post("/test-loan")
async def run_test_loan(payload: dict = None, user: dict = Depends(get_current_user)) -> dict:
    """Run a synthetic test loan through an ADVISORY config probe (the pure
    ProgramRecommender — never the writing 14-persona engine). Persists NOTHING.
    Validates the tenant config is coherent end-to-end. Admin/manager only.
    Payload: {scenario?: clean_approval|borderline|fraud, profile?: {...}}."""
    _require_admin_manager(user)
    payload = payload or {}
    profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else None
    if not profile:
        profile = synthetic_test_profile(payload.get("scenario", "clean_approval"))
    result = advise_test_loan(profile)

    # Best-effort config-readiness checks (degrade gracefully on a slow/absent DB).
    checks = {"active_rules": None, "products": None, "users": None}
    missing = list(result.get("missing_inputs") or [])
    try:
        _require_db()
        tenant_id = user["tenant_id"]
        pool = await _get_pool()
        async with pool.acquire() as conn:
            checks["active_rules"] = bool(await conn.fetchval(
                "SELECT 1 FROM tenant_rules WHERE tenant_id=$1 AND status='active' LIMIT 1", tenant_id))
            checks["products"] = int(await conn.fetchval(
                "SELECT count(*) FROM products WHERE tenant_id=$1", tenant_id) or 0)
            checks["users"] = int(await conn.fetchval(
                "SELECT count(*) FROM users WHERE tenant_id=$1", tenant_id) or 0)
    except Exception:
        missing.append("config readiness checks unavailable (DB) — recommendation still computed")

    config_valid = bool(checks.get("active_rules")) and bool(checks.get("products"))
    result.update({
        "tenant_id": user.get("tenant_id"),
        "scenario": payload.get("scenario", "clean_approval"),
        "config_checks": checks,
        "config_valid": config_valid,
        "missing_inputs": missing,
    })
    return result
