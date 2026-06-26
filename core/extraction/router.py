"""Extraction router (RA-EX-D) — pick the extractor tier by document type.

  Tier 1 (Textract)  structured forms with stable layouts (W2, paystub, URLA)
  Tier 2 (Vision)    complex / variable-layout docs (schedules, appraisal,
                     purchase agreement, title, gift letter, VOE, decrees)
  Tier 3 (Regex)     simple key/value docs (flood cert, HOI, rate lock, credit
                     report, bank statements)

Extractors are imported lazily so a missing optional dependency only affects the
doc types that need it. All three tiers are real (RA-EX-F): Tier 1 = pdfplumber,
Tier 2 = Claude Vision, Tier 3 = regex. Each returns a clearly-flagged result
(method + warnings) so the pipeline never crashes on unparseable input.
"""
from __future__ import annotations

from typing import Optional

from core.extraction.base import ExtractionResult

TIER_1_TEXTRACT = {
    "W2_CURRENT", "W2_PRIOR",
    "PAYSTUB_CURRENT", "PAYSTUB_PRIOR",
    "1099_CURRENT",
    "URLA_1003",
}

TIER_2_VISION = {
    "SCHEDULE_C", "SCHEDULE_C_PRIOR",
    "SCHEDULE_E",
    "APPRAISAL_URAR",
    "PURCHASE_AGREEMENT",
    "TITLE_COMMITMENT",
    "GIFT_LETTER",
    "VOE",
    "DIVORCE_DECREE",
    "SSA_AWARD_LETTER",
    "TAX_RETURN_4506C",
}

TIER_3_REGEX = {
    "FLOOD_CERT",
    "HOI_BINDER",
    "RATE_LOCK",
    "CREDIT_REPORT",
    "BANK_STATEMENT_M1",
    "BANK_STATEMENT_M2",
    "BANK_STATEMENT_M3",
}


def tier_for(doc_type: str) -> Optional[str]:
    """Which tier handles this doc type (for routing / tests / introspection)."""
    if doc_type in TIER_1_TEXTRACT:
        return "textract"
    if doc_type in TIER_2_VISION:
        return "vision"
    if doc_type in TIER_3_REGEX:
        return "regex"
    return None


async def route_extraction(
    file_bytes: bytes,
    doc_type: str,
    application_id: Optional[str] = None,
) -> ExtractionResult:
    # URLA_1003 uses the MI-D hybrid extractor (pdfplumber text -> Vision fallback
    # for scanned paper + checkboxes). It stays listed in TIER_1_TEXTRACT for tier
    # routing/classification (text-first), but dispatches here.
    if doc_type == "URLA_1003":
        from core.extraction.urla_extractor import URLAExtractor
        return await URLAExtractor().extract(file_bytes, doc_type, application_id)
    if doc_type in TIER_1_TEXTRACT:
        from core.extraction.textract_extractor import TextractExtractor
        return await TextractExtractor().extract(file_bytes, doc_type, application_id)
    if doc_type in TIER_2_VISION:
        from core.extraction.vision_extractor import VisionExtractor
        return await VisionExtractor().extract(file_bytes, doc_type, application_id)
    if doc_type in TIER_3_REGEX:
        from core.extraction.regex_extractor import RegexExtractor
        return await RegexExtractor().extract(file_bytes, doc_type, application_id)
    return ExtractionResult(
        fields={}, confidence=0.0, method="unknown", doc_type=doc_type,
        warnings=[f"No extractor for doc_type: {doc_type}"],
    )


__all__ = ["route_extraction", "tier_for",
           "TIER_1_TEXTRACT", "TIER_2_VISION", "TIER_3_REGEX"]
