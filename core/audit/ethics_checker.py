from __future__ import annotations

from typing import Iterable

from .schema import (
    AuditRecord,
    CheckResult,
    CheckStatus,
    FairnessFlag,
)


# PRD §23.9 protected_attributes_excluded_by_default.
PROTECTED_ATTRIBUTES = frozenset(
    {
        "race",
        "sex",
        "gender",
        "national_origin",
        "religion",
        "marital_status",
        "age",
    }
)


# PRD §23.4 CHECK 3 thresholds.
BIAS_MONITORING_THRESHOLD = 0.15
BIAS_ACTION_THRESHOLD = 0.30
DISPARATE_IMPACT_RATIO = 2.0


class EthicsChecker:
    """PRD §23.4 CHECK 3.

    Evaluates protected attributes in context vs excluded, the
    bias_score, and segment divergence. Flags above the monitoring
    threshold and fails above the action threshold."""

    name = "ethics"

    def __init__(self, protected: Iterable[str] = PROTECTED_ATTRIBUTES):
        self._protected = frozenset(protected)

    def check(self, record: AuditRecord) -> CheckResult:
        findings: list[str] = []
        status = CheckStatus.PASS

        # Protected attributes must be either explicitly excluded or
        # explicitly permitted; presence in the agent's context without
        # an entry in protected_attrs_excluded is a hard fail.
        unaccounted = [
            attr
            for attr in record.protected_attrs_used
            if attr in self._protected
            and attr not in record.protected_attrs_excluded
        ]
        if unaccounted:
            findings.append(
                f"protected attributes touched without exclusion entry: "
                f"{sorted(unaccounted)}"
            )
            status = CheckStatus.FAIL
            for attr in unaccounted:
                record.fairness_flags.append(
                    FairnessFlag(
                        attribute=attr,
                        flag_type="protected_attribute_in_context",
                        description=(
                            f"{attr} present in agent reasoning surface but not "
                            f"in protected_attrs_excluded"
                        ),
                        severity="fail",
                    )
                )

        # Bias score thresholds.
        if record.bias_score is not None:
            if record.bias_score >= BIAS_ACTION_THRESHOLD:
                findings.append(
                    f"bias_score={record.bias_score:.3f} ≥ action threshold "
                    f"{BIAS_ACTION_THRESHOLD}"
                )
                status = CheckStatus.FAIL
            elif record.bias_score >= BIAS_MONITORING_THRESHOLD:
                findings.append(
                    f"bias_score={record.bias_score:.3f} ≥ monitoring threshold "
                    f"{BIAS_MONITORING_THRESHOLD}"
                )
                if status == CheckStatus.PASS:
                    status = CheckStatus.WARN

        if record.disparate_impact_flag:
            findings.append("disparate_impact_flag set upstream")
            if status != CheckStatus.FAIL:
                status = CheckStatus.WARN

        return CheckResult(
            name=self.name,
            status=status,
            findings=findings,
            details={
                "protected_attrs_used_count": len(record.protected_attrs_used),
                "protected_attrs_excluded_count": len(record.protected_attrs_excluded),
                "bias_score": record.bias_score,
            },
        )
