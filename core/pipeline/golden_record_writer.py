"""
Golden Record Writer — RA-EX-B

The LIVE document_index -> entity_states populator. Loads an application's
current documents, runs them through golden_record_builder.build_golden_record
(the pure derivation primitives), and — only when explicitly asked — writes the
derived golden-record columns back to entity_states.

WHY write defaults to FALSE (dry-run):
  The meridian fixtures are hand-seeded and tuned for scenario outcomes (RA-2),
  and two extraction gaps mean the derived record currently DIFFERS from those
  fixtures (RA-EX-B dry-run): LTV (purchase_price is not yet extracted from the
  purchase agreement — RA-EX-D — so the lesser-of falls back to appraised value)
  and tuned per-scenario obligations. Blanket-writing would change LTV on every
  meridian app and break 16/16. So this writer:
    * NEVER runs on meridian as part of the eval,
    * defaults to dry_run (returns the diff, writes nothing),
    * is the production ingestion path for NEW loans once RA-EX-C/D close the
      remaining field gaps (purchase_price, credit tradelines, large deposits).

Only the top-level scalar columns golden_record derives are touched, and only
when the derived value is not None (safe/additive — never nulls a seeded value).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from core.pipeline.golden_record_builder import build_golden_record

logger = logging.getLogger(__name__)

# Golden-record key -> entity_states scalar column. Nested/derived fields
# (flood_zone, property_type, occupancy_type, loan_purpose, loan_type) live in
# loan_terms/property JSONB and are intentionally NOT written here — they need a
# JSONB merge the ingestion path owns; this writer only sets the flat columns.
_COLUMN_MAP = {
    "mid_credit_score":    "mid_credit_score",
    "ltv":                 "ltv",
    "appraised_value":     "appraised_value",
    "purchase_price":      "purchase_price",
    "loan_amount":         "loan_amount",
    "monthly_obligations": "monthly_obligations",
}


async def load_doc_map(conn, application_id: str, tenant_id: str) -> dict:
    """Build the {document_type: {extracted_fields}} map from the application's
    CURRENT documents (latest current row per type)."""
    rows = await conn.fetch(
        """
        SELECT document_type, extracted_fields
        FROM document_index
        WHERE application_id = $1 AND tenant_id = $2 AND is_current = true
        ORDER BY document_type
        """,
        application_id, tenant_id,
    )
    doc_map: dict[str, dict] = {}
    for r in rows:
        fields = r["extracted_fields"]
        if isinstance(fields, str):
            try:
                fields = json.loads(fields)
            except Exception:  # noqa: BLE001
                fields = {}
        doc_map[r["document_type"]] = {"extracted_fields": fields or {}}
    return doc_map


def _num(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(v: Any) -> Optional[int]:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _inq_last_90(inquiries: Any) -> Optional[int]:
    """Count credit inquiries within the last 90 days. Defensive: the inquiry
    date lives under a few possible keys; if none parse, fall back to the total
    array length. Returns None only when the input isn't a list."""
    from datetime import datetime, timedelta, timezone
    if not isinstance(inquiries, list):
        return None
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=90)
    recent, parsed_any = 0, False
    for it in inquiries:
        d = it.get('date') or it.get('inquiry_date') or it.get('pulled_at') if isinstance(it, dict) else None
        if not d:
            continue
        try:
            dt = datetime.fromisoformat(str(d)[:10]).date()
            parsed_any = True
            if dt >= cutoff:
                recent += 1
        except (ValueError, TypeError):
            continue
    return recent if parsed_any else len(inquiries)


# v4.9 canonical columns written additively by the golden-record path. Strings/
# dates/ints/bools — the numeric _COLUMN_MAP diff path above only covers floats.
_V49_COLUMNS = (
    "amortization_type", "lien_position", "lien_status_hmda", "credit_report_date",
    "public_records_count", "inquiries_last_90", "residual_income", "action_taken",
    "aus_submission_count", "manual_review_required",
)


