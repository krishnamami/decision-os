from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

from core.context_store import ContextBundle
from core.normalizer.models import DecisionOutcome
from core.policy_engine import PolicyDecision
from core.trace import SignalDirection

from .base import LendingPersona, OfflineReasoning, latest_object, make_signal


# ─────────────────────────────────────────────────────────────────────
# Employer-name normalization. Same problem as document entity
# resolution from the brainstorm — share with core/entity_resolution/
# when that module lands. For now it lives inline because the rules
# are small.
# ─────────────────────────────────────────────────────────────────────


_ENTITY_SUFFIXES = (
    "incorporated",
    "corporation",
    "company",
    "limited",
    "holdings",
    "group",
    "inc",
    "corp",
    "llc",
    "ltd",
    "co",
    "lp",
    "llp",
    "plc",
)
_PUNCT_RE = re.compile(r"[\.,&/\\()\[\]]+")
_WS_RE = re.compile(r"\s+")


def _normalize_employer(name: Optional[str]) -> str:
    """Lowercase, drop common entity suffixes + punctuation. Two raw
    names that resolve to the same canonical form are treated as the
    same employer. Reasonable for the 70%+ deterministic-match cases;
    fuzzy / LLM matching belongs in core/entity_resolution/."""
    if not name:
        return ""
    n = name.lower()
    n = _PUNCT_RE.sub(" ", n)
    n = _WS_RE.sub(" ", n).strip()
    tokens = [t for t in n.split() if t and t not in _ENTITY_SUFFIXES]
    return " ".join(tokens)


def _employer_match_confidence(stated: str, attempts: list[str]) -> float:
    """Highest deterministic confidence between the stated employer and
    any verification attempt's reported name. 1.0 on canonical match,
    0.6 on substring (one contains the other after normalization),
    0.0 otherwise."""
    s = _normalize_employer(stated)
    if not s or not attempts:
        return 0.0
    best = 0.0
    for raw in attempts:
        a = _normalize_employer(raw)
        if not a:
            continue
        if a == s:
            return 1.0
        if a in s or s in a:
            best = max(best, 0.6)
    return best


# ─────────────────────────────────────────────────────────────────────
# Timeline math
# ─────────────────────────────────────────────────────────────────────


@dataclass
class _Window:
    employer_canonical: str
    employer_aliases: list[str]
    start: date
    end: date
    sources: list[str]
    attempt_ids: list[str]
    gross_amounts: list[float]


def _parse_iso_date(value: Any) -> Optional[date]:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    s = str(value)
    # Accept full ISO datetimes and bare dates.
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None


def _months_between(a: date, b: date) -> int:
    if b < a:
        a, b = b, a
    return (b.year - a.year) * 12 + (b.month - a.month)


def _merge_into_windows(
    attempts: list[dict[str, Any]]
) -> list[_Window]:
    """Group attempts by canonical employer + overlapping windows.

    One Window per (canonical employer, contiguous date range). Two
    attempts for the same employer with non-overlapping dates produce
    two separate windows — captures e.g. an employee who left and was
    rehired."""

    by_employer: dict[str, list[dict[str, Any]]] = {}
    for a in attempts:
        canonical = _normalize_employer(a.get("employer_name_raw"))
        if not canonical:
            continue
        by_employer.setdefault(canonical, []).append(a)

    windows: list[_Window] = []
    for canonical, group in by_employer.items():
        # Sort by period_start, merge overlapping or touching ranges.
        normalized: list[tuple[date, date, dict[str, Any]]] = []
        for attempt in group:
            s = _parse_iso_date(attempt.get("period_start"))
            e = _parse_iso_date(attempt.get("period_end"))
            if s is None or e is None:
                continue
            if e < s:
                s, e = e, s
            normalized.append((s, e, attempt))
        normalized.sort(key=lambda t: t[0])

        for s, e, attempt in normalized:
            attached = False
            for w in windows:
                if w.employer_canonical != canonical:
                    continue
                # Overlap or touching (within 1 day) — merge.
                if s <= w.end and e >= w.start:
                    w.start = min(w.start, s)
                    w.end = max(w.end, e)
                    src = attempt.get("source") or "unknown"
                    if src not in w.sources:
                        w.sources.append(src)
                    aid = attempt.get("verification_attempt_id")
                    if aid and aid not in w.attempt_ids:
                        w.attempt_ids.append(aid)
                    raw = attempt.get("employer_name_raw")
                    if raw and raw not in w.employer_aliases:
                        w.employer_aliases.append(raw)
                    g = attempt.get("gross_amount")
                    if isinstance(g, (int, float)):
                        w.gross_amounts.append(float(g))
                    attached = True
                    break
            if attached:
                continue
            windows.append(_Window(
                employer_canonical=canonical,
                employer_aliases=[attempt.get("employer_name_raw")] if attempt.get("employer_name_raw") else [],
                start=s,
                end=e,
                sources=[attempt.get("source") or "unknown"],
                attempt_ids=[attempt.get("verification_attempt_id") or ""],
                gross_amounts=(
                    [float(attempt.get("gross_amount") or 0.0)]
                    if isinstance(attempt.get("gross_amount"), (int, float))
                    else []
                ),
            ))

    windows.sort(key=lambda w: w.start)
    return windows


