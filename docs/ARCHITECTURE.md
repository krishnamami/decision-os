# Accord Decision OS — Architecture Reference

> MANDATORY READ before every task.
> This file describes the system **design** (stable across sessions).
> `CONTEXT.md` tracks build **state** (changes every session).
>
> Verified against the live repo + RDS on 2026-06-22. Where the live runtime
> differs from the designed flow, it is called out inline (see ⚠️ notes).

---

## The Complete Data Flow

```
DOCUMENT ARRIVES
  ↓
document_index (extracted_fields JSONB)
  • EDMS extracts fields from PDF/image
  • Stores raw extracted values per document
  ↓
golden_record_builder (core/pipeline/golden_record_builder.py)
  • Maps document fields → entity_states columns
  •   entity_states.qualifying_monthly ← W2 box1 / 12
  •   entity_states.appraised_value    ← APPRAISAL_URAR
  •   entity_states.mid_credit_score   ← credit report
  • NULL if document not uploaded — never assumed
  ⚠️ DESIGN vs RUNTIME: golden_record_builder is the production-correct
     derivation primitive set (21/21 unit tests). The live population path now
     exists for REAL tenants (RA-EX-E/F): POST /api/accord/documents/upload ->
     ingest_document -> route_extraction (pdfplumber / Vision / regex) ->
     document_index -> apply_golden_record(write=True) -> entity_states.
     Meridian is HARD-REFUSED: its `entity_states` are hand-seeded fixtures
     (scripts/seed_meridian_tenant.py), intentionally tuned for scenario
     outcomes. Only SAFE additive corrections were applied to live data (RA-2).
  ↓
entity_states (ACTUAL VALUES — one row per application)
  • What the documents said. Nothing derived.
  • Source of truth for all raw values.
  ↓ (parallel)
fact_nodes (QUALIFIED EVIDENCE)
  • Evidence resolvers read document_index
  • Produce fact_nodes with confidence + method:
  •   qualifying_income      conf≈0.97 method="W2 box1/12"
  •   verified_assets        conf≈0.93 method="bank statement sum"
  •   governing_credit_score conf≈0.99
  •   employment_continuity  conf≈0.95
  •   fraud_indicator        conf≈0.75 (if detected)
  ↓
14 vw_*_context VIEWS (one per persona — DONE RA-3C)
  • Each view joins entity_states + fact_nodes
  • Shaped for that persona's domain
  • Exposes: entity_states values + ev_* evidence columns
  •   vw_income_verification_context
  •   vw_credit_assessment_context
  •   ... (14 total)
  ↓
RUNNER (core/cron/runner.py — _process_one())
  For each persona, in wave order:

  STEP 1: Load rules ASYNC from catalogue
    • load_{domain}_rules(conn, tenant_id)
    • Returns {rule_key: {value, governed_by, layers}}
    • FROM: agency_guidelines + overlay_rules + regulatory_rules
    • overlay ALWAYS WINS over agency
    • agency ALWAYS WINS over regulatory

  STEP 2: Query that persona's view
    • Gets entity_states values + evidence columns

  STEP 3: Call ContextEnricher
    • Attaches evidence keys to bundle:
    •   ev_{income,credit,asset,employment}_confidence
    •   ev_{income,credit,asset,employment}_conflicts
    •   ev_{income,credit,asset,employment}_method
    •   evidence_populated / evidence_any_conflicts / evidence_overall_confidence
    • Also attaches catalogue threshold values:
    •   income_documentation_confidence_min etc.

  STEP 4: Build ONE ContextBundle for THIS persona
    • Contains: entity_states values + evidence keys + injected rules dict
    • ONE bundle per persona. Not shared.
    • "Each decision builds its own bundle. There is no global context." — CONTEXT.md

  STEP 5: Pass bundle to persona
    • persona._compute_offline(bundle)
    • SYNC. DB-LESS. No DB access inside persona.

  STEP 6 (RA-3F — DONE):
    • After decision_outputs commits, best-effort (never blocks the decision):
    •   Write persona_bundles row (audit snapshot):
    •     entity_snapshot + evidence_snapshot + rules_snapshot + upstream_snapshot
    •   is_current=true, version=N ; old row is_current=false
    •   decision_outputs.bundle_id = persona_bundles.id (stamped on the exact row)
  ↓
PERSONA (domains/lending/personas/*.py)
  • _compute_offline(bundle) — SYNC, DB-LESS
  • Reads from bundle: entity_states values + evidence quality + injected rules
  • Calls resolver with injected rules:
  •   resolver = CreditFindingsResolver(rules=rules)
  •   findings = resolver.resolve(values)   # IN MEMORY — not written to DB
  • Reads findings + evidence → emits make_signal()
  • Writes to output_payload → context_snapshot
  ↓
decision_outputs (persisted to DB)
  • outcome, confidence, output_payload, bundle_id
  ↓
persona_bundles (persisted to DB — RA-3F, done)
  • Frozen snapshot of exactly what the persona saw
  • Enables: audit, replay, repurchase defense
```

---

## Architecture Rules (Non-Negotiable)

**RULE 1 — ZERO HARDCODED VALUES**
Every threshold, rate, factor, period, percentage lives in a catalogue table.
Never in Python. Test: grep for numeric lending constants in resolver files → zero hits.
Holds with ZERO exceptions as of Gap (c) fix (f35ae33) — the SE business-ownership
cutoffs + factors in asset_resolver were the last hardcoded lending value; now
catalogue-driven. Remaining grep hits are structural (accumulator inits,
sentinels like _NO_PRIORITY, the SAFE_DEFAULTS fallback, rule_validator's
synthetic boundary-test loans).

**RULE 2 — THREE LAYERS ONLY**
`regulatory_rules` → federal law (floor, cannot override).
`agency_guidelines` → Fannie/FHA/VA/Freddie guidelines.
`overlay_rules` → lender credit policy (ALWAYS WINS).
No other rule source. No `platform_guardrails` as a rule source.

**RULE 3 — ACCORD SURFACES RULES. LENDER DECIDES.**
Workbench shows: Federal | Agency | Overlay | Applied | Citation
for every rule applied to every decision.

**RULE 4 — ENRICHER IS THE CATALOGUE GATEWAY**
Enricher has the DB conn, calls rule_loader, attaches results to the bundle.
Persona reads from the bundle. Persona NEVER calls rule_loader directly.

**RULE 5 — PERSONA IS SYNC AND DB-LESS**
`_compute_offline(bundle)` has no DB access. Everything the persona needs is in
the bundle. No `await`, no `conn`, no DB calls inside a persona.

**RULE 6 — RESOLVERS RETURN IN MEMORY**
Resolver receives values from the persona, reads the injected rules dict (loaded
by the runner), returns findings to the persona. Resolver NEVER writes to DB,
views, or entity_states.

**RULE 7 — SIGNALS NOT FLAGS**
`make_signal()` only. No `add_flag()`. No flags column.
Output → `output_payload` → `context_snapshot`.

**RULE 8 — CATALOGUE BEFORE CODE**
Seed rule into catalogue → verify rule_loader returns it → THEN rewrite resolver
to read it. Never add a Python constant as a placeholder.

**RULE 9 — SAFE_DEFAULTS = ONLY FALLBACK**
`rule_loader.SAFE_DEFAULTS` is the only acceptable Python fallback. If a rule is
missing from the catalogue, log a WARNING + use the SAFE_DEFAULT. Never a local
hardcoded constant in the resolver.

