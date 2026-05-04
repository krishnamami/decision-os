from __future__ import annotations

from typing import Optional

from .schema import (
    AuditRecord,
    CheckResult,
    CheckStatus,
    FairnessFlag,
)


# PRD §23.4 CHECK 4 — flag if any segment deviates > 15% from
# overall rate without credit-based explanation.
SEGMENT_DEVIATION_THRESHOLD = 0.15


class FairnessChecker:
    """PRD §23.4 CHECK 4.

    Evaluates approval rates across credit bands, geographies, and
    product types. Flags any segment whose rate deviates more than
    15% from the overall baseline without a credit-based explanation.

    Per-decision execution is informational — a single decision
    cannot itself fail fairness — but the checker still records the
    expected segment so the population-level report (PRD §23.7) can
    aggregate across many decisions.
    """

    name = "fairness"

    def __init__(
        self,
        deviation_threshold: float = SEGMENT_DEVIATION_THRESHOLD,
        baseline_rates: Optional[dict[str, float]] = None,
    ):
        self._threshold = deviation_threshold
        # baseline_rates maps segment label → approval rate observed in
        # the rolling population. Engine wiring can pass these in from
        # the audit reports layer when it lands.
        self._baselines = baseline_rates or {}

    def check(self, record: AuditRecord) -> CheckResult:
        findings: list[str] = []
        status = CheckStatus.PASS

        segment = record.applicant_segment
        if segment is None or not self._baselines:
            return CheckResult(
                name=self.name,
                status=status,
                findings=findings,
                details={
                    "baseline_segments": len(self._baselines),
                    "applicant_segment": segment,
                },
            )

        # Baseline lookup.
        overall = self._baselines.get("__overall__")
        segment_rate = self._baselines.get(segment)
        if overall is None or segment_rate is None:
            return CheckResult(
                name=self.name,
                status=status,
                findings=findings,
                details={
                    "applicant_segment": segment,
                    "missing_baseline": True,
                },
            )

        deviation = abs(segment_rate - overall)
        if deviation > self._threshold:
            findings.append(
                f"segment {segment!r} approval rate {segment_rate:.3f} "
                f"deviates {deviation:.3f} from overall {overall:.3f} "
                f"(>{self._threshold:.3f})"
            )
            record.fairness_flags.append(
                FairnessFlag(
                    attribute=segment,
                    flag_type="segment_deviation",
                    description=(
                        f"approval rate {segment_rate:.3f} vs overall "
                        f"{overall:.3f}"
                    ),
                    severity="warn",
                )
            )
            record.disparate_impact_flag = True
            status = CheckStatus.WARN

        return CheckResult(
            name=self.name,
            status=status,
            findings=findings,
            details={
                "applicant_segment": segment,
                "segment_rate": segment_rate,
                "overall_rate": overall,
                "deviation": deviation,
            },
        )
