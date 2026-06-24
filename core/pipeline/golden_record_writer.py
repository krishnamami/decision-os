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
               loan_amount, monthly_obligations
        FROM entity_states
        WHERE application_id = $1 AND tenant_id = $2
        """,
        application_id, tenant_id,
    )
    current = dict(current_row) if current_row else {}

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

    # INC-A: also populate income_sources (additive; W2 stream). Only on the real
    # write path — meridian raised above, dry-run leaves the model alone.
    income_written = False
    if write:
        income_written = await _write_w2_income_source(
            conn, application_id, tenant_id)

    return {"golden": golden, "current": current, "diff": diff,
            "written": written, "income_written": income_written}


__all__ = ["apply_golden_record", "load_doc_map", "build_golden_record"]
