"""Document ingestion pipeline (RA-EX-D, STEP 4).

The composition the document-upload path should call:

    raw bytes -> route_extraction -> document_index.extracted_fields
              -> golden_record_writer.apply_golden_record(write=True)
              -> entity_states

There is no live upload path today (document_index is created only by seed
scripts), so this is the ready-to-wire entry point, not a change to existing
code. It HARD-REFUSES the meridian tenant: its document_index + entity_states are
hand-seeded scenario fixtures and must never be overwritten by live extraction
(that would break 16/16). Real tenants run the full flow.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from core.extraction.router import route_extraction
from core.pipeline.golden_record_writer import apply_golden_record

logger = logging.getLogger(__name__)


async def ingest_document(
    conn,
    application_id: str,
    tenant_id: str,
    doc_type: str,
    file_bytes: bytes,
    *,
    applicant_id: Optional[str] = None,
    document_id: Optional[str] = None,
    write_golden: bool = True,
) -> dict:
    """Extract one document, store it in document_index, and (optionally) derive
    entity_states. Returns {extraction, document_id, golden_written}.

    Refuses meridian (seeded fixtures). For real tenants, write_golden=True runs
    apply_golden_record(write=True) so entity_states reflects the documents."""
    if tenant_id == "meridian":
        raise ValueError(
            "ingest_document refuses the meridian demo tenant — its "
            "document_index and entity_states are seeded scenario fixtures. "
            "Run live extraction against a real tenant only."
        )

    result = await route_extraction(file_bytes, doc_type, application_id)

    # Upsert the document_index row for this (app, doc_type, tenant).
    existing = await conn.fetchrow(
        "SELECT document_id, applicant_id FROM document_index "
        "WHERE application_id=$1 AND tenant_id=$2 AND document_type=$3 "
        "AND is_current=true LIMIT 1",
        application_id, tenant_id, doc_type,
    )
    if existing:
        document_id = existing["document_id"]
        await conn.execute(
            "UPDATE document_index SET extracted_fields=$1::jsonb, "
            "confidence_score=$2, extraction_method=$3 WHERE document_id=$4",
            json.dumps(result.fields), result.confidence, result.method,
            document_id,
        )
    else:
        document_id = document_id or f"DOC-{application_id}-{doc_type}"
        await conn.execute(
            """
            INSERT INTO document_index (
                document_id, applicant_id, application_id, document_type,
                document_category, borrower_role, status, received_at,
                is_current, extracted_fields, confidence_score,
                extraction_method, tenant_id)
            VALUES ($1,$2,$3,$4,'other','primary','processed', NOW(), true,
                    $5::jsonb,$6,$7,$8)
            ON CONFLICT (document_id) DO UPDATE SET
                extracted_fields = EXCLUDED.extracted_fields,
                confidence_score = EXCLUDED.confidence_score,
                extraction_method = EXCLUDED.extraction_method,
                is_current = true
            """,
            document_id, applicant_id or f"APPLICANT-{application_id}",
            application_id, doc_type,
            json.dumps(result.fields), result.confidence, result.method,
            tenant_id,
        )

    golden_written = None
    if write_golden:
        gr = await apply_golden_record(conn, application_id, tenant_id, write=True)
        golden_written = gr.get("written")

    logger.info("ingested %s for %s (method=%s, golden_written=%s)",
                doc_type, application_id, result.method, golden_written)
    return {"extraction": result, "document_id": document_id,
            "golden_written": golden_written}


__all__ = ["ingest_document"]
