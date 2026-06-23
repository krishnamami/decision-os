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
  core/income/      rental_income_resolver.py + self_employed_resolver.py (RA-4G pending)
  core/compliance/  rule_validator.py                                  (RA-4E ✅)

Seed scripts:    scripts/compliance/
Verify gate:     scripts/verify_catalogue_ready.py   (59/59 exit 0)
Evaluate:        scripts/evaluate_meridian_scenarios.py
                 ⚠️ DO NOT IMPORT — runs asyncio.run(main()) at module level
                    (no __main__ guard). Call as a subprocess only.
Bundles:         persona_bundles table (RA-3F — done; scripts/migrations/create_persona_bundles.sql)
```

---

## What Each Table Holds

```
document_index            Raw extracted fields from each document
entity_states             Actual values mapped from documents (one row per app)
fact_nodes                Qualified evidence with confidence + method
agency_guidelines         Fannie/FHA/VA/Freddie published rules (81 rows)
regulatory_rules          Federal law (CFPB/HUD/VA) (23 rows)
overlay_rules             Lender credit policy — Meridian + Summit (6 rows)
decision_outputs          What each persona decided (outcome + output_payload)
decision_trace            Immutable audit record per decision
persona_bundles           Frozen snapshot of what each persona saw (RA-3F — done)
fraud_signals             Fraud detector outputs (IncomeMismatchDetector etc.)
loan_condition_instances  Conditions generated by personas
```

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

---

## Catalogue State (verified 2026-06-22)

```
agency_guidelines:   81 rows  (Fannie 58 / FHA 13 / VA 8 / Freddie 2)
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
  RA-P0/A/B    Pipeline + parallel runner
  RA-EX/A-F    Extraction SHIPPED: audit (A), golden_record builder+writer (B),
               gap-field derivation + demo seeding (C), pipeline + Claude Vision
               extractor (D), upload trigger wired (E), real Tier-1 pdfplumber +
               Tier-3 regex extractors + field manifest (F). Live path:
               POST /api/accord/documents/upload -> ingest_document ->
               route_extraction (3 tiers, all real) -> document_index ->
               golden_record -> entity_states. Meridian is hard-refused (seeded
               fixtures). Tier 1 = pdfplumber (no AWS creds; swap to Textract
               later); Tier 2 = Claude Vision; Tier 3 = regex over text.
  RA-AUS/A/B/C AUS integration (DU + LP)
  RA-5/A/B     Policy transparency
  RA-7/A/B/C   Compliance (ATR/QM + adverse action + HMDA)
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

(c) SE business-ownership: asset_resolver.py hardcodes biz_pct >= 100/50
    (factor 1.00/0.50/0.00). The catalogue rows (Self-Employed Business
    Ownership Majority/Full/Partial = 25/100/50) are seeded but NOT read.
    Fix: wire the resolver to read them from catalogue. (This is the one
    remaining hardcoded lending-value site found by CHECK 1.)

(d) Student-loan deferred rate: catalogue seeds 1.0%. Current Fannie B3-6-05
    uses a 0.5% floor for $0 / unreported payments. Review before production.

(e) months_remaining_exclusion is wired (RA-4J) but unreachable by the 16
    Meridian scenarios (no app carries months_remaining data).

(f) approval_routing conflict preference: ROUTE_CONFLICT_PRESENT is advisory
    only. Conflicts should route to manual review (not auto-approve) — a
    deliberate future OUTCOME change, out of the advisory-only scope.

(g) Eval runs the 16 apps sequentially (~165s nominal). asyncio.gather +
    semaphore(5) -> ~40s. RA-P0-B backlog.

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
