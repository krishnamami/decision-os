"""Lien Resolver — TL-C.

Classifies and resolves each lien type: priority (federal > state > local >
private), whether it can clear at closing, the required action + documents,
the UW condition to generate, and the per-agency (Fannie/FHA/VA) treatment.

Lien priority (highest to lowest): property tax (super) > IRS > state tax >
mechanics > HOA (super in many states) > judgment > mortgage/HELOC > other.
All agencies require liens paid/released before or at closing; VA specifically
will not close over an outstanding IRS lien; a lis pendens cannot clear at all.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

LIEN_RULES = {
    "tax_lien_property": {
        "priority": 1, "super_priority": True, "blocks_closing": True,
        "resolvable": True, "resolution_method": "pay_at_closing",
        "required_docs": ["TAX_PAYOFF_LETTER", "TAX_RECEIPT"],
        "condition_code": "TITLE_PROPERTY_TAX_LIEN",
        "condition_text": ("Property tax lien must be paid in full at or before "
                           "closing. Obtain current payoff from {county} County Tax Office."),
        "agency_treatment": {"fannie": "must clear at closing", "fha": "must clear at closing",
                             "va": "must clear at closing"},
        "auto_block": True,
    },
    "tax_lien_irs": {
        "priority": 2, "super_priority": False, "blocks_closing": True,
        "resolvable": True, "resolution_method": "payoff_letter",
        "required_docs": ["IRS_PAYOFF_LETTER", "IRS_LIEN_RELEASE"],
        "condition_code": "TITLE_IRS_LIEN",
        "condition_text": ("IRS federal tax lien of ${amount:,.0f} must be satisfied "
                           "prior to closing. Obtain IRS payoff letter (Form 14135 or "
                           "lien discharge). Allow 30-45 days for IRS processing."),
        "agency_treatment": {"fannie": "must clear before closing",
                             "fha": "must clear before closing",
                             "va": "hard block - VA will not close with IRS lien"},
        "auto_block": True,
        "warning": "IRS lien processing takes 30-45 days. Start immediately to avoid closing delay.",
    },
    "tax_lien_state": {
        "priority": 3, "super_priority": False, "blocks_closing": True,
        "resolvable": True, "resolution_method": "payoff_letter",
        "required_docs": ["STATE_TAX_PAYOFF_LETTER", "STATE_TAX_RELEASE"],
        "condition_code": "TITLE_STATE_TAX_LIEN",
        "condition_text": ("State tax lien of ${amount:,.0f} must be paid before closing. "
                           "Obtain payoff from State Revenue Dept."),
        "agency_treatment": {"fannie": "must clear at closing", "fha": "must clear at closing",
                             "va": "must clear at closing"},
        "auto_block": True,
    },
    "judgment_lien": {
        "priority": 6, "super_priority": False, "blocks_closing": True,
        "resolvable": True, "resolution_method": "payoff_letter",
        "required_docs": ["JUDGMENT_PAYOFF_LETTER", "JUDGMENT_SATISFACTION"],
        "condition_code": "TITLE_JUDGMENT_LIEN",
        "condition_text": ("Judgment lien of ${amount:,.0f} held by {holder} must be "
                           "satisfied before or at closing. Obtain satisfaction of judgment "
                           "or payoff letter from creditor."),
        "agency_treatment": {"fannie": "must pay at closing or obtain subordination",
                             "fha": "must pay at closing", "va": "must pay at closing"},
        "auto_block": True,
    },
    "hoa_lien": {
        "priority": 5, "super_priority": True, "blocks_closing": False,
        "resolvable": True, "resolution_method": "pay_at_closing",
        "required_docs": ["HOA_ESTOPPEL_LETTER", "HOA_PAYOFF"],
        "condition_code": "TITLE_HOA_LIEN",
        "condition_text": ("HOA lien of ${amount:,.0f} owed to {holder}. Obtain HOA estoppel "
                           "letter showing current balance. Will be paid at closing from proceeds."),
        "agency_treatment": {"fannie": "payable at closing - obtain estoppel letter",
                             "fha": "payable at closing", "va": "payable at closing"},
        "auto_block": False, "escalate": True,
    },
    "mechanics_lien": {
        "priority": 4, "super_priority": False, "blocks_closing": True,
        "resolvable": True, "resolution_method": "release_required",
        "required_docs": ["MECHANICS_LIEN_RELEASE", "CONTRACTOR_WAIVER"],
        "condition_code": "TITLE_MECHANICS_LIEN",
        "condition_text": ("Mechanics lien of ${amount:,.0f} filed by {holder}. Obtain lien "
                           "release or waiver from contractor before closing. Contact {holder} to resolve."),
        "agency_treatment": {"fannie": "must clear before closing",
                             "fha": "must clear before closing", "va": "must clear before closing"},
        "auto_block": True,
    },
    "child_support_lien": {
        "priority": 5, "super_priority": False, "blocks_closing": True,
        "resolvable": True, "resolution_method": "legal_review",
        "required_docs": ["CHILD_SUPPORT_PAYOFF", "COURT_ORDER_SATISFACTION"],
        "condition_code": "TITLE_CHILD_SUPPORT_LIEN",
        "condition_text": ("Child support lien of ${amount:,.0f}. Must be paid or subordinated. "
                           "Provide court order satisfaction or payment plan approval."),
        "agency_treatment": {"fannie": "must clear at closing", "fha": "must clear at closing",
                             "va": "must clear at closing"},
        "auto_block": True,
    },
    "mortgage_lien": {
        "priority": 7, "super_priority": False, "blocks_closing": False,
        "resolvable": True, "resolution_method": "payoff_letter",
        "required_docs": ["MORTGAGE_PAYOFF_LETTER"],
        "condition_code": "TITLE_EXISTING_MORTGAGE",
        "condition_text": ("Existing mortgage lien held by {holder}. Obtain payoff letter "
                           "valid through closing date."),
        "agency_treatment": {"fannie": "must pay off at closing unless refi assumption",
                             "fha": "must pay off at closing", "va": "must pay off at closing"},
        "auto_block": False,
    },
    "heloc_lien": {
        "priority": 7, "super_priority": False, "blocks_closing": False,
        "resolvable": True, "resolution_method": "payoff_letter",
        "required_docs": ["HELOC_PAYOFF_LETTER", "HELOC_SUBORDINATION"],
        "condition_code": "TITLE_HELOC",
        "condition_text": ("HELOC lien held by {holder}. Must be paid off or subordinated. "
                           "Obtain payoff or subordination agreement before closing."),
        "agency_treatment": {"fannie": "subordination acceptable in some products",
                             "fha": "must pay off", "va": "must pay off"},
        "auto_block": False,
    },
    "lis_pendens": {
        "priority": 1, "super_priority": True, "blocks_closing": True,
        "resolvable": False, "resolution_method": "cannot_clear",
        "required_docs": [],
        "condition_code": "TITLE_LIS_PENDENS",
        "condition_text": ("Lis pendens (pending lawsuit) on property. Cannot close until "
                           "lawsuit resolved. Refer to legal counsel."),
        "agency_treatment": {"fannie": "cannot close with active lis pendens",
                             "fha": "cannot close with active lis pendens",
                             "va": "cannot close with active lis pendens"},
        "auto_block": True, "unresolvable": True,
    },
    "easement": {
        "priority": None, "super_priority": False, "blocks_closing": False,
        "resolvable": True, "resolution_method": "already_released",
        "required_docs": [],
        "condition_code": "TITLE_EASEMENT",
        "condition_text": ("Easement recorded on property. Review easement terms to confirm "
                           "it does not affect intended use. Note for borrower disclosure."),
        "agency_treatment": {"fannie": "acceptable if does not impair use or value",
                             "fha": "acceptable", "va": "acceptable"},
        "auto_block": False,
    },
    "other": {
        "priority": 9, "super_priority": False, "blocks_closing": True,
        "resolvable": None, "resolution_method": "legal_review",
        "required_docs": ["LEGAL_REVIEW"],
        "condition_code": "TITLE_OTHER_LIEN",
        "condition_text": ("Encumbrance found on title. Legal review required before closing "
                           "can proceed."),
        "agency_treatment": {"fannie": "legal review required", "fha": "legal review required",
                             "va": "legal review required"},
        "auto_block": True,
    },
}

# Priority sentinel for liens whose rule defines no numeric priority (easement).
_NO_PRIORITY = 999


@dataclass
class LienResolution:
    lien_type: str
    lien_holder: str
    lien_amount: float
    priority: int
    blocks_closing: bool
    resolvable: Optional[bool]
    resolution_method: str
    condition_code: str
    condition_text: str
    required_docs: List[str]
    agency_treatment: dict
    auto_block: bool
    unresolvable: bool = False
    warning: Optional[str] = None


class LienResolver:
    def resolve_lien(self, lien_type: str, lien_holder: str = "",
                     lien_amount: float = 0) -> LienResolution:
        rules = LIEN_RULES.get(lien_type, LIEN_RULES["other"])
        condition_text = rules["condition_text"].format(
            amount=lien_amount, holder=lien_holder or "unknown holder", county="",
        )
        prio = rules.get("priority")
        priority = prio if prio is not None else _NO_PRIORITY
        return LienResolution(
            lien_type=lien_type, lien_holder=lien_holder, lien_amount=lien_amount,
            priority=priority, blocks_closing=rules["blocks_closing"],
            resolvable=rules.get("resolvable", True),
            resolution_method=rules["resolution_method"],
            condition_code=rules["condition_code"], condition_text=condition_text,
            required_docs=rules.get("required_docs", []),
            agency_treatment=rules.get("agency_treatment", {}),
            auto_block=rules.get("auto_block", True),
            unresolvable=rules.get("unresolvable", False),
            warning=rules.get("warning"),
        )

    def resolve_all(self, encumbrances: list) -> dict:
        resolutions: list[LienResolution] = []
        blocking: list[LienResolution] = []
        conditions: list[dict] = []
        total_payoff = 0.0
        has_unresolvable = False

        for enc in encumbrances:
            r = self.resolve_lien(
                enc.get("lien_type", "other"), enc.get("lien_holder", ""),
                float(enc.get("lien_amount") or 0),
            )
            resolutions.append(r)
            if r.blocks_closing:
                blocking.append(r)
            if r.unresolvable:
                has_unresolvable = True
            if r.lien_amount > 0 and r.blocks_closing:
                total_payoff += r.lien_amount
            conditions.append({
                "code": r.condition_code, "text": r.condition_text,
                "lien_type": r.lien_type, "blocks": r.blocks_closing,
                "docs_needed": r.required_docs, "prior_to": "closing",
            })

        resolutions.sort(key=lambda r: r.priority)
        blocking.sort(key=lambda r: r.priority)

        if has_unresolvable:
            overall = "fatal_block"
        elif blocking:
            overall = "block"
        elif resolutions:
            overall = "conditions"
        else:
            overall = "clear"

        return {
            "resolutions": resolutions, "blocking_liens": blocking,
            "conditions": conditions, "overall_status": overall,
            "total_payoff": total_payoff, "has_unresolvable": has_unresolvable,
            "lien_count": len(resolutions), "blocking_count": len(blocking),
        }


__all__ = ["LienResolver", "LienResolution", "LIEN_RULES"]