async def _derive_v49_columns(
    conn, application_id: str, tenant_id: str, golden: dict, cur: dict,
) -> dict:
    """Compute the 10 v4.9 canonical columns (RA-2B / Capital Loans). Three come
    from the pure golden record (doc-derived); seven are queried from
    credit_profiles / aus_results / decision_outputs / entity_states. Returns
    {col: value}; None where no source exists (never invents a value)."""
    out: dict[str, Any] = {
        "amortization_type":    golden.get("amortization_type"),
        "lien_position":        golden.get("lien_position"),
        "lien_status_hmda":     golden.get("lien_status_hmda"),
        "credit_report_date":   None,
        "public_records_count": None,
        "inquiries_last_90":    None,
        "residual_income":      None,
        "action_taken":         "application_received",   # default for a new loan
        "aus_submission_count": 0,
        "manual_review_required": False,
    }

    # credit_profiles — joined by applicant_id (NOT application_id); JSONB is
    # profile_data (NOT credit_data). Empty for summit today -> stays None.
    applicant_id = (cur or {}).get("applicant_id")
    if applicant_id:
        cp = await conn.fetchrow(
            """SELECT report_date, profile_data FROM credit_profiles
               WHERE applicant_id=$1 AND tenant_id=$2 AND is_current=true
               ORDER BY report_date DESC NULLS LAST LIMIT 1""",
            applicant_id, tenant_id,
        )
        if cp:
            out["credit_report_date"] = cp["report_date"]
            pd = cp["profile_data"]
            if isinstance(pd, str):
                try:
                    pd = json.loads(pd)
                except Exception:  # noqa: BLE001
                    pd = {}
            pd = pd or {}
            pr = pd.get("public_records")
            out["public_records_count"] = (
                len(pr) if isinstance(pr, list) else _int(pd.get("public_records_count")))
            inq = pd.get("inquiries")
            out["inquiries_last_90"] = (
                _inq_last_90(inq) if isinstance(inq, list) else _int(pd.get("inquiries_last_90")))

    # residual_income = qualifying_monthly - obligations - (appraised * 0.0014).
    # NULL when qualifying_monthly is NULL.
    qm = (cur or {}).get("qualifying_monthly")
    if qm is not None:
        oblig = _num(golden.get("monthly_obligations")) or _num((cur or {}).get("monthly_obligations")) or 0.0
        appr = _num(golden.get("appraised_value")) or _num((cur or {}).get("appraised_value")) or 0.0
        out["residual_income"] = round(float(qm) - oblig - appr * 0.0014, 2)

    # action_taken — from the human-reviewed underwriting decision.
    ha = await conn.fetchval(
        """SELECT human_action FROM decision_outputs
           WHERE application_id=$1 AND tenant_id=$2 AND decision_id='underwriting_decision'
             AND human_action IS NOT NULL ORDER BY version DESC LIMIT 1""",
        application_id, tenant_id,
    )
    if ha == "approved":
        out["action_taken"] = "loan_originated"
    elif ha == "denied":
        out["action_taken"] = "application_denied"

    # aus_results — submission count + manual-review (refer) downgrade flag.
    out["aus_submission_count"] = await conn.fetchval(
        "SELECT COUNT(*) FROM aus_results WHERE application_id=$1 AND tenant_id=$2",
        application_id, tenant_id) or 0
    out["manual_review_required"] = await conn.fetchval(
        """SELECT EXISTS(SELECT 1 FROM aus_results WHERE application_id=$1 AND tenant_id=$2
             AND recommendation ILIKE '%refer%' AND COALESCE(system,'') <> 'MANUAL')""",
        application_id, tenant_id) or False
    return out


async def _write_w2_income_source(
    conn, application_id: str, tenant_id: str,
) -> bool:
    """INC-A: populate income_sources with the primary borrower's W2 stream from
    the extracted W2 document. ADDITIVE — entity_states.qualifying_monthly is left
    untouched (the 14 personas still read it). Best-effort: returns False (never
    raises) if there is no W2 doc, no wages, or the income_sources table is
    absent. Idempotent — replaces the current primary W2 row on re-ingest."""
    try:
        row = await conn.fetchrow(
            """SELECT document_id, extracted_fields, confidence_score
               FROM document_index
               WHERE application_id=$1 AND tenant_id=$2
                 AND document_type='W2_CURRENT' AND is_current=true
               LIMIT 1""",
            application_id, tenant_id,
        )
        if not row:
            return False
        fields = row["extracted_fields"]
        if isinstance(fields, str):
            fields = json.loads(fields) if fields else {}
        fields = fields or {}
        annual = _num(fields.get("box1_wages"))
        if not annual:
            return False
        monthly = round(annual / 12.0, 2)
        employer = fields.get("employer_name")
        confidence = _num(row["confidence_score"]) or 0.0

        # Idempotent: clear any prior current primary W2 stream, then insert.
        await conn.execute(
            """UPDATE income_sources SET is_current=false, updated_at=NOW()
               WHERE application_id=$1 AND tenant_id=$2
                 AND borrower_role='primary' AND income_type='W2'
                 AND is_current=true""",
            application_id, tenant_id,
        )
        await conn.execute(
            """INSERT INTO income_sources (
                   application_id, tenant_id, borrower_role, income_type,
                   employer_name, monthly_amount, frequency, is_current,
                   confidence, method, doc_references)
               VALUES ($1,$2,'primary','W2',$3,$4,'monthly',true,$5,
                       'W2 box1/12',$6)""",
            application_id, tenant_id, employer, monthly, confidence,
            [row["document_id"]],
        )
        logger.info("income_sources: wrote W2 stream %s/mo for %s",
                    monthly, application_id)
        return True
    except Exception as exc:  # noqa: BLE001 — additive, must never break ingestion
        logger.warning("income_sources W2 write skipped for %s: %s",
                       application_id, exc)
        return False


