"""QA-B — model accuracy backtesting framework (SR 11-7).

Compares Accord's recorded decisions against ACTUAL loan performance. Requires a
loan_performance table (NOT yet collected) mapping application_id ->
{status, months_seasoned, default_date}, fed by servicer / Fannie-Freddie
loan-level / investor remittance / internal loss data.

When performance data is present:
  confusion matrix (positive class = block / "model predicts a problem loan"),
  precision/recall/F1 for the block decision, approval rate + default rate among
  approved, confidence calibration, and a Gini coefficient (discriminatory power).
Without it: insufficient_data + an explicit GAP_DESCRIPTION (the engine is ready).

Pure + sync + RULE 11. Read-only -> 16/16 by construction. Foundation on meridian
(no performance data); the engine is unit-tested on synthetic labels.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

PERFORMANCE_LABELS = {"performed", "defaulted", "delinquent", "prepaid"}
DECISION_OUTCOMES = {"recommend", "block", "escalate"}
_PROBLEM = ("defaulted", "delinquent")


@dataclass
class LoanPerformanceRecord:
    application_id: str
    decision_outcome: str
    confidence: float
    actual_status: str
    months_seasoned: int
    default_date: Optional[str] = None


class ModelAccuracyBacktester:
    GAP_DESCRIPTION = (
        "Backtesting requires a loan_performance table mapping application_id -> "
        "{actual_status, months_seasoned, default_date}, populated from (1) servicer "
        "monthly reports, (2) Fannie/Freddie loan-level performance data, (3) investor "
        "remittance files, or (4) internal default/loss tracking. Minimum seasoning: "
        "12 months for a meaningful accuracy assessment.")

    def _confusion_matrix(self, records: list) -> dict:
        # positive class = block (model predicts a problem loan)
        tp = fp = fn = tn = 0
        for r in records:
            predicted_block = r.decision_outcome == "block"
            actual_problem = r.actual_status in _PROBLEM
            if predicted_block and actual_problem:
                tp += 1
            elif predicted_block and not actual_problem:
                fp += 1
            elif not predicted_block and actual_problem:
                fn += 1
            else:
                tn += 1
        return {"tp": tp, "fp": fp, "fn": fn, "tn": tn}

    def _metrics(self, cm: dict) -> dict:
        tp, fp, fn, tn = cm["tp"], cm["fp"], cm["fn"], cm["tn"]
        total = tp + fp + fn + tn
        precision = round(tp / (tp + fp), 4) if (tp + fp) else None
        recall = round(tp / (tp + fn), 4) if (tp + fn) else None
        f1 = (round(2 * precision * recall / (precision + recall), 4)
              if precision and recall else None)
        approval_rate = round((fn + tn) / total * 100, 1) if total else None
        default_rate_approved = round(fn / (fn + tn) * 100, 1) if (fn + tn) else None
        return {"precision": precision, "recall": recall, "f1_score": f1,
                "approval_rate_pct": approval_rate,
                "default_rate_approved_pct": default_rate_approved, "total_loans": total}

    def _calibration(self, records: list) -> dict:
        buckets = {"0.0-0.5": [], "0.5-0.7": [], "0.7-0.85": [], "0.85-1.0": []}
        for r in records:
            c = float(r.confidence or 0)
            problem = r.actual_status in _PROBLEM
            band = ("0.0-0.5" if c < 0.5 else "0.5-0.7" if c < 0.7
                    else "0.7-0.85" if c < 0.85 else "0.85-1.0")
            buckets[band].append(problem)
        return {band: {"n": len(vals), "default_rate_pct": round(sum(vals) / len(vals) * 100, 1)}
                for band, vals in buckets.items() if vals}

    def _gini(self, records: list) -> Optional[float]:
        if not records:
            return None
        ordered = sorted(records, key=lambda r: -(r.confidence or 0))
        n = len(ordered)
        n_default = sum(1 for r in ordered if r.actual_status in _PROBLEM)
        if n_default in (0, n):
            return None
        lorenz_sum = running = 0
        for r in ordered:
            if r.actual_status in _PROBLEM:
                running += 1
            lorenz_sum += running / n_default
        auc = lorenz_sum / n
        return round(2 * auc - 1, 4)

    def backtest(self, decisions: list, performance_labels: dict,
                 min_seasoning_months: int = 12, tenant_id: str = "", period: str = "") -> dict:
        decisions = decisions or []
        if not performance_labels:
            return {"status": "insufficient_data", "tenant_id": tenant_id, "period": period,
                    "decisions_available": len(decisions), "performance_labels_available": 0,
                    "gap_description": self.GAP_DESCRIPTION,
                    "note": ("Backtesting engine is ready. Provide loan_performance data to "
                             "compute accuracy metrics; see gap_description for sources."),
                    "citation": "SR 11-7 Model Risk Management",
                    "data_source": "decision_outputs (decisions available; no performance data)",
                    "missing_inputs": [self.GAP_DESCRIPTION]}

        records, unmatched, unseasoned = [], [], []
        for d in decisions:
            app_id = d.get("application_id", "")
            perf = performance_labels.get(app_id)
            if not perf:
                unmatched.append(app_id)
                continue
            months = int(perf.get("months_seasoned", 0) or 0)
            if months < min_seasoning_months:
                unseasoned.append(f"{app_id}: {months}mo seasoned (< {min_seasoning_months})")
                continue
            records.append(LoanPerformanceRecord(
                application_id=app_id,
                decision_outcome=str(d.get("outcome") or d.get("decision_outcome") or ""),
                confidence=float(d.get("confidence") or 0.5),
                actual_status=str(perf.get("status", "unknown")),
                months_seasoned=months, default_date=perf.get("default_date")))

        if not records:
            return {"status": "insufficient_data", "tenant_id": tenant_id, "period": period,
                    "decisions_available": len(decisions),
                    "performance_labels_available": len(performance_labels),
                    "unmatched": len(unmatched), "unseasoned": len(unseasoned),
                    "gap_description": (f"No matched + seasoned records: {len(unmatched)} decisions "
                                        f"unmatched, {len(unseasoned)} below {min_seasoning_months}mo."),
                    "citation": "SR 11-7 Model Risk Management",
                    "data_source": "decision_outputs + loan_performance",
                    "missing_inputs": unseasoned[:5] or [self.GAP_DESCRIPTION]}

        cm = self._confusion_matrix(records)
        missing = list(unseasoned)
        if unmatched:
            missing.append(f"{len(unmatched)} decisions had no performance label (not seasoned yet)")
        return {
            "status": "complete", "tenant_id": tenant_id, "period": period,
            "records_backtested": len(records), "confusion_matrix": cm,
            "metrics": self._metrics(cm), "confidence_calibration": self._calibration(records),
            "gini_coefficient": self._gini(records),
            "sr_11_7_note": ("SR 11-7 requires ongoing model monitoring. Run quarterly; flag if "
                             "approval-rate drift > 5pp or default-rate-among-approved > 2x baseline."),
            "citation": "SR 11-7 Model Risk Management",
            "data_source": "decision_outputs + loan_performance (joined)",
            "missing_inputs": missing}


async def fetch_backtest_data(conn, tenant_id: str, year: Optional[int] = None) -> tuple:
    """Fetch underwriting decisions + loan_performance labels (if the table exists)."""
    params = [tenant_id]
    year_clause = ""
    if year:
        params.append(year)
        year_clause = " AND EXTRACT(YEAR FROM created_at)=$2"
    decisions = await conn.fetch(
        "SELECT DISTINCT ON (application_id) application_id, outcome, confidence "
        "FROM decision_outputs "
        f"WHERE tenant_id=$1 AND decision_id='underwriting_decision'{year_clause} "
        "ORDER BY application_id, version DESC", *params)
    has_perf = await conn.fetchval(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name='loan_performance'")
    perf_labels = {}
    if has_perf:
        rows = await conn.fetch(
            "SELECT application_id, status, months_seasoned, default_date "
            "FROM loan_performance WHERE tenant_id=$1", tenant_id)
        perf_labels = {r["application_id"]: dict(r) for r in rows}
    return [dict(r) for r in decisions], perf_labels


__all__ = ["ModelAccuracyBacktester", "LoanPerformanceRecord", "fetch_backtest_data",
           "PERFORMANCE_LABELS", "DECISION_OUTCOMES"]
