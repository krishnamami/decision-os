"""Regex extractor (RA-EX-D) — Tier 3 simple key/value docs. STUB.

Pattern-based extraction for stable-layout docs (flood cert, HOI, rate lock,
credit report, bank statements) isn't wired yet; this returns a clearly-flagged
empty result so the router never crashes on a tier-3 doc. Real implementation
lands in a later RA-EX pass.
"""
from __future__ import annotations

from typing import Optional

from core.extraction.base import BaseExtractor, ExtractionResult


class RegexExtractor(BaseExtractor):
    async def extract(
        self, file_bytes: bytes, doc_type: str,
        application_id: Optional[str] = None,
    ) -> ExtractionResult:
        return ExtractionResult(
            fields={}, confidence=0.0, method="regex_stub", doc_type=doc_type,
            warnings=["RegexExtractor not implemented yet (RA-EX-D stub)"],
        )


__all__ = ["RegexExtractor"]
