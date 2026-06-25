"""IN-E — document auto-classifier (hybrid rules + Vision).

Identifies a document's type from its CONTENT so the upload path no longer
requires the caller to label it. Sits BEFORE route_extraction:

    upload (no doc_type) -> classify_document -> doc_type -> route_extraction

Hybrid:
  1. rule-based — distinctive-anchor signatures over the pdfplumber text (+ filename);
     fast, deterministic, no per-call cost. Reuses the signal logic of the Tier-3
     regex extractor's PATTERNS.
  2. Vision fallback — only when rules are low-confidence / ambiguous (one Claude
     Vision call). Degrades gracefully to UNKNOWN if Vision is unavailable.
  3. UNKNOWN — when neither path is confident. RULE 11: never guess a type (a wrong
     type routes the wrong extractor) — surface candidates + missing_inputs and let
     a human confirm.

Thresholds are classification HEURISTICS (like the regex PATTERNS / tier_for
registry), NOT lending values — they live in code, not the catalogue.

Targets only the routable doc types (those with an extractor); others fall through
to UNKNOWN. Pure logic given text; the only I/O is pdfplumber (text) + the optional
Vision call. No DB, no decisions — extraction/onboarding layer only.
"""
from __future__ import annotations

import re
from typing import Optional

RULES_CONFIDENCE_THRESHOLD = 0.60
RULES_MARGIN_THRESHOLD = 0.20
VISION_CONFIDENCE_THRESHOLD = 0.70

# Distinctive anchors per doc type (regex, matched case-insensitively over the
# document text). Form titles / bureau names / IRS schedule names are single-type
# anchors; generic tokens (amounts, dates, names) are deliberately excluded.
CLASSIFIER_SIGNATURES: dict[str, dict] = {
    "W2_CURRENT": {
        "anchors": [r"W-2\s+Wage\s+and\s+Tax\s+Statement", r"wages,?\s*tips,?\s*other\s+compensation",
                    r"employer\s+identification\s+number", r"box\s*1\b"],
        "filename_hints": ["w2", "w-2", "wage"], "weight": 1.0},
    "PAYSTUB_CURRENT": {
        "anchors": [r"earnings\s+statement", r"pay\s+period", r"ytd\s+(gross|earnings|total)",
                    r"net\s+pay", r"regular\s+(pay|earnings)"],
        "filename_hints": ["paystub", "pay_stub", "paycheck", "earnings"], "weight": 1.0},
    "CREDIT_REPORT": {
        "anchors": [r"\bequifax\b", r"\bexperian\b", r"\btransunion\b", r"credit\s+score", r"tradeline"],
        "filename_hints": ["credit", "credit_report", "tri_merge"], "weight": 1.0},
    "APPRAISAL_URAR": {
        "anchors": [r"uniform\s+residential\s+appraisal\s+report", r"\bURAR\b",
                    r"appraised\s+value", r"subject\s+property"],
        "filename_hints": ["appraisal", "urar", "bpo"], "weight": 1.0},
    "PURCHASE_AGREEMENT": {
        "anchors": [r"purchase\s+(price|agreement|contract)", r"earnest\s+money",
                    r"buyer.{0,40}seller", r"closing\s+date"],
        "filename_hints": ["purchase", "contract", "sales_contract"], "weight": 1.0},
    "URLA_1003": {
        "anchors": [r"uniform\s+residential\s+loan\s+application", r"\b1003\b",
                    r"fannie\s+mae\s+form\s+1003"],
        "filename_hints": ["1003", "urla", "loan_app", "application"], "weight": 1.0},
    "BANK_STATEMENT_M1": {
        "anchors": [r"(ending|closing)\s+balance", r"statement\s+period",
                    r"account\s+(number|summary)", r"deposits?\s+and\s+(credits?|additions?)"],
        "filename_hints": ["bank", "statement", "checking", "savings"], "weight": 1.0},
    "RATE_LOCK": {
        "anchors": [r"rate\s+lock", r"lock\s+(expir|confirmation)", r"lock\s+period",
                    r"interest\s+rate"],
        "filename_hints": ["rate_lock", "lock", "rate_confirmation"], "weight": 1.0},
    "HOI_BINDER": {
        "anchors": [r"homeowners?\s+insurance", r"dwelling\s+coverage", r"coverage\s+[a-e]\b",
                    r"annual\s+premium", r"policy\s+number"],
        "filename_hints": ["hoi", "homeowners", "insurance", "binder"], "weight": 1.0},
    "FLOOD_CERT": {
        "anchors": [r"flood\s+zone\s+[a-z]\d*", r"FEMA\s+(map|community|panel)",
                    r"national\s+flood\s+insurance", r"flood\s+determination"],
        "filename_hints": ["flood", "fema", "flood_cert"], "weight": 1.0},
    "SCHEDULE_C": {
        "anchors": [r"profit\s+or\s+loss\s+from\s+business", r"schedule\s+c\b",
                    r"sole\s+proprietor"],
        "filename_hints": ["schedule_c", "sch_c", "schedule-c"], "weight": 1.0},
    "SCHEDULE_E": {
        "anchors": [r"supplemental\s+income\s+and\s+loss", r"schedule\s+e\b",
                    r"from\s+rental\s+real\s+estate"],
        "filename_hints": ["schedule_e", "sch_e", "schedule-e"], "weight": 1.0},
    # NOTE: SSN_VALIDATION was dropped — it has no extractor in router.py, so
    # classifying into it would route nowhere. Only routable types are targeted;
    # SSN docs fall to Vision/UNKNOWN until an extractor exists for them.
}

