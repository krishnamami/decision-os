# Accord Platform Agreement — TEMPLATE

> **TEMPLATE — requires legal review before use.** This document is a starting
> template for the agreement between Accord and a lender. It is **not legal advice**
> and is **not a substitute for counsel.** Fields in `[BRACKETS]` are lender-/
> deal-specific and must be completed. Accord-specific facts (endpoints, models,
> safeguards) are stated as implemented as of the platform version below.
>
> Platform reference: Accord Decision OS (`docs/ARCHITECTURE.md`, verified 2026-06-22).
> Test baseline at drafting: 1,215 automated tests passing.

---

## 1. Parties + Effective Date

This Accord Platform Agreement (the "Agreement") is entered into as of `[EFFECTIVE DATE]`
(the "Effective Date") by and between:

- **Accord** — `[ACCORD LEGAL ENTITY]`, `[ADDRESS]` ("Accord," "Platform," "Processor"); and
- **Lender** — `[LENDER LEGAL NAME]`, `[ADDRESS]`, NMLS ID `[NMLS ID]` ("Lender," "Controller").

Collectively the "Parties."

## 2. Platform Description

**What Accord is.** Accord Decision OS is an **advisory mortgage-underwriting decision
engine**. It evaluates a loan application through **14 decision personas** (credit_assessment,
fraud_screening, compliance_check, employment_reconciliation, asset_verification,
title_assessment, income_verification, dti_calculation, ltv_assessment, product_eligibility,
rate_pricing, underwriting_decision, approval_routing, closing_readiness) and produces
**advisory signals + a recommended outcome** (recommend / escalate / block) with a full
rule-trace (Federal | Agency | Overlay | Applied | Citation).

**What Accord does NOT do.** Accord does **not** originate loans, **does not make the final
credit decision**, and **does not** disburse funds. Every persona output is an **advisory
signal**; the Lender's underwriter or automated policy retains final credit authority.

**Data-processing role.** With respect to applicant personal data, **Lender is the data
controller** and **Accord is the data processor / service provider**, processing data solely
on Lender's documented instructions (see §4 and `docs/DATA_RETENTION_PRIVACY_POLICY.md`).

## 3. Decision Scope + Limitations

1. **Advisory only.** Accord recommends; Lender decides. The 14 persona outputs are advisory
   signals aggregated by `underwriting_decision` into a recommendation, never a binding action.
2. **Final authority.** Lender retains sole, final credit-granting authority and is the
   "creditor" under ECOA/Reg B for every decision.
3. **Human review.** High-risk decisions (`fraud_screening`, `compliance_check`,
   `underwriting_decision`, `closing_readiness`) run in human-approval mode by configuration.
4. **No performance guarantee.** Accord does **not** guarantee that any recommended loan will
   perform, nor that any blocked loan would have defaulted. Model accuracy backtesting
   (`/api/accord/qa/backtest`, MR-B) requires Lender-supplied loan-performance data.
5. **Catalogue-governed.** All lending thresholds resolve from a three-layer catalogue
   (regulatory → agency → lender overlay); Accord hardcodes no lending values (Architecture
   RULE 1).

## 4. Data Processing Agreement (GDPR / CCPA)

- **PII categories processed:** financial (income, assets, credit score, SSN/tax ID),
  identity (name, address, DOB, employment), and HMDA demographic data (ethnicity, race, sex,
  age) — **demographics are collected for HMDA reporting only and are NEVER used in any
  decision** (see §5). Sensitive-field set per `core/audit/security_checker.PII_FIELDS`.
- **Purpose limitation:** Accord processes applicant data solely to provide the advisory
  decision service and the compliance artifacts described herein.
- **Retention:** per `docs/DATA_RETENTION_PRIVACY_POLICY.md` (DOC-D) — e.g. decision outputs
  7 years, HMDA LAR 3 years (Reg C 12 CFR 1003.5).
- **Sub-processors:** `[CLOUD INFRASTRUCTURE PROVIDER(S)]`, `[OTHER SUB-PROCESSORS]`. Object
  storage is encrypted at rest (AES-256). Lender will be notified of new sub-processors at
  least `[N]` days in advance.