async def apply_golden_record(
    conn,
    application_id: str,
    tenant_id: str,
    *,
    write: bool = False,
    **builder_kw,
) -> dict:
    """Derive the golden record from the application's documents and diff it
    against the current entity_states. Returns
    ``{golden, current, diff, written}``.

    write=False (DEFAULT) is a dry-run: nothing is written. write=True updates
    the mapped scalar columns where the derived value is not None. NEVER call
    with write=True on the meridian demo tenant — see module docstring.
    """
    # Hard guard: the meridian fixtures are hand-seeded scenarios that
    # deliberately contradict the seeded documents (e.g. SC08 mid 578 vs doc
    # 760), so writing the derived record would break 16/16. Dry-run (write=
    # False) over meridian is still allowed and useful.
    if write and tenant_id == "meridian":
        raise ValueError(
            "Cannot write golden record over meridian fixtures. "
            "These are hand-seeded scenarios — use write=False for dry-run."
        )

    doc_map = await load_doc_map(conn, application_id, tenant_id)
    golden = build_golden_record(doc_map, **builder_kw)

    current_row = await conn.fetchrow(
        """
        SELECT mid_credit_score, ltv, appraised_value, purchase_price,
               loan_amount, monthly_obligations, qualifying_monthly,
               borrower ->> 'applicant_id' AS applicant_id
        FROM entity_states
        WHERE application_id = $1 AND tenant_id = $2
        """,
        application_id, tenant_id,
    )
    current = dict(current_row) if current_row else {}

    # v4.9 — 10 canonical columns (3 doc-derived from `golden`, 7 from DB).
    v49 = await _derive_v49_columns(conn, application_id, tenant_id, golden, current)

    diff: dict[str, dict] = {}
    for gk, col in _COLUMN_MAP.items():
        g = _num(golden.get(gk))
        c = _num(current.get(col))
        if g is None:
            continue                       # no source document — never overwrite
        if c is None or abs(g - c) >= 0.6:
            diff[col] = {"golden": g, "current": c}

    written = False
    if write and diff:
        sets, vals = [], []
        for i, (col, d) in enumerate(diff.items(), start=1):
            sets.append(f"{col} = ${i}")
            vals.append(d["golden"])
        vals.extend([application_id, tenant_id])
        await conn.execute(
            f"UPDATE entity_states SET {', '.join(sets)} "
            f"WHERE application_id = ${len(vals) - 1} AND tenant_id = ${len(vals)}",
            *vals,
        )
        written = True
        logger.info("golden_record: wrote %s for %s", list(diff), application_id)

    # v4.9: write the 10 canonical columns additively (only non-None values, so a
    # missing source never nulls a seeded value). Same write/meridian guard.
    v49_written: list[str] = []
    if write:
        cols = [(c, v49[c]) for c in _V49_COLUMNS if v49.get(c) is not None]
        if cols:
            sets = [f"{c} = ${i}" for i, (c, _) in enumerate(cols, start=1)]
            vals = [v for _, v in cols]
            vals.extend([application_id, tenant_id])
            await conn.execute(
                f"UPDATE entity_states SET {', '.join(sets)} "
                f"WHERE application_id = ${len(vals) - 1} AND tenant_id = ${len(vals)}",
                *vals,
            )
            v49_written = [c for c, _ in cols]
            logger.info("golden_record v4.9: wrote %s for %s", v49_written, application_id)

    # INC-A: also populate income_sources (additive; W2 stream). Only on the real
    # write path — meridian raised above, dry-run leaves the model alone.
    income_written = False
    if write:
        income_written = await _write_w2_income_source(
            conn, application_id, tenant_id)

    return {"golden": golden, "current": current, "diff": diff,
            "written": written, "income_written": income_written,
            "v49": v49, "v49_written": v49_written}


__all__ = ["apply_golden_record", "load_doc_map", "build_golden_record"]