def _continuity_coverage(
    windows: list[_Window], window_start: date, window_end: date
) -> tuple[float, int]:
    """Fraction of (window_start, window_end) covered by at least one
    EmploymentRecord, plus the largest contiguous gap in days.

    Treats the 24-month rolling window as the regulator-relevant
    surface: anything outside doesn't count, anything inside that's
    uncovered counts against coverage_pct + max_gap."""

    if window_end <= window_start:
        return (0.0, 0)
    total_days = (window_end - window_start).days
    if total_days <= 0:
        return (0.0, 0)

    intervals = []
    for w in windows:
        s = max(w.start, window_start)
        e = min(w.end, window_end)
        if e > s:
            intervals.append((s, e))
    if not intervals:
        return (0.0, total_days)

    intervals.sort()
    covered = 0
    cursor = window_start
    max_gap = 0
    for s, e in intervals:
        if s > cursor:
            gap = (s - cursor).days
            if gap > max_gap:
                max_gap = gap
            cursor = s
        if e > cursor:
            covered += (e - cursor).days
            cursor = e
    if cursor < window_end:
        tail = (window_end - cursor).days
        if tail > max_gap:
            max_gap = tail
    return (round(covered / total_days, 3), int(max_gap))


# ─────────────────────────────────────────────────────────────────────
# Persona
# ─────────────────────────────────────────────────────────────────────


