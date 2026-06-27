# Fair Lending Policy — TEMPLATE

> **TEMPLATE — requires legal review before use.** Covers ECOA (Reg B, 12 CFR 1002/202),
> HMDA (Reg C, 12 CFR 1003), and the Fair Housing Act. Fields in `[BRACKETS]` are
> institution-specific. Accord-specific facts are as implemented.
>
> Platform reference: `docs/ARCHITECTURE.md` (verified 2026-06-22).

---

## 1. Policy Statement

`[LENDER NAME]` and Accord are committed to fair, non-discriminatory lending under ECOA, HMDA,
and the Fair Housing Act. **Accord never uses demographic data in underwriting decisions** —
race, ethnicity, sex, and age are collected for HMDA reporting only and are assembled *after*
the decision is made; they are never inputs to any of the 14 decision personas. This is an
architectural invariant, enforced in continuous integration (see §3).

## 2. Protected Classes Covered

ECOA (12 CFR 1002.2 / 202): **race, color, religion, national origin, sex, marital status, age**
(provided the applicant has capacity to contract), and receipt of income from **public
assistance**; plus the good-faith exercise of rights under the Consumer Credit Protection Act.
Fair Housing Act adds **familial status** and **disability**.

## 3. How Accord Prevents Discrimination

a. **Proxy exclusion (by design).** Demographic and proxy fields (name, ZIP, race, sex,
   ethnicity) are not part of the decision inputs. The decision personas read only
   creditworthiness fields (score, DTI, LTV, income, loan attributes).
b. **QA-A proxy-swap regression harness** (`core/qa/fair_lending_regression.py`, commit
   `cb3c93b`; `GET /api/accord/qa/fair-lending-regression`): **8 paired tests** swap only a
   protected-class proxy (James/Jamal, Emily/Lakisha, Michael/Jose, ZIP 10022/10037,
   90210/90001, race, sex, ethnicity) and assert **byte-identical** outcomes. A divergence =
   a proxy leak = CI fails. Runs on every deploy.
c. **CM-G structural bias detector** (`core/compliance/overlay_bias_detector.py`, `2c58c76`;
   `GET /api/accord/audit/overlay-bias`): a **pre-deployment** proxy-risk screen scoring each
   overlay from criterion proxy-correlation weights (credit 0.70 / DTI 0.45 / LTV 0.35),
   severity vs the agency floor, and population exclusion — no demographics required.

## 4. How Accord Monitors for Disparate Impact

a. **CM-D `FairLendingMonitor`** (`e18114c`): aggregate EEOC 4/5-rule denial-rate analysis by
   race/sex/ethnicity, with insufficient-data guards. Cadence: **quarterly**.
b. **CM-F overlay attribution** (`aa47a4d`; `GET /api/accord/audit/hmda/overlay-disparity`):
   attributes a demographic gap to the specific overlay (pass-agency / fail-overlay), 4/5 ratio
   + 20pp-gap screen.
c. **CF-B ECOA 12 CFR 202.15 self-test** (`507f526`; `GET /api/accord/audit/fair-lending/self-test`):
   a **privileged** annual self-test with peer-group matched analysis (credit × DTI × LTV bands)
   + findings + remediation tracking.
d. **HMDA filing** — CF-A LAR file + 15 CFPB edit checks (`9d69e54`; `/api/accord/audit/hmda/lar-file`,
   `/hmda/edit-checks`), annual.

> **Honesty note.** On the meridian fixture tenant, applicant demographics are "not provided,"
> so CM-D / CF-B / CM-F correctly return `insufficient_data` rather than a fabricated finding.
> Real disparate-impact analysis requires real reported demographics.

## 5. Overlay Review Process

1. Every new/changed overlay is screened by **CM-G** (structural proxy-risk score).
2. **Elevated/high** risk (composite ≥ 0.55 / ≥ 0.75) → a documented **business
   justification** is required + the CM-F retrospective is run.
3. **Legal review** by the Fair Lending Officer before the overlay reaches production.
4. The change is recorded in `tenant_rules` **version history** with the justification.

## 6. Annual Fair Lending Testing Commitment

| Activity | Tool | Cadence |
|---|---|---|
| Proxy-swap regression | QA-A (`cb3c93b`) | Every deploy (CI) |
| Aggregate disparate-impact monitor | CM-D (`e18114c`) | Quarterly |
| ECOA 202.15 privileged self-test | CF-B (`507f526`) | Annual |
| Structural overlay bias audit | CM-G (`2c58c76`) | Annual + per overlay change |
| HMDA LAR + edit checks | CF-A (`9d69e54`) | Annual |

## 7. Governance

- **Fair Lending Officer:** `[NAME / TITLE]` — owns this policy, overlay sign-off, and the
  annual testing calendar.
- **Board reporting:** fair-lending testing results reported to `[BOARD / COMMITTEE]` on a
  `[QUARTERLY]` cadence; any disparate-impact finding escalated immediately.
- **Adverse action:** ECOA/Reg B adverse-action notices generated on decline (RA-7B,
  30-day deadline, HMDA denial codes); demographic data is never a basis for adverse action.

## 8. Contact + Complaint Process

Fair-lending complaints: `[CONTACT / ADDRESS / EMAIL]`. Complaints are logged, investigated by
the Fair Lending Officer, and tracked to resolution; regulators are notified where required.

---

*TEMPLATE — requires legal review before use. Accord facts current as of platform build
(commits referenced inline). Not legal advice.*