**RULE 10 — persona_bundles AFTER DECISION**
Write the `persona_bundles` row AFTER `decision_outputs` is committed, in the
same transaction. The memory bundle is the source of truth during a live run;
the PG bundle is the audit record (never read during a live run). Replay reads
from `persona_bundles` directly — no view, no enricher.

**RULE 11 — RESOLVER OUTPUT STANDARD**
Every resolver method that returns a findings dict MUST include `'data_source'`
and `'missing_inputs'`. See the **Resolver Output Standard** section below.

---

## Resolver Output Standard (RULE 11)

Every resolver method that returns a findings dict MUST include two provenance
keys, so every advisory result is auditable and the data gaps are explicit:

- `'data_source'` — where each input came from, e.g. `"CREDIT_REPORT.tradelines"`,
  `"entity_states.total_liquid_assets"`, `"DIVORCE_DECREE Vision (RA-EX-D)"`.
- `'missing_inputs'` — the fields the method needs but that are NOT extractable
  today; `[]` when every input is present.

**Principle — never silently assume data is present.** A missing input MUST
surface in `missing_inputs` and the method MUST degrade to a documented default /
`not_applicable` — never a silent guess or an assumed value. This makes the
PATH-2 extraction/wiring gap explicit on the UW workbench rather than hidden
behind a fabricated number.

Reference implementation — `core/obligations/obligation_resolver.py` (OB-B):

```
{
  "type": "business_debt", "monthly_obligation": 600.0, "included": True,
  "citation": "Fannie B3-3.4-02",
  "data_source": "CREDIT_REPORT.tradelines",
  "missing_inputs": ["is_business_paying", "months_business_paid"],
  "docs_needed": ["12 months cancelled checks / business bank statements ..."],
}
```

Standard for ALL new/extended resolver methods. Existing resolvers
(asset/credit/income/title/fraud/...) adopt it incrementally as they are next
touched — not a blanket retrofit.

---

## Real File Paths

```
Personas:        domains/lending/personas/*.py
                 (NOT core/personas/ — does not exist)

Rule loader:     core/catalogue/rule_loader.py
                 get_rule(conn, guideline_name, tenant_id)
                   → {applied, governed_by, layers, using_default, risk, as_of}

ContextBundle:   core/context_store/context_builder.py
Enricher:        core/evidence/context_enricher.py
                 (wired in core/cron/runner.py _process_one)

Fact resolvers:  core/evidence/resolvers/*.py + backfill scripts

Domain resolvers:
  core/assets/      asset_resolver.py + deposit_analyzer.py            (RA-4A ✅)
  core/credit/      findings_resolver.py + tradeline_analyzer.py       (RA-4B ✅)
  core/collateral/  appraisal_analyzer.py + property_eligibility_resolver.py (RA-4C ✅)
  core/title/       lien_resolver.py                                   (RA-4D ✅)
  core/fraud/       income_mismatch_detector.py + undisclosed_debt_detector.py
                    + employment_fraud_detector.py + fraud_rules.py    (RA-4F ✅)
  core/income/      rental_income_resolver.py + self_employed_resolver.py (RA-4G ✅)
  core/compliance/  rule_validator.py                                  (RA-4E ✅)

Seed scripts:    scripts/compliance/
Verify gate:     scripts/verify_catalogue_ready.py   (59/59 exit 0)
Evaluate:        scripts/evaluate_meridian_scenarios.py
                 ⚠️ DO NOT IMPORT — runs asyncio.run(main()) at module level
                    (no __main__ guard). Call as a subprocess only.
Bundles:         persona_bundles table (RA-3F — done; scripts/migrations/create_persona_bundles.sql)
Storage:         core/storage/  s3_keys.py (MISMO key builder) + s3_client.py
                 (async boto3 wrapper, graceful no-AWS no-op)        (RA-P0-A ✅)
Income model:    core/income/  income_aggregator.py (get_qualifying_income /
                 get_employment_gaps + INCOME_TYPES/BORROWER_ROLES consts) +
                 w2_income_resolver.py (W2 base salary) + retirement_income_resolver.py
                 (SS/pension/asset-depletion/investment) + alimony_resolver.py
                 (alimony/child support). All sync/DB-less.    (INC-A→F ✅)
Obligations:     core/obligations/  obligation_resolver.py (ObligationResolver —
                 per-type monthly debt: student/alimony/installment/revolving/
                 heloc/business-debt/rental-offset; sync/DB-less)   (OB-A/B ✅)
Exceptions:      core/exceptions/  exception_engine.py (ExceptionEngine — eligibility:
                 agency-floor/overlay-breach/factors gates) + compensating_factors_engine.py
                 (CompensatingFactorsEngine — detect 6 factors); sync/DB-less  (EX-A/B ✅)
                 + exception_writer.py (population job) + exception_workflow.py
                 (RBAC + status transitions); DB writers, NOT runner-wired (EX-C ✅)
Intelligence:    core/intelligence/  change_impact_simulator.py (ChangeImpactSimulator —
                 read-only "what-if" over recorded decisions; no engine re-run) (CI-A ✅)
                 + decision_replay.py (replay_decision / replay_all_decisions — replay a
                 recorded decision against a different tenant_rules version) (CI-B ✅)
                 API: api/accord/intelligence.py (POST /simulate-impact + GET
                 /simulatable-rules)
Scenarios:       core/scenarios/  base.py (Scenario + ScenarioCondition dataclasses) +
                 meridian.py (16 typed scenarios — single source of truth) (SC-B ✅)
                 + runner.py (ScenarioRunner — tenant-agnostic shared engine) (SC-C ✅)
                 CLI: scripts/generate_scenarios.py (--tenant any; library->PASS/FAIL,
                 else REPORTED). scripts/evaluate_meridian_scenarios.py = the meridian
                 16/16 gate (delegates the run loop to ScenarioRunner)
```

---

## What Each Table Holds

```
document_index            Raw extracted fields from each document
entity_states             Actual values mapped from documents (one row per app)
fact_nodes                Qualified evidence with confidence + method
agency_guidelines         Fannie/FHA/VA/Freddie published rules (98 rows)
regulatory_rules          Federal law (CFPB/HUD/VA) (23 rows)
overlay_rules             Lender credit policy — Meridian + Summit (6 rows)
decision_outputs          What each persona decided (outcome + output_payload)
decision_trace            Immutable audit record per decision
persona_bundles           Frozen snapshot of what each persona saw (RA-3F — done)
fraud_signals             Fraud detector outputs (IncomeMismatchDetector etc.)
loan_condition_instances  Conditions generated by personas
adverse_action_notices    ECOA/Reg B notice tracking — declines + 30-day deadline
                          + HMDA denial codes (RA-7B)
hmda_lar                   HMDA Loan/Application Register — one row per app, loan +
                          action + demographic data, Reg C (RA-7C)
aus_responses             Parsed AUS (DU/LP) recommendations — one per app+system
                          (DU RA-AUS-A, LP RA-AUS-C). LP feedbacks stored in the
                          shared `findings` JSONB (no `feedbacks` column)
income_sources            One row per income stream per borrower (INC-A) — type,
                          monthly/annual (generated), confidence, method,
                          fact_node_ids. Additive to entity_states.qualifying_monthly
employment_history        Per-job history (INC-A) — start/end, is_self_employed,
                          ownership_pct; FK income_source_id
loan_exceptions           Structured exception request→review→grant lifecycle
                          (EX-A schema; EX-C populates via exception_writer) — FK
                          decision_outputs + loan_actions; breach_pct,
                          below_agency_floor, status, compensating_factors JSONB
compensating_factors      Per-factor detail per exception (EX-A schema; EX-C populates);
                          FK loan_exceptions
```