ROUTABLE_TYPES = set(CLASSIFIER_SIGNATURES)


class DocumentClassifier:
    def __init__(self, rules_confidence_threshold: float = RULES_CONFIDENCE_THRESHOLD,
                 rules_margin_threshold: float = RULES_MARGIN_THRESHOLD,
                 vision_confidence_threshold: float = VISION_CONFIDENCE_THRESHOLD):
        self._rules_threshold = rules_confidence_threshold
        self._margin_threshold = rules_margin_threshold
        self._vision_threshold = vision_confidence_threshold

    def _extract_text(self, file_bytes: bytes) -> str:
        """First 3 pages of text via pdfplumber (same engine the Tier-1 extractor
        uses). Returns '' on any failure — the caller degrades to Vision/UNKNOWN."""
        try:
            import io

            import pdfplumber
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                return "\n".join(p.extract_text() or "" for p in pdf.pages[:3])
        except Exception:
            return ""

    def _score_rules(self, text: str, filename: str = ""):
        scores: dict[str, float] = {}
        matched: dict[str, list] = {}
        fn = (filename or "").lower()
        for doc_type, sig in CLASSIFIER_SIGNATURES.items():
            score, hits = 0.0, []
            for anchor in sig.get("anchors", []):
                if re.search(anchor, text, re.IGNORECASE):
                    score += 1.0
                    hits.append(anchor[:40])
            for hint in sig.get("filename_hints", []):
                if hint in fn:
                    score += 0.5
                    hits.append(f"filename:{hint}")
            if score > 0:
                scores[doc_type] = score * sig.get("weight", 1.0)
                matched[doc_type] = hits
        return scores, matched

    def _rules_classify(self, text: str, filename: str = "") -> dict:
        scores, matched = self._score_rules(text, filename)
        if not scores:
            return {
                "doc_type": "UNKNOWN", "confidence": 0.0, "margin": 0.0, "method": "rules",
                "matched_signals": [], "candidates": {},
                "data_source": "pdfplumber text + filename",
                "missing_inputs": ["no distinctive signals found in document"]}
        total = sum(scores.values())
        norm = {k: round(v / total, 3) for k, v in scores.items()}
        ranked = sorted(norm.items(), key=lambda x: x[1], reverse=True)
        top_type, top_conf = ranked[0]
        margin = top_conf - (ranked[1][1] if len(ranked) > 1 else 0.0)
        return {
            "doc_type": top_type, "confidence": top_conf, "margin": round(margin, 3),
            "method": "rules", "matched_signals": matched.get(top_type, []),
            "candidates": dict(ranked[:3]),
            "data_source": "pdfplumber text + filename", "missing_inputs": []}

    async def _vision_classify(self, file_bytes: bytes) -> dict:
        import base64
        import json
        try:
            import anthropic
            client = anthropic.Anthropic()
            b64 = base64.standard_b64encode(file_bytes).decode()
            options = ", ".join(sorted(ROUTABLE_TYPES))
            prompt = (
                "This is a mortgage document. Identify the document type. "
                f"Choose from: {options}, or UNKNOWN. "
                'Respond ONLY with JSON: '
                '{"doc_type": "...", "confidence": 0.0-1.0, "reasoning": "..."}')
            resp = client.messages.create(
                model="claude-3-5-sonnet-20241022", max_tokens=200,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64",
                     "media_type": "application/pdf", "data": b64}},
                    {"type": "text", "text": prompt}]}])
            text = resp.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            result = json.loads(text.strip())
            return {
                "doc_type": result.get("doc_type", "UNKNOWN"),
                "confidence": float(result.get("confidence", 0.0)), "method": "vision",
                "reasoning": result.get("reasoning", ""),
                "matched_signals": [result.get("reasoning", "")[:80]], "candidates": {},
                "data_source": "Claude Vision (claude-3-5-sonnet)", "missing_inputs": []}
        except Exception as e:
            return {
                "doc_type": "UNKNOWN", "confidence": 0.0, "method": "vision_failed",
                "matched_signals": [], "candidates": {},
                "data_source": "Claude Vision (unavailable)",
                "missing_inputs": [f"Vision classification failed: {str(e)[:80]}"]}

    async def classify(self, file_bytes: bytes, filename: str = "") -> dict:
        """Hybrid: rules first, Vision fallback, UNKNOWN when neither is confident."""
        text = self._extract_text(file_bytes)
        result = self._rules_classify(text, filename)

        if (result["confidence"] >= self._rules_threshold
                and result.get("margin", 0.0) >= self._margin_threshold):
            result["classification_path"] = "rules_only"
            return result

        vision = await self._vision_classify(file_bytes)
        if vision["confidence"] >= self._vision_threshold and vision["doc_type"] != "UNKNOWN":
            vision["classification_path"] = "vision_fallback"
            vision["rules_candidates"] = result["candidates"]
            return vision

        return {
            "doc_type": "UNKNOWN", "confidence": 0.0, "method": "unknown",
            "classification_path": "both_low_confidence",
            "rules_result": result, "vision_result": vision,
            "matched_signals": [], "candidates": result["candidates"],
            "data_source": "pdfplumber + Claude Vision",
            "missing_inputs": ["Classification confidence below threshold — "
                               "human confirmation required for document type."]}

    def validate_supplied(self, file_bytes: bytes, supplied_type: str,
                          filename: str = "") -> Optional[dict]:
        """Light check on a caller-supplied type: if rules confidently name a
        DIFFERENT type, return a mismatch warning (never rejects — the caller may
        be right). Returns None when no confident disagreement."""
        text = self._extract_text(file_bytes)
        r = self._rules_classify(text, filename)
        if (r["doc_type"] != "UNKNOWN" and r["doc_type"] != supplied_type
                and r["confidence"] >= self._vision_threshold):
            return {"supplied": supplied_type, "classifier_suggests": r["doc_type"],
                    "confidence": r["confidence"], "matched_signals": r["matched_signals"]}
        return None


__all__ = ["DocumentClassifier", "CLASSIFIER_SIGNATURES", "ROUTABLE_TYPES"]
