"""PL-C — Platform Studio credit-policy PDF extractor (the EXTRACT stage).

Turns a lender credit-policy PDF into a STRUCTURED overlay proposal shaped like the
tenant_rules.rules JSONB (credit/dti/ltv/programs/loan-limits) + the 3 typed
overlay_rules updates. Hybrid like IN-E: pdfplumber-text regex patterns first, a
self-contained Claude Vision fallback for free-form prose (graceful no-key degrade).

Produces a DRAFT PROPOSAL ONLY — it writes nothing. Review + activation use the
EXISTING api/accord/rules.py plumbing (validate_overlay → create version → activate,
with hard agency/regulatory-floor guardrails). RULE 11: per-field confidence +
source_quote + missing_inputs; never invents a value; items with no rules-schema
home are returned as `unmapped_items`.
"""
from __future__ import annotations

import re
from typing import Callable, Optional

# Known tenant_rules.rules JSONB keys (the mapping target).
RULES_SCHEMA = {
    "credit": ["min_score", "prime_threshold"],
    "dti": ["back_max", "front_max"],
    "ltv": ["max", "cashout_max", "jumbo_max", "no_mi_threshold"],
    "income": ["employment_history_months"],
    "programs": [],
    "max_loan_amount": None,
    "min_loan_amount": None,
}

POLICY_PATTERNS = {
    "credit.min_score": [
        r"minimum\s+credit\s+score[:\s]+(\d{3})",
        r"min(?:imum)?\s+(?:fico|score)[:\s]+(\d{3})",
        r"credit\s+score\s+(?:of\s+)?(\d{3})",
    ],
    "dti.back_max": [
        r"(?:maximum|max)\s+(?:back[\-\s]?end\s+)?dti[:\s]+(\d{1,2})",
        r"debt[\-\s]to[\-\s]income[:\s]+(\d{1,2})",
        r"total\s+dti[:\s]+(?:not\s+to\s+exceed\s+)?(\d{1,2})",
    ],
    "ltv.max": [
        r"(?:maximum|max)\s+ltv[:\s]+(\d{1,2}(?:\.\d)?)",
        r"loan[\-\s]to[\-\s]value[:\s]+(?:not\s+to\s+exceed\s+)?(\d{1,2}(?:\.\d)?)",
    ],
    "ltv.cashout_max": [
        r"(\d{1,2})%?\s+(?:for\s+)?cash[\-\s]out",
        r"cash[\-\s]out\s+(?:refi(?:nance)?\s+)?(?:maximum|max)?\s*ltv[:\s]+(\d{1,2})",
    ],
    "max_loan_amount": [
        r"maximum\s+loan\s+(?:amount|size)[:\s]+\$?([\d,]+)",
        r"loan\s+(?:amount\s+)?(?:cap|limit)[:\s]+\$?([\d,]+)",
    ],
    "min_loan_amount": [
        r"minimum\s+loan\s+(?:amount|size)[:\s]+\$?([\d,]+)",
    ],
    "income.employment_history_months": [
        r"employment\s+history[:\s]+(\d+)\s+months?",
        r"employment\s+history[:\s]+(\d+)\s+years?",
    ],
}

PRODUCT_PATTERNS = {
    "conventional": r"conventional[^.\n]{0,30}?\b(yes|no|approved|not\s+approved)\b",
    "fha": r"\bfha\b[^.\n]{0,30}?\b(yes|no|approved|not\s+approved)\b",
    "va": r"\bva\b[^.\n]{0,30}?\b(yes|no|approved|not\s+approved)\b",
    "jumbo": r"jumbo[^.\n]{0,30}?\b(yes|no|approved|not\s+approved)\b",
    "heloc": r"heloc[^.\n]{0,30}?\b(yes|no|approved|not\s+approved)\b",
}
_KEY_FIELDS = ("credit.min_score", "dti.back_max", "ltv.max")
_OVERLAY_MAP = {"credit.min_score": "credit_floor", "dti.back_max": "dti_back_max",
                "ltv.max": "ltv_max_purchase"}


