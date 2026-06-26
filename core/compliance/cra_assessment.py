"""CF-C — CRA (Community Reinvestment Act) data collection + assessment.

Classifies census tracts by income tier (federal 50/80/120% AMI cutoffs, 12 CFR
25/228) and assesses a bank/credit-union's lending in low-and-moderate-income (LMI)
tracts + to LMI borrowers, producing an INTERNAL self-assessment benchmark rating.

Sync + pure + RULE 11. Post-decision read-only -> 16/16 by construction.

HONEST SCOPE: the geographic inputs CRA needs (census_tract geocoding, the FFIEC
tract-income file, area median income) are not collected today, so meridian -> a
documented insufficient_data result, never a fabricated rating. CRA applies only to
banks / credit unions / savings institutions — NOT mortgage companies — so an
IMC/broker tenant -> not_applicable.

IMPORTANT: the rating is an INTERNAL benchmark only. Official CRA ratings are
assigned by federal examiners (OCC/FDIC/Fed/NCUA) and weigh qualitative factors
not captured here.

DATA SOURCES:
  hmda_lar.{census_tract, action_taken, loan_amount, applicant_income}
  tenants.settings.company_type   (applicability)
  FFIEC Census File (tract median income) + HUD AMI tables  (NOT yet loaded)
"""
from __future__ import annotations

from typing import Optional

APPLICABILITY = {"bank", "credit_union", "savings_institution"}
INCOME_TIERS = ["low", "moderate", "middle", "upper"]
ACTION_ORIGINATED = {"1", "2", "originated", "recommend", "approve", "allow"}


def classify_income_tier(tract_median_income, area_median_income, cutoffs: dict) -> Optional[str]:
    """Census tract income tier from % of AMI. Both inputs required (RULE 11 — never
    guessed). low <low_max%, moderate <moderate_max%, middle <middle_max%, else upper."""
    if tract_median_income is None or area_median_income is None:
        return None
    try:
        ami = float(area_median_income)
        ti = float(tract_median_income)
    except (TypeError, ValueError):
        return None
    if ami <= 0:
        return None
    ratio = ti / ami * 100.0
    if ratio < cutoffs.get("low_max", 50):
        return "low"
    if ratio < cutoffs.get("moderate_max", 80):
        return "moderate"
    if ratio < cutoffs.get("middle_max", 120):
        return "middle"
    return "upper"


