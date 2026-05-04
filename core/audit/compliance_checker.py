from __future__ import annotations

from typing import Optional

from .schema import (
    AuditRecord,
    CheckResult,
    CheckStatus,
    ConsentStatus,
)


# Decision types → minimum regulation tags expected. Conservative
# defaults; the integration layer can extend this per agency overlay.
DEFAULT_REGULATION_TAGS: dict[str, tuple[str, ...]] = {
    "lead_scoring": ("ECOA",),
    "income_verification": ("ECOA", "FCRA"),
    "credit_assessment": ("FCRA", "ECOA"),
    "fraud_screening": ("FCRA",),
    "compliance_check": ("HMDA", "ECOA", "TRID"),
    "dti_calculation": ("ECOA",),
    "ltv_assessment": ("ECOA",),
    "product_eligibility": ("ECOA",),
    "rate_pricing": ("ECOA", "TRID"),
    "underwriting_decision": ("ECOA", "FCRA", "HMDA"),
    "approval_routing": ("ECOA",),
    "closing_readiness": ("TRID", "RESPA"),
}

DEFAULT_DATA_SOURCES_BY_TAG: dict[str, tuple[str, ...]] = {
    # FCRA gates third-party credit pulls. RESPA gates title/escrow
    # access. HMDA is a reporting regime, not a data-source gate, so
    # it does NOT appear here — application_form intake doesn't
    # require HMDA tagging.
    "FCRA":  ("credit_bureau",),
    "RESPA": ("title_provider",),
}


class ComplianceChecker:
    """PRD §23.4 CHECK 1.

    Evaluates regulation_tags, consent_status, disclosure timing,
    data-source permissions. Fails if consent missing, required
    disclosure not sent, or unpermitted data source used."""

    name = "compliance"

    def __init__(self, default_tags: Optional[dict[str, tuple[str, ...]]] = None):
        self._default_tags = default_tags or DEFAULT_REGULATION_TAGS

    def check(self, record: AuditRecord) -> CheckResult:
        findings: list[str] = []
        status = CheckStatus.PASS

        # Required tags for this decision type
        expected_tags = self._default_tags.get(record.decision_type, ())
        missing_tags = [t for t in expected_tags if t not in record.regulation_tags]
        if missing_tags:
            findings.append(
                f"missing required regulation tags for {record.decision_type}: "
                f"{sorted(missing_tags)}"
            )
            status = CheckStatus.WARN

        # Consent
        if record.consent_status == ConsentStatus.MISSING:
            findings.append("consent_status=missing — required for any data-source pull")
            status = CheckStatus.FAIL
        elif record.consent_status == ConsentStatus.WITHDRAWN:
            findings.append("consent withdrawn — decision must be rolled back")
            status = CheckStatus.FAIL
        elif record.consent_status == ConsentStatus.PENDING:
            findings.append("consent pending — decision should defer to human review")
            if status != CheckStatus.FAIL:
                status = CheckStatus.WARN

        # Disclosure timing — for closing-related decisions, disclosure
        # must already be on file before the decision is made.
        if "TRID" in record.regulation_tags or "RESPA" in record.regulation_tags:
            if not record.disclosure_sent:
                findings.append(
                    "TRID/RESPA decision without disclosure_sent — TRID timing rule"
                )
                status = CheckStatus.FAIL

        # Data source ↔ regulation alignment. If we used a credit
        # bureau, FCRA must be tagged; etc.
        for tag, expected_sources in DEFAULT_DATA_SOURCES_BY_TAG.items():
            if tag in record.regulation_tags:
                continue
            for src in record.data_sources_used:
                if src in expected_sources:
                    findings.append(
                        f"data source {src!r} used without {tag} regulation tag"
                    )
                    if status == CheckStatus.PASS:
                        status = CheckStatus.WARN

        return CheckResult(
            name=self.name,
            status=status,
            findings=findings,
            details={
                "expected_tags": list(expected_tags),
                "consent_status": record.consent_status.value,
            },
        )