class CreditPolicyExtractor:
    def __init__(self, vision_call: Optional[Callable] = None):
        # vision_call(file_bytes) -> dict of {field: {value, confidence, source_quote}}.
        # Injected for tests; None -> self-contained anthropic call (no-key -> {}).
        self._vision_call = vision_call

    def _extract_text(self, file_bytes: bytes) -> str:
        try:
            import io

            import pdfplumber
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                return "\n".join(p.extract_text() or "" for p in pdf.pages)
        except Exception:
            # Not a PDF (e.g. a raw-text fixture / .txt) — decode as text.
            try:
                return file_bytes.decode("utf-8", errors="ignore")
            except Exception:
                return ""

    def _pattern_extract(self, text: str) -> dict:
        findings: dict = {}
        for field, patterns in POLICY_PATTERNS.items():
            for pat in patterns:
                m = re.search(pat, text, re.IGNORECASE)
                if not m:
                    continue
                raw = m.group(1).replace(",", "")
                try:
                    val = float(raw)
                    if "years" in pat:  # normalize "2 years" -> 24 months
                        val *= 12
                except ValueError:
                    val = raw
                s, e = max(0, m.start() - 30), min(len(text), m.end() + 30)
                findings[field] = {"value": val, "confidence": 0.85, "method": "regex_pattern",
                                   "source_quote": text[s:e].strip()}
                break
        programs = []
        for product, pat in PRODUCT_PATTERNS.items():
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                offered = m.group(1).lower() in ("yes", "approved")
                programs.append({"product": product, "offered": offered, "confidence": 0.80,
                                 "source_quote": m.group(0)[:80].strip()})
        if programs:
            findings["programs"] = {"value": programs, "confidence": 0.80,
                                    "method": "regex_pattern",
                                    "source_quote": f"{len(programs)} products found"}
        return findings

    async def _vision_extract(self, file_bytes: bytes) -> dict:
        if self._vision_call is not None:
            try:
                return await self._vision_call(file_bytes) or {}
            except Exception:
                return {}
        # self-contained Claude Vision (no-key / no-pdf -> {}), like IN-E classifier
        import base64
        import json
        try:
            import anthropic
            client = anthropic.Anthropic()
            prompt = (
                "This is a lender credit-policy document. Extract as JSON, each field as "
                '{"value":..,"confidence":0-1,"source_quote":".."}: credit.min_score, '
                "dti.back_max, ltv.max, ltv.cashout_max, max_loan_amount, min_loan_amount, "
                "income.employment_history_months, and programs (list of "
                '{product,offered}). Omit anything not stated; never invent. JSON only.')
            resp = client.messages.create(
                model="claude-3-5-sonnet-20241022", max_tokens=600,
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
            return json.loads(txt.strip()) or {}
        except Exception:
            return {}

    def _map_to_rules_schema(self, findings: dict):
        rules: dict = {}
        overlay_updates: list = []
        unmapped: list = []

        def _set_nested(d, path, value):
            keys = path.split(".")
            for k in keys[:-1]:
                d = d.setdefault(k, {})
            d[keys[-1]] = value

        for field, finding in findings.items():
            value = finding.get("value") if isinstance(finding, dict) else finding
            if field == "programs":
                rules["programs"] = [p["product"] for p in (value or [])
                                     if isinstance(p, dict) and p.get("offered", True)]
            elif field in ("max_loan_amount", "min_loan_amount"):
                rules[field] = value
            elif "." in field and field.split(".")[0] in RULES_SCHEMA:
                _set_nested(rules, field, value)
                if field in _OVERLAY_MAP:
                    overlay_updates.append({"rule_type": _OVERLAY_MAP[field],
                                            "overlay_value": value, "direction": "stricter",
                                            "loan_type": "conventional", "source": field})
            else:
                unmapped.append({"field": field, "value": value})
        return rules, overlay_updates, unmapped

    async def extract(self, file_bytes: bytes, filename: str = "") -> dict:
        text = self._extract_text(file_bytes)
        findings = self._pattern_extract(text)

        low_conf = {k for k, v in findings.items()
                    if isinstance(v, dict) and v.get("confidence", 0) < 0.7}
        needs_vision = bool(low_conf or (set(_KEY_FIELDS) - set(findings)))
        if needs_vision:
            for k, v in (await self._vision_extract(file_bytes)).items():
                if k not in findings or findings[k].get("confidence", 0) < 0.7:
                    findings[k] = v if isinstance(v, dict) else {"value": v, "confidence": 0.7,
                                                                 "method": "vision",
                                                                 "source_quote": ""}

        rules, overlay_updates, unmapped = self._map_to_rules_schema(findings)
        missing = [f"{f} not found in policy document" for f in _KEY_FIELDS if f not in findings]
        confs = [v.get("confidence", 0) for v in findings.values() if isinstance(v, dict)]
        avg_conf = round(sum(confs) / len(confs), 2) if confs else 0.0

        return {
            "status": "draft", "proposal": rules, "overlay_updates": overlay_updates,
            "findings": findings, "unmapped_items": unmapped,
            "fields_extracted": len(findings), "avg_confidence": avg_conf,
            "method": "regex+vision" if needs_vision else "regex", "text_length": len(text),
            "note": ("REVIEW REQUIRED — verify extracted values before activation. Use the "
                     "existing rules.py validate_overlay -> create version -> activate flow. "
                     "This extractor produces a draft proposal only and writes nothing."),
            "data_source": f"credit policy PDF ({filename})", "missing_inputs": missing}


__all__ = ["CreditPolicyExtractor", "POLICY_PATTERNS", "PRODUCT_PATTERNS", "RULES_SCHEMA"]
