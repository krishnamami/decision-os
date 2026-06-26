"""CM-D — fair-lending monitor (post-decision, read-only).

Reads HMDA demographics (race / sex / ethnicity) from hmda_lar AFTER decisions are
made and looks for disparate-impact patterns via the EEOC four-fifths rule. Accord
NEVER uses demographic data in underwriting — hmda_lar is built after the outcome
is set (RA-7C). This monitor only *analyzes* it afterward, per ECOA.

`FairLendingMonitor` is sync + pure (RULE 5/6): the caller passes the rows, the
monitor reads its thresholds from the injected catalogue rules (regulatory layer,
SAFE_DEFAULTS fallback). RULE 11: data_source + missing_inputs on every output, and
a hard guard — **insufficient_data (with the reason) rather than a fabricated
disparity flag** when the sample is too small, single-group, or all not-provided.

DATA SOURCES:
  hmda_lar.{applicant_race, applicant_sex, applicant_ethnicity}  (HMDA integer codes)
  hmda_lar.action_taken  (1=originated 2=approved-not-accepted 3=denied 7=preapproval-denied …)
  loan_exceptions.{application_id, granted, status}  (joined on application_id)
"""
from __future__ import annotations

from typing import Optional

FAIR_LENDING_RULE_KEYS = [
    "fair_lending_four_fifths_ratio",
    "fair_lending_min_sample_size",
]

# HMDA code -> label, per protected class (Reg C / 12 CFR 1003).
HMDA_CODES = {
    "race": {1: "American Indian/Alaska Native", 2: "Asian", 3: "Black/African American",
             4: "Native Hawaiian/Pacific Islander", 5: "White",
             6: "Not provided", 7: "Not applicable"},
    "sex": {1: "Male", 2: "Female", 3: "Not provided", 4: "Not applicable", 6: "Both"},
    "ethnicity": {1: "Hispanic/Latino", 2: "Not Hispanic/Latino",
                  3: "Not provided", 4: "Not applicable"},
}
# Codes that mean "no usable demographic" (excluded from comparison groups).
NOT_PROVIDED_CODES = {"race": {6, 7}, "sex": {3, 4}, "ethnicity": {3, 4}}
PROTECTED_CLASS_COLUMN = {
    "race": "applicant_race", "sex": "applicant_sex", "ethnicity": "applicant_ethnicity",
}
# HMDA action_taken: denial vs approval (others — withdrawn/incomplete/purchased —
# are excluded from the rate denominator).
ACTION_DENY = {3, 7}
ACTION_APPROVE = {1, 2, 8}
_MIN_GROUP = 5  # a group needs at least this many to enter the 4/5 comparison


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


