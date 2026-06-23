"""Textract extractor (RA-EX-D) — Tier 1 structured forms. STUB.

AWS Textract (or an equivalent form-parser) isn't wired yet; this returns a
clearly-flagged empty result so the router never crashes on a tier-1 doc. Real
implementation lands in a later RA-EX pass.
"""
from __future__ import annotations

from typing import Optional

from core.extraction.base import BaseExtractor, ExtractionResult


class TextractExtractor(BaseExtractor):
    async def extract(
        self, file_bytes: bytes, doc_type: str,
        application_id: Optional[str] = None,
    ) -> ExtractionResult:
        return ExtractionResult(
            fields={}, confidence=0.0, method="textract_stub", doc_type=doc_type,
            warnings=["TextractExtractor not implemented yet (RA-EX-D stub)"],
        )


__all__ = ["TextractExtractor"]
