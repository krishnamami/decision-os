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
