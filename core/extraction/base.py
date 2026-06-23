"""Extraction base types (RA-EX-D)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ExtractionResult:
    """The structured output of one extractor over one document."""
    fields: dict[str, Any]
    confidence: float
    method: str
    doc_type: str
    warnings: list[str] = field(default_factory=list)


class BaseExtractor(ABC):
    @abstractmethod
    async def extract(
        self,
        file_bytes: bytes,
        doc_type: str,
        application_id: Optional[str] = None,
    ) -> ExtractionResult:
        """Extract structured fields from raw document bytes."""
        raise NotImplementedError


__all__ = ["ExtractionResult", "BaseExtractor"]
