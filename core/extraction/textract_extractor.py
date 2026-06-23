"""Tier 1 extractor (RA-EX-F) — structured forms with stable layouts.

Replaces the RA-EX-D stub. Named ``textract_extractor`` for router compatibility,
but uses **pdfplumber** under the hood (no AWS): boto3 is installed in this env
but no AWS credentials are configured, and pdfplumber extracts structured PDF
text locally with good accuracy on forms (W2 / paystub / URLA).

When AWS Textract becomes available, swap the body of ``_extract_text`` for a
``textract.analyze_document`` call — the FIELD_PATTERNS + parsing stay identical.

Patterns run against the ORIGINAL extracted text with re.IGNORECASE (NOT a
lower-cased copy) so case-sensitive captures like employer names survive.
"""
from __future__ import annotations

import io
import re
from typing import Any, Optional

from core.extraction.base import BaseExtractor, ExtractionResult

# Per-doc-type field patterns. Each capture group 1 is the field value.
FIELD_PATTERNS: dict[str, dict[str, str]] = {
    "W2_CURRENT": {
        "box1_wages": r"(?:wages|salary|tips)[^\d]{0,20}(\d[\d,]+(?:\.\d{2})?)",
        "employer_name": r"employer[:\s]+([A-Z][\w&.,'\- ]+?)(?=\s+(?:ein|tax|wages|\d{2}-)|\n|$)",
        "employer_ein": r"(\d{2}-\d{7})",
        "tax_year": r"\b(20\d{2})\b",
    },
    "W2_PRIOR": {
        "box1_wages": r"(?:wages|salary|tips)[^\d]{0,20}(\d[\d,]+(?:\.\d{2})?)",
        "employer_name": r"employer[:\s]+([A-Z][\w&.,'\- ]+?)(?=\s+(?:ein|tax|wages|\d{2}-)|\n|$)",
        "employer_ein": r"(\d{2}-\d{7})",
        "tax_year": r"\b(20\d{2})\b",
    },
    "PAYSTUB_CURRENT": {
        "gross_pay_ytd": r"(?:ytd|year.to.date)[^\d]{0,20}(\d[\d,]+(?:\.\d{2})?)",
        "gross_pay_period": r"(?:gross\s*pay|current\s*gross|gross)[^\d]{0,20}(\d[\d,]+(?:\.\d{2})?)",
        "pay_date": r"(?:pay\s*date|check\s*date)[^\d]{0,20}(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})",
    },
    "PAYSTUB_PRIOR": {
        "gross_pay_ytd": r"(?:ytd|year.to.date)[^\d]{0,20}(\d[\d,]+(?:\.\d{2})?)",
        "gross_pay_period": r"(?:gross\s*pay|current\s*gross|gross)[^\d]{0,20}(\d[\d,]+(?:\.\d{2})?)",
        "pay_date": r"(?:pay\s*date|check\s*date)[^\d]{0,20}(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})",
    },
    "URLA_1003": {
        "loan_amount": r"(?:loan\s*amount|base\s*loan)[^\d]{0,20}(\d[\d,]+)",
        "property_type": r"property\s*type[:\s]*(SFR|condo|2-4|manufactured)",
    },
}


def _coerce(raw: str) -> Any:
    """Numbers -> float, everything else -> trimmed string."""
    cleaned = raw.replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return raw.strip()


class TextractExtractor(BaseExtractor):

    @staticmethod
    def _extract_text(file_bytes: bytes) -> str:
        """Pull all page text out of a PDF. Swap this for AWS Textract when
        credentials are available."""
        import pdfplumber

        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            return " ".join(page.extract_text() or "" for page in pdf.pages)

    async def extract(
        self,
        file_bytes: bytes,
        doc_type: str,
        application_id: Optional[str] = None,
    ) -> ExtractionResult:
        patterns = FIELD_PATTERNS.get(doc_type, {})
        if not patterns:
            return ExtractionResult(
                fields={}, confidence=0.0, method="pdfplumber",
                doc_type=doc_type,
                warnings=[f"No Tier-1 patterns for {doc_type}"],
            )

        try:
            text = self._extract_text(file_bytes)
        except Exception as exc:  # not a PDF / corrupt / pdfminer error
            return ExtractionResult(
                fields={}, confidence=0.0, method="pdfplumber_error",
                doc_type=doc_type, warnings=[str(exc)],
            )

        fields: dict[str, Any] = {}
        for field, pattern in patterns.items():
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                fields[field] = _coerce(m.group(1))

        confidence = round(len(fields) / max(len(patterns), 1), 2) if fields else 0.0
        return ExtractionResult(
            fields=fields, confidence=confidence, method="pdfplumber",
            doc_type=doc_type,
        )


__all__ = ["TextractExtractor", "FIELD_PATTERNS"]