- **Security:** see DOC-D §5 (RBAC, row-level security, audit logging) and the platform
  security posture report (`/api/accord/qa/security-audit`, QA-C).

## 5. Fair Lending Commitments

- **Accord's ECOA obligations (12 CFR 202 / Reg B):** demographic data is never an input to
  any decision (architectural invariant), enforced in CI by the QA-A proxy-swap regression
  harness (8 proxy pairs — name/zip/race/sex/ethnicity — asserting byte-identical outcomes;
  commit `cb3c93b`).
- **Proxy detection:** every lender overlay is screened by the CM-G proactive proxy-risk
  detector (`/api/accord/audit/overlay-bias`; commit `2c58c76`) before/while in production.
- **Disparate-impact monitoring:** CM-D aggregate 4/5-rule monitor (`e18114c`), CM-F
  overlay-attribution analyzer (`aa47a4d`), and the CF-B ECOA 12 CFR 202.15 **privileged**
  self-test (`507f526`).
- **HMDA:** LAR file + CFPB edit checks (CF-A, `9d69e54`).
- **Lender's independent obligations.** Lender remains independently responsible for its own
  ECOA, FHA, and HMDA compliance, including adverse-action notices and HMDA submission.

## 6. Model Risk (SR 11-7)

- **Accord provides model documentation:** SR 11-7 model cards for all 14 models
  (`/api/accord/model-risk/cards`, MR-A `55eb401`) — purpose, inputs, outputs, assumptions,
  limitations, validation approach, risk tier (4 high / 7 medium / 3 low). Ongoing monitoring:
  drift (MR-B `c4b7a5e`), backtesting (QA-B), champion/challenger (CI-B replay).
- **Lender's validation obligations.** Bank-regulated Lenders remain responsible for
  independent model validation per SR 11-7 / OCC 2011-12; Accord's artifacts are inputs to,
  not a substitute for, that validation.
- **Change-notification SLA.** Accord will notify Lender of material model/catalogue changes
  within `[N]` business days; shadow testing + version history + emergency rollback are
  available (`scripts/rules_cron.py`).

## 7. Liability + Indemnification

1. **Liability cap.** Accord's aggregate liability is limited to the platform fees paid by
   Lender in the `[12]` months preceding the claim, except as stated in §7.3.
2. **Lender indemnity.** Lender indemnifies Accord for claims arising from Lender's **final
   credit decisions**, its lending products, and its independent regulatory obligations.
3. **Mutual indemnity.** Each Party indemnifies the other for its own fraud, willful
   misconduct, or gross negligence; the §7.1 cap does not apply to these.
4. **No consequential damages** except as required by law.

## 8. Confidentiality + IP

- **Accord IP:** the catalogue rule sets (regulatory_rules, agency_guidelines), the decision
  engine, personas, and platform software are Accord's confidential IP.
- **Lender IP:** Lender's tenant overlay rules (`overlay_rules`) and tenant configuration are
  Lender's confidential IP.
- **Aggregate data:** Accord may use de-identified, aggregated data for model improvement;
  no applicant-level or Lender-identifying data is used without consent.

## 9. Term + Termination

Initial term: `[TERM]` from the Effective Date, auto-renewing for `[RENEWAL]` unless either
Party gives `[N]` days' notice. Either Party may terminate for uncured material breach after
`[N]` days' written notice. On termination, Accord will return or delete Lender data per DOC-D.

## 10. Governing Law + Dispute Resolution

This Agreement is governed by the laws of `[JURISDICTION]`. Disputes resolved by
`[ARBITRATION / COURTS]` in `[VENUE]`.

## 11. Signature Block

| | Accord | Lender |
|---|---|---|
| By | __________________ | __________________ |
| Name | `[NAME]` | `[NAME]` |
| Title | `[TITLE]` | `[TITLE]` |
| Date | `[DATE]` | `[DATE]` |

---

*TEMPLATE — requires legal review before use. Accord-specific facts current as of platform
build (1,215 tests; commits referenced inline). Not legal advice.*
