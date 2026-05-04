"""Synthetic applicant factory.

`build_synthetic_applicants(n, seed=42)` returns a deterministic list
of ApplicantProfile objects with varied:
  - credit_band      (super_prime / prime / near_prime / subprime)
  - property_state   (CA / TX / FL / NY / WA / IL / GA)
  - age_band         (25-35 / 35-50 / 50-65)
  - loan_type        (conforming / fha / jumbo / va)
  - audit overlays   (consent_missing / protected_attr_leak / clean)

`inject_into_platform(platform, profiles)` writes:
  - Applicant + Application + Property + Loan + ComplianceRecord
  - CreditProfile + IncomeProfile + FraudProfile (Applicant-bound)
  - Five EDMS Documents per applicant (W-2, paystub, 1040, ID,
    appraisal) with verified Claims

After injection the caller can run
`platform.executor().run_application(app_id, ...)` for each id.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from core.context_store.base import Lineage


SEGMENTS: tuple[tuple[str, int, int], ...] = (
    # (segment_label, score_low, score_high)
    ("super_prime", 760, 820),
    ("prime",       700, 759),
    ("near_prime",  660, 699),
    ("subprime",    600, 659),
)

STATES: tuple[str, ...] = ("CA", "TX", "FL", "NY", "WA", "IL", "GA")
LOAN_TYPES: tuple[str, ...] = ("conforming", "fha", "jumbo", "va")
AGE_BANDS: tuple[tuple[str, int, int], ...] = (
    ("25-35", 25, 35),
    ("35-50", 35, 50),
    ("50-65", 50, 65),
)


# Five canonical EDMS doc types every applicant carries. Real EDMS
# integrations land in TIER 2.5; this scaffold lets reports + UI
# exercise the doc-set shape today.
EDMS_DOC_TYPES: tuple[tuple[str, str, dict[str, Any]], ...] = (
    ("w2",                "income/w2_2024.pdf",         {"verified_income": "$$"}),
    ("paystub",           "income/paystub_recent.pdf",  {"gross_pay": "$$"}),
    ("tax_return_1040",   "income/1040_2024.pdf",       {"agi": "$$"}),
    ("government_id",     "identity/drivers_license.pdf", {"id_verified": True}),
    ("appraisal_report",  "property/urar_1004.pdf",     {"appraised_value": "$$"}),
)


@dataclass
class DocumentSpec:
    document_id: str
    doc_type: str
    source_url: str
    status: str = "verified"
    ocr_confidence: float = 0.95


@dataclass
class AuditOverlay:
    """Optional violations to inject. Each defaults to False; set one
    or more to make this applicant's audit fire warn / fail."""

    consent_missing: bool = False
    protected_attr_leak: bool = False  # adds Applicant.race
    no_disclosure: bool = False        # ComplianceRecord.disclosure_sent=False


@dataclass
class ApplicantProfile:
    """Everything needed to materialize one synthetic applicant."""

    applicant_id: str
    application_id: str
    first_name: str
    last_name: str
    age: int
    age_band: str
    state: str
    loan_type: str
    credit_score: int
    credit_band: str
    annual_income: int
    requested_amount: int
    appraised_value: int
    documents: list[DocumentSpec] = field(default_factory=list)
    overlay: AuditOverlay = field(default_factory=AuditOverlay)


# Tiny name pool — keep deterministic, avoid faker dependency.
_FIRST = (
    "Alex", "Jordan", "Sam", "Taylor", "Morgan", "Casey", "Drew", "Riley",
    "Quinn", "Avery", "Cameron", "Skyler", "Reese", "Hayden", "Parker",
    "Devon", "Charlie", "Robin", "Logan", "Emerson",
)
_LAST = (
    "Patel", "Garcia", "Kim", "Nguyen", "Smith", "Johnson", "Singh", "Lee",
    "Brown", "Davis", "Lopez", "Khan", "Chen", "Mendoza", "Williams",
    "Rivera", "Anderson", "Cohen", "Park", "Hall",
)