class FairLendingMonitor:
    def __init__(self, rules: Optional[dict] = None):
        from core.catalogue.rule_loader import SAFE_DEFAULTS
        r = dict(SAFE_DEFAULTS)
        if rules:
            r.update({k: v for k, v in rules.items() if v is not None})
        self._four_fifths = float(r.get("fair_lending_four_fifths_ratio", 0.80))
        self._min_sample = int(r.get("fair_lending_min_sample_size", 30))

    def analyze_denial_rates(self, hmda_rows: list, protected_class: str) -> dict:
        col = PROTECTED_CLASS_COLUMN.get(protected_class)
        labels = HMDA_CODES.get(protected_class, {})
        np_codes = NOT_PROVIDED_CODES.get(protected_class, set())
        if not col:
            return {"protected_class": protected_class, "status": "invalid_class",
                    "data_source": "hmda_lar", "citation": "ECOA 12 CFR 202",
                    "missing_inputs": [f"unknown protected class: {protected_class}"]}

        groups: dict = {}   # label -> {total, denied, approved, is_not_provided}
        for row in hmda_rows or []:
            code = _int(row.get(col))
            label = labels.get(code, f"code_{code}")
            action = _int(row.get("action_taken"))
            g = groups.setdefault(label, {"total": 0, "denied": 0, "approved": 0,
                                          "is_not_provided": code in np_codes})
            if action in ACTION_DENY:
                g["denied"] += 1
                g["total"] += 1
            elif action in ACTION_APPROVE:
                g["approved"] += 1
                g["total"] += 1
            # else (withdrawn/incomplete/purchased): not a decision -> excluded

        usable = {lbl: c for lbl, c in groups.items()
                  if not c["is_not_provided"] and c["total"] >= _MIN_GROUP}

        ds = f"hmda_lar.{col} + hmda_lar.action_taken"
        if not any(not c["is_not_provided"] for c in groups.values()):
            return self._insufficient(protected_class, "all_not_provided", groups, ds,
                f"All {len(hmda_rows or [])} applications report not-provided for "
                f"{protected_class}; disparate-impact analysis not possible.")
        if len(hmda_rows or []) < self._min_sample:
            return self._insufficient(protected_class, "sample_too_small", groups, ds,
                f"Sample {len(hmda_rows or [])} < minimum {self._min_sample}; not "
                f"statistically meaningful.", sample_size=len(hmda_rows or []))
        if len(usable) < 2:
            return self._insufficient(protected_class, "single_group", groups, ds,
                f"Fewer than two comparable {protected_class} groups (>= {_MIN_GROUP} "
                f"decisions each); cannot compute comparative rates.")

        rates = {lbl: {"total": c["total"], "denied": c["denied"], "approved": c["approved"],
                       "denial_rate": round(c["denied"] / c["total"], 4),
                       "approval_rate": round(c["approved"] / c["total"], 4)}
                 for lbl, c in usable.items()}
        # Reference = the group with the HIGHEST approval (selection) rate.
        ref_group = max(rates, key=lambda g: rates[g]["approval_rate"])
        ref_appr = rates[ref_group]["approval_rate"]

        disparities = []
        for lbl, r in rates.items():
            if lbl == ref_group:
                continue
            ratio = (r["approval_rate"] / ref_appr) if ref_appr > 0 else 0.0
            disparities.append({
                "group": lbl, "reference_group": ref_group,
                "group_approval_rate": r["approval_rate"], "ref_approval_rate": ref_appr,
                "group_denial_rate": r["denial_rate"],
                "four_fifths_ratio": round(ratio, 4), "threshold": self._four_fifths,
                "disparate_impact": ratio < self._four_fifths,
                "citation": "EEOC 29 CFR 1607.4(D)"})
        flagged = any(d["disparate_impact"] for d in disparities)
        return {
            "protected_class": protected_class,
            "status": "disparate_impact_detected" if flagged else "no_disparate_impact",
            "sample_size": len(hmda_rows), "groups": rates, "reference_group": ref_group,
            "disparities": disparities, "four_fifths_threshold": self._four_fifths,
            "has_disparate_impact": flagged, "data_source": ds, "missing_inputs": [],
            "citation": "ECOA 12 CFR 202 + EEOC 29 CFR 1607.4(D)"}

    def analyze_exception_grant_rates(self, hmda_rows: list, exception_rows: list) -> dict:
        labels = HMDA_CODES["race"]
        np_codes = NOT_PROVIDED_CODES["race"]
        hmda_by_app = {str(r.get("application_id")): r for r in (hmda_rows or [])}
        joined = []
        for e in (exception_rows or []):
            h = hmda_by_app.get(str(e.get("application_id")))
            if h is not None:
                joined.append((_int(h.get("applicant_race")), bool(e.get("granted"))))
        ds = "loan_exceptions.granted + hmda_lar.applicant_race"
        if not joined:
            return {"status": "insufficient_data", "reason": "no_exceptions_with_demographics",
                    "data_source": ds, "citation": "ECOA 12 CFR 202.9",
                    "missing_inputs": ["no exceptions could be joined to HMDA demographics"]}
        if len(joined) < self._min_sample:
            return {"status": "insufficient_data", "reason": "sample_too_small",
                    "sample_size": len(joined), "min_sample": self._min_sample,
                    "data_source": ds, "citation": "ECOA 12 CFR 202.9",
                    "missing_inputs": [f"only {len(joined)} exceptions with demographics "
                                       f"< minimum {self._min_sample}"]}
        by_race: dict = {}
        for code, granted in joined:
            lbl = labels.get(code, f"code_{code}")
            g = by_race.setdefault(lbl, {"total": 0, "granted": 0})
            g["total"] += 1
            g["granted"] += 1 if granted else 0
        rates = {lbl: {"total": c["total"], "granted": c["granted"],
                       "grant_rate": round(c["granted"] / c["total"], 4) if c["total"] else 0.0}
                 for lbl, c in by_race.items()}
        return {"status": "complete", "exceptions_analyzed": len(joined),
                "grant_rates_by_race": rates, "data_source": ds,
                "citation": "ECOA 12 CFR 202.9", "missing_inputs": []}

    def run_full_monitor(self, hmda_rows: list, exception_rows: list = None) -> dict:
        analyses = {f"denial_rate_{pc}": self.analyze_denial_rates(hmda_rows, pc)
                    for pc in ("race", "sex", "ethnicity")}
        if exception_rows:
            analyses["exception_grant_rates"] = self.analyze_exception_grant_rates(
                hmda_rows, exception_rows)
        has_disparity = any(v.get("has_disparate_impact") for v in analyses.values())
        has_insufficient = any(v.get("status") == "insufficient_data" for v in analyses.values())
        status = ("disparity_detected" if has_disparity
                  else "insufficient_data" if has_insufficient else "clean")
        return {
            "monitor_status": status, "analyses": analyses,
            "sample_size": len(hmda_rows or []), "has_disparate_impact": has_disparity,
            "four_fifths_threshold": self._four_fifths,
            "note": ("Accord never uses demographic data in underwriting decisions. This "
                     "analysis reads demographics ONLY after decisions are made (ECOA). A "
                     "disparate-impact signal requires further review by qualified counsel."),
            "citation": "ECOA 12 CFR 202 + HMDA 12 CFR 1003",
            "data_source": "hmda_lar + loan_exceptions (post-decision only)",
            "missing_inputs": [m for v in analyses.values() for m in v.get("missing_inputs", [])]}

    @staticmethod
    def _insufficient(protected_class, reason, groups, data_source, msg, sample_size=None) -> dict:
        out = {"protected_class": protected_class, "status": "insufficient_data",
               "reason": reason, "groups": groups, "has_disparate_impact": False,
               "data_source": data_source, "citation": "ECOA 12 CFR 202",
               "missing_inputs": [msg]}
        if sample_size is not None:
            out["sample_size"] = sample_size
        return out


