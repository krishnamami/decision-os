"""CF-B — ECOA 12 CFR 202.15 fair-lending self-testing PROGRAM.

A formal, privileged self-test wrapped AROUND CM-D's FairLendingMonitor (no
re-implementation): it reuses `run_full_monitor` for the aggregate 4/5 analysis and
ADDS (a) a similarly-situated PEER-GROUP analysis that controls for creditworthiness
(credit × DTI × LTV bands), (b) formal program metadata + the ECOA 202.15 privilege
notice, and (c) findings + remediation recommendations.

Distinction from CM-D: CM-D *detects* disparity post-hoc; CF-B *is the program* —
it proves the institution looked, documents the methodology + privilege, and tracks
remediation. Sync + pure + RULE 11. Post-decision READ-ONLY (demographics are never
used in any decision path) -> 16/16 by construction.

DATA SOURCES:
  hmda_lar.{applicant_race, applicant_sex, action_taken}  (post-decision)
  entity_states.{mid_credit_score, dti_back, ltv}         (peer-band controls)
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from core.compliance.fair_lending_monitor import (
    ACTION_APPROVE,
    ACTION_DENY,
    FairLendingMonitor,
    HMDA_CODES,
    NOT_PROVIDED_CODES,
    PROTECTED_CLASS_COLUMN,
)

# Contiguous bands (matched by `val <= hi`, so no value falls through a gap).
CREDIT_BANDS = [(619, "<620"), (659, "620-659"), (699, "660-699"),
                (739, "700-739"), (10 ** 9, "740+")]
DTI_BANDS = [(36, "<=36%"), (43, "37-43%"), (50, "44-50%"), (10 ** 9, ">50%")]
LTV_BANDS = [(80, "<=80%"), (90, "81-90%"), (97, "91-97%"), (10 ** 9, ">97%")]


def _band(val, bands) -> str:
    if val is None:
        return "unknown"
    try:
        v = float(val)
    except (TypeError, ValueError):
        return "unknown"
    for hi, label in bands:
        if v <= hi:
            return label
    return bands[-1][1]


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


class PeerGroupMatcher:
    """Bucket applicants into peer groups (credit × DTI × LTV) and run the EEOC 4/5
    rule WITHIN each bucket (similarly-situated). Pure. RULE 11: insufficient_data
    (with reason) when a bucket is too small or lacks ≥2 identifiable groups —
    never a fabricated disparity."""

    def __init__(self, min_sample: int = 5, four_fifths_ratio: float = 0.80):
        self._min_sample = min_sample
        self._four_fifths = four_fifths_ratio

    def build_peer_groups(self, joined_rows: list) -> dict:
        groups: dict = {}
        for row in joined_rows or []:
            key = (_band(row.get("mid_credit_score"), CREDIT_BANDS),
                   _band(row.get("dti_back"), DTI_BANDS),
                   _band(row.get("ltv"), LTV_BANDS))
            groups.setdefault(key, []).append(row)
        return groups

    def analyze_peer_group(self, group_key: tuple, rows: list,
                           protected_class: str = "race") -> dict:
        label = f"credit={group_key[0]} dti={group_key[1]} ltv={group_key[2]}"
        col = PROTECTED_CLASS_COLUMN[protected_class]
        labels = HMDA_CODES[protected_class]
        np_codes = NOT_PROVIDED_CODES[protected_class]
        ds = f"hmda_lar.{col} + entity_states (credit/dti/ltv)"

        if len(rows) < self._min_sample:
            return {"peer_group": label, "protected_class": protected_class,
                    "status": "insufficient_data",
                    "reason": f"sample_too_small ({len(rows)} < {self._min_sample})",
                    "n": len(rows), "has_disparate_impact": False, "data_source": ds,
                    "missing_inputs": [f"peer group {label}: {len(rows)} < min {self._min_sample}"]}

        by_class: dict = {}
        for row in rows:
            code = _int(row.get(col))
            lbl = labels.get(code, f"code_{code}")
            action = _int(row.get("action_taken"))
            g = by_class.setdefault(lbl, {"total": 0, "denied": 0, "approved": 0,
                                          "is_not_provided": code in np_codes})
            if action in ACTION_DENY:
                g["denied"] += 1
                g["total"] += 1
            elif action in ACTION_APPROVE:
                g["approved"] += 1
                g["total"] += 1
            # withdrawn/incomplete/purchased excluded from the rate denominator

        identifiable = {lbl: c for lbl, c in by_class.items()
                        if not c["is_not_provided"] and c["total"] >= 1}
        if len(identifiable) < 2:
            return {"peer_group": label, "protected_class": protected_class,
                    "status": "insufficient_data",
                    "reason": "single_group_or_all_not_provided",
                    "n": len(rows), "has_disparate_impact": False, "data_source": ds,
                    "missing_inputs": [f"peer group {label}: {len(identifiable)} identifiable "
                                       f"{protected_class} group(s) — need >= 2 to compare"]}

        rates = {lbl: round(c["denied"] / c["total"], 4) for lbl, c in identifiable.items()}
        min_denial = min(rates.values())
        ref_class = next(c for c, r in rates.items() if r == min_denial)
        ref_approval = 1.0 - min_denial

        disparities = []
        for lbl, dr in rates.items():
            if lbl == ref_class:
                continue
            ratio = ((1.0 - dr) / ref_approval) if ref_approval > 0 else 0.0
            disparities.append({"class": lbl, "ref_class": ref_class,
                                "denial_rate": dr, "ref_denial_rate": min_denial,
                                "four_fifths_ratio": round(ratio, 4),
                                "disparate_impact": ratio < self._four_fifths,
                                "citation": "EEOC 29 CFR 1607.4(D)"})
        flagged = any(d["disparate_impact"] for d in disparities)
        return {"peer_group": label, "protected_class": protected_class,
                "status": "disparate_impact" if flagged else "clean", "n": len(rows),
                "denial_rates": rates, "reference_class": ref_class,
                "disparities": disparities, "has_disparate_impact": flagged,
                "data_source": ds, "missing_inputs": []}

    def run(self, joined_rows: list, protected_class: str = "race") -> dict:
        groups = self.build_peer_groups(joined_rows)
        results = [self.analyze_peer_group(k, v, protected_class) for k, v in groups.items()]
        with_disp = [r for r in results if r["status"] == "disparate_impact"]
        insufficient = [r for r in results if r["status"] == "insufficient_data"]
        return {"protected_class": protected_class, "peer_groups_analyzed": len(results),
                "groups_with_disparity": len(with_disp),
                "insufficient_data_groups": len(insufficient), "results": results,
                "has_disparate_impact": bool(with_disp),
                "data_source": "hmda_lar join entity_states (credit x dti x ltv bands)",
                "missing_inputs": [m for r in results for m in r.get("missing_inputs", [])]}


class FairLendingSelfTest:
    PRIVILEGE_NOTICE = (
        "PRIVILEGED SELF-TEST — ECOA 12 CFR 202.15. Prepared as a self-test to assess "
        "compliance with the Equal Credit Opportunity Act / Regulation B. Results are "
        "privileged and not subject to disclosure to regulators unless the privilege is "
        "waived; the privilege is maintained only if the institution takes corrective "
        "action for any discriminatory practice found. DO NOT DISCLOSE WITHOUT LEGAL REVIEW.")

    def __init__(self, rules: Optional[dict] = None):
        from core.catalogue.rule_loader import SAFE_DEFAULTS
        r = dict(SAFE_DEFAULTS)
        if rules:
            r.update({k: v for k, v in rules.items() if v is not None})
        self._monitor = FairLendingMonitor(rules=rules)
        self._matcher = PeerGroupMatcher(
            min_sample=5, four_fifths_ratio=float(r.get("fair_lending_four_fifths_ratio", 0.80)))

    def run(self, hmda_rows: list, joined_rows: list, exception_rows: Optional[list] = None,
            period_start: str = "", period_end: str = "", run_by: str = "system",
            tenant_id: str = "", now_iso: Optional[str] = None) -> dict:
        test_id = uuid.uuid4().hex[:8]
        run_date = now_iso or (datetime.utcnow().isoformat() + "Z")

        aggregate = self._monitor.run_full_monitor(hmda_rows, exception_rows or [])
        peer_race = self._matcher.run(joined_rows, "race")
        peer_sex = self._matcher.run(joined_rows, "sex")

        findings = []
        if aggregate.get("has_disparate_impact"):
            findings.append({"finding_id": f"{test_id}-AGG-001",
                             "type": "aggregate_disparate_impact", "severity": "high",
                             "description": "Aggregate denial-rate disparity by protected class",
                             "details": aggregate.get("analyses", {})})
        if peer_race.get("has_disparate_impact"):
            findings.append({"finding_id": f"{test_id}-PEER-RACE-001",
                             "type": "peer_group_disparate_impact", "severity": "high",
                             "protected_class": "race",
                             "description": "Within-peer-group denial disparity by race",
                             "groups_affected": peer_race.get("groups_with_disparity")})
        if peer_sex.get("has_disparate_impact"):
            findings.append({"finding_id": f"{test_id}-PEER-SEX-001",
                             "type": "peer_group_disparate_impact", "severity": "medium",
                             "protected_class": "sex",
                             "description": "Within-peer-group denial disparity by sex",
                             "groups_affected": peer_sex.get("groups_with_disparity")})

        remediation = [{"finding_id": f["finding_id"],
                        "action": "Review underwriting guidelines for the flagged peer "
                                  "group(s) / class and document the legitimate business "
                                  "justification or remediate.",
                        "timeline": "60 days", "owner": "Fair Lending Officer",
                        "status": "open", "citation": "ECOA 12 CFR 202.15(c)"}
                       for f in findings]

        return {
            "test_id": test_id, "tenant_id": tenant_id,
            "period_start": period_start, "period_end": period_end,
            "run_date": run_date, "run_by": run_by,
            "methodology": ("EEOC 4/5 disparate-impact rule (29 CFR 1607.4(D)) — aggregate "
                            "analysis by protected class (CM-D) + similarly-situated "
                            "peer-group matched analysis (credit x DTI x LTV bands)"),
            "privilege_notice": self.PRIVILEGE_NOTICE, "ecoa_citation": "ECOA 12 CFR 202.15",
            "scope": {"applications_reviewed": len(hmda_rows or []),
                      "protected_classes": ["race", "sex"],
                      "analysis_types": ["aggregate_4/5", "peer_group_matched"],
                      "period": f"{period_start} to {period_end}"},
            "aggregate_analysis": aggregate,
            "peer_group_analysis": {"by_race": peer_race, "by_sex": peer_sex},
            "findings": findings, "findings_count": len(findings),
            "remediation_recommendations": remediation,
            "overall_status": "findings_requiring_remediation" if findings else "clean",
            "data_source": "hmda_lar + entity_states (post-decision only)",
            "missing_inputs": (aggregate.get("missing_inputs", [])
                               + peer_race.get("missing_inputs", [])
                               + peer_sex.get("missing_inputs", [])),
            "note": ("ECOA: Accord never uses demographic data in underwriting decisions. "
                     "Demographics are collected but read ONLY post-decision for this "
                     "compliance self-test. A disparate-impact signal requires review by "
                     "qualified counsel before any conclusion."),
        }


async def fetch_self_test_data(conn, tenant_id: str, year: Optional[int] = None) -> tuple:
    """Fetch hmda_lar + the hmda_lar⋈entity_states join for the self-test. Post-decision
    only. Returns (hmda_rows, joined_rows)."""
    params = [tenant_id]
    year_clause = ""
    if year:
        params.append(year)
        year_clause = " AND EXTRACT(YEAR FROM h.action_taken_date) = $2"
    hmda = await conn.fetch(
        f"SELECT * FROM hmda_lar h WHERE h.tenant_id=$1{year_clause} ORDER BY h.application_id",
        *params)
    joined = await conn.fetch(
        "SELECT h.application_id, h.action_taken, h.applicant_race, h.applicant_sex, "
        "       h.applicant_ethnicity, e.mid_credit_score, e.dti_back, e.ltv, e.loan_amount "
        "FROM hmda_lar h LEFT JOIN entity_states e "
        "  ON h.application_id=e.application_id AND h.tenant_id=e.tenant_id "
        f"WHERE h.tenant_id=$1{year_clause} ORDER BY h.application_id", *params)
    return [dict(r) for r in hmda], [dict(r) for r in joined]


__all__ = ["FairLendingSelfTest", "PeerGroupMatcher", "fetch_self_test_data",
           "CREDIT_BANDS", "DTI_BANDS", "LTV_BANDS"]