def build_synthetic_applicants(
    n: int = 24,
    *,
    seed: int = 42,
    fail_rate: float = 0.10,
    warn_rate: float = 0.20,
) -> list[ApplicantProfile]:
    """Generate `n` deterministic ApplicantProfiles.

    fail_rate × n applicants get a hard violation (consent_missing or
    protected_attr_leak). warn_rate × n get a softer one. Remaining
    are clean.

    Distribution targets:
      - segments: 25% super_prime / 40% prime / 25% near_prime / 10% subprime
      - loan types: 50% conforming / 25% fha / 15% jumbo / 10% va
    """

    rng = random.Random(seed)

    n_fail = max(0, int(round(n * fail_rate)))
    n_warn = max(0, int(round(n * warn_rate)))
    overlay_assignments = (
        ["fail"] * n_fail + ["warn"] * n_warn + ["clean"] * (n - n_fail - n_warn)
    )
    rng.shuffle(overlay_assignments)

    profiles: list[ApplicantProfile] = []
    for i in range(n):
        applicant_id  = f"cust_synth_{i:03d}"
        application_id = f"app_synth_{i:03d}"
        first         = rng.choice(_FIRST)
        last          = rng.choice(_LAST)

        age_band, lo, hi = rng.choice(AGE_BANDS)
        age = rng.randint(lo, hi)

        # Weighted segment selection.
        seg = rng.choices(
            [s[0] for s in SEGMENTS],
            weights=[0.25, 0.40, 0.25, 0.10],
        )[0]
        score_low, score_high = next(s[1:] for s in SEGMENTS if s[0] == seg)
        score = rng.randint(score_low, score_high)

        # Loan type, weighted to mirror real US distribution.
        loan_type = rng.choices(LOAN_TYPES, weights=[0.50, 0.25, 0.15, 0.10])[0]

        state = rng.choice(STATES)

        # Income tracks credit band — loose correlation, not deterministic.
        income_base = {
            "super_prime": 350_000,
            "prime":       170_000,
            "near_prime":   95_000,
            "subprime":     65_000,
        }[seg]
        annual_income = income_base + rng.randint(-15_000, 25_000)

        # Loan amount tracks loan_type. Jumbo only goes to super_prime
        # so DTI stays under the 0.50 BLOCK threshold; other types are
        # band-agnostic.
        if loan_type == "jumbo" and seg != "super_prime":
            loan_type = "conforming"
        amt_base = {
            "conforming": 400_000,
            "fha":        300_000,
            "jumbo":      800_000,
            "va":         350_000,
        }[loan_type]
        requested_amount = amt_base + rng.randint(-50_000, 50_000)
        # Appraised value = requested + meaningful equity. Tuned per
        # credit band so LTV outcomes track real underwriting:
        #   super_prime / prime: ≤ 0.80 → ALLOW
        #   near_prime: 0.80 – 0.90 → RECOMMEND
        #   subprime: 0.90 – 0.95 → RECOMMEND/ESCALATE
        # The persona's _MAX_LTV_BY_BAND drives whether each lands in
        # ALLOW vs RECOMMEND; the equity here just makes the mix
        # realistic across a synthetic batch.
        equity_multiplier = {
            "super_prime": rng.uniform(1.30, 1.50),
            "prime":       rng.uniform(1.25, 1.40),
            "near_prime":  rng.uniform(1.15, 1.30),
            "subprime":    rng.uniform(1.08, 1.18),
        }[seg]
        appraised_value = int(requested_amount * equity_multiplier)

        overlay_kind = overlay_assignments[i]
        overlay = AuditOverlay()
        if overlay_kind == "fail":
            # 50/50 between consent_missing and protected_attr_leak.
            if rng.random() < 0.5:
                overlay.consent_missing = True
            else:
                overlay.protected_attr_leak = True
        elif overlay_kind == "warn":
            overlay.no_disclosure = True

        documents = [
            DocumentSpec(
                document_id=f"doc_synth_{i:03d}_{doc_type}",
                doc_type=doc_type,
                source_url=f"edms://encompass/loans/{application_id}/{path}",
                status="verified",
                ocr_confidence=round(0.90 + rng.uniform(0.00, 0.09), 2),
            )
            for doc_type, path, _claims in EDMS_DOC_TYPES
        ]

        profiles.append(ApplicantProfile(
            applicant_id=applicant_id,
            application_id=application_id,
            first_name=first,
            last_name=last,
            age=age,
            age_band=age_band,
            state=state,
            loan_type=loan_type,
            credit_score=score,
            credit_band=seg,
            annual_income=annual_income,
            requested_amount=requested_amount,
            appraised_value=appraised_value,
            documents=documents,
            overlay=overlay,
        ))

    return profiles


# ─────────────────────────────────────────────────────────────────────
# Injection — writes entities into the platform's context store.
#
# Bypasses the EntityHydrator / event pipeline because the goal is
# bulk-seed for reports / smoke. The canonical event-driven path
# stays the way the runtime hydrates from connectors; synthetic data
# uses store.set() directly so we don't have to thread N events
# through the sink for every applicant.
# ─────────────────────────────────────────────────────────────────────


