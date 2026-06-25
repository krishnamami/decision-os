"""FR-G — 4506-C IRS transcript income cross-check.

The highest-assurance income check: FR-B (IncomeMismatchDetector) compares W2 vs
URLA stated income (both borrower-submitted); FR-G compares borrower-submitted
income against the **IRS-reported** figures on the 4506-C transcript — catching
falsification that even a doctored W2 would pass.

`TranscriptIncomeVerifier` is sync + DB-less (RULE 5/6): the caller passes the
extracted-field dicts, the verifier reads its variance tolerances from the injected
catalogue rules (REUSING FR-B's income_mismatch_{medium,high,critical}_pct — NO new
seeding), and returns findings in memory. RULE 11: data_source + missing_inputs on
every output. Income is only compared within the SAME tax year (else year_mismatch).

DATA SOURCES (PATH 2 — meridian has 0 transcripts → not_applicable):
  submitted: W2_CURRENT.box1_wages / SCHEDULE_C.net_profit / entity_states.qualifying_monthly
  IRS:       IRS_TRANSCRIPT.{wages_salaries, self_employment_income, agi, tax_year}
"""
from __future__ import annotations

from typing import Optional

# Reused from FR-B (fraud_rules) — NOT re-seeded.
TRANSCRIPT_RULE_KEYS = [
    "income_mismatch_medium_pct",
    "income_mismatch_high_pct",
    "income_mismatch_critical_pct",
]