---

## Document Storage (S3 — RA-P0-A)

`core/storage/` is the canonical object-storage layer. `s3_keys.py` builds keys
(pure, no I/O — the single source of truth for layout); `s3_client.py` is the
async boto3 wrapper that degrades to no-ops when AWS is unconfigured (local dev,
CI, meridian), so S3 is never a hard dependency. Keys are tenant-isolated and
discoverable (doc_type/system in the path, never opaque UUIDs).

```
s3://{S3_BUCKET (default accord-docs)}/
  {tenant_id}/
    {application_id}/
      uploads/raw/{doc_type}/{filename}      original files as uploaded
      uploads/processed/{doc_type}.json      extracted fields per doc
      mismo/raw/{version}.xml                MISMO XML as received from the LOS
      mismo/parsed/canonical.json            canonical fields extracted
      aus/du/{casefile_id}.json              DU response files
      aus/lp/{key_number}.json               LP response files
    platform/onboarding/{filename}           Platform Studio uploads (tenant-level)
    exports/hmda/{year}/{month}/lar.csv      HMDA LAR exports
    exports/dmn/{version}/rules.xml          DMN rule export (MI-F future)
```

Live wiring (RA-P0-A): POST /api/accord/documents/upload, after extraction
succeeds, stores the raw file (AES256) + processed JSON and stamps
`document_index.s3_key` with the raw key — best-effort, gated on a successful put
(S3 off -> s3_key untouched, extraction unaffected). The other key builders
(mismo/aus/exports) are ready for their future producers.

---

## Income Model (INC-A / INC-B — UW OS)

`entity_states.qualifying_monthly` is a single scalar; it cannot represent
multiple income streams, per-stream evidence, or co-borrower separation. The
income model (INC-A) adds that WITHOUT removing the scalar — **two data paths,
both must work**:

```
PATH 1 (meridian / seeded tenants):  entity_states.qualifying_monthly  (UNCHANGED)
PATH 2 (real tenants post-ingestion): income_sources rows -> get_qualifying_income()
```

- **income_sources / employment_history** tables + `vw_employment_gaps` view
  (INC-A, `scripts/migrations/create_income_tables.sql`). Additive; no RLS yet
  (a later INC slice adds tenant policy).
- **core/income/income_aggregator.py** (INC-A): `get_qualifying_income()` sums
  current streams across borrower roles; `get_employment_gaps()` reads the view;
  `INCOME_TYPES` / `BORROWER_ROLES` constants (no magic strings). Read-only.
- **golden_record_writer.apply_golden_record(write=True)** (INC-A) additively
  writes the primary W2 stream into income_sources (best-effort, idempotent);
  `entity_states.qualifying_monthly` is never touched. income_sources is EMPTY
  for meridian (its writes are hard-refused — seeded fixtures).
- **core/income/w2_income_resolver.py** (INC-B): W2 base salary only —
  `qualify_from_w2_doc` (box1/12), `qualify_from_paystub` (gross×freq/12),
  `check_employment_history` (24-month, catalogue `employment_history_months_required`
  Fannie B3-3.1-01), `select_qualifying_income` (lesser-of). SYNC + DB-LESS;
  SAFE_DEFAULTS fallback. income_verification consumes it ADVISORY-only
  (output_payload.income_analysis) — proposed_outcome + the seeded
  qualifying_monthly are unchanged (16/16 holds).
- **Variable income** (overtime/bonus/commission/hourly) is OUT of scope until
  the paystub extractor adds the fields (overtime_ytd, bonus_ytd, commission_ytd,
  hourly_rate, hours_per_week) — none exist in document_index today. See
  `VARIABLE_INCOME_TODO`. ENRICHER TODO: it does not yet attach W2/PAYSTUB
  extracted_fields to the income bundle, so the doc-level resolver runs on PATH 2
  only.
- **INC-E — retirement/SS/asset-depletion/investment** (`retirement_income_resolver.py`):
  qualify_ss (1.25× gross-up + 3yr continuance), qualify_pension, qualify_asset_depletion
  (eligible-with-haircuts / 360), qualify_dividends_interest (2yr avg). 8 catalogue
  rules (Fannie B3-3.1-09). Asset depletion runs on REAL data — the enricher's
  `_attach_income_entity` surfaces `entity_states.total_liquid_assets` to the income
  bundle; SS/pension/investment are foundation-only (no source docs). Advisory →
  `output_payload.retirement_income_analysis`.
- **INC-F — alimony/child support** (`alimony_resolver.py`):
  qualify_alimony_received / qualify_child_support_received (3yr continuance gate),
  treat_alimony_paid (monthly_debt | reduce_income per catalogue) / treat_child_support_paid
  (always monthly_debt). 3 catalogue rules (B3-3.1-09 / B3-6-05). Input = DIVORCE_DECREE
  Vision fields (RA-EX-D); meridian has no decree docs → all methods not_applicable
  (foundation). Advisory → `output_payload.alimony_child_support_analysis`. DTI breakout
  of alimony/child-support PAID is deferred to OB-A/B (an obligations resolver) — not
  wired into dti_calculation yet.
- All four income resolvers share ONE `income_rules` bundle key (w2_income_resolver.
  INCOME_RULE_KEYS aggregates employment + retirement + alimony keys; the runner's
  income_verification branch loads them all). INC-C/D (variable income, INC-G+) and
  document→income_sources population remain extraction-prompt follow-ups.

### Obligations (OB-A / OB-B)

`core/obligations/obligation_resolver.py:ObligationResolver` decomposes monthly
debt obligations by type (Fannie B3-6-02 / B3-6-05 / B3-3.4-02 / B3-3.1-08), sync + DB-less,
catalogue-driven (SAFE_DEFAULTS fallback). `resolve(obligations)` → total +
per-type breakdown + excluded list. Routes:
- **student_loan** — uses the PRE-COMPUTED TradelineAnalyzer payment (deferred-1%/
  IBR/PSLF, RA-4I); never recomputed.
- **alimony_paid / child_support_paid** — delegates to the INC-F AlimonyChildSupportResolver.
- **installment** — actual, else balance/months; excluded ≤ months_remaining_exclusion (10).
- **revolving** — reported min, else revolving_payment_factor_pct (5%) of balance.
- **heloc** — actual, else heloc_payment_factor_pct (1%) of balance/limit (OB-A).
- **business_debt** (OB-B, Fannie B3-3.4-02) — EXCLUDED only if business-paid ≥
  business_debt_exclusion_months (12) with no 30-day delinquency; else INCLUDED +
  docs_needed. is_business_paying/months_business_paid absent today → default to included.
- **rental_property** (OB-B) — net = rental_net_monthly − pitia_monthly (B3-3.1-08);
  ≥0 positive offset (not a DTI obligation), <0 shortfall added. Both inputs absent
  today → not_applicable.

Wired into dti_calculation via the runner's `obligation_rules` bundle key →
`output_payload.obligation_breakdown` (ADVISORY). The DTI ratio (dti/dti_front/
dti_back) is UNCHANGED — folding the breakdown into the ratio is a later OB slice.
Meridian's dti bundle carries only the aggregate existing_debt_obligations (no
per-type list), so the breakdown is foundation there; live per-obligation inputs
(tradelines, decree, per-property PITIA) + RA-4G rental wiring flow on PATH 2.

