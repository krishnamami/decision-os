# Accord Loan Import Guide

Get your pipeline into Accord in three steps: **download the template → fill it
from your LOS → upload**. One row per loan, ~30 minutes from CSV to production.

---

## 1. Get the template

Download `accord_import_template.csv` (Settings → Import Loans → *Download CSV
template*, or `GET /api/accord/onboarding/template`). It has all 50 columns with
two example rows. Required columns are marked below.

## 2. Export from your LOS

### Encompass (ICE / Ellie Mae)
1. **Pipeline → Select All → Export → Custom Fields**
2. Select the fields that map to the columns in the template.
3. Export as **CSV**.

### ICE Mortgage Technology
1. **Reports → Loan Export → Standard Fields**
2. Map your fields to the Accord template columns.

### Generic / any LOS
1. Open `accord_import_template.csv`.
2. Fill in your loan data, **one row per loan**.
3. Save as **CSV** and upload.

> Don't worry about exact column names — if your headers differ, Accord shows a
> **column-mapping screen** that auto-matches most columns (fuzzy + keyword
> matching) and lets you map the rest. You can save the mapping for next time.

## 3. Upload

Settings → **Import Loans** → drag-and-drop your CSV. Accord validates it first
(shows valid rows, errors, warnings, and a preview), then imports on your
confirmation. Imported loans appear in your **Pipeline** and are assigned to
your team by status.

---

## Required vs optional columns

**Required:** `loan_number`, `application_date`, `loan_purpose`, `loan_type`,
`borrower_first_name`, `borrower_last_name`, `employer_name`, `employment_type`,
`stated_annual_income`, `mid_credit_score`, `monthly_debt_payments`,
`property_address`, `property_type`, `property_state`, `property_zip`,
`occupancy`, `loan_amount`, `interest_rate`, `loan_term_months`.
Plus `purchase_price` for purchase loans.

**Optional** (Accord fills/derives if blank): credit bureau scores, verified
income, `monthly_income`, `appraised_value`/`estimated_value`, `ltv`,
`dti_front`, `dti_back` (computed if omitted), co-borrower fields,
`assigned_to_email`, `loan_status`.

## Accepted values

| Column | Values |
|---|---|
| `loan_purpose` | purchase, refinance, cash_out |
| `loan_type` | conventional, fha, va, usda, jumbo |
| `channel` | retail, wholesale, correspondent |
| `employment_type` | salaried, self_employed, retired, other |
| `property_type` | sfr, condo, townhouse, multi_2_4, manufactured |
| `occupancy` | primary, secondary, investment |
| `amortization_type` | fixed, arm_5_6, arm_7_6, arm_10_6, io |
| `loan_status` | active, approved, denied, withdrawn, funded |

## Privacy

Never include full SSNs — use **`borrower_ssn_last4`** (last 4 digits only).
Accord stores a one-way hash, never the SSN itself.
