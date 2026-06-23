"""Tier 3 extractor (RA-EX-F) — simple key/value docs.

Replaces the RA-EX-D stub. These doc types (flood cert, HOI binder, rate lock,
credit report, bank statement) are short and mostly text-based, so we decode the
bytes as UTF-8 and run per-doc-type regex patterns. No PDF parsing, no AWS, no
network. Patterns run with re.IGNORECASE; capture group 1 is the field value.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from core.extraction.base import BaseExtractor, ExtractionResult

PATTERNS: dict[str, dict[str, str]] = {
    "FLOOD_CERT": {
        "flood_zone": r"(?:flood\s*)?zone[:\s]*([A-Z]{1,2}\d{0,2})",
        "community_number": r"(?:community|panel)[^\d]{0,15}(\d{6})",
        "effective_date": r"(?:effective|date)[^\d]{0,15}(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})",
    },
    "HOI_BINDER": {
        "coverage_amount": r"(?:dwelling|coverage\s*a)[^\d]{0,20}\$?(\d[\d,]+)",
        "annual_premium": r"(?:annual|total)\s*premium[^\d]{0,15}\$?(\d[\d,]+)",
        "policy_expiry": r"(?:expir\w*|policy\s*end)[^\d]{0,15}(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})",
        "policy_number": r"policy[^\w#]{0,6}#?([A-Z]{1,4}[\-\d]{5,18})",
    },
    "RATE_LOCK": {
        "interest_rate": r"(\d+\.\d+)\s*%",
        "lock_expiry": r"(?:lock|expir\w*)[^\d]{0,15}(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})",
        "loan_amount": r"loan\s*amount[^\d]{0,15}\$?(\d[\d,]+)",
    },
    "CREDIT_REPORT": {
        "equifax_score": r"(?:equifax|efx)[^\d]{0,15}(\d{3})",
        "experian_score": r"(?:experian|exp)[^\d]{0,15}(\d{3})",
        "transunion_score": r"(?:transunion|tu)[^\d]{0,15}(\d{3})",
        "total_monthly_obligations": r"total\s*(?:monthly|obligations)[^\d]{0,20}\$?(\d[\d,]+)",
    },
    "BANK_STATEMENT_M1": {
        "ending_balance": r"(?:ending|closing)\s*balance[^\d]{0,15}\$?(\d[\d,]+(?:\.\d{2})?)",
        "statement_date": r"(?:statement\s*period|through)[^\d]{0,15}(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})",
        "account_number": r"account[^\d*]{0,15}(\*{4,}\d{4}|\d{4})",
    },
}
# M2/M3 reuse the M1 bank-statement patterns.
PATTERNS["BANK_STATEMENT_M2"] = PATTERNS["BANK_STATEMENT_M1"]
PATTERNS["BANK_STATEMENT_M3"] = PATTERNS["BANK_STATEMENT_M1"]


def _coerce(raw: str) -> Any:
    """Numbers -> float, everything else (dates, zones, masked accounts) -> str."""
    cleaned = raw.replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return raw.strip()


class RegexExtractor(BaseExtractor):
    async def extract(
        self,
        file_bytes: bytes,
        doc_type: str,
        application_id: Optional[str] = None,
    ) -> ExtractionResult:
        patterns = PATTERNS.get(doc_type, {})
        if not patterns:
            return ExtractionResult(
                fields={}, confidence=0.0, method="regex",
                doc_type=doc_type,
                warnings=[f"No Tier-3 patterns for {doc_type}"],
            )

        try:
            text = file_bytes.decode("utf-8", errors="ignore")
        except Exception as exc:
            return ExtractionResult(
                fields={}, confidence=0.0, method="regex_error",
                doc_type=doc_type, warnings=[str(exc)],
            )

        fields: dict[str, Any] = {}
        for field, pattern in patterns.items():
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                fields[field] = _coerce(m.group(1))

        confidence = round(len(fields) / max(len(patterns), 1), 2) if fields else 0.0
        return ExtractionResult(
            fields=fields, confidence=confidence, method="regex",
            doc_type=doc_type,
        )


__all__ = ["RegexExtractor", "PATTERNS"]
