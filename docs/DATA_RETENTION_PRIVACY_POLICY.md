# Data Retention + Privacy Policy — TEMPLATE

> **TEMPLATE — requires legal review before use.** Covers GLBA (Safeguards Rule, 16 CFR 314),
> CCPA/CPRA, and state privacy laws. Fields in `[BRACKETS]` are institution-specific. Accord
> facts are as implemented.
>
> Platform reference: `docs/ARCHITECTURE.md` (verified 2026-06-22). PII set:
> `core/audit/security_checker.PII_FIELDS`. Security posture: QA-C (`/api/accord/qa/security-audit`).

---

## 1. Purpose + Scope

This policy describes how applicant and loan data is collected, processed, secured, retained,
and deleted across the Accord Decision OS on behalf of `[LENDER NAME]`. It applies to all
personal information processed through the platform.

## 2. PII Categories Processed

Sensitive fields are enumerated in `core/audit/security_checker.PII_FIELDS` and masked in
audit/log surfaces:

`ssn`, `tax_id`, `dob` / `date_of_birth`, `address_full`, `bank_account`, `routing_number`,
`drivers_license`.

Additional personal data: name, employment, income, assets, credit score, and HMDA demographic
data (ethnicity, race, sex, age). **HMDA demographics are collected for reporting only and are
never inputs to any decision** (see `docs/FAIR_LENDING_POLICY.md`).

## 3. Data Processing Roles

- **`[LENDER NAME]` — controller / business.** Determines purposes and means of processing.
- **Accord — processor / service provider.** Processes solely on `[LENDER NAME]`'s documented
  instructions to deliver the advisory decision service and compliance artifacts.

## 4. Retention Periods

| Data | Retention | Basis |
|---|---|---|
| Loan application records | **7 years** after action/closing | `[STATE]` recordkeeping + investor reqs |
| `decision_outputs` (decision trace) | **7 years** | Aligns to application retention |
| HMDA LAR | **3 years** | Reg C, **12 CFR 1003.5** |
| Audit / access logs | **7 years** | GLBA / examiner expectations |
| Model snapshots + validation evidence | **5 years** | SR 11-7 model documentation |
| Adverse-action records | **25 months** (consumer) | ECOA / Reg B 12 CFR 1002.12 |

`[LENDER NAME]` confirms final periods against its own legal/regulatory matrix; where periods
conflict, the **longest** controlling period applies.

## 5. Access Controls + Security

- **RBAC roles:** `underwriter`, `manager`, `admin`, `compliance`, `super_admin` — least
  privilege; compliance/audit endpoints gated to `admin`/`compliance`.
- **Row-level security:** **58 RLS policies across 28 tables** for tenant isolation.
- **Encryption:** TLS in transit; object storage encrypted at rest (**AES-256**).
- **Audit logging:** sensitive reads/writes logged; PII masked per `PII_FIELDS`.
- **Known finding (QA-C, remediation pending).** The application database role
  (`edms_admin`) currently has `bypassrls = true`, which makes the 58 RLS policies **inert at
  the application layer**; tenant isolation is presently enforced by application-layer
  `tenant_id` WHERE filters. Remediation — provisioning a non-bypass app role so RLS is
  enforced in depth — is **tracked and pending**. This is disclosed here intentionally rather
  than overstating the control.

## 6. Right of Access + Deletion

`[LENDER NAME]` honors verified consumer access/deletion requests under CCPA/CPRA and
applicable state law. **Deletion is subject to the retention obligations in §4** — records under
a legal hold or a mandatory retention period (e.g. HMDA LAR, 7-year application records) are
retained until that period lapses, then deleted. Accord supports `[LENDER NAME]` in fulfilling
requests as processor.

## 7. Breach Notification

Per the **GLBA Safeguards Rule (FTC, 16 CFR 314)** and applicable state breach laws: on a
confirmed security event affecting personal data, Accord notifies `[LENDER NAME]` **without
undue delay, target within 72 hours** of confirmation, with known scope, affected data
categories, and remediation. `[LENDER NAME]`, as controller, makes required regulator/consumer
notifications.

## 8. State-Specific Provisions

- **California — CCPA/CPRA:** right to know, delete, correct, opt out of sale/sharing
  (Accord does not sell personal information).
- **New York — SHIELD Act:** reasonable safeguards for private information.
- **Virginia — CDPA**, **Colorado — CPA**: access/deletion/correction + opt-out rights.
- Other `[STATE]` requirements as applicable.

## 9. Data Minimization

The decision personas read only the creditworthiness fields they require (RULE 5/6 resolvers
are DB-less and operate on the in-memory entity context). Demographics are segregated from the
decision path. Accord collects no personal data beyond what the advisory service and the named
compliance artifacts require.

## 10. Contact + Data Protection Officer

Privacy inquiries / requests: `[DPO NAME]`, `[CONTACT / ADDRESS / EMAIL]`. Requests are logged
and tracked to resolution.

---

*TEMPLATE — requires legal review before use. Accord facts current as of platform build
(commits/findings referenced inline). Not legal advice.*
