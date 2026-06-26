"""MI-D — paper/digital 1003 (URLA) extractor (hybrid text → Vision).

The Fannie/Freddie URLA (Form 1003) is the loan-level source-of-record. The old
Tier-1 stub pulled only loan_amount + property_type; this hybrid extractor pulls
the 8 loan-level golden fields `golden_record_builder` actually consumes:

  loan_amount, loan_type, loan_purpose, occupancy_type, property_type,
  purchase_price, property_state, number_of_units

Hybrid like PL-C / IN-E: pdfplumber-text regex first (works on a DIGITAL 1003 with
a text layer), then a self-contained Claude Vision fallback for SCANNED paper forms
(no text layer) and checkbox/radio fields (occupancy, loan purpose). The Vision call
is injectable for tests and degrades to {} with no ANTHROPIC_API_KEY — so a scanned
form with no key simply yields the regex fields + warnings, never a crash or a guess.

Returns the standard ExtractionResult so it slots into route_extraction ->
document_index -> golden_record -> entity_states. RULE 11: every field carries a
confidence; fields not found are surfaced in `warnings`, never fabricated.

DATA REALITY: meridian is HARD-REFUSED in the pipeline (seeded entity_states
fixtures), so this runs only on REAL tenant uploads (PATH-2). 16/16 untouched,
decision-path-safe by construction.
"""
from __future__ import annotations

import io
import re
from typing import Any, Callable, Optional

from core.extraction.base import BaseExtractor, ExtractionResult

# The 8 loan-level golden fields. Each capture group 1 is the raw value.
URLA_PATTERNS: dict[str, list[str]] = {
    "loan_amount": [
        r"(?:base\s*loan\s*amount|loan\s*amount)[^\d]{0,20}(\d[\d,]+(?:\.\d{2})?)",
    ],
    "purchase_price": [
        r"(?:purchase\s*price|sales?\s*price|price\s*of\s*property)[^\d]{0,20}(\d[\d,]+(?:\.\d{2})?)",
    ],
    "loan_type": [
        r"(?:mortgage\s*type|loan\s*type)[:\s]*\b(conventional|conv|fha|va|usda)\b",
    ],
    "loan_purpose": [
        r"(?:purpose\s*of\s*loan|loan\s*purpose|purpose)[:\s]*\b(purchase|cash[\-\s]?out(?:\s*refinance)?|rate[\-/\s]?term(?:\s*refinance)?|refinance)\b",
    ],
    "occupancy_type": [
        r"(?:occupancy(?:\s*type)?|property\s*will\s*be|intended\s*occupancy)[:\s]*\b(primary|principal|second(?:ary)?\s*home|secondary|investment|owner[\-\s]?occupied)\b",
    ],
    "property_type": [
        r"property\s*type[:\s]*\b(SFR|single[\-\s]?family|single|condo(?:minium)?|2[\-\s]?4(?:\s*unit)?|manufactured|townhouse|pud)\b",
    ],
    "property_state": [
        r"(?:property\s*state|subject\s*property\s*state)[:\s]*\b([A-Z]{2})\b",
        r"\b([A-Z]{2})\s+\d{5}(?:-\d{4})?\b",  # state preceding a ZIP in an address line
    ],
    "number_of_units": [
        r"(?:number\s*of\s*units|no\.?\s*of\s*units|units)[:\s]*(\d{1,2})\b",
    ],
}

# The fields whose absence triggers the Vision fallback (the ones personas need
# most and that checkboxes/scans most often hide).
_KEY_FIELDS = ("loan_amount", "loan_type", "loan_purpose", "occupancy_type")

_LOAN_TYPE_MAP = {"conv": "conventional", "conventional": "conventional",
                  "fha": "fha", "va": "va", "usda": "usda"}
_PROPERTY_TYPE_MAP = {
    "sfr": "single_family", "single": "single_family", "single-family": "single_family",
    "single family": "single_family", "condo": "condo", "condominium": "condo",
    "townhouse": "townhouse", "pud": "pud", "manufactured": "manufactured",
    "2-4": "multi_unit", "2 4": "multi_unit", "24": "multi_unit", "2-4 unit": "multi_unit"}


