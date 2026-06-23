"""Document extraction pipeline (RA-EX-D).

raw document bytes -> route_extraction (3-tier) -> ExtractionResult -> the
ingestion path writes extracted_fields to document_index, then
golden_record_builder/_writer derive entity_states (for real, non-meridian
loans only; the meridian demo docs stay seeded)."""
from core.extraction.base import BaseExtractor, ExtractionResult
from core.extraction.router import route_extraction

__all__ = ["BaseExtractor", "ExtractionResult", "route_extraction"]
