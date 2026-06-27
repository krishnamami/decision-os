# Model Risk Management Policy (SR 11-7) — TEMPLATE

> **TEMPLATE — requires legal/risk review before use.** Aligns to the Federal Reserve /
> OCC Supervisory Guidance on Model Risk Management (SR 11-7 / OCC 2011-12). Fields in
> `[BRACKETS]` are institution-specific. Accord-specific facts are as implemented.
>
> Platform reference: `docs/ARCHITECTURE.md` (verified 2026-06-22). Model cards: MR-A
> (commit `55eb401`). Monitoring: MR-B (commit `c4b7a5e`).

---

## 1. Purpose + Scope

This policy governs model risk for the **14 Accord decision models** used in `[LENDER NAME]`'s
underwriting. SR 11-7 applies to bank-regulated institutions; this policy covers each Accord
model as a "model" under that guidance. It does not replace `[LENDER NAME]`'s enterprise model
risk policy — it documents how Accord's models are inventoried, validated, and monitored.

## 2. Model Inventory

Source of truth: `MODEL_REGISTRY` in `core/model_risk/model_card.py` (MR-A), exposed read-only
at `GET /api/accord/model-risk/cards` and `GET /api/accord/model-risk/inventory`. Risk tier,
wave, and mode are **derived from the live engine config** (`WAVE_CONFIG` + `DECISION_DEFAULTS`
in `core/cron/runner.py`), so the inventory cannot drift from production.

| Model | Wave | Risk tier | Owner team | Mode |
|---|---|---|---|---|
| credit_assessment | 1 | medium | credit_risk | recommend |
| fraud_screening | 1 | **high** | fraud_ops | human_approval |
| compliance_check | 1 | **high** | compliance | human_approval |
| employment_reconciliation | 1 | medium | underwriting | recommend |
| asset_verification | 1 | medium | underwriting | recommend |
| title_assessment | 1 | medium | title_ops | recommend |
| income_verification | 2 | medium | underwriting | recommend |
| dti_calculation | 2 | low | credit_risk | auto_execute |
| ltv_assessment | 2 | low | collateral_risk | auto_execute |
| product_eligibility | 3 | medium | product_ops | recommend |
| rate_pricing | 3 | medium | secondary_markets | recommend |
| underwriting_decision | 4 | **high** | underwriting | human_approval |
| approval_routing | 5 | low | loan_ops | auto_execute |
| closing_readiness | 5 | **high** | closing_ops | human_approval |

Distribution: **4 high / 7 medium / 3 low.**

## 3. Model Card Template

Each model card (from `ModelCardGenerator`, MR-A) carries: `model_id, name, type, wave, mode,
risk_tier, owner_team, purpose, inputs{entity_fields, catalogue_rules, upstream_personas},
outputs{outcome, signals}, key_assumptions, known_limitations, ecoa_note, validation,
approval_status, last_review, next_review, sr_11_7_tier`. Every card states: **demographics are
never used in the decision path (ECOA).** `[LENDER NAME]` completes institution-specific fields
(model owner of record, validation independence sign-off, board-reporting reference).

## 4. Validation Requirements by Risk Tier

| Tier | Models | Validation cadence |
|---|---|---|
| **High** (4) | fraud_screening, compliance_check, underwriting_decision, closing_readiness | **Annual** |
| **Medium** (7) | credit_assessment, employment_reconciliation, asset_verification, title_assessment, income_verification, product_eligibility, rate_pricing | **Biennial** |
| **Low** (3) | dti_calculation, ltv_assessment, approval_routing | **Triennial or change-triggered** |

Any material catalogue/overlay change retriggers validation regardless of cadence.

## 5. Validation Approach

1. **Scenario evaluation** — the 16/16 meridian scenario suite (`scripts/evaluate_meridian_scenarios.py`)
   verifies each model's key decision against expected outcomes.
2. **Boundary self-test** — `rule_validator` asserts catalogue floors/ceilings.
3. **Backtesting** — QA-B `ModelAccuracyBacktester` (`core/qa/backtesting.py`, `dae6529`):
   confusion matrix / precision / recall / Gini / calibration. Returns `insufficient_data`
   until a `loan_performance` table is supplied (no fabricated accuracy).
4. **Fair-lending** — QA-A proxy-swap regression (`cb3c93b`, CI-enforced) + CM-G structural
   bias detector (`2c58c76`).

## 6. Ongoing Monitoring

- **Drift** — MR-B PSI detector (`core/model_risk/drift.py`, `c4b7a5e`; `/api/accord/model-risk/monitoring`).
  Bands: PSI **< 0.10 no-drift / 0.10–0.25 moderate / ≥ 0.25 significant**. *Live meridian
  readings at drafting:* credit_score PSI 0.012 (no-drift), dti_ratio 0.174 (moderate — watch),
  ltv 3.35 (**significant — attention**, flagged for revalidation).
- **Decision replay** — CI-B (`decision_replay.py`) re-scores recorded decisions under a
  different `tenant_rules` version.
- **Champion/challenger** — replay a challenger rule version vs the champion (real once ≥2
  versions exist).

## 7. Change Control

- Catalogue/overlay changes flow through `PUT /api/accord/rules/overlay` with hard
  agency/regulatory-floor guardrails (`/overlay/guardrails`, PL-B `78138d5`) and create a new
  versioned `tenant_rules` row (draft → pending_approval → active).
- **Shadow testing** before activation (existing shadow mode).
- **Rollback** via emergency-revert / scheduled jobs (`scripts/rules_cron.py`): unratified
  emergency changes auto-revert within 24h.

## 8. Governance

- **Model owner** (per inventory `owner_team`) maintains the card + validation evidence.
- **Validation independence** — validation is performed/reviewed independently of model
  development per SR 11-7.
- **Reporting** — model inventory + monitoring status reported to `[BOARD / AUDIT COMMITTEE]`
  on a `[QUARTERLY]` cadence; significant-drift or fair-lending findings escalated immediately.

## 9. Incident Response

- **Suspend a model** when: significant unexplained drift (PSI ≥ 0.25), a confirmed
  fair-lending finding, or a validation failure.
- **Escalation path:** model owner → Chief Risk Officer / Fair Lending Officer → `[BOARD]`.
- **Documentation:** every suspension/remediation recorded with root cause, action, and
  re-validation result.

---

*TEMPLATE — requires legal/risk review before use. Accord facts current as of platform build
(commits referenced inline). Not regulatory advice.*
