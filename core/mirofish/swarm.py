"""MiroFish SwarmAnalyzer — 12 agents scan the WHOLE portfolio at once.

A single-loan review can't see that 40 loans share one employer, that the
book is 97% conforming, or that 200 rate locks expire the same week. The
swarm can: every agent runs a portfolio-level scan, the engine looks for
CROSS-agent patterns (employer concentration ∩ income discrepancy; high
LTV ∩ high DTI), and each agent writes a one-paragraph portfolio summary.

Deterministic by default (local-first, no API key). Pass an
``anthropic_client`` to have Claude review the assembled findings for
emergent risks the individual scans might miss.

Honest about data: this dataset has no property geography / occupancy and
(currently) no overrides, so the geographic-cluster, straw-buyer, and
override-concentration scans surface nothing rather than inventing a
pattern. Everything else runs on real fields.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional

from core.mirofish.models import SwarmInsight, SwarmResult


_SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}
_SAMPLE = 25  # cap affected-app id lists so payloads stay small
_ANTHROPIC_MODEL = "claude-sonnet-4-6"

# Generic self-employment labels are NOT a single employer — excluded from
# employer-concentration math so "Self-Employed" isn't a layoff-risk cluster.
_NON_EMPLOYER_MARKERS = (
    "self-employed", "self employed", "self_employed", "sole propr",
    "independent consultant", "independent contractor", "unemployed",
    "retired", "n/a", "none",
)


def _is_real_employer(name: Optional[str]) -> bool:
    if not name:
        return False
    low = str(name).lower()
    return not any(m in low for m in _NON_EMPLOYER_MARKERS)


def _J(v: Any) -> Any:
    if isinstance(v, (bytes, bytearray)):
        v = v.decode("utf-8", "replace")
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (ValueError, json.JSONDecodeError):
            return {}
    return v or {}


def _f(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _b(v: Any) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes", "t")


def _pct(part: int, whole: int) -> float:
    return (part / whole * 100.0) if whole else 0.0


def _median(values: list[float]) -> Optional[float]:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    n = len(vals)
    mid = n // 2
    return vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2


class SwarmAnalyzer:
    """Runs all 12 agents across the portfolio and returns ranked
    emergent insights + per-agent summaries as a :class:`SwarmResult`."""

    def __init__(self, db_connection: Any, anthropic_client: Optional[Any] = None):
        self.db = db_connection
        self.client = anthropic_client

    @asynccontextmanager
    async def _acquire(self):
        db = self.db
        if hasattr(db, "acquire"):
            async with db.acquire() as conn:
                yield conn
        else:
            yield db

    # ── Public entrypoint ────────────────────────────────────────────

    async def analyze(self, tenant_id: str = "default") -> SwarmResult:
        apps = await self._load_portfolio(tenant_id)

        scans = [
            self._scan_credit, self._scan_fraud, self._scan_compliance,
            self._scan_employment, self._scan_income, self._scan_ltv,
            self._scan_dti, self._scan_product, self._scan_rate,
            self._scan_underwriting, self._scan_routing, self._scan_closer,
        ]
        insights: list[SwarmInsight] = []
        for scan in scans:
            insights.extend(scan(apps))

        insights.extend(self._cross_agent_synthesis(apps, insights))

        summaries = self._agent_summaries(apps)
        insights.sort(key=lambda i: _SEVERITY_RANK.get(i.severity, 9))

        if self.client is not None:
            emergent = await self._claude_emergent(apps, insights)
            insights.extend(emergent)

        return SwarmResult(
            tenant_id=tenant_id,
            total_apps_scanned=len(apps),
            insights=insights,
            agent_summaries=summaries,
            created_at=datetime.now(timezone.utc),
        )

    # ── Portfolio load + flatten ─────────────────────────────────────

    async def _load_portfolio(self, tenant_id: str) -> list[dict]:
        async with self._acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT application_id, loan_amount, appraised_value, interest_rate,
                       mid_credit_score, ltv, dti_back, days_in_current_status,
                       loan_age_days, status, completeness_pct, conflict_count,
                       critical_conflict_count, title_clear, insurance_bound,
                       clear_to_close, borrower, property, loan_terms
                FROM entity_states WHERE tenant_id = $1
                """,
                tenant_id,
            )
            decisions = await conn.fetch(
                """
                SELECT application_id, decision_id, outcome, mode,
                       human_action, human_reviewer
                FROM decision_outputs dout
                WHERE tenant_id = $1
                  AND version = (
                      SELECT MAX(version) FROM decision_outputs d2
                      WHERE d2.application_id = dout.application_id
                        AND d2.decision_id = dout.decision_id
                  )
                """,
                tenant_id,
            )

        by_app: dict[str, dict] = defaultdict(dict)
        for d in decisions:
            by_app[d["application_id"]][d["decision_id"]] = {
                "outcome": d["outcome"], "mode": d["mode"],
                "human_action": d["human_action"], "human_reviewer": d["human_reviewer"],
            }

        apps: list[dict] = []
        for r in rows:
            borrower = _J(r["borrower"])
            prop = _J(r["property"])
            lt = _J(r["loan_terms"])
            identity = borrower.get("identity") or {}
            employment = borrower.get("employment") or {}
            income = borrower.get("income") or {}
            apps.append({
                "app_id": r["application_id"],
                "loan_amount": _f(r["loan_amount"]),
                "appraised_value": _f(r["appraised_value"]),
                "interest_rate": _f(r["interest_rate"]),
                "credit_score": _f(r["mid_credit_score"]),
                "ltv": self._as_pct(_f(r["ltv"])),
                "dti_back": self._as_pct(_f(r["dti_back"])),
                "days_in_status": _f(r["days_in_current_status"]),
                "loan_age_days": _f(r["loan_age_days"]),
                "status": r["status"],
                "completeness": self._as_pct(_f(r["completeness_pct"])),
                "conflict_count": _f(r["conflict_count"]) or 0,
                "critical_conflicts": _f(r["critical_conflict_count"]) or 0,
                "title_clear": r["title_clear"],
                "insurance_bound": r["insurance_bound"],
                # identity / fraud
                "fraud_score": _f(identity.get("fraud_score")),
                "watchlist_match": _b(identity.get("watchlist_match")),
                "synthetic_flag": _b(identity.get("synthetic_identity_flag")),
                "doc_auth": _f(identity.get("document_authenticity_score")),
                "id_match": _f(identity.get("identity_match_confidence")),
                # employment
                "employer_name": (employment.get("employer_name")
                                  or income.get("stated_employer")),
                "max_gap_days": _f(employment.get("max_gap_days")),
                "reconciliation_status": employment.get("reconciliation_status"),
                "employer_match_conf": _f(employment.get("employer_name_match_confidence")),
                "employer_on_watchlist": _b(employment.get("employer_on_watchlist")),
                # income
                "employment_type": (income.get("employment_type") or "").lower(),
                "income_discrepancy": _f(income.get("income_discrepancy_pct")),
                "income_confidence": _f(income.get("income_confidence_score")),
                "verified_income": _f(income.get("verified_income_annual")),
                "multiple_income": _b(income.get("multiple_income_sources")),
                # property risk flags
                "title_defect": _b(prop.get("title_defect")),
                "lien_dispute": _b(prop.get("lien_dispute")),
                "insurance_gap": _b(prop.get("insurance_gap")),
                "appraisal_disputed": _b(prop.get("appraisal_disputed")),
                # product / rate
                "loan_type": lt.get("loan_type"),
                "lock_expiry": (lt.get("rate_lock") or {}).get("lock_expiry"),
                # decisions
                "decisions": by_app.get(r["application_id"], {}),
            })
        return apps

    @staticmethod
    def _as_pct(v: Optional[float]) -> Optional[float]:
        if v is None:
            return None
        return v * 100 if -1.5 <= v <= 1.5 else v

    # ── Per-agent scans ──────────────────────────────────────────────

    def _scan_credit(self, apps: list[dict]) -> list[SwarmInsight]:
        out = []
        scored = [a for a in apps if a["credit_score"]]
        n = len(scored)
        near = [a for a in scored if 620 <= a["credit_score"] <= 680]
        if n and _pct(len(near), n) >= 15:
            out.append(SwarmInsight(
                insight_type="concentration", severity="warning",
                detected_by=["credit_assessment"],
                description=(
                    f"{len(near)} loans ({_pct(len(near), n):.0f}%) sit in the 620–680 "
                    "near-boundary credit range. A small credit-floor change would flip "
                    "many decisions at once."
                ),
                affected_apps=[a["app_id"] for a in near][:_SAMPLE],
                evidence=[{"metric": "score_distribution", "near_boundary": len(near),
                           "scored": n}],
            ))
        thin = [a for a in apps if not a["credit_score"]]
        if apps and _pct(len(thin), len(apps)) >= 5:
            out.append(SwarmInsight(
                insight_type="pattern", severity="info",
                detected_by=["credit_assessment"],
                description=(
                    f"{len(thin)} loans ({_pct(len(thin), len(apps)):.0f}%) have no mid "
                    "credit score on file — a thin-file concentration that can't be "
                    "auto-scored."
                ),
                affected_apps=[a["app_id"] for a in thin][:_SAMPLE],
                evidence=[{"metric": "thin_file", "count": len(thin)}],
            ))
        return out

    def _scan_fraud(self, apps: list[dict]) -> list[SwarmInsight]:
        out = []
        watch = [a for a in apps if a["watchlist_match"] or a["synthetic_flag"]]
        if watch:
            out.append(SwarmInsight(
                insight_type="anomaly", severity="critical",
                detected_by=["fraud_screening"],
                description=(
                    f"{len(watch)} loan(s) hit a watchlist or synthetic-identity flag — "
                    "these should be quarantined and re-reviewed before any progress."
                ),
                affected_apps=[a["app_id"] for a in watch][:_SAMPLE],
                evidence=[{"metric": "watchlist_or_synthetic", "count": len(watch)}],
            ))
        # (Employer-level discrepancy is owned by the cross-agent pass,
        # which compares against the portfolio baseline so it doesn't just
        # re-report a book-wide discrepancy rate. No property geography in
        # this dataset, so the geographic-cluster scan can't run.)
        low_auth = [a for a in apps if a["doc_auth"] is not None and a["doc_auth"] < 0.7]
        if apps and _pct(len(low_auth), len(apps)) >= 8:
            out.append(SwarmInsight(
                insight_type="pattern", severity="warning",
                detected_by=["fraud_screening"],
                description=(
                    f"{len(low_auth)} loans ({_pct(len(low_auth), len(apps)):.0f}%) carry a "
                    "document-authenticity score below 0.70 — a systematic document-quality "
                    "problem worth tracing to source."
                ),
                affected_apps=[a["app_id"] for a in low_auth][:_SAMPLE],
                evidence=[{"metric": "low_doc_authenticity", "count": len(low_auth)}],
            ))
        return out

    def _scan_compliance(self, apps: list[dict]) -> list[SwarmInsight]:
        out = []
        # No protected-class / geography data here, so true disparate-impact
        # analysis can't run — surface the completeness gaps that would block
        # HMDA reporting instead.
        gaps = [a for a in apps if a["completeness"] is not None and a["completeness"] < 80]
        share = _pct(len(gaps), len(apps))
        # Only emit when the gap is notable but NOT universal — a 100% rate
        # is a constant-value data artifact, not an actionable concentration.
        if apps and 10 <= share <= 90:
            out.append(SwarmInsight(
                insight_type="pattern", severity="warning",
                detected_by=["compliance_check"],
                description=(
                    f"{len(gaps)} loans ({share:.0f}%) are below 80% data completeness — an "
                    "HMDA-reporting gap that compounds at portfolio scale."
                ),
                affected_apps=[a["app_id"] for a in gaps][:_SAMPLE],
                evidence=[{"metric": "completeness_lt_80", "count": len(gaps)}],
            ))
        return out

    def _scan_employment(self, apps: list[dict]) -> list[SwarmInsight]:
        out = []
        # Only real employers, and only when one stands out from the pack
        # (≥10% of the book) — a roughly-uniform spread of employers is not
        # a concentration risk.
        counts = Counter(a["employer_name"] for a in apps if _is_real_employer(a["employer_name"]))
        for employer, c in counts.most_common(3):
            if _pct(c, len(apps)) >= 10:
                ids = [a["app_id"] for a in apps if a["employer_name"] == employer]
                out.append(SwarmInsight(
                    insight_type="concentration", severity="warning",
                    detected_by=["employment_reconciliation"],
                    description=(
                        f"Employer concentration: '{employer}' appears on {c} loans "
                        f"({_pct(c, len(apps)):.1f}% of the book) — a single-employer "
                        "layoff would hit many loans together."
                    ),
                    affected_apps=ids[:_SAMPLE],
                    evidence=[{"employer": employer, "loans": c}],
                ))
        gaps = [a for a in apps if (a["max_gap_days"] or 0) > 90]
        if apps and _pct(len(gaps), len(apps)) >= 8:
            out.append(SwarmInsight(
                insight_type="pattern", severity="info",
                detected_by=["employment_reconciliation"],
                description=(
                    f"{len(gaps)} loans show an employment gap over 90 days — a continuity "
                    "pattern that may need gap letters across the book."
                ),
                affected_apps=[a["app_id"] for a in gaps][:_SAMPLE],
                evidence=[{"metric": "gap_gt_90d", "count": len(gaps)}],
            ))
        return out

    def _scan_income(self, apps: list[dict]) -> list[SwarmInsight]:
        out = []
        disc = [a for a in apps if (a["income_discrepancy"] or 0) > 0.10]
        if apps and _pct(len(disc), len(apps)) >= 25:
            out.append(SwarmInsight(
                insight_type="pattern", severity="warning",
                detected_by=["income_verification"],
                description=(
                    f"{len(disc)} loans ({_pct(len(disc), len(apps)):.0f}%) across the book "
                    "show a >10% stated-vs-verified income discrepancy — a systematic "
                    "documentation gap, not isolated cases. Tighten income verification at "
                    "intake."
                ),
                affected_apps=[a["app_id"] for a in disc][:_SAMPLE],
                evidence=[{"metric": "portfolio_discrepancy_rate", "count": len(disc),
                           "pct": round(_pct(len(disc), len(apps)), 1)}],
            ))
        self_emp = [a for a in apps if "self" in a["employment_type"] or "1099" in a["employment_type"]]
        if apps and _pct(len(self_emp), len(apps)) >= 15:
            out.append(SwarmInsight(
                insight_type="concentration", severity="info",
                detected_by=["income_verification"],
                description=(
                    f"{len(self_emp)} loans ({_pct(len(self_emp), len(apps)):.0f}%) are "
                    "self-employed / 1099 — income volatility concentration that warrants "
                    "tighter reserve scrutiny."
                ),
                affected_apps=[a["app_id"] for a in self_emp][:_SAMPLE],
                evidence=[{"metric": "self_employed", "count": len(self_emp)}],
            ))
        # Income-to-loan leverage outliers.
        lev = [a for a in apps if a["verified_income"] and a["loan_amount"]
               and a["loan_amount"] / a["verified_income"] > 5]
        if lev:
            out.append(SwarmInsight(
                insight_type="anomaly", severity="info",
                detected_by=["income_verification"],
                description=(
                    f"{len(lev)} loans exceed 5× verified annual income in loan size — "
                    "high-leverage outliers relative to documented income."
                ),
                affected_apps=[a["app_id"] for a in lev][:_SAMPLE],
                evidence=[{"metric": "loan_over_5x_income", "count": len(lev)}],
            ))
        return out

    def _scan_ltv(self, apps: list[dict]) -> list[SwarmInsight]:
        out = []
        high = [a for a in apps if a["ltv"] and a["ltv"] > 90]
        if apps and _pct(len(high), len(apps)) >= 12:
            out.append(SwarmInsight(
                insight_type="concentration", severity="warning",
                detected_by=["ltv_assessment"],
                description=(
                    f"{len(high)} loans ({_pct(len(high), len(apps)):.0f}%) are above 90% "
                    "LTV — a thin-equity concentration that is highly sensitive to any "
                    "home-price decline."
                ),
                affected_apps=[a["app_id"] for a in high][:_SAMPLE],
                evidence=[{"metric": "ltv_gt_90", "count": len(high)}],
            ))
        # Appraisal clustering at convenient round values.
        round_vals = [a for a in apps if a["appraised_value"]
                      and a["appraised_value"] % 10000 == 0]
        if apps and _pct(len(round_vals), len(apps)) >= 25:
            out.append(SwarmInsight(
                insight_type="anomaly", severity="info",
                detected_by=["ltv_assessment"],
                description=(
                    f"{len(round_vals)} appraisals ({_pct(len(round_vals), len(apps)):.0f}%) "
                    "land on exact $10K round numbers — convenient-value clustering worth a "
                    "spot audit."
                ),
                affected_apps=[a["app_id"] for a in round_vals][:_SAMPLE],
                evidence=[{"metric": "round_appraisal", "count": len(round_vals)}],
            ))
        return out

    def _scan_dti(self, apps: list[dict]) -> list[SwarmInsight]:
        out = []
        edge = [a for a in apps if a["dti_back"] and 42 <= a["dti_back"] <= 43]
        if apps and len(edge) >= max(5, len(apps) * 0.05):
            out.append(SwarmInsight(
                insight_type="concentration", severity="warning",
                detected_by=["dti_calculation"],
                description=(
                    f"{len(edge)} loans sit at the 42–43% DTI edge — a cluster right at the "
                    "guideline line, so a 1-point tightening would block them all."
                ),
                affected_apps=[a["app_id"] for a in edge][:_SAMPLE],
                evidence=[{"metric": "dti_42_43", "count": len(edge)}],
            ))
        high = [a for a in apps if a["dti_back"] and a["dti_back"] > 43]
        if apps and _pct(len(high), len(apps)) >= 10:
            out.append(SwarmInsight(
                insight_type="pattern", severity="info",
                detected_by=["dti_calculation"],
                description=(
                    f"{len(high)} loans ({_pct(len(high), len(apps)):.0f}%) carry a back-end "
                    "DTI above 43% — leverage concentration if rates rise."
                ),
                affected_apps=[a["app_id"] for a in high][:_SAMPLE],
                evidence=[{"metric": "dti_gt_43", "count": len(high)}],
            ))
        return out

    def _scan_product(self, apps: list[dict]) -> list[SwarmInsight]:
        out = []
        counts = Counter(a["loan_type"] for a in apps if a["loan_type"])
        total = sum(counts.values())
        if total:
            top_type, c = counts.most_common(1)[0]
            if _pct(c, total) >= 85:
                out.append(SwarmInsight(
                    insight_type="concentration", severity="warning",
                    detected_by=["product_eligibility"],
                    description=(
                        f"Product concentration: {_pct(c, total):.0f}% of the book is "
                        f"'{top_type}' — almost no product diversification, so one agency "
                        "guideline change moves the whole portfolio."
                    ),
                    affected_apps=[a["app_id"] for a in apps if a["loan_type"] == top_type][:_SAMPLE],
                    evidence=[{"loan_type": t, "count": n} for t, n in counts.most_common(5)],
                ))
        return out

    def _scan_rate(self, apps: list[dict]) -> list[SwarmInsight]:
        out = []
        weeks: dict[str, list[str]] = defaultdict(list)
        for a in apps:
            if a["lock_expiry"]:
                try:
                    d = datetime.fromisoformat(str(a["lock_expiry"])[:10]).date()
                    iso = d.isocalendar()
                    weeks[f"{iso[0]}-W{iso[1]:02d}"].append(a["app_id"])
                except ValueError:
                    continue
        locked = sum(len(v) for v in weeks.values())
        if weeks:
            top_week, ids = max(weeks.items(), key=lambda kv: len(kv[1]))
            if locked and _pct(len(ids), locked) >= 15:
                out.append(SwarmInsight(
                    insight_type="concentration", severity="warning",
                    detected_by=["rate_pricing"],
                    description=(
                        f"{len(ids)} rate locks ({_pct(len(ids), locked):.0f}% of locked "
                        f"loans) all expire in {top_week} — an operational crunch; unresolved "
                        "files that week will need costly re-locks."
                    ),
                    affected_apps=ids[:_SAMPLE],
                    evidence=[{"week": top_week, "expiring": len(ids), "locked": locked}],
                ))
        return out

    def _scan_underwriting(self, apps: list[dict]) -> list[SwarmInsight]:
        out = []
        uw = [a for a in apps if "underwriting_decision" in a["decisions"]]
        blocked = [a for a in uw if a["decisions"]["underwriting_decision"]["outcome"] == "block"]
        if uw and _pct(len(blocked), len(uw)) >= 20:
            out.append(SwarmInsight(
                insight_type="pattern", severity="warning",
                detected_by=["underwriting_decision"],
                description=(
                    f"Underwriting block/decline rate is {_pct(len(blocked), len(uw)):.0f}% "
                    f"({len(blocked)}/{len(uw)}) — elevated; worth checking whether intake "
                    "quality or a policy is too tight."
                ),
                affected_apps=[a["app_id"] for a in blocked][:_SAMPLE],
                evidence=[{"metric": "uw_block_rate", "blocked": len(blocked), "total": len(uw)}],
            ))
        # Override concentration by reviewer (no overrides in this data → silent).
        overrides = Counter(
            a["decisions"][d]["human_reviewer"]
            for a in apps for d in a["decisions"]
            if a["decisions"][d]["human_action"] == "overridden" and a["decisions"][d]["human_reviewer"]
        )
        total_ov = sum(overrides.values())
        if total_ov >= 10:
            reviewer, c = overrides.most_common(1)[0]
            if _pct(c, total_ov) >= 50:
                out.append(SwarmInsight(
                    insight_type="anomaly", severity="warning",
                    detected_by=["underwriting_decision"],
                    description=(
                        f"Override concentration: '{reviewer}' accounts for {_pct(c, total_ov):.0f}% "
                        f"of all overrides ({c}/{total_ov}) — a control point worth a QC review."
                    ),
                    affected_apps=[],
                    evidence=[{"reviewer": reviewer, "overrides": c, "total": total_ov}],
                ))
        aging = [a for a in apps if (a["days_in_status"] or 0) > 30]
        if apps and _pct(len(aging), len(apps)) >= 15:
            out.append(SwarmInsight(
                insight_type="pattern", severity="info",
                detected_by=["underwriting_decision"],
                description=(
                    f"{len(aging)} loans ({_pct(len(aging), len(apps)):.0f}%) have been in "
                    "their current status over 30 days — pipeline aging that risks rate-lock "
                    "and document staleness."
                ),
                affected_apps=[a["app_id"] for a in aging][:_SAMPLE],
                evidence=[{"metric": "aging_gt_30d", "count": len(aging)}],
            ))
        return out

    def _scan_routing(self, apps: list[dict]) -> list[SwarmInsight]:
        out = []
        routed = [a for a in apps if "approval_routing" in a["decisions"]]
        # Adverse-action volume — declines being routed to notices.
        declines = [
            a for a in routed
            if a["decisions"].get("underwriting_decision", {}).get("outcome") == "block"
        ]
        if routed and _pct(len(declines), len(routed)) >= 25:
            out.append(SwarmInsight(
                insight_type="pattern", severity="info",
                detected_by=["approval_routing"],
                description=(
                    f"{len(declines)} routed files ({_pct(len(declines), len(routed)):.0f}%) "
                    "carry a declined underwriting decision — a sizeable adverse-action "
                    "notice volume that must clear ECOA timing."
                ),
                affected_apps=[a["app_id"] for a in declines][:_SAMPLE],
                evidence=[{"metric": "adverse_action_volume", "count": len(declines)}],
            ))
        return out

    def _scan_closer(self, apps: list[dict]) -> list[SwarmInsight]:
        out = []
        gaps = [a for a in apps if a["title_defect"] or a["lien_dispute"] or a["insurance_gap"]]
        if gaps:
            sev = "warning" if _pct(len(gaps), len(apps)) >= 5 else "info"
            out.append(SwarmInsight(
                insight_type="pattern", severity=sev,
                detected_by=["closing_readiness"],
                description=(
                    f"{len(gaps)} loans have an open title defect, lien dispute, or insurance "
                    "gap — closing blockers that should be worked in parallel, not at the "
                    "table."
                ),
                affected_apps=[a["app_id"] for a in gaps][:_SAMPLE],
                evidence=[{"metric": "title_insurance_gaps", "count": len(gaps)}],
            ))
        return out

    # ── Cross-agent synthesis ────────────────────────────────────────

    def _cross_agent_synthesis(
        self, apps: list[dict], insights: list[SwarmInsight]
    ) -> list[SwarmInsight]:
        out = []
        # High LTV ∩ high DTI — compound risk cluster.
        compound = [
            a for a in apps
            if a["ltv"] and a["ltv"] > 90 and a["dti_back"] and a["dti_back"] > 43
        ]
        if len(compound) >= 5:
            out.append(SwarmInsight(
                insight_type="correlation", severity="critical",
                detected_by=["ltv_assessment", "dti_calculation"],
                description=(
                    f"Compound-risk cluster: {len(compound)} loans are BOTH above 90% LTV "
                    "and above 43% DTI — thin equity and stretched income together. These "
                    "fail first under any rate or price stress."
                ),
                affected_apps=[a["app_id"] for a in compound][:_SAMPLE],
                evidence=[{"metric": "high_ltv_and_high_dti", "count": len(compound)}],
            ))
        # Employer ∩ income discrepancy — only employers whose discrepancy
        # RATE materially exceeds the portfolio baseline (else we'd just be
        # re-reporting a book-wide rate). Consolidated into one insight.
        disc_all = [a for a in apps if (a["income_discrepancy"] or 0) > 0.10]
        baseline = (len(disc_all) / len(apps)) if apps else 0.0
        offenders = []
        emp_loans: dict[str, list[dict]] = defaultdict(list)
        for a in apps:
            if _is_real_employer(a["employer_name"]):
                emp_loans[a["employer_name"]].append(a)
        for employer, group in emp_loans.items():
            if len(group) < 30:
                continue
            d = sum(1 for a in group if (a["income_discrepancy"] or 0) > 0.10)
            rate = d / len(group)
            if rate >= baseline + 0.15 and rate >= 0.50:
                offenders.append((employer, len(group), d, rate))
        if offenders:
            offenders.sort(key=lambda x: -x[3])
            top = offenders[:5]
            names = ", ".join(f"{e} ({r*100:.0f}%)" for e, _, _, r in top)
            ids = [a["app_id"] for e, *_ in top
                   for a in emp_loans[e] if (a["income_discrepancy"] or 0) > 0.10][:_SAMPLE]
            out.append(SwarmInsight(
                insight_type="correlation", severity="warning",
                detected_by=["employment_reconciliation", "income_verification"],
                description=(
                    f"{len(offenders)} employer(s) show an income-discrepancy rate well above "
                    f"the {baseline*100:.0f}% book baseline — worst: {names}. Concentration "
                    "and misrepresentation risk reinforce each other at these employers."
                ),
                affected_apps=ids,
                evidence=[{"baseline_pct": round(baseline * 100, 1),
                           "employer": e, "loans": g, "discrepant": d, "rate_pct": round(r * 100, 1)}
                          for e, g, d, r in top],
            ))
        return out

    # ── Per-agent portfolio summaries ────────────────────────────────

    def _agent_summaries(self, apps: list[dict]) -> dict[str, str]:
        n = len(apps) or 1
        scores = [a["credit_score"] for a in apps if a["credit_score"]]
        dtis = [a["dti_back"] for a in apps if a["dti_back"]]
        ltvs = [a["ltv"] for a in apps if a["ltv"]]
        med_score = _median(scores)
        med_dti = _median(dtis)
        med_ltv = _median(ltvs)
        near = sum(1 for s in scores if 620 <= s <= 680)
        emp_counts = Counter(a["employer_name"] for a in apps if _is_real_employer(a["employer_name"]))
        top_emp = emp_counts.most_common(1)[0] if emp_counts else (None, 0)
        self_emp = sum(1 for a in apps if "self" in a["employment_type"] or "1099" in a["employment_type"])
        disc = sum(1 for a in apps if (a["income_discrepancy"] or 0) > 0.10)
        high_ltv = sum(1 for a in apps if a["ltv"] and a["ltv"] > 90)
        loan_types = Counter(a["loan_type"] for a in apps if a["loan_type"])
        top_type = loan_types.most_common(1)[0] if loan_types else (None, 0)
        gaps = sum(1 for a in apps if a["title_defect"] or a["lien_dispute"] or a["insurance_gap"])
        aging = sum(1 for a in apps if (a["days_in_status"] or 0) > 30)
        uw = [a for a in apps if "underwriting_decision" in a["decisions"]]
        blocked = sum(1 for a in uw if a["decisions"]["underwriting_decision"]["outcome"] == "block")

        return {
            "credit_assessment": (
                f"Median mid score {med_score:.0f}. " if med_score else "No scored loans. "
            ) + (
                f"{_pct(near, len(scores)):.0f}% of scored loans cluster near the 620–680 "
                "boundary, making the book sensitive to credit-floor changes."
                if scores else "Most loans are unscoreable (thin file)."
            ),
            "fraud_screening": (
                f"{sum(1 for a in apps if a['watchlist_match'] or a['synthetic_flag'])} "
                "watchlist/synthetic flags; "
                f"{sum(1 for a in apps if a['doc_auth'] is not None and a['doc_auth'] < 0.7)} "
                "loans below 0.70 document authenticity."
            ),
            "compliance_check": (
                f"{sum(1 for a in apps if a['completeness'] is not None and a['completeness'] < 80)} "
                "loans under 80% completeness; protected-class/geography data isn't present, "
                "so disparate-impact analysis can't run on this book."
            ),
            "employment_reconciliation": (
                f"Top employer '{top_emp[0]}' on {top_emp[1]} loans "
                f"({_pct(top_emp[1], n):.1f}% of the book)." if top_emp[0]
                else "No employer names on file."
            ),
            "income_verification": (
                f"{_pct(self_emp, n):.0f}% self-employed/1099; {disc} loans show a >10% "
                "stated-vs-verified income discrepancy."
            ),
            "ltv_assessment": (
                f"Median LTV {med_ltv:.0f}%. " if med_ltv else ""
            ) + f"{_pct(high_ltv, n):.0f}% of loans exceed 90% LTV (thin equity).",
            "dti_calculation": (
                f"Median back-end DTI {med_dti:.0f}%. " if med_dti else "DTI sparsely computed. "
            ) + f"{sum(1 for a in apps if a['dti_back'] and a['dti_back'] > 43)} loans exceed 43%.",
            "product_eligibility": (
                f"{_pct(top_type[1], n):.0f}% '{top_type[0]}' — "
                f"{'heavy concentration, little diversification' if top_type[1]/n >= 0.85 else 'reasonable mix'}."
                if top_type[0] else "No product types on file."
            ),
            "rate_pricing": (
                f"{sum(1 for a in apps if a['lock_expiry'])} loans have an active rate lock; "
                "watch for week-level expiry clustering."
            ),
            "underwriting_decision": (
                f"Underwriting block/decline rate {_pct(blocked, len(uw)):.0f}% "
                f"({blocked}/{len(uw)}); {_pct(aging, n):.0f}% of loans are aging past 30 days."
                if uw else "No underwriting decisions yet."
            ),
            "approval_routing": (
                f"{sum(1 for a in apps if 'approval_routing' in a['decisions'])} loans routed; "
                "declines route to adverse-action notices under ECOA timing."
            ),
            "closing_readiness": (
                f"{gaps} loans carry an open title/lien/insurance gap blocking clear-to-close."
            ),
        }

    # ── Claude emergent pass (opt-in) ────────────────────────────────

    async def _claude_emergent(
        self, apps: list[dict], insights: list[SwarmInsight]
    ) -> list[SwarmInsight]:
        if not insights:
            return []
        findings = "\n".join(
            f"- [{i.severity}] {i.insight_type} ({', '.join(i.detected_by)}): {i.description}"
            for i in insights
        )
        system = (
            "You are the lead risk officer reviewing portfolio-level findings from 12 "
            "underwriting agents. Identify EMERGENT risks that span findings — patterns no "
            "single agent's scan would catch. Return ONLY a JSON array of objects: "
            '[{"severity":"info|warning|critical","description":"..."}].'
        )
        user = (
            f"{len(apps)} loans scanned. Agent findings:\n{findings}\n\n"
            "What emergent, cross-cutting risks do you see? Be specific and concise."
        )
        try:
            resp = await self.client.messages.create(
                model=_ANTHROPIC_MODEL,
                max_tokens=900,
                system=[{"type": "text", "text": system,
                         "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
            )
        except Exception:
            return []
        data = self._parse_json(resp)
        if not isinstance(data, list):
            return []
        out = []
        for item in data:
            if isinstance(item, dict) and item.get("description"):
                sev = str(item.get("severity", "info")).lower()
                out.append(SwarmInsight(
                    insight_type="emergent",
                    severity=sev if sev in _SEVERITY_RANK else "info",
                    detected_by=["swarm_synthesis"],
                    description=str(item["description"]),
                    affected_apps=[],
                    evidence=[{"source": "claude_emergent_pass"}],
                ))
        return out

    @staticmethod
    def _parse_json(resp: Any) -> Any:
        content = getattr(resp, "content", None)
        text = ""
        if isinstance(content, list):
            text = "\n".join(getattr(b, "text", "") or "" for b in content)
        elif content:
            text = str(content)
        text = text.strip()
        start, end = text.find("["), text.rfind("]")
        if start != -1 and end != -1:
            text = text[start:end + 1]
        try:
            return json.loads(text)
        except (ValueError, json.JSONDecodeError):
            return None