def _num(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(str(v).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return None


def _year(v):
    return str(v)[:4] if v is not None else None


class TranscriptIncomeVerifier:
    def __init__(self, rules: Optional[dict] = None):
        from core.catalogue.rule_loader import SAFE_DEFAULTS
        r = dict(SAFE_DEFAULTS)
        if rules:
            r.update({k: v for k, v in rules.items() if v is not None})
        self._medium_pct = float(r.get("income_mismatch_medium_pct", 10))
        self._high_pct = float(r.get("income_mismatch_high_pct", 25))
        self._critical_pct = float(r.get("income_mismatch_critical_pct", 50))

    # ── individual checks ─────────────────────────────────────────────────────
    def verify_w2_vs_transcript(self, submitted_fields: dict, transcript_fields: dict) -> dict:
        sf, tf = submitted_fields or {}, transcript_fields or {}
        sub = _num(sf.get("box1_wages"))
        irs = _num(tf.get("wages_salaries"))
        sy, ty = sf.get("tax_year"), tf.get("tax_year")
        missing = []
        if sub is None:
            missing.append("W2 box1_wages not extracted from W2_CURRENT")
        if irs is None:
            missing.append("wages_salaries not in IRS_TRANSCRIPT — transcript may be unavailable")
        if missing:
            return self._na("w2_vs_transcript", "transcript_check_missing_inputs",
                            "W2_CURRENT.box1_wages + IRS_TRANSCRIPT.wages_salaries", missing,
                            "Fannie B3-3.1-01 + IRS Form 4506-C")
        if sy is not None and ty is not None and _year(sy) != _year(ty):
            return self._year_mismatch("w2_vs_transcript", sy, ty,
                                       "W2_CURRENT.tax_year + IRS_TRANSCRIPT.tax_year")
        return self._compare(sub, irs, "w2_vs_transcript", "W2_CURRENT.box1_wages",
                             "IRS_TRANSCRIPT.wages_salaries", sy or ty)

    def verify_se_vs_transcript(self, schedule_c_fields: dict, transcript_fields: dict) -> dict:
        sf, tf = schedule_c_fields or {}, transcript_fields or {}
        sub = _num(sf.get("net_profit") or sf.get("net_income"))
        irs = _num(tf.get("self_employment_income"))
        missing = []
        if sub is None:
            missing.append("Schedule C net_profit not extracted")
        if irs is None:
            missing.append("self_employment_income not in IRS_TRANSCRIPT")
        if missing:
            return self._na("se_vs_transcript", "transcript_se_check_missing_inputs",
                            "SCHEDULE_C.net_profit + IRS_TRANSCRIPT.self_employment_income",
                            missing, "Fannie B3-3.4-01 + IRS Form 4506-C")
        return self._compare(sub, irs, "se_vs_transcript", "SCHEDULE_C.net_profit",
                             "IRS_TRANSCRIPT.self_employment_income",
                             sf.get("tax_year") or tf.get("tax_year"))

    def verify_total_vs_agi(self, qualifying_monthly, transcript_fields: dict) -> dict:
        tf = transcript_fields or {}
        agi = _num(tf.get("agi"))
        qm = _num(qualifying_monthly)
        if not qm:
            return self._na("total_vs_agi", "agi_check_no_qualifying_income",
                            "entity_states.qualifying_monthly + IRS_TRANSCRIPT.agi",
                            ["qualifying_monthly is zero or null"], "IRS Form 4506-C")
        if agi is None:
            return self._na("total_vs_agi", "agi_check_no_transcript",
                            "IRS_TRANSCRIPT.agi",
                            ["agi not in IRS_TRANSCRIPT — transcript not available"],
                            "IRS Form 4506-C")
        return self._compare(qm * 12.0, agi, "total_vs_agi",
                             "entity_states.qualifying_monthly x 12",
                             "IRS_TRANSCRIPT.agi", tf.get("tax_year"))

    # ── core comparison ───────────────────────────────────────────────────────
    def _compare(self, submitted, irs_reported, check_type, submitted_source,
                 irs_source, tax_year=None) -> dict:
        if irs_reported == 0:
            return {
                "check_type": check_type, "status": "zero_irs_income",
                "submitted": round(submitted, 2), "irs_reported": 0.0,
                "method": "transcript_irs_income_zero", "severity": "high",
                "fraud_signal": True, "auto_block": False,
                "citation": "IRS Form 4506-C",
                "data_source": f"{submitted_source} + {irs_source}", "missing_inputs": [],
                "note": f"IRS reports $0 but borrower submitted ${submitted:,.0f}",
            }
        variance_pct = abs(submitted - irs_reported) / abs(irs_reported) * 100
        inflation = submitted > irs_reported
        if variance_pct >= self._critical_pct:
            severity, auto_block = "critical", True
        elif variance_pct >= self._high_pct:
            severity, auto_block = "high", False
        elif variance_pct >= self._medium_pct:
            severity, auto_block = "medium", False
        else:
            severity, auto_block = None, False
        status = ("match" if severity is None
                  else ("income_inflation" if inflation else "income_understatement"))
        return {
            "check_type": check_type, "status": status,
            "submitted": round(submitted, 2), "irs_reported": round(irs_reported, 2),
            "delta": round(submitted - irs_reported, 2), "variance_pct": round(variance_pct, 1),
            "inflation": inflation, "severity": severity, "auto_block": auto_block,
            "fraud_signal": severity is not None,
            "medium_threshold": self._medium_pct, "high_threshold": self._high_pct,
            "critical_threshold": self._critical_pct, "tax_year": tax_year,
            "method": (f"{submitted_source} ${submitted:,.0f} vs {irs_source} "
                       f"${irs_reported:,.0f} = {variance_pct:.1f}% variance "
                       f"({severity or 'match'})"),
            "citation": "IRS Form 4506-C + Fannie B3-3.1-01",
            "data_source": f"{submitted_source} + {irs_source}", "missing_inputs": [],
            "docs_needed": ([f"Reconcile {variance_pct:.0f}% income discrepancy vs IRS transcript"]
                            if severity in ("high", "critical") else []),
        }

    def run_all_checks(self, w2_fields: dict = None, schedule_c_fields: dict = None,
                       transcript_fields: dict = None, qualifying_monthly=None) -> dict:
        checks = []
        if w2_fields and transcript_fields:
            checks.append(self.verify_w2_vs_transcript(w2_fields, transcript_fields))
        if schedule_c_fields and transcript_fields:
            checks.append(self.verify_se_vs_transcript(schedule_c_fields, transcript_fields))
        if qualifying_monthly and transcript_fields:
            checks.append(self.verify_total_vs_agi(qualifying_monthly, transcript_fields))

        if not checks:
            return {
                "status": "not_applicable", "method": "no_transcript_available",
                "checks": [], "checks_run": 0, "fraud_signals": 0, "auto_block": False,
                "highest_severity": None, "citation": "IRS Form 4506-C",
                "data_source": "IRS_TRANSCRIPT (not available)",
                "missing_inputs": ["IRS_TRANSCRIPT not ingested for this application"],
                "note": "Upload IRS 4506-C transcript to enable the income cross-check",
            }
        fraud = [c for c in checks if c.get("fraud_signal")]
        highest = next((s for s in ("critical", "high", "medium")
                        if any(c.get("severity") == s for c in checks)), None)
        return {
            "status": "fraud_detected" if fraud else "clean",
            "checks": checks, "checks_run": len(checks),
            "fraud_signals": len(fraud), "highest_severity": highest,
            "auto_block": any(c.get("auto_block") for c in checks),
            "citation": "IRS Form 4506-C + Fannie B3-3.1-01",
            "data_source": "W2_CURRENT + SCHEDULE_C + IRS_TRANSCRIPT + entity_states",
            "missing_inputs": [m for c in checks for m in c.get("missing_inputs", [])],
        }

    # ── RULE 11 helpers ───────────────────────────────────────────────────────
    @staticmethod
    def _na(check_type, method, data_source, missing, citation) -> dict:
        return {"check_type": check_type, "status": "not_applicable", "method": method,
                "fraud_signal": False, "auto_block": False, "citation": citation,
                "data_source": data_source, "missing_inputs": missing}

    @staticmethod
    def _year_mismatch(check_type, sy, ty, data_source) -> dict:
        return {"check_type": check_type, "status": "year_mismatch",
                "method": "transcript_year_mismatch", "submitted_year": sy,
                "transcript_year": ty, "fraud_signal": False, "auto_block": False,
                "citation": "IRS Form 4506-C", "data_source": data_source,
                "missing_inputs": [],
                "note": f"submitted year {sy} vs transcript year {ty} — cannot compare"}


__all__ = ["TranscriptIncomeVerifier", "TRANSCRIPT_RULE_KEYS"]