async def load_fair_lending_rules(conn, tenant_id: str, agency: str = "cfpb") -> dict:
    from core.catalogue.rule_loader import get_rule
    values, trace = {}, {}
    for key in FAIR_LENDING_RULE_KEYS:
        r = await get_rule(conn, key, tenant_id, agency=agency)
        values[key] = r.get("applied")
        trace[key] = {"applied": r.get("applied"), "governed_by": r.get("governed_by")}
    return {"values": values, "trace": trace}


async def fetch_fair_lending_data(conn, tenant_id: str, start_date=None, end_date=None):
    """Read hmda_lar + decisioned loan_exceptions for the monitor (post-decision only)."""
    q = "SELECT * FROM hmda_lar WHERE tenant_id=$1"
    params = [tenant_id]
    if start_date:
        params.append(start_date)
        q += f" AND action_taken_date >= ${len(params)}"
    if end_date:
        params.append(end_date)
        q += f" AND action_taken_date <= ${len(params)}"
    hmda_rows = await conn.fetch(q, *params)
    exc_rows = await conn.fetch(
        "SELECT application_id, granted, exception_type, status FROM loan_exceptions "
        "WHERE tenant_id=$1 AND status IN ('granted','denied')", tenant_id)
    return [dict(r) for r in hmda_rows], [dict(r) for r in exc_rows]


__all__ = ["FairLendingMonitor", "load_fair_lending_rules", "fetch_fair_lending_data",
           "FAIR_LENDING_RULE_KEYS", "HMDA_CODES"]
