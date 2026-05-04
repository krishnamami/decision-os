from __future__ import annotations

from datetime import timedelta
from typing import Optional

from .schema import (
    AuditRecord,
    CheckResult,
    CheckStatus,
)


# PII fields that are always sensitive regardless of decision type.
# The set is intentionally narrow; extend per domain as needed.
PII_FIELDS = frozenset(
    {
        "ssn",
        "tax_id",
        "dob",
        "date_of_birth",
        "address_full",
        "bank_account",
        "routing_number",
        "drivers_license",
    }
)


class SecurityChecker:
    """PRD §23.4 CHECK 2.

    Evaluates who accessed what PII, which permissions were used,
    and access timing/velocity. Flags access outside normal workflow,
    PII accessed beyond decision scope, and same user accessing
    multiple sensitive records in a short window."""

    name = "security"

    def __init__(
        self,
        velocity_window_seconds: int = 60,
        velocity_threshold: int = 10,
    ):
        self._velocity_window = timedelta(seconds=velocity_window_seconds)
        self._velocity_threshold = velocity_threshold

    def check(self, record: AuditRecord) -> CheckResult:
        findings: list[str] = []
        status = CheckStatus.PASS

        # PII fields touched but no permission listed → access beyond scope.
        sensitive_touched = [f for f in record.pii_fields_accessed if f in PII_FIELDS]
        if sensitive_touched and not record.permissions_used:
            findings.append(
                f"PII fields accessed without recorded permissions: {sorted(sensitive_touched)}"
            )
            status = CheckStatus.FAIL

        # Velocity — same user touching the audit record many times in
        # the velocity window suggests a scraping pattern or runaway job.
        per_user: dict[str, list] = {}
        for entry in record.accessed_by:
            per_user.setdefault(entry.user_id, []).append(entry.timestamp)

        for user_id, stamps in per_user.items():
            stamps_sorted = sorted(stamps)
            for i in range(self._velocity_threshold, len(stamps_sorted)):
                window = stamps_sorted[i] - stamps_sorted[i - self._velocity_threshold]
                if window <= self._velocity_window:
                    findings.append(
                        f"velocity anomaly: user {user_id!r} touched record "
                        f"{self._velocity_threshold + 1} times within "
                        f"{self._velocity_window.total_seconds():.0f}s"
                    )
                    if status != CheckStatus.FAIL:
                        status = CheckStatus.WARN
                    break

        # Encryption — restricted/confidential data must be both at-rest
        # and in-transit. If only one is set, warn.
        if record.data_classification.value in ("confidential", "restricted"):
            if record.encryption_status.value != "both":
                findings.append(
                    f"data_classification={record.data_classification.value} "
                    f"requires encryption=both; saw {record.encryption_status.value}"
                )
                if status == CheckStatus.PASS:
                    status = CheckStatus.WARN

        # Anomaly already flagged upstream
        if record.access_anomaly:
            findings.append(
                f"access_anomaly upstream-flagged: "
                f"{record.access_anomaly_reason or 'no reason given'}"
            )
            if status == CheckStatus.PASS:
                status = CheckStatus.WARN

        return CheckResult(
            name=self.name,
            status=status,
            findings=findings,
            details={
                "pii_field_count": len(record.pii_fields_accessed),
                "sensitive_pii_field_count": len(sensitive_touched),
                "user_count": len(per_user),
            },
        )