BACKLOG (later OB slice, when the DTI ratio is wired): the resolver output keys
are the canonical `type` / `monthly_obligation` / `included` (consistent across
all 7 obligation types + resolve() + the persona + tests). The OB-B spec proposed
`obligation_type` / `monthly_payment` / `included_in_dti` — aspirational; the
existing canonical naming is correct and stays. Do a clean naming refactor across
the FULL ObligationResolver (all types + resolve() + tests in one pass) only when
the breakdown is folded into the actual DTI ratio, so the rename and the
ratio-wiring land together rather than churning the schema twice.

---

## Exceptions (EX-A / EX-B)

`core/exceptions/` is the underwriting-exception framework. It builds ON the
existing override capture (loan_actions + decision_outputs.human_*) — it does NOT
duplicate it — and is ADVISORY: wired into approval_routing as output only, never
moving proposed_outcome (Known Gap f stands).

- **EX-A — ExceptionEngine** (`exception_engine.py`, Fannie B3-2-02): three gates —
  agency floor is ABSOLUTE (below it, never) → overlay-breach tolerance (catalogue
  max %) → compensating-factors-required. `classify_exception_type` maps a blocked
  signal to a type. 4 catalogue rules. New tables `loan_exceptions`
  (request→review→grant lifecycle, FK decision_outputs + loan_actions) +
  `compensating_factors` — EX-A does NOT write them (EX-C populates).
- **EX-B — CompensatingFactorsEngine** (`compensating_factors_engine.py`): detects
  6 factors from REAL entity_states data — substantial_reserves (liquid/piti),
  low_ltv, excellent_credit (score−floor), long_employment (months from
  period_start), limited_debt (oblig/income), large_down_payment (100−ltv); scores
  strong/moderate/weak → exception_score → recommended approval level (senior /
  manager / uw / insufficient). payment_shock + residual_income → not_applicable
  (no input). 6 catalogue factor-bar thresholds. The enricher's
  `_attach_compensating_factor_inputs` surfaces the inputs to the approval_routing
  bundle as `cf_inputs`; detected factors feed the EX-A ExceptionEngine.