class EmploymentReconciliationAgent(LendingPersona):
    """employment_reconciliation — join multi-source verification
    attempts into a continuity timeline.

    Reads bundle.objects["VerificationAttempt"] for the applicant. Joins
    by canonical employer name + overlapping date ranges. Produces a
    reconciliation_status, per-employer projection, continuity coverage
    over the policy window, and the worst gap in days.

    Initially shadow mode — gates nothing. The smoke
    (scripts/smoke_employment_continuity.py) shows it producing PARTIAL
    on the same scenario where today's income_verification produces
    ALLOW. A later commit will make income_verification depend on this
    decision's output."""

    DEFAULT_AGENT_ID = "employment_reconciliation_agent_v1"
    CONTINUITY_WINDOW_MONTHS = 24

    def __init__(
        self,
        *,
        agent_id: str = DEFAULT_AGENT_ID,
        use_anthropic: bool = False,
        **kw,
    ):
        super().__init__(
            agent_id=agent_id,
            persona="employment_reconciliation_agent",
            decision_id="employment_reconciliation",
            use_anthropic=use_anthropic,
            **kw,
        )

    def _compute_offline(
        self, bundle: ContextBundle, policy: Optional[PolicyDecision]
    ) -> OfflineReasoning:
        # Verification attempts arrive as bundle.objects["VerificationAttempt"]
        # keyed by entity_id. Multiple per applicant — append-only.
        attempts_map = bundle.objects.get("VerificationAttempt") or {}
        attempts = list(attempts_map.values())

        income = latest_object(bundle, "IncomeProfile") or {}
        stated_employer_raw = income.get("stated_employer") or ""
        stated_income = float(income.get("stated_income") or 0.0)

        windows = _merge_into_windows(attempts)
        n_windows = len(windows)

        # Continuity over the regulator-relevant surface — the last
        # CONTINUITY_WINDOW_MONTHS ending at the latest period_end we
        # observed (proxy for "now" inside the deterministic test).
        if windows:
            window_end = max(w.end for w in windows)
        else:
            window_end = date.today()
        # Roll back 24 months. Naive month math — month-aware enough
        # for the offline tests; production should handle leap days.
        wy = window_end.year
        wm = window_end.month - self.CONTINUITY_WINDOW_MONTHS
        while wm <= 0:
            wm += 12
            wy -= 1
        window_start = date(wy, wm, min(window_end.day, 28))
        coverage_pct, max_gap = _continuity_coverage(
            windows, window_start, window_end
        )

        # Stated-vs-verified employer match. Pick the highest-coverage
        # employer in the window as the "current" one for the comparison.
        if windows:
            current = max(windows, key=lambda w: (w.end - w.start).days)
            current_aliases = current.employer_aliases
            current_grosses = current.gross_amounts
        else:
            current = None
            current_aliases = []
            current_grosses = []

        employer_match_confidence = _employer_match_confidence(
            stated_employer_raw, current_aliases
        )

        # Comp drift across providers for the current employer. Uses
        # spread / mean — proxy for "do the providers agree on what
        # this employer pays this applicant".
        if len(current_grosses) >= 2:
            mean = sum(current_grosses) / len(current_grosses)
            spread = max(current_grosses) - min(current_grosses)
            comp_drift_pct = round(spread / mean, 3) if mean else 0.0
        else:
            comp_drift_pct = 0.0

        # Stated vs verified — only when applicant declared a number.
        if stated_income > 0 and current_grosses:
            verified_avg = sum(current_grosses) / len(current_grosses)
            stated_drift = round(abs(verified_avg - stated_income) / stated_income, 3)
        else:
            stated_drift = 0.0

        # Prior-employer corroboration: did we cover the window with
        # more than one employer? Single-employer 24-month tenure is
        # acceptable too, so this is a flag, not a fail.
        prior_employer_count = max(0, n_windows - 1)

        # ── Status synthesis ────────────────────────────────────────
        if not attempts:
            reconciliation_status = "missing"
        elif coverage_pct >= 0.95 and max_gap <= 30 \
                and employer_match_confidence >= 0.90 \
                and stated_drift <= 0.10 \
                and comp_drift_pct <= 0.10:
            reconciliation_status = "auto_verified"
        elif comp_drift_pct > 0.15:
            reconciliation_status = "conflict"
        else:
            reconciliation_status = "partial"

        # ── Outcome routing ─────────────────────────────────────────
        # Mode is shadow; the policy outcome is recorded but no
        # writeback fires. Boundary clauses from decisions.yaml drive
        # the proposed_outcome.
        if reconciliation_status == "auto_verified":
            outcome = DecisionOutcome.ALLOW
            confidence = 0.92
        elif reconciliation_status == "partial" and coverage_pct >= 0.80:
            outcome = DecisionOutcome.RECOMMEND
            confidence = 0.7
        elif reconciliation_status == "conflict":
            outcome = DecisionOutcome.ESCALATE
            confidence = 0.55
        else:
            outcome = DecisionOutcome.ESCALATE
            confidence = 0.5

        # ── Signals ─────────────────────────────────────────────────
        signals = [
            make_signal(
                "verification_attempts_count",
                len(attempts),
                source="verification_layer",
            ),
            make_signal(
                "employer_windows_count",
                n_windows,
                source="reconciliation",
            ),
            make_signal(
                "continuity_coverage_pct",
                coverage_pct,
                direction=(
                    SignalDirection.SUPPORTS
                    if coverage_pct >= 0.95
                    else SignalDirection.CONTRADICTS
                    if coverage_pct < 0.80
                    else SignalDirection.NEUTRAL
                ),
                source="reconciliation",
            ),
            make_signal(
                "max_gap_days",
                max_gap,
                direction=(
                    SignalDirection.CONTRADICTS
                    if max_gap > 30
                    else SignalDirection.SUPPORTS
                ),
                source="reconciliation",
            ),
            make_signal(
                "employer_name_match_confidence",
                employer_match_confidence,
                direction=(
                    SignalDirection.SUPPORTS
                    if employer_match_confidence >= 0.90
                    else SignalDirection.CONTRADICTS
                ),
                source="reconciliation",
            ),
            make_signal(
                "comp_drift_pct",
                comp_drift_pct,
                direction=(
                    SignalDirection.CONTRADICTS
                    if comp_drift_pct > 0.10
                    else SignalDirection.NEUTRAL
                ),
                source="reconciliation",
            ),
            make_signal(
                "stated_vs_verified_drift_pct",
                stated_drift,
                direction=(
                    SignalDirection.CONTRADICTS
                    if stated_drift > 0.10
                    else SignalDirection.NEUTRAL
                ),
                source="reconciliation",
            ),
            make_signal(
                "prior_employer_count",
                prior_employer_count,
                source="reconciliation",
            ),
        ]

        # Per-employer projection — packed into output_payload so
        # downstream personas + the UI can render it without re-running
        # the reconciliation. Future commit: write each window as a
        # SHARED EmploymentRecord row.
        employer_records = [
            {
                "employer_name_canonical": w.employer_canonical,
                "employer_name_aliases": list(w.employer_aliases),
                "start_date": w.start.isoformat(),
                "end_date": w.end.isoformat(),
                "tenure_months": _months_between(w.start, w.end),
                "corroborating_sources": list(w.sources),
                "corroborating_attempt_ids": list(w.attempt_ids),
                "monthly_gross_estimate": (
                    round(sum(w.gross_amounts) / len(w.gross_amounts) / 12, 0)
                    if w.gross_amounts
                    else None
                ),
            }
            for w in windows
        ]

        # Manual remediation flags — a future iteration writes these
        # into a HumanQueue item with structured sub-tasks.
        manual_voe_required = (
            reconciliation_status in ("partial", "conflict", "missing")
            and prior_employer_count == 0
        )
        gap_letter_required = max_gap > 30
        tax_transcript_required = (
            coverage_pct < 0.80 and prior_employer_count == 0
        )

        return OfflineReasoning(
            output_payload={
                "reconciliation_status": reconciliation_status,
                "continuity_coverage_pct": coverage_pct,
                "max_gap_days": max_gap,
                "employer_name_match_confidence": employer_match_confidence,
                "comp_drift_pct": comp_drift_pct,
                "stated_vs_verified_drift_pct": stated_drift,
                "prior_employer_count": prior_employer_count,
                "verification_attempts_count": len(attempts),
                "employer_records": employer_records,
                "manual_voe_required": manual_voe_required,
                "gap_letter_required": gap_letter_required,
                "tax_transcript_required": tax_transcript_required,
                "continuity_window_months": self.CONTINUITY_WINDOW_MONTHS,
            },
            proposed_outcome=outcome,
            confidence=confidence,
            signals=signals,
            contradictions=[],
            hypothesis=(
                "Auto-verifiable when: 24-month coverage ≥ 95%, max gap "
                "≤ 30 days, current-employer name matches stated, "
                "providers agree on comp within 10%, and stated income "
                "is within 10% of verified."
            ),
            conclusion=(
                f"reconciliation_status={reconciliation_status}, "
                f"coverage={coverage_pct:.0%} on "
                f"{n_windows} employer window(s), max_gap={max_gap}d, "
                f"employer_match={employer_match_confidence:.2f}, "
                f"comp_drift={comp_drift_pct:.0%}, "
                f"stated_drift={stated_drift:.0%} → {outcome.value}"
            ),
            confidence_basis=(
                "Confidence reflects the agreement of independent "
                "providers across the continuity window. Single-source "
                "or partial-coverage cases drop confidence; provider "
                "conflict on amount drops it further. A successful "
                "manual VOE / tax transcript later raises confidence "
                "via re-reconciliation."
            ),
            summary=(
                f"{len(attempts)} verification attempt(s) merged into "
                f"{n_windows} employer window(s). Continuity "
                f"{coverage_pct:.0%} over {self.CONTINUITY_WINDOW_MONTHS} "
                f"months; status={reconciliation_status}."
            ),
        )


__all__ = ["EmploymentReconciliationAgent"]
