"""EV-G — document staleness / recency checks (advisory).

`StalenessChecker` is sync + DB-less (RULE 5/6): the persona/caller passes in the
per-document `extracted_fields` + the closing/note date, the checker reads its
thresholds from the injected catalogue rules (RULE 1/8/9 — SAFE_DEFAULTS fallback),
and returns findings IN MEMORY. RULE 11: every check carries `data_source` +
`missing_inputs` and distinguishes fresh / stale / not_checkable — it never assumes.

CRITICAL: `document_index.received_at` is the INGEST timestamp, NOT the document's
own date — it is NEVER used as a recency proxy. Doc types whose own date is not yet
extracted (credit report pull date, bank statement period-end) return `not_checkable`
with `missing_inputs`, never a fabricated fresh/stale verdict.

Checkable today (date present in extracted_fields + PURCHASE_AGREEMENT.close_date):
  appraisal · paystub · W2 tax-year · tax-return tax-year · rate-lock · HOI binder.
Needs extraction first: credit report · bank statement.

Advisory only — the consuming persona must not move proposed_outcome (Gap f).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

# The numeric thresholds this checker reads from the catalogue (EV-G seed).
STALENESS_RULE_KEYS = [
    "appraisal_validity_days_conventional",
    "appraisal_validity_days_fha",
    "paystub_max_age_days",
    "bank_statement_max_age_days",
    "credit_report_validity_days",
    "w2_tax_year_lookback_years",
    "tax_return_lookback_years",
]


async def load_staleness_rules(conn, tenant_id: str, agency: str = "fannie") -> dict:
    """Resolve the EV-G thresholds through the three catalogue layers (enricher use)."""
    from core.catalogue.rule_loader import get_rule
    values, trace = {}, {}
    for key in STALENESS_RULE_KEYS:
        r = await get_rule(conn, key, tenant_id, agency=agency)
        values[key] = r.get("applied")
        trace[key] = {"applied": r.get("applied"), "governed_by": r.get("governed_by")}
    return {"values": values, "trace": trace}


def _parse_date(s) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


class StalenessChecker:
    """Sync, DB-less, catalogue-driven. Thresholds come from the injected rules
    dict (loaded by the runner via load_staleness_rules); SAFE_DEFAULTS is the only
    fallback (RULE 9)."""

    def __init__(self, rules: Optional[dict] = None):
        from core.catalogue.rule_loader import SAFE_DEFAULTS
        r = dict(SAFE_DEFAULTS)
        if rules:
            r.update({k: v for k, v in rules.items() if v is not None})
        self._appraisal_days_conv = int(r.get("appraisal_validity_days_conventional", 120))
        self._appraisal_days_fha = int(r.get("appraisal_validity_days_fha", 180))
        self._paystub_days = int(r.get("paystub_max_age_days", 30))
        self._bank_days = int(r.get("bank_statement_max_age_days", 60))
        self._credit_days = int(r.get("credit_report_validity_days", 120))
        self._w2_lookback_years = int(r.get("w2_tax_year_lookback_years", 2))
        self._tax_return_years = int(r.get("tax_return_lookback_years", 2))

    @staticmethod
    def _days_between(earlier: str, later: str) -> Optional[int]:
        d, c = _parse_date(earlier), _parse_date(later)
        if d is None or c is None:
            return None
        return (c - d).days

    @staticmethod
    def _nc(doc_type, method, citation, data_source, missing) -> dict:
        return {"doc_type": doc_type, "status": "not_checkable", "method": method,
                "citation": citation, "data_source": data_source, "missing_inputs": missing}

    # ── date-anchored checks ─────────────────────────────────────────────────
    def check_appraisal(self, fields: dict, close_date: str,
                        loan_type: str = "conventional") -> dict:
        eff = (fields or {}).get("effective_date") or (fields or {}).get("appraisal_date")
        max_days = self._appraisal_days_fha if loan_type == "fha" else self._appraisal_days_conv
        if not eff:
            return self._nc("APPRAISAL_URAR", "appraisal_no_effective_date",
                            "Fannie B3-4.3-05", "APPRAISAL_URAR.extracted_fields",
                            ["effective_date not extracted from appraisal"])
        if not close_date:
            return self._nc("APPRAISAL_URAR", "appraisal_no_close_date",
                            "Fannie B3-4.3-05", "PURCHASE_AGREEMENT.close_date",
                            ["close_date not available (no PURCHASE_AGREEMENT)"])
        age = self._days_between(eff, close_date)
        if age is None:
            return self._nc("APPRAISAL_URAR", "appraisal_unparseable_date",
                            "Fannie B3-4.3-05", "APPRAISAL_URAR.effective_date",
                            [f"unparseable date(s): effective={eff!r} close={close_date!r}"])
        fresh = age <= max_days
        return {
            "doc_type": "APPRAISAL_URAR", "status": "fresh" if fresh else "stale",
            "age_days": age, "max_days": max_days, "effective_date": eff,
            "close_date": close_date, "loan_type": loan_type,
            "method": f"appraisal age {age}d vs max {max_days}d ({loan_type})",
            "citation": "Fannie B3-4.3-05",
            "data_source": "APPRAISAL_URAR.effective_date + PURCHASE_AGREEMENT.close_date",
            "missing_inputs": [],
            "docs_needed": [] if fresh else [
                f"Appraisal is {age - max_days} days past the {max_days}-day limit. "
                f"New appraisal required."],
        }

    def check_paystub(self, fields: dict, close_date: str) -> dict:
        end = (fields or {}).get("pay_period_end") or (fields or {}).get("period_end_date")
        if not end:
            return self._nc("PAYSTUB_CURRENT", "paystub_no_period_end",
                            "Fannie B3-2-10", "PAYSTUB_CURRENT.extracted_fields",
                            ["pay_period_end not extracted from paystub"])
        if not close_date:
            return self._nc("PAYSTUB_CURRENT", "paystub_no_close_date",
                            "Fannie B3-2-10", "PURCHASE_AGREEMENT.close_date",
                            ["close_date not available"])
        age = self._days_between(end, close_date)
        if age is None:
            return self._nc("PAYSTUB_CURRENT", "paystub_unparseable_date",
                            "Fannie B3-2-10", "PAYSTUB_CURRENT.pay_period_end",
                            [f"unparseable date(s): end={end!r} close={close_date!r}"])
        fresh = age <= self._paystub_days
        return {
            "doc_type": "PAYSTUB_CURRENT", "status": "fresh" if fresh else "stale",
            "age_days": age, "max_days": self._paystub_days, "pay_period_end": end,
            "close_date": close_date,
            "method": f"paystub age {age}d vs max {self._paystub_days}d",
            "citation": "Fannie B3-2-10",
            "data_source": "PAYSTUB_CURRENT.pay_period_end + PURCHASE_AGREEMENT.close_date",
            "missing_inputs": [],
            "docs_needed": [] if fresh else [
                f"Paystub is {age - self._paystub_days} days past the "
                f"{self._paystub_days}-day limit. Updated paystub required."],
        }

    def _check_tax_year(self, fields: dict, doc_type: str, lookback: int,
                        citation: str) -> dict:
        ty = (fields or {}).get("tax_year")
        if ty is None:
            return self._nc(doc_type, f"{doc_type.lower()}_no_tax_year", citation,
                            f"{doc_type}.extracted_fields",
                            ["tax_year not extracted"])
        try:
            ty_int = int(str(ty)[:4])
        except (ValueError, TypeError):
            return self._nc(doc_type, f"{doc_type.lower()}_unparseable_tax_year", citation,
                            f"{doc_type}.tax_year", [f"unparseable tax_year={ty!r}"])
        current_year = datetime.now().year
        min_year = current_year - lookback
        fresh = ty_int >= min_year
        return {
            "doc_type": doc_type, "status": "fresh" if fresh else "stale",
            "tax_year": ty_int, "current_year": current_year, "min_year": min_year,
            "method": f"{doc_type} tax_year {ty_int} vs min {min_year} "
                      f"(current {current_year} - {lookback}yr lookback)",
            "citation": citation, "data_source": f"{doc_type}.extracted_fields.tax_year",
            "missing_inputs": [],
            "docs_needed": [] if fresh else [
                f"{doc_type} is from {ty_int} — must be {min_year} or later."],
        }

    def check_w2(self, fields: dict) -> dict:
        return self._check_tax_year(fields, "W2_CURRENT", self._w2_lookback_years,
                                    "Fannie B3-3.1-01")

    def check_tax_return(self, fields: dict, doc_type: str = "SCHEDULE_E") -> dict:
        return self._check_tax_year(fields, doc_type, self._tax_return_years,
                                    "Fannie B3-3.1-02")

    def check_rate_lock(self, fields: dict, close_date: str) -> dict:
        exp = ((fields or {}).get("lock_expiry") or (fields or {}).get("expiration_date")
               or (fields or {}).get("lock_expiration"))
        if not exp:
            return self._nc("RATE_LOCK", "rate_lock_no_expiry", "Lender requirement",
                            "RATE_LOCK.extracted_fields",
                            ["lock_expiry not extracted from rate lock"])
        if not close_date:
            return self._nc("RATE_LOCK", "rate_lock_no_close_date", "Lender requirement",
                            "PURCHASE_AGREEMENT.close_date", ["close_date not available"])
        days_to_expiry = self._days_between(close_date, exp)
        if days_to_expiry is None:
            return self._nc("RATE_LOCK", "rate_lock_unparseable_date", "Lender requirement",
                            "RATE_LOCK.lock_expiry",
                            [f"unparseable date(s): expiry={exp!r} close={close_date!r}"])
        valid = days_to_expiry >= 0
        return {
            "doc_type": "RATE_LOCK", "status": "fresh" if valid else "stale",
            "lock_expiry": exp, "close_date": close_date, "days_to_expiry": days_to_expiry,
            "method": f"rate lock expires {exp} vs closing {close_date} "
                      f"({days_to_expiry}d margin)",
            "citation": "Lender requirement",
            "data_source": "RATE_LOCK.lock_expiry + PURCHASE_AGREEMENT.close_date",
            "missing_inputs": [],
            "docs_needed": [] if valid else [
                f"Rate lock expires {abs(days_to_expiry)} days before closing. "
                f"New rate lock required."],
        }

    def check_hoi(self, fields: dict, close_date: str) -> dict:
        exp = (fields or {}).get("expiration_date") or (fields or {}).get("policy_expiration")
        if not exp:
            return self._nc("HOI_BINDER", "hoi_no_expiration", "Fannie B7-2-03",
                            "HOI_BINDER.extracted_fields",
                            ["expiration_date not extracted from HOI binder"])
        if not close_date:
            return self._nc("HOI_BINDER", "hoi_no_close_date", "Fannie B7-2-03",
                            "PURCHASE_AGREEMENT.close_date", ["close_date not available"])
        days_valid = self._days_between(close_date, exp)
        if days_valid is None:
            return self._nc("HOI_BINDER", "hoi_unparseable_date", "Fannie B7-2-03",
                            "HOI_BINDER.expiration_date",
                            [f"unparseable date(s): expiry={exp!r} close={close_date!r}"])
        current = days_valid >= 0
        return {
            "doc_type": "HOI_BINDER", "status": "fresh" if current else "stale",
            "expiration_date": exp, "close_date": close_date, "days_valid": days_valid,
            "method": f"HOI expires {exp} vs closing {close_date} ({days_valid}d margin)",
            "citation": "Fannie B7-2-03",
            "data_source": "HOI_BINDER.expiration_date + PURCHASE_AGREEMENT.close_date",
            "missing_inputs": [],
            "docs_needed": [] if current else [
                "HOI binder has expired before closing. Updated binder required."],
        }

    # ── not-yet-extractable (RULE 11 — never use received_at) ────────────────
    def check_credit_report(self, fields: dict) -> dict:
        return self._nc(
            "CREDIT_REPORT", "credit_report_no_pull_date", "Fannie B3-5.3-01",
            "CREDIT_REPORT.extracted_fields",
            ["pull_date not extracted from credit report. document_index.received_at "
             "is INGEST time, not the document date — not used as a recency proxy."])

    def check_bank_statement(self, fields: dict, doc_type: str = "BANK_STATEMENT_M1") -> dict:
        return self._nc(
            doc_type, "bank_statement_no_period_end", "Fannie B3-2-10",
            f"{doc_type}.extracted_fields",
            ["statement_period_end not extracted from bank statement. received_at is "
             "INGEST time, not the document date — not used as a recency proxy."])

    # ── full sweep ───────────────────────────────────────────────────────────
    def check_all(self, documents: dict, close_date: str,
                  loan_type: str = "conventional") -> dict:
        checks: list = []
        docs = documents or {}
        if "APPRAISAL_URAR" in docs:
            checks.append(self.check_appraisal(docs["APPRAISAL_URAR"], close_date, loan_type))
        if "PAYSTUB_CURRENT" in docs:
            checks.append(self.check_paystub(docs["PAYSTUB_CURRENT"], close_date))
        if "W2_CURRENT" in docs:
            checks.append(self.check_w2(docs["W2_CURRENT"]))
        for tr in ("SCHEDULE_E", "SCHEDULE_C"):
            if tr in docs:
                checks.append(self.check_tax_return(docs[tr], tr))
        if "RATE_LOCK" in docs:
            checks.append(self.check_rate_lock(docs["RATE_LOCK"], close_date))
        if "HOI_BINDER" in docs:
            checks.append(self.check_hoi(docs["HOI_BINDER"], close_date))
        if "CREDIT_REPORT" in docs:
            checks.append(self.check_credit_report(docs["CREDIT_REPORT"]))
        for key in docs:
            if "BANK_STATEMENT" in key:
                checks.append(self.check_bank_statement(docs[key], key))
                break

        stale = sum(1 for c in checks if c["status"] == "stale")
        not_checkable = sum(1 for c in checks if c["status"] == "not_checkable")
        fresh = sum(1 for c in checks if c["status"] == "fresh")
        all_missing = [m for c in checks for m in c.get("missing_inputs", [])]
        return {
            "checks": checks,
            "fresh_count": fresh, "stale_count": stale,
            "not_checkable_count": not_checkable,
            "has_stale": stale > 0,
            "stale_doc_types": [c["doc_type"] for c in checks if c["status"] == "stale"],
            "docs_needed": [d for c in checks for d in c.get("docs_needed", [])],
            "data_source": "document_index.extracted_fields + PURCHASE_AGREEMENT.close_date",
            "missing_inputs": all_missing,
        }


__all__ = ["StalenessChecker", "load_staleness_rules", "STALENESS_RULE_KEYS"]