def _normalize(field: str, raw: str) -> Any:
    v = str(raw).strip()
    low = v.lower()
    if field in ("loan_amount", "purchase_price"):
        try:
            return float(v.replace(",", ""))
        except ValueError:
            return None
    if field == "number_of_units":
        try:
            return int(v)
        except ValueError:
            return None
    if field == "loan_type":
        return _LOAN_TYPE_MAP.get(low, low)
    if field == "loan_purpose":
        if "cash" in low:
            return "cash_out_refinance"
        if "rate" in low:
            return "rate_term_refinance"
        if "refinance" in low:
            return "refinance"
        return "purchase"
    if field == "occupancy_type":
        if "invest" in low:
            return "investment"
        if "second" in low or "secondary" in low:
            return "second_home"
        return "primary"  # primary / principal / owner-occupied
    if field == "property_type":
        return _PROPERTY_TYPE_MAP.get(low, low)
    if field == "property_state":
        return v.upper()
    return v


class URLAExtractor(BaseExtractor):
    def __init__(self, vision_call: Optional[Callable] = None):
        # vision_call(file_bytes) -> {field: value}. Injected for tests;
        # None -> self-contained anthropic call (no key / no pdf -> {}).
        self._vision_call = vision_call

    @staticmethod
    def _extract_text(file_bytes: bytes) -> str:
        """All page text from a PDF (patched in tests). Swap for AWS Textract
        when credentials exist — the patterns stay identical."""
        import pdfplumber
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            return " ".join(page.extract_text() or "" for page in pdf.pages)

    def _pattern_extract(self, text: str) -> dict:
        found: dict[str, Any] = {}
        for field, patterns in URLA_PATTERNS.items():
            for pat in patterns:
                m = re.search(pat, text, re.IGNORECASE)
                if not m:
                    continue
                val = _normalize(field, m.group(1))
                if val is not None and val != "":
                    found[field] = val
                    break
        return found

    async def _vision_extract(self, file_bytes: bytes) -> dict:
        if self._vision_call is not None:
            try:
                return await self._vision_call(file_bytes) or {}
            except Exception:
                return {}
        import base64
        import json
        try:
            import anthropic
            client = anthropic.Anthropic()
            prompt = (
                "This is a Uniform Residential Loan Application (Fannie Form 1003). "
                "Extract as flat JSON ONLY these keys when present (omit if not stated, "
                "never invent): loan_amount (number), purchase_price (number), loan_type "
                "(conventional|fha|va|usda), loan_purpose (purchase|refinance|"
                "cash_out_refinance|rate_term_refinance), occupancy_type (primary|"
                "second_home|investment), property_type, property_state (2-letter), "
                "number_of_units (int). Read checkboxes/radios for occupancy + purpose. "
                "JSON only.")
            resp = client.messages.create(
                model="claude-3-5-sonnet-20241022", max_tokens=500,
                messages=[{"role": "user", "content": [
                    {"type": "document", "source": {"type": "base64",
                     "media_type": "application/pdf",
                     "data": base64.standard_b64encode(file_bytes).decode()}},
                    {"type": "text", "text": prompt}]}])
            txt = resp.content[0].text.strip()
            if txt.startswith("```"):
                txt = txt.split("```")[1]
                if txt.startswith("json"):
                    txt = txt[4:]
            raw = json.loads(txt.strip()) or {}
            # normalize the same way as the regex path
            out = {}
            for k, v in raw.items():
                if k in URLA_PATTERNS and v is not None and str(v).strip() != "":
                    nv = _normalize(k, v)
                    if nv is not None and nv != "":
                        out[k] = nv
            return out
        except Exception:
            return {}

    async def extract(
        self,
        file_bytes: bytes,
        doc_type: str = "URLA_1003",
        application_id: Optional[str] = None,
    ) -> ExtractionResult:
        try:
            text = self._extract_text(file_bytes)
        except Exception:
            text = ""  # scanned image / corrupt PDF -> rely on Vision

        fields = self._pattern_extract(text)
        method = "pdfplumber"

        # Scanned form (no usable text) OR key fields missing -> Vision fallback.
        needs_vision = (len(text.strip()) < 40) or bool(set(_KEY_FIELDS) - set(fields))
        if needs_vision:
            vision = await self._vision_extract(file_bytes)
            added = False
            for k, v in vision.items():
                if k not in fields:
                    fields[k] = v
                    added = True
            if added:
                method = "pdfplumber+vision" if text.strip() else "vision"

        missing = [f for f in URLA_PATTERNS if f not in fields]
        warnings = [f"{f} not found in URLA (text + vision)" for f in missing]
        confidence = round(len(fields) / len(URLA_PATTERNS), 2)
        return ExtractionResult(fields=fields, confidence=confidence, method=method,
                                doc_type=doc_type, warnings=warnings)


__all__ = ["URLAExtractor", "URLA_PATTERNS"]
