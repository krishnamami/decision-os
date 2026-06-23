"""Claude Vision extractor (RA-EX-D) — Tier 2 complex / variable-layout docs.

Sends the document (PDF or image) to Claude with a per-doc-type extraction prompt
and parses the returned JSON. Uses the Anthropic SDK; model defaults to
claude-opus-4-8 (override with CLAUDE_MODEL_ID). The client is constructed inside
extract() so unit tests can patch anthropic.Anthropic without real API calls.
"""
from __future__ import annotations

import base64
import json
import os
import re
from typing import Optional

from core.extraction.base import BaseExtractor, ExtractionResult

_DEFAULT_MODEL = "claude-opus-4-8"


class VisionExtractor(BaseExtractor):

    PROMPTS = {
        "PURCHASE_AGREEMENT": """
Extract these fields from this purchase agreement/contract:
- purchase_price: number (the agreed sale price in dollars)
- close_date: string (expected closing date, ISO format YYYY-MM-DD)
- seller_concessions_pct: number (seller credits as % of purchase price, 0 if none)
- seller_concessions_amt: number (seller credits in dollars, 0 if none)
- earnest_money: number (earnest money deposit amount)
- property_address: string (full property address)
- contract_date: string (date contract was signed, ISO format)

Return JSON only. Use null for any field not found.
Example: {"purchase_price": 612500, "close_date": "2025-08-15"}
""",
        "APPRAISAL_URAR": """
Extract these fields from this appraisal report (URAR Form 1004):
- appraised_value: number (the appraised value in dollars)
- property_address: string (subject property address)
- property_type: string (SFR/Condo/2-4 Unit/Manufactured)
- effective_date: string (appraisal effective date, ISO format)
- condition_rating: string (C1/C2/C3/C4/C5/C6)
- gla_sqft: number (gross living area in square feet)
- year_built: number (year property was built)
- flood_zone: string (FEMA flood zone designation)

Return JSON only. Use null for any field not found.
""",
        "GIFT_LETTER": """
Extract these fields from this gift letter:
- gift_amount: number (the gift amount in dollars)
- donor_name: string (full name of the donor)
- donor_relationship: string (relationship to borrower)
- no_repayment_statement: boolean (true if letter states no repayment required)
- gift_date: string (date of gift or expected gift date, ISO format)
- donor_account_type: string (checking/savings/other)

Return JSON only. Use null for any field not found.
""",
        "VOE": """
Extract these fields from this Verification of Employment (VOE):
- employer_name: string (company name)
- employment_start_date: string (hire date, ISO format)
- current_position: string (job title)
- current_salary: number (annual salary or hourly rate)
- pay_frequency: string (annual/monthly/bi-weekly/weekly/hourly)
- probability_of_continuance: string (yes/no/likely/unlikely)
- voe_date: string (date VOE was completed, ISO format)
- employer_phone: string (employer contact phone)

Return JSON only. Use null for any field not found.
""",
        "DIVORCE_DECREE": """
Extract these fields from this divorce decree or separation agreement:
- alimony_monthly: number (monthly alimony/spousal support amount, 0 if none)
- alimony_receiving: boolean (true if borrower is RECEIVING alimony)
- alimony_termination_date: string (date alimony ends, ISO format, null if no end date)
- child_support_monthly: number (monthly child support amount, 0 if none)
- child_support_paying: boolean (true if borrower is PAYING child support)
- decree_date: string (date decree was finalized, ISO format)
- court_jurisdiction: string (state/county of jurisdiction)

Return JSON only. Use null for any field not found.
""",
        "SSA_AWARD_LETTER": """
Extract these fields from this Social Security Award Letter:
- monthly_benefit: number (monthly SS benefit amount)
- benefit_type: string (retirement/disability/survivor)
- effective_date: string (date benefit begins or was effective, ISO format)
- cola_adjustments: boolean (true if subject to annual COLA adjustments)
- recipient_name: string (beneficiary name)

Return JSON only. Use null for any field not found.
""",
    }

    @staticmethod
    def _media_type(file_bytes: bytes) -> str:
        if file_bytes[:4] == b"%PDF":
            return "application/pdf"
        if file_bytes[:3] == b"\xff\xd8\xff":
            return "image/jpeg"
        return "image/png"

    @staticmethod
    def _parse_json(text: str) -> Optional[dict]:
        """Parse the model's reply into a dict. Tolerates ```json fences and
        leading/trailing prose by falling back to the outermost {...} block."""
        t = (text or "").strip()
        if t.startswith("```"):
            # ```json ... ``` or ``` ... ```
            inner = t.split("```")
            if len(inner) >= 2:
                t = inner[1]
                if t.lstrip().lower().startswith("json"):
                    t = t.lstrip()[4:]
        t = t.strip()
        try:
            obj = json.loads(t)
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", t, re.DOTALL)
            if m:
                try:
                    obj = json.loads(m.group(0))
                    return obj if isinstance(obj, dict) else None
                except json.JSONDecodeError:
                    return None
            return None

    async def extract(
        self,
        file_bytes: bytes,
        doc_type: str,
        application_id: Optional[str] = None,
    ) -> ExtractionResult:
        import anthropic

        prompt = self.PROMPTS.get(doc_type)
        if not prompt:
            return ExtractionResult(
                fields={}, confidence=0.5, method="vision_no_prompt",
                doc_type=doc_type,
                warnings=[f"No Vision prompt defined for {doc_type}"],
            )

        media_type = self._media_type(file_bytes)
        image_data = base64.standard_b64encode(file_bytes).decode("utf-8")
        block_type = "document" if media_type == "application/pdf" else "image"
        model = os.environ.get("CLAUDE_MODEL_ID", _DEFAULT_MODEL)

        client = anthropic.Anthropic()
        message = client.messages.create(
            model=model,
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    {"type": block_type,
                     "source": {"type": "base64",
                                "media_type": media_type,
                                "data": image_data}},
                    {"type": "text", "text": prompt.strip()},
                ],
            }],
        )

        text = message.content[0].text if message.content else ""
        fields = self._parse_json(text)
        if fields is None:
            return ExtractionResult(
                fields={}, confidence=0.0, method="claude_vision",
                doc_type=doc_type,
                warnings=["Vision output was not valid JSON"],
            )
        # Drop nulls so golden_record never sees an explicit null as a value.
        fields = {k: v for k, v in fields.items() if v is not None}
        return ExtractionResult(
            fields=fields, confidence=0.85, method="claude_vision",
            doc_type=doc_type,
        )


__all__ = ["VisionExtractor"]