class CRAAssessment:
    INTERNAL_RATING_DISCLAIMER = (
        "IMPORTANT: This is an internal self-assessment benchmark only. Official CRA "
        "ratings are determined by federal banking examiners (OCC, FDIC, Federal Reserve, "
        "NCUA) and involve qualitative factors not captured here. This benchmark does not "
        "constitute a CRA rating and must not be represented as such to regulators or the public.")

    def __init__(self, rules: Optional[dict] = None):
        from core.catalogue.rule_loader import SAFE_DEFAULTS
        r = dict(SAFE_DEFAULTS)
        if rules:
            r.update({k: v for k, v in rules.items() if v is not None})
        self._cutoffs = {
            "low_max": float(r.get("cra_lmi_low_max_pct", 50)),
            "moderate_max": float(r.get("cra_moderate_max_pct", 80)),
            "middle_max": float(r.get("cra_middle_max_pct", 120)),
        }
        self._outstanding_pct = float(r.get("cra_lmi_ratio_outstanding_pct", 40))
        self._satisfactory_pct = float(r.get("cra_lmi_ratio_satisfactory_pct", 25))
        self._needs_improve_pct = float(r.get("cra_lmi_ratio_needs_improvement_pct", 10))

    def _internal_rating(self, lmi_ratio_pct: float) -> str:
        if lmi_ratio_pct >= self._outstanding_pct:
            return "outstanding"
        if lmi_ratio_pct >= self._satisfactory_pct:
            return "satisfactory"
        if lmi_ratio_pct >= self._needs_improve_pct:
            return "needs_to_improve"
        return "substantial_noncompliance"

    def assess(self, loans: list, area_median_income: Optional[float] = None,
               tract_incomes: Optional[dict] = None, institution_type: str = "",
               tenant_id: str = "", period: str = "") -> dict:
        loans = loans or []

        # ── Applicability gate (CRA = banks/CUs/thrifts only) ──
        inst_type = (institution_type or "").lower().replace(" ", "_")
        if inst_type and inst_type not in APPLICABILITY:
            return {"status": "not_applicable", "institution_type": institution_type,
                    "tenant_id": tenant_id,
                    "reason": (f"CRA does not apply to '{institution_type}'. CRA applies to "
                               "banks, credit unions, and savings institutions only."),
                    "citation": "12 CFR 25, 228, 345, 563e",
                    "data_source": "tenants.settings.company_type", "missing_inputs": []}

        # ── Data availability ──
        missing = []
        if not loans:
            missing.append("No loans to assess")
        loans_with_tract = [l for l in loans if l.get("census_tract")]
        if not loans_with_tract:
            missing.append("census_tract is NULL for all loans — geocode property addresses "
                           "(FFIEC Geocoder / HUD API) before CRA assessment")
        if area_median_income is None:
            missing.append("area_median_income not provided — obtain from the FFIEC Census "
                           "File / HUD AMI tables for the assessment area")
        if not tract_incomes:
            missing.append("tract_incomes lookup not provided — load the FFIEC Census File "
                           "(~75k tracts, annual) to classify tract income tiers")
        if missing:
            return {"status": "insufficient_data", "tenant_id": tenant_id, "period": period,
                    "institution_type": institution_type, "total_loans": len(loans),
                    "loans_with_tract": len(loans_with_tract), "collection_gaps": missing,
                    "note": ("CRA assessment requires (1) census-tract geocoding of property "
                             "addresses, (2) the FFIEC Census File for tract income, (3) "
                             "HUD/FFIEC AMI for the assessment area — none are populated for "
                             "this tenant."),
                    "citation": "12 CFR 25, 228, 345, 563e",
                    "data_source": "hmda_lar.census_tract + FFIEC Census File + HUD AMI",
                    "missing_inputs": missing}

        # ── Tier classification ──
        tract_tiers, unclassifiable = {}, []
        for tract, t_income in (tract_incomes or {}).items():
            tier = classify_income_tier(t_income, area_median_income, self._cutoffs)
            if tier:
                tract_tiers[str(tract)] = tier
            else:
                unclassifiable.append(str(tract))

        originated = [l for l in loans if str(l.get("action_taken", "")) in ACTION_ORIGINATED]
        ami_lmi_cut = float(area_median_income) * 0.80

        lmi_tract = [l for l in originated
                     if tract_tiers.get(str(l.get("census_tract", ""))) in ("low", "moderate")]
        # NOTE: hmda_lar.applicant_income is full dollars (RA-7C: monthly*12) — compared
        # directly to 80% AMI (the spec's *1000 assumed thousands, wrong for our schema).
        lmi_borrower = [l for l in originated
                        if l.get("income") not in (None, "")
                        and _f(l.get("income")) < ami_lmi_cut]

        n = len(originated)
        lmi_tract_ratio = round(len(lmi_tract) / n * 100, 1) if n else 0.0
        with_income = [l for l in originated if l.get("income") not in (None, "")]
        lmi_borrower_ratio = round(len(lmi_borrower) / len(with_income) * 100, 1) if with_income else None

        tier_counts = {"low": 0, "moderate": 0, "middle": 0, "upper": 0, "unclassified": 0}
        for l in originated:
            tier = tract_tiers.get(str(l.get("census_tract", "")))
            tier_counts[tier if tier else "unclassified"] += 1

        rating = self._internal_rating(lmi_tract_ratio)
        missing_inputs = []
        if unclassifiable:
            missing_inputs.append(f"{len(unclassifiable)} tract(s) not in the FFIEC file — "
                                  "excluded from classification")
        if not with_income:
            missing_inputs.append("no applicant_income on originated loans — LMI-borrower "
                                  "ratio not computed")

        return {
            "status": "assessed", "tenant_id": tenant_id, "period": period,
            "institution_type": institution_type, "total_loans": len(loans),
            "originated_loans": n,
            "metrics": {
                "lmi_tract_loans": len(lmi_tract), "lmi_tract_ratio_pct": lmi_tract_ratio,
                "lmi_borrower_loans": len(lmi_borrower), "lmi_borrower_ratio_pct": lmi_borrower_ratio,
                "tier_breakdown": tier_counts,
            },
            "income_tier_cutoffs": self._cutoffs,
            "internal_benchmark": {
                "rating": rating, "lmi_ratio_used_pct": lmi_tract_ratio,
                "thresholds": {"outstanding": self._outstanding_pct,
                               "satisfactory": self._satisfactory_pct,
                               "needs_to_improve": self._needs_improve_pct},
                "disclaimer": self.INTERNAL_RATING_DISCLAIMER,
            },
            "citation": "12 CFR 25, 228, 345, 563e",
            "data_source": ("hmda_lar.census_tract + FFIEC Census File + HUD AMI + "
                            "entity_states (post-decision)"),
            "missing_inputs": missing_inputs,
        }


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


async def fetch_cra_data(conn, tenant_id: str, year: Optional[int] = None) -> tuple:
    """Fetch hmda_lar loans + the tenant's institution type. Returns (loans, institution_type)."""
    import json
    params = [tenant_id]
    year_clause = ""
    if year:
        params.append(year)
        year_clause = " AND EXTRACT(YEAR FROM h.action_taken_date) = $2"
    loans = await conn.fetch(
        "SELECT h.application_id, h.action_taken, h.census_tract, h.loan_amount, "
        "       h.applicant_income AS income "
        f"FROM hmda_lar h WHERE h.tenant_id=$1{year_clause} ORDER BY h.application_id", *params)
    inst = await conn.fetchrow("SELECT settings FROM tenants WHERE tenant_id=$1", tenant_id)
    settings = {}
    if inst and inst["settings"]:
        settings = json.loads(inst["settings"]) if isinstance(inst["settings"], str) else (inst["settings"] or {})
    return [dict(r) for r in loans], settings.get("company_type", "")


__all__ = ["CRAAssessment", "classify_income_tier", "fetch_cra_data",
           "APPLICABILITY", "INCOME_TIERS"]