async def inject_into_platform(
    platform: Any, profiles: list[ApplicantProfile]
) -> list[str]:
    """Write entities for each profile and return the application_ids.
    Caller can then iterate executor().run_application(...) per id."""

    base_time = datetime.utcnow() - timedelta(hours=2)
    application_ids: list[str] = []

    for i, p in enumerate(profiles):
        lineage = Lineage(
            decision_id=None,
            agent="synthetic.factory",
            written_by="synthetic.factory",
            notes=f"synthetic profile {p.applicant_id}",
        )

        # ── Applicant ────────────────────────────────────────────────
        # Note: PRD §23.9 lists age, race, sex, national_origin etc as
        # protected attrs that must NOT be in agent context unless
        # explicitly permitted. The factory stores age on the
        # ApplicantProfile (factory metadata) but does not write it to
        # the Applicant entity, otherwise every applicant would trip
        # the ethics check. Real production stores DOB and computes
        # age out of band; we mirror that pattern here.
        #
        # session_behavior + lead_source + channel matter — lead_scoring
        # persona derives intent_score from session_behavior. Values
        # tuned so the default applicant lands above the 0.7 ALLOW
        # threshold.
        applicant_value: dict[str, Any] = {
            "applicant_id":     p.applicant_id,
            "first_name":       p.first_name,
            "last_name":        p.last_name,
            "lead_source":      "web_form",
            "channel":          "digital",
            "consent_obtained": not p.overlay.consent_missing,
            "session_behavior": {"pages_viewed": 8, "time_on_site_seconds": 240},
            "prior_inquiries":  0,
        }
        if p.overlay.protected_attr_leak:
            # Intentional leak — race is in PROTECTED_ATTRIBUTES so the
            # ethics checker should fire.
            applicant_value["race"] = "white"
        await platform.store.set(
            "Applicant", p.applicant_id, applicant_value, lineage
        )

        # ── Application ──────────────────────────────────────────────
        # existing_debt_obligations is the monthly payment that DTI
        # adds onto proposed mortgage payment. ~10% of monthly income
        # keeps DTI clean (mortgage at 28% of income → DTI ~38%).
        existing_debt_monthly = int(p.annual_income * 0.10 / 12)
        await platform.store.set(
            "Application",
            p.application_id,
            {
                "application_id":   p.application_id,
                "applicant_id":     p.applicant_id,
                "submitted_at":     (base_time + timedelta(minutes=i)).isoformat(),
                "loan_type":        p.loan_type,
                "requested_amount": p.requested_amount,
                "property_state":   p.state,
                "purpose":          "purchase",
                "existing_debt_obligations": existing_debt_monthly,
            },
            lineage,
        )

        # ── Property ────────────────────────────────────────────────
        # ltv_assessment reads appraised_value + (purchase_price OR
        # principal_amount). dti_calculation reads proposed_payment
        # via amortization on the Loan principal.
        purchase_price = int(p.requested_amount * 1.10)  # 10% down typical
        down_payment = purchase_price - p.requested_amount
        await platform.store.set(
            "Property",
            f"prop_synth_{i:03d}",
            {
                "property_id":     f"prop_synth_{i:03d}",
                "application_id":  p.application_id,
                "appraised_value": p.appraised_value,
                "purchase_price":  purchase_price,
                "down_payment":    down_payment,
                "state":           p.state,
                "occupancy":       "primary",
                "appraisal_disputed": False,
            },
            lineage,
        )

        # ── Loan ────────────────────────────────────────────────────
        await platform.store.set(
            "Loan",
            f"loan_synth_{i:03d}",
            {
                "loan_id":         f"loan_synth_{i:03d}",
                "application_id":  p.application_id,
                "loan_type":       p.loan_type,
                "principal_amount": p.requested_amount,
                "term_months":     360,
                "lock_period":     30,
                "interest_rate":   0.065,
            },
            lineage,
        )

        # ── ComplianceRecord ────────────────────────────────────────
        await platform.store.set(
            "ComplianceRecord",
            f"comp_synth_{i:03d}",
            {
                "compliance_record_id":         f"comp_synth_{i:03d}",
                "application_id":               p.application_id,
                "all_hmda_fields_complete":     True,
                "fair_lending_violation":       False,
                "missing_required_disclosures": p.overlay.no_disclosure,
                "disclosure_sent":              not p.overlay.no_disclosure,
                "state_rules_passed":           True,
                "cd_timing_compliant":          not p.overlay.no_disclosure,
                "regulatory_ambiguity":         False,
                "mixed_jurisdiction":           False,
                "final_conditions_checklist":   {"all_cleared": True},
                "insurance_binder":             True,
            },
            lineage,
        )

        # ── CreditProfile ───────────────────────────────────────────
        # Persona reads: credit_score, credit_band, active_bankruptcy,
        # foreclosure_last_36_months, thin_file, derogatory_marks,
        # open_tradelines, credit_utilization, no_derogatory_last_24_months.
        await platform.store.set(
            "CreditProfile",
            f"credit_synth_{i:03d}",
            {
                "credit_profile_id":   f"credit_synth_{i:03d}",
                "applicant_id":        p.applicant_id,
                "credit_score":        p.credit_score,
                "credit_band":         p.credit_band,
                "bureau":              "experian",
                "pulled_at":           (base_time + timedelta(minutes=i)).isoformat(),
                "open_tradelines":     8,
                "derogatory_marks":    0,
                "credit_utilization":  0.20,
                "thin_file":           False,
                "active_bankruptcy":   False,
                "foreclosure_last_36_months": False,
                "no_derogatory_last_24_months": True,
            },
            lineage,
        )

        # ── IncomeProfile ───────────────────────────────────────────
        # Persona reads: stated_income, verified_income, employment_type,
        # payroll_verified, multiple_income_sources, foreign_income,
        # income_confidence_score.
        await platform.store.set(
            "IncomeProfile",
            f"income_synth_{i:03d}",
            {
                "income_profile_id":     f"income_synth_{i:03d}",
                "applicant_id":          p.applicant_id,
                "stated_income":         p.annual_income,
                "verified_income":       p.annual_income,
                "verification_source":   "payroll_provider",
                "income_confidence_score": 0.95,
                "employment_type":       "salaried",
                "payroll_verified":      True,
                "multiple_income_sources": False,
                "foreign_income":        False,
            },
            lineage,
        )

        # ── FraudProfile ────────────────────────────────────────────
        # Persona reads: fraud_score, identity_match_confidence,
        # document_authenticity_score, watchlist_match,
        # synthetic_identity_flag.
        await platform.store.set(
            "FraudProfile",
            f"fraud_synth_{i:03d}",
            {
                "fraud_profile_id":          f"fraud_synth_{i:03d}",
                "applicant_id":              p.applicant_id,
                "fraud_score":               0.05,
                "identity_match_confidence": 0.97,
                "document_authenticity_score": 0.95,
                "watchlist_match":           False,
                "synthetic_identity_flag":   False,
                "reviewed_at":               (base_time + timedelta(minutes=i)).isoformat(),
            },
            lineage,
        )

        # ── Documents + Claims ──────────────────────────────────────
        knowledge_store = getattr(platform, "knowledge_store", None)
        for doc in p.documents:
            await platform.store.set(
                "Document",
                doc.document_id,
                {
                    "document_id":    doc.document_id,
                    "application_id": p.application_id,
                    "applicant_id":   p.applicant_id,
                    "doc_type":       doc.doc_type,
                    "status":         doc.status,
                    "source_url":     doc.source_url,
                    "source_system":  "encompass",
                    "uploaded_at":    (base_time + timedelta(minutes=i)).isoformat(),
                    "uploaded_by":    f"borrower:{p.applicant_id}",
                    "verified_at":    (base_time + timedelta(minutes=i+5)).isoformat(),
                    "verified_by":    "underwriter:auto",
                    "ocr_confidence": doc.ocr_confidence,
                    "page_count":     1,
                    "mime_type":      "application/pdf",
                },
                lineage,
            )

            # One claim per doc keyed off the doc_type's primary field.
            if doc.doc_type == "w2":
                await platform.store.set(
                    "Claim",
                    f"claim_synth_{i:03d}_w2",
                    {
                        "claim_id":         f"claim_synth_{i:03d}_w2",
                        "document_id":      doc.document_id,
                        "application_id":   p.application_id,
                        "applicant_id":     p.applicant_id,
                        "field_name":       "verified_income",
                        "field_value":      p.annual_income,
                        "source_page":      1,
                        "extraction_method": "synthetic",
                        "extraction_confidence": 0.95,
                        "status":           "verified",
                        "verified_at":      (base_time + timedelta(minutes=i+5)).isoformat(),
                        "verified_by":      "underwriter:auto",
                        "extracted_at":     (base_time + timedelta(minutes=i+1)).isoformat(),
                        "extracted_by":     "synthetic.factory",
                    },
                    lineage,
                )
            elif doc.doc_type == "appraisal_report":
                await platform.store.set(
                    "Claim",
                    f"claim_synth_{i:03d}_appraisal",
                    {
                        "claim_id":         f"claim_synth_{i:03d}_appraisal",
                        "document_id":      doc.document_id,
                        "application_id":   p.application_id,
                        "applicant_id":     p.applicant_id,
                        "field_name":       "appraised_value",
                        "field_value":      p.appraised_value,
                        "source_page":      3,
                        "extraction_method": "synthetic",
                        "extraction_confidence": 0.94,
                        "status":           "verified",
                        "verified_at":      (base_time + timedelta(minutes=i+5)).isoformat(),
                        "verified_by":      "underwriter:auto",
                        "extracted_at":     (base_time + timedelta(minutes=i+1)).isoformat(),
                        "extracted_by":     "synthetic.factory",
                    },
                    lineage,
                )

        application_ids.append(p.application_id)

    return application_ids