- Both engines: sync + DB-less, catalogue-driven (SAFE_DEFAULTS fallback), RULE 11
  (data_source + missing_inputs on every return). One shared `exception_rules`
  bundle key (EXCEPTION_RULE_KEYS aggregates the 4 exception + 6 factor + 3 score
  + baseline reserves keys; the runner's approval_routing branch loads them all).
- **EX-C — workflow + approver hierarchy + register** (the WRITE layer):
  - `exception_writer.py:populate_exception_records` — post-decision POPULATION JOB
    (persona stays DB-less, RULE 5/6): reads `decision_outputs.context_snapshot`
    (output_payload.exception_analysis + compensating_factors_analysis) and persists
    `loan_exceptions` + `compensating_factors`. Idempotent per decision_output. Same
    pattern as the adverse_action / hmda backfills — `backfill_exception_records.py`
    runs it; NOT runner-wired, so the decision path + 16/16 are untouched.
  - `exception_workflow.py:ExceptionWorkflowService` — `can_approve` (role × required
    level × ABSOLUTE agency floor) + `transition_status` (requested → under_review →
    granted/denied with valid-transition + RBAC checks, writing a `loan_actions`
    audit row). APPROVER_AUTHORITY = role→levels RBAC map; the agency floor can never
    be breached by any role (catalogue exception_cannot_breach_agency_floor).
  - `overrides.py:generate_exception_register` — ECOA consistent-treatment / CFPB
    report (total/granted/denied/pending + by_type + grant_rate); demographic data
    never collected or used (mirrors HMDA RA-7C).
  - **RULE 1 gap from EX-B CLOSED**: the score→approval-level thresholds (9/5/2) are
    now catalogue-driven (`exception_score_{senior,manager,uw}_min`), not hardcoded.
  - proposed_outcome UNCHANGED — Known Gap (f) still holds (the conflict→manual-review
    OUTCOME change remains deliberate future work). NOTE: `decision_outputs` stores the
    persona payload in `context_snapshot` (there is NO output_payload column) — the
    writer reads context_snapshot.

---

## Intelligence Subsystem — Change Impact + Replay (CI-A / CI-B)

`core/intelligence/` is the read-only analytics layer that reasons OVER recorded
decisions without re-running the engine and without writing the catalogue or any
decision (same posture as `core/audit/reports`). Two slices share its proven
reduction primitives (`_reduce_outcome` / `_normalize_upstream`):
`change_impact_simulator.py` (CI-A — hypothetical rule changes) and
`decision_replay.py` (CI-B — replay against a different rule version).

### CI-A — change impact simulator

`change_impact_simulator.py` answers "if we moved this overlay rule, what happens
to the pipeline?" It does NOT re-run the engine.

**Approach (delta short-circuit + binding-constraint cross-check):** each
simulatable overlay rule maps to one `entity_states` field + one upstream persona
+ a gate direction —

```
SIMULATABLE_FIELDS = {
  "credit_floor":     ("mid_credit_score", "credit_assessment", "gte"),  # floor
  "dti_back_max":     ("dti_back",          "dti_calculation",   "lte"),  # ceiling
  "ltv_max_purchase": ("ltv",               "ltv_assessment",    "lte"),  # ceiling
}
```

For each application: re-evaluate ONLY that gate against the hypothetical
threshold; flip the controlled persona's outcome ONLY if the field gate itself
flips (a persona that blocked for a non-threshold reason — bankruptcy, thin file —
is left intact); then **re-reduce the recorded upstream persona outcomes** (with
that one persona swapped) to the simulated underwriting outcome. The reducer is
the real boundary — *any block → block; else any escalate → escalate; else
recommend* — and reproduces all **16/16** recorded meridian outcomes.

**Correctness guarantee — an app only flips if the simulated rule is its SOLE
binding constraint.** Because the full upstream set is re-reduced, multi-constraint
apps are excluded automatically: clearing credit on an app that also has
`product_eligibility=block` still reduces to block. A would-be flip that is
masked by another blocker is reported as `shadowed` (dollars NOT counted toward
unblocks), not silently dropped.

**Data source (spec correction, important):** the binding constraint is read from
the authoritative `decision_outputs.upstream_decisions` column (a `{persona:
outcome}` map), NOT from `output_payload.signals` — that array is EMPTY in the
live data, and using it would make every app look sole-binding (false flips
everywhere). RULE 11 holds: a NULL field (e.g. SC03 `dti_back`) is reported in
`missing_inputs` and skipped, never assumed. Every result carries `data_source`
+ `missing_inputs`; the top-level result carries a plain-language `honesty_caveat`
(true unblocks vs shadowed-by-other-constraint, dollars excluded, NULL skips,
dataset size). Thresholds are always caller-supplied — nothing hardcoded.

### CI-B — historical decision replay

`decision_replay.py` answers "what would this loan have decided under a different
rule version?" `replay_decision(conn, application_id, tenant_id, target_rule_version_id)`
re-runs a recorded underwriting decision against ANY `tenant_rules` version using
the EXISTING `ThresholdResolver(rule_version_id)` (already version-parametric —
the cron path uses it to score rate-locked loans under their pinned version). It:

1. reads the recorded outcome + its `rule_version_id` (`decision_outputs`),
2. reads the FROZEN upstream persona outcomes (`persona_bundles.upstream_snapshot`)
   and gate values (`entity_states`),
3. re-resolves credit/dti/ltv thresholds at the original vs target version, and
4. re-evaluates ONLY those gates, swaps the affected personas into the frozen
   upstream set, and **re-reduces** to the underwriting outcome (CI-A's shadow-safe
   method — a cleared gate never unblocks a loan blocked by another persona;
   `reduce()` reproduces all 16 recorded outcomes, `fidelity_failures=0`).

`replay_all_decisions()` rolls this up across the pipeline (changed count +
`dollars_changed`). Read-only — nothing written; RULE 11 (`data_source` +
`missing_inputs` + `honest_caveat`) on every result. SCOPE: credit/dti/ltv gates
only; fraud/product/income held at their frozen outcomes; full 14-persona cascade
re-run remains a future slice.

**Cross-version requires ≥2 versions.** Meridian shipped with only v1, so
`scripts/compliance/seed_ci_b_v2_rules.py` seeds a synthetic v2 in `tenant_rules`
as **`status='draft'`** — the live path resolves only the *active* version (v1), so
decisions + 16/16 are UNCHANGED, while replay targets v2 by id (`ThresholdResolver`
reads any version by `rule_version_id` regardless of status). v2 deltas:
`credit.min_score` 640→680, `dti.back_max` 43→40 (both stricter). Demo: 3 loans
flip block under v2 ($1.15M) — cross-validating CI-A's tighten-DTI finding.

### Eval timeout fix (gap g — actual fix)

The 16/16 eval (`scripts/evaluate_meridian_scenarios.py`) was already concurrent
(`--concurrency`, default 4) — gap g's "sequential ~165s" was stale. The real
remaining issue was an UNBOUNDED await: a single stuck RDS call hung the whole
`asyncio.gather`. CI-B wraps each `_process_one` in
`asyncio.wait_for(timeout=SCENARIO_TIMEOUT)` (default 30s, env-tunable) so a stuck
decision becomes a bounded `TIMEOUT` error and the run continues. Gap g is now
addressed (concurrency + timeout); the remaining latency is network RTT to live RDS.

---

## Scenario Infrastructure (SC-B / SC-C)

`core/scenarios/` is the typed scenario library + the tenant-agnostic engine that
runs it. Read-only over the decision path — it runs EXISTING apps (never fabricates
synthetic loans) and writes nothing new beyond the normal `decision_outputs` the
engine already produces.

### SC-B — the Scenario library (`base.py` + `meridian.py`)

`base.py` defines `Scenario` + `ScenarioCondition` (dataclasses). A `Scenario`
carries identity, the real loan inputs (from `entity_states`), BOTH the
`expected_key_decision`/`expected_outcome` (the per-persona decision the 16/16 eval
verifies) AND the `underwriting_outcome` (the loan aggregate — they legitimately
differ, e.g. SC16's key `closing_readiness`=escalate vs the loan = recommend), plus
provenance (`conditions`, `notify_role`, `explanation`) and RULE 11 `data_source` +
`missing_inputs`. Helpers: `reserve_months`, `is_multi_block`, `demo_talking_points`.

`meridian.py` holds the 16 meridian scenarios as the **single source of truth**,
consolidating what were two loose dicts (`EXPECTED_OUTCOMES` + `SCENARIO_NOTES`) plus
the `entity_states` inputs. Built from LIVE data (cross-checked 0 mismatches);
`conditions` are computed from each loan's real value vs the meridian overlays
(credit 660 / dti 43 / ltv 95) — factual breaches only, never fabricated (SC03's NULL
dti → `missing_inputs`, no fabricated condition). The overlay constants are inlined
as fixture data — acceptable for a fixture library, NOT production rule code
(production reads them from the catalogue via rule_loader/ThresholdResolver).

### SC-C — `ScenarioRunner` (the tenant-agnostic engine)

`runner.py:ScenarioRunner(database_url, tenant_id, concurrency, timeout)` is the
shared engine extracted from the meridian eval so the 16/16 gate AND
`generate_scenarios.py` drive the SAME production path:
- `execute(app_ids)` — runs every `(wave, decision)` for every app through the REAL
  `PersonaRunner._process_one` (one decision per call, written not returned), apps
  concurrent under a semaphore, each bounded by `SCENARIO_TIMEOUT` (the CI-B guard).
- `verify_one(scenario)` — PASS/FAIL on the KEY decision (the eval's criterion); the
  underwriting aggregate is reported as context, derived with the shared CI-A reducer
  (`core.intelligence.change_impact_simulator._reduce_outcome`) — never re-implemented.
- `report_one(app_id)` — for tenants WITHOUT a library: the actual outcome is REPORTED,
  never an invented PASS/FAIL.
- `run_all` + `_build_summary` — status counts / outcome breakdown / dollars / pass-rate.

**Tenant landscape:** 7 tenants have `entity_states` (meridian 16, summit 49,
atlas/heartland/pacific 50 each, demo 8696, default 1). Only **meridian** has a
curated `core/scenarios` library today, so "tenant-agnostic" means the ENGINE
generalizes — meridian gets PASS/FAIL, every other tenant gets REPORTED outcomes
(no fabricated expectations).

`scripts/generate_scenarios.py` is the CLI: `--tenant <t>` (any tenant),
`--concurrency N`, `--seq`, `--direct` (compat — direct-off-DB is the only mode),
`--scenario SCxx` (single scenario, library tenants only).

**Honest flag — the meridian eval keeps its ordered dicts.** `evaluate_meridian_
scenarios.py` delegates only its RUN LOOP to `ScenarioRunner.execute()`; it keeps
`EXPECTED_OUTCOMES` + `SCENARIO_NOTES` + the verification prints/query verbatim so the
16/16 output is byte-identical. Rebuilding `EXPECTED_OUTCOMES` from the library would
reorder the verification lines (the dict's insertion order ≠ SC01–SC16), so the dicts
stay; the library is the typed source of truth for `generate_scenarios.py` + tests. A
full eval→library migration is a deferred cosmetic pass.

---

## Platform Studio Onboarding (PL-A / PL-C / PL-D / PL-E)

`core/extraction/` hosts the Platform Studio onboarding **extractors** (PL-C/D/E) —
the EXTRACT stage that turns a lender's raw config document into a STRUCTURED DRAFT
proposal for admin review — and `api/accord/onboarding.py` hosts the **config-step
endpoints** (PL-A) that round out the 8-step onboarding API surface. Everything here
is config-layer, NOT decision-path: extractors parse an upload into a proposal and
**write nothing** (activation reuses the EXISTING rules.py / refresh / upload
plumbing); the PL-A config endpoints write only tenant config (`tenants` /
additive `tenant_rules.rules` subkeys), never `decision_outputs`/`entity_states`.
Extractor posture: **EXTRACT → REVIEW → ACTIVATE**. RULE 11 throughout (per-field/row
confidence + source provenance + `missing_inputs`; unparseable items surface as
`unmapped_items`, never silently dropped). All are 16/16-safe by construction
(onboarding layer, no persona wiring, no decision-path writes).

- **PL-C — credit-policy PDF extractor** (`policy_extractor.py:CreditPolicyExtractor`):
  hybrid pdfplumber-text regex + a self-contained Claude Vision fallback (graceful
  no-key degrade). Maps a policy PDF → a `tenant_rules.rules`-shaped overlay proposal
  (credit/dti/ltv/programs/loan-limits) + the 3 typed `overlay_rules` updates.
  Endpoint `POST /api/accord/onboarding/extract-policy`. Review/activate via the
  existing `rules.py` flow (validate_overlay → create version → activate, with the
  hard agency/regulatory-floor guardrails).

- **PL-D — rate-sheet CSV extractor** (`rate_sheet_extractor.py:RateSheetExtractor`):
  stdlib `csv` only — **no openpyxl/pandas/xlrd** (none installed; a lender exports
  Excel as CSV — same data). Pure + sync + DB-less. Produces TWO output shapes:
  - `rate_sheet_entry_rows` (tenant base rates: product/credit_band/ltv_max/base_rate/
    llpa_adjustment/effective_date — the EXACT columns the existing
    `POST /api/accord/rules/rate-sheet/upload` endpoint requires) and
  - `llpa_rows` (the FICO×LTV matrix via `parse_fico_ltv_grid` + the
    purpose/property/occupancy adjustment blocks → `llpa_adjustments`-shaped rows,
    feeding the existing `scripts/refresh_llpa_grid.py` stage→promote path).

  Endpoint `POST /api/accord/onboarding/extract-rate-sheet`. The extractor is the
  parse-and-propose front-end ONLY; it does not duplicate the upload/promote writers.
  NOTE: `rate_pricing` computes its own inline base+LLPA rate and does **not** read
  `rate_sheet_entry`/`llpa_adjustments` — de-hardcoding the persona to consume these
  tables is a separate future slice, out of PL-D's scope.

- **PL-E — product-matrix CSV extractor + activate** (`product_matrix_extractor.py:
  ProductMatrixExtractor`): stdlib `csv` only, pure + sync + DB-less. Parses a lender
  product matrix → `products`-table-shaped rows (product_name/loan_type/loan_purpose/
  min_credit_score/max_dti/max_ltv/max_loan_amount/is_active) with messy-header
  normalization (synonyms), `$`/`%` coercion, derived product_id, per-row confidence +
  warnings; unrecognized columns + empty-name rows → `unmapped_items`. Endpoints
  `POST /extract-product-matrix` (draft) + `POST /products/upload` (ACTIVATE — the
  **first programmatic writer** of the `products` matrix table outside seeding).
  The `products` PK is `product_id` ALONE, so the upsert is **tenant-guarded**
  (`ON CONFLICT (product_id) DO UPDATE … WHERE products.tenant_id = EXCLUDED.tenant_id
  RETURNING`) — a product_id owned by another tenant is rejected, never clobbered.
  Decision-path-safe: `product_eligibility` uses its inline `_PRODUCTS` matrix, not the
  `products` table (and `GET /products` reads the separate `product` catalog).

- **PL-A — the 4 config-step endpoints** (`api/accord/onboarding.py`, validation in
  PURE module-level helpers so it is unit-testable without a DB; endpoints are thin DB
  wrappers): `POST /company` (tenant name + NMLS/company fields → `tenants.settings`),
  `POST /licenses` (state licenses → `tenants.settings.licenses[]`, deduped by state),
  `POST /exception-config` (bounds-checked level 1-4 / DTI ≤ 60% / LTV ≤ 100% / CFs 0-6,
  stored additively under `tenant_rules.rules.exceptions` — a subkey the live personas
  do NOT read), and `POST /test-loan` (advisory probe). **test-loan correction:** the
  real 14-persona engine (`PersonaRunner._process_one`) WRITES `decision_outputs`, which
  conflicts with the advisory/no-write requirement — so test-loan runs the pure
  `ProgramRecommender` (EX2-B, no writes) and maps eligibility → advisory
  recommend/escalate/block; it does NOT claim 14 personas ran, and points to `/import`
  for the full persisting evaluation.

**8-step onboarding API surface (complete):** 1 `/company` · 2 `/licenses` ·
3 `/products/upload` (PL-E) · 4 `/extract-policy` (PL-C) + `GET /api/accord/rules` ·
5 `/exception-config` · 6 `/extract-rate-sheet` (PL-D) · 7 `/import` · 8 `/test-loan`.
The React 8-step wizard (PL-A-UI, `frontend/`) is a deferred follow-up — not covered
by the pytest / 16/16 gate.

---

## Persona Status

Legend: ✅ done · ❌ pending · the parenthetical names the prompt(s) that close it.

All 14 personas now read the evidence graph (EVIDENCE ✅) and have their frozen
audit snapshot (BUNDLE ✅ — RA-3F). Evidence reading is ADVISORY + outcome-neutral
across the board (signals + provenance, never moves proposed_outcome).

```
PERSONA                    VIEW  RESOLVER  EVIDENCE  BUNDLE
income_verification         ✅     ✅        ✅        ✅
credit_assessment           ✅     ✅        ✅        ✅
asset_verification          ✅     ✅        ✅        ✅
fraud_screening             ✅    detectors  ✅        ✅
dti_calculation             ✅     ✅        ✅        ✅
ltv_assessment              ✅     ✅        ✅        ✅
product_eligibility         ✅     ✅        ✅        ✅
employment_reconciliation   ✅    none       ✅        ✅
title_assessment            ✅     ✅        ✅        ✅
compliance_check            ✅     ✅        ✅        ✅
approval_routing            ✅    none       ✅        ✅
closing_readiness           ✅    none       ✅        ✅
rate_pricing                ✅    llpa       ✅        ✅
underwriting_decision       ✅    reads      ✅        ✅
lead_scoring                ✅    none       ✅        ✅  (off the meridian path)
```

Notes:
- fraud_screening has no persona-injected domain resolver — its signals come
  from the async fraud detectors (RA-4F, catalogue-driven thresholds) via
  `fraud_signals` → `fraud_indicator` fact, read as evidence.
- Evidence-confidence threshold is the single catalogue documentation-confidence
  floor `income_documentation_confidence_min`=0.75 (Fannie B3-3.1-01), reused
  across all domains (per-domain thresholds are a possible future seed).
- approval_routing surfaces a conflict→manual-review *preference* as an advisory
  signal but does NOT change the routing outcome (a deliberate future change).
- underwriting_decision, on a DECLINE (BLOCK) only, emits an ECOA adverse-action
  notice (RA-7B) into output_payload.adverse_action — HMDA denial codes mapped
  from the blocking upstream decisions, 30-day deadline from the catalogue. The
  enricher attaches the deadline only for this decision. Advisory; the persona
  never writes the DB (the population job fills adverse_action_notices).
- approval_routing reads the parsed DU result (RA-AUS-A) when one exists and
  emits AUS_ACCORD_CONFLICT if DU disagrees with Accord's underwriting outcome
  (DU approve vs Accord decline, or DU refer/ineligible vs Accord approve). The
  enricher attaches aus_result for this decision only; meridian has no DU data so
  no signal fires. Advisory.
- AUS phase COMPLETE (RA-AUS-A/B/C): DU + LP both wired end-to-end. The enricher
  attaches BOTH aus_result (DU) and aus_result_lp (LP) for approval_routing only.
  The persona runs the RA-AUS-B reconciliation engine (core/aus/reconciliation.py)
  against the MORE CONSERVATIVE of the two systems (RA-AUS-C — an LP Caution is
  never masked by a DU Approve): it classifies an Accord-vs-AUS disagreement into
  4 named cases (risk tier + explanation + UW action + HMDA implication) and emits
  AUS_CONFLICT_HIGH_RISK / AUS_CONFLICT_REVIEW on conflict or AUS_ACCORD_AGREEMENT
  on agreement, reconciling against the upstream UNDERWRITING outcome (not the
  routing outcome). output_payload carries aus_reconciliation + aus_reconciled_system
  on every decision. Advisory; proposed_outcome untouched; 16/16 holds.
- underwriting_decision also emits a HMDA LAR record (RA-7C) into
  output_payload.hmda_lar on EVERY application. Demographic data (ethnicity/race/
  sex/age) is collected + reported but NEVER read by any decision logic — the
  record is built after the outcome is set. Enricher attaches the source fields
  (vw_hmda_reporting + entity_states) for this decision only.
- compliance_check also runs the RA-7A ATR 8-factor checklist + QM classifier
  (12 CFR 1026.43). The enricher loads the 4 thresholds from regulatory_rules and
  the 8 factors from entity_states onto the evidence object, but ONLY for the
  compliance_check decision. Output is advisory: output_payload (atr_satisfied,
  qm_classification, safe_harbor_protected, rule traces) + SUPPORTS/CONTRADICTS
  signals; proposed_outcome is never moved. QM with no verified DTI is
  conservatively NON_QM; points/fees default to 0 until fee data is wired.

---

## Catalogue State (verified 2026-06-24)

```
agency_guidelines:   114 rows  (Fannie 91 / FHA 13 / VA 8 / Freddie 2)
                     (Gap c +2; INC-B +1; INC-E +8; INC-F +3; OB-A +2; OB-B +1;
                      EX-A +4; EX-B +6; EX-C +6 score thresholds + approver roles;
                      OB-A also updated student_loan_deferred_rate 1.0->0.5, gap d)
regulatory_rules:    23 rows
overlay_rules:        6 rows  (Meridian 4 / Summit 2)
verify gate:         59/59 exit 0   (scripts/verify_catalogue_ready.py)
```

---

## What Is Done vs Pending

The full RA arc is DONE: every lending threshold is catalogue-driven, every
decision is captured in persona_bundles, and all 14 personas read the evidence
graph.

```
DONE:
  RA-0A/B/C    Architecture decisions locked
  RA-1A/B/C/D  Catalogue + rule_loader built
  RA-2A/B/C/D  Golden record primitives + audit baseline
  RA-3A/B/C/D/E Evidence graph wired (enricher + views + fraud fact)
  RA-3F        persona_bundles table + runner wiring (frozen audit snapshot)
  RA-SEED-A/B/C Catalogue gap audit + seeds (gate 59/59)
  RA-4A        AssetResolver + DepositAnalyzer
  RA-4B        CreditFindingsResolver + TradelineAnalyzer
  RA-4C        PropertyEligibilityResolver + AppraisalAnalyzer
  RA-4D        LienResolver
  RA-4E        rule_validator (boundary self-test, catalogue-driven)
  RA-4F        Fraud detectors from catalogue (income_mismatch + undisclosed_debt)
  RA-4G        Income resolvers from catalogue (rental + self-employed)
  RA-4H        Title gap fix + runner one-shot retry around rule injection
  RA-4I        Student-loan IBR/PSLF treatment (Fannie B3-6-05)
  RA-4J        Months-remaining DTI exclusion from catalogue
  RA-PERSONA-A credit + asset + fraud read evidence
  RA-PERSONA-B dti + ltv + product read evidence
  RA-PERSONA-C 8 remaining personas read evidence (all 14 now read evidence)
  RA-6A        Stage 1 audit — all 8 checks PASS (demo-ready)
  RA-6B        Final lock-in + tag (rearch-core-complete)

BACKLOG (after client demo):
  RA-P0-A      SHIPPED: S3 document storage aligned to MISMO (FINAL re-arch
               prompt). core/storage/s3_keys.py = canonical key builder (pure):
               tenant-isolated {tenant}/{app}/... hierarchy, discoverable
               (doc_type/system in path, no UUIDs). core/storage/s3_client.py =
               async boto3 wrapper, AES256 on every put, graceful no-op when AWS
               is unconfigured (detects creds via Session.get_credentials()
               up front; put=False/get=None/exists=False). The /upload endpoint
               stores raw + processed JSON and stamps document_index.s3_key —
               best-effort, never a hard dependency (S3 off -> extraction
               unaffected). 16/16 preserved. -> RA re-arch arc COMPLETE.
  RA-P0-B      Parallel runner (asyncio.gather + semaphore) — perf only, see
               gap (g). Not a correctness item.
  RA-EX/A-F    Extraction SHIPPED: audit (A), golden_record builder+writer (B),
               gap-field derivation + demo seeding (C), pipeline + Claude Vision
               extractor (D), upload trigger wired (E), real Tier-1 pdfplumber +
               Tier-3 regex extractors + field manifest (F). Live path:
               POST /api/accord/documents/upload -> ingest_document ->
               route_extraction (3 tiers, all real) -> document_index ->
               golden_record -> entity_states. Meridian is hard-refused (seeded
               fixtures). Tier 1 = pdfplumber (no AWS creds; swap to Textract
               later); Tier 2 = Claude Vision; Tier 3 = regex over text.
  RA-AUS-A     SHIPPED: DU (Desktop Underwriter) response parser. core/aus/
               du_parser.py parses a DU response (Approve|Refer / Eligible|
               Ineligible, EA tiers, findings, conditions) into a stable shape;
               aus_responses table + store (ingest/load). approval_routing reads
               the parsed result (enricher, gated) and emits AUS_ACCORD_CONFLICT
               when DU disagrees with Accord's outcome. ADVISORY — reconciliation
               is RA-AUS-B; no DU response -> no signal. 16/16 holds.
  RA-AUS-B     SHIPPED: AUS reconciliation engine (core/aus/reconciliation.py).
               AUSReconciliationEngine.reconcile() classifies an Accord-vs-DU
               disagreement into 4 named cases (ACCORD_BLOCK_DU_APPROVE HIGH /
               ACCORD_RECOMMEND_DU_REFER HIGH / ACCORD_ESCALATE_DU_APPROVE MEDIUM
               / ACCORD_RECOMMEND_DU_REFER_ELIGIBLE LOW), each with risk +
               explanation + UW action + HMDA implication. approval_routing emits
               AUS_CONFLICT_HIGH_RISK / AUS_CONFLICT_REVIEW (CONTRADICTS) on
               conflict and AUS_ACCORD_AGREEMENT (SUPPORTS) on agreement; reconciles
               against the upstream UNDERWRITING outcome, not the routing outcome.
               output_payload.aus_reconciliation on every decision. ADVISORY —
               proposed_outcome untouched; no DU response -> reconciliation_required
               =False; meridian has no DU data so 16/16 holds.
  RA-AUS-C     SHIPPED: LP (Loan Prospector / Loan Product Advisor) parser —
               Freddie's AUS. core/aus/lp_parser.py:LPParser mirrors the DUParser
               shape (Accept/Caution/Ineligible/Out of Scope + A+/A/B/C/D/E grade
               + risk scale -> exceptional..not_eligible; feedbacks + conditions).
               LP Caution = ELIGIBLE-but-not-accept (DU Refer/Eligible analogue),
               NEVER conflated with Refer/Ineligible. Parsed dict exposes `approve`
               as an alias for `accept` so AUSReconciliationEngine consumes LP
               identically to DU (engine UNCHANGED). store.ingest_lp_response upserts
               under aus_system='LP' (feedbacks stored in the shared `findings`
               JSONB; full dict in parsed_response — no `feedbacks` column).
               Enricher attaches BOTH aus_result (DU) + aus_result_lp (LP);
               approval_routing reconciles against the MORE CONSERVATIVE of the two
               (LP Caution not masked by DU Approve). ADVISORY — proposed_outcome
               untouched; meridian has no LP data so 16/16 holds.
               -> AUS phase RA-AUS-A/B/C COMPLETE: DU + LP both parsed, stored,
               reconciled with Accord end-to-end.
  RA-5/A/B     Policy transparency
  RA-7A        SHIPPED: ATR 8-factor checklist + QM classifier (12 CFR 1026.43)
               in compliance_check. Thresholds from regulatory_rules via the
               enricher (atr_required_factors=8, QM safe-harbor DTI=43,
               points/fees=3%, HPML=150bps); factors from entity_states.
               ADVISORY only — output_payload + SUPPORTS/CONTRADICTS signals,
               proposed_outcome untouched (16/16 holds).
  RA-7B        SHIPPED: Adverse Action Notice engine (ECOA / Reg B §1002.9).
               underwriting_decision, on a DECLINE only, emits notice data into
               output_payload.adverse_action: HMDA denial codes (Reg C 1–9)
               mapped from the blocking upstream decisions, 30-day deadline from
               the catalogue ("Adverse Action Notice Deadline"), ECOA rights
               statement. Builds on the existing core/audit/adverse_action.py
               (added HMDA codes + catalogue-driven days_max). New
               adverse_action_notices table + population job. ADVISORY —
               proposed_outcome untouched (16/16 holds).
  RA-7C        SHIPPED: HMDA LAR record generator (Reg C, 12 CFR Part 1003).
               underwriting_decision emits a per-application LAR record into
               output_payload.hmda_lar: action_taken (1=originated/2=approved/
               3=denied/...), loan data, denial_reasons (from RA-7B), and
               applicant demographic data (ethnicity/race/sex/age) COLLECTED +
               REPORTED but NEVER used in any decision (ECOA). Sourced from the
               existing vw_hmda_reporting view + entity_states via the enricher.
               New hmda_lar table + population job. Advisory — 16/16 holds.
               -> Full compliance phase RA-7A/B/C complete.
  Stage 2 audit Full production readiness
```

See **Known Gaps** at the bottom for the Stage-1 deferred items.

---

## Never Do

```
❌ Hardcode any lending value in Python
❌ Reference core/personas/ (does not exist — use domains/lending/personas/)
❌ Use add_flag() — use make_signal()
❌ Import evaluate_meridian_scenarios.py — subprocess only
❌ Make a persona or domain resolver async
❌ Write resolver output to DB — return to the persona only
❌ Use platform_guardrails as a rule source
❌ Call rule_loader inside a persona — the enricher does this
❌ Create a Python constant as a "temporary" fallback
❌ Skip reading this file before writing any code
```

---

## Known Gaps (Stage 1 Audit — deferred to post-demo)

From RA-6A (all 8 checks PASS; these are documented, not blocking the demo):

```
(a) LIEN_META: 5 newly-wired entries carry a redundant blocks_closing=True
    (ignored once the type is catalogued). Harmless. Cleanup in a post-demo pass.

(b) Income resolver classes (RentalIncomeResolver / SelfEmployedResolver) are
    not directly wired to any persona. SC12 rental income flows via the
    income_verification own path. Confirm/complete wiring post-demo.

(c) CLOSED (Gap c fix, f35ae33). asset_resolver no longer hardcodes the SE
    business-ownership cutoffs/factors — all 4 values are catalogue-driven via
    the RA-4A property pattern. ACTUAL live rows (the earlier "Majority/Full/
    Partial = 25/100/50" note was wrong; verified by query):
      Self-Employed Business Ownership Sole Threshold     = 100  (cutoff, NEW)
      Self-Employed Business Ownership Majority Threshold =  50  (cutoff, NEW)
      Self-Employed Full Business Asset Credit            = 100  (factor /100 = 1.00)
      Self-Employed Partial Business Asset Credit         =  50  (factor /100 = 0.50)
    The two cutoffs had no catalogue backing (only "Business Ownership Majority"
    =25, a different SE-definition threshold) so they were seeded fresh (Fannie
    B3-3.4-02) rather than repurposing the 25% row (which would have moved the
    gate 50→25 and changed behavior). Value-equivalent — 16/16 holds. This was
    the LAST hardcoded lending value; RULE 1 now has ZERO exceptions.

(d) CLOSED (OB-A, commit 1c7b2b4). student_loan_deferred_rate_pct updated
    1.0 -> 0.5 per current Fannie B3-6-05 (0.5% floor for $0/unreported deferred
    payments). Catalogue-driven (tradeline_analyzer reads value/100); 0 meridian
    apps carry student-loan tradelines so 16/16 held.

(e) months_remaining_exclusion is wired (RA-4J) but unreachable by the 16
    Meridian scenarios (no app carries months_remaining data).

(f) approval_routing conflict→manual-review = advisory only. ROUTE_CONFLICT_PRESENT
    and the RA-AUS-B reconciliation signals (AUS_CONFLICT_HIGH_RISK /
    AUS_CONFLICT_REVIEW / AUS_ACCORD_AGREEMENT) surface conflicts as advisory
    signals + a detailed reconciliation surface (output_payload.aus_reconciliation:
    risk tier, explanation, UW action, HMDA implication) — but do NOT move the
    routing outcome. Conflicts SHOULD route to manual review (not auto-approve):
    that OUTCOME change is deliberate future work, out of the advisory-only scope.

(g) CLOSED (CI-B). The eval was already concurrent (RA-P0-B/IN-B —
    asyncio.gather + semaphore, --concurrency=N default 4). The residual hang
    was an UNBOUNDED await on a degraded RDS link, now bounded by
    asyncio.wait_for(timeout=SCENARIO_TIMEOUT, default 30s) around _process_one:
    a stuck decision becomes a TIMEOUT error, the run continues. Remaining
    latency is network RTT to live RDS, not a code structure issue.

(h) ~1283 superseded decision_outputs versions carry NULL bundle_id (from
    network-degraded RA-PERSONA evals — RA-3F bundle write is best-effort by
    design). Current decisions: 0 NULL (the audit/replay invariant holds).
    Self-heals on re-run. Optional cleanup (backfill/prune) post-demo.

(i) CLOSED (RA-EX-F). All three tiers now extract for real: Tier 1 pdfplumber
    (W2/paystub/URLA — boto3 is installed but no AWS creds, so pdfplumber is the
    local stand-in; swap _extract_text for Textract when creds land), Tier 2
    Claude Vision, Tier 3 regex (flood/HOI/rate-lock/credit/bank-statement).
    Field-manifest dry-run on a throwaway tenant: 12/17 golden scalar fields
    derived from real extraction; remaining nulls are absent inputs, not
    extractor gaps. Patterns run on original text + IGNORECASE (the lower-case +
    [A-Z] approach would drop capitalized captures like employer names).
```

Also noted (persona-layer, separate from the resolver catalogue-isation):
asset_verification `LARGE_DEPOSIT_THRESHOLD`/`MIN_RESERVES_MONTHS` and
fraud_screening fraud-score constants are persona BOUNDARY thresholds (SC15
depends on them) — a distinct de-hardcoding pass; and only the shared
income-documentation confidence floor (0.75) backs evidence signals across all
domains (per-domain thresholds are a possible future seed).

---

*Accord Decision OS · docs/ARCHITECTURE.md · permanent flow reference (RA-0-ARCH).
Update this file only when the system DESIGN changes; build state lives in CONTEXT.md.*
