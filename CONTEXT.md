# Decision OS — Project Context

> For the full product spec — vision, architecture, diagrams, build sequence,
> and coding standards — read [docs/PRD.md](docs/PRD.md) first.
> This file tracks session history and live build status only.

---

## What this is

Decision OS is a platform for structured, governed, AI-augmented decisioning.
Any business brings their domain, maps their decisions (independent and dependent),
connects their data sources, and the platform builds context, evaluates policy,
runs AI agents, enforces governance, and produces a complete explainable trace
for every decision made.

Every decision has an owner, a boundary, a mode, and a trace.
No decision is a black box. No action happens without a policy. No context is untracked.

---

## Current domain: Lending (mortgage)

13 decisions covering the full mortgage cycle (12 original + asset_verification, Session 16).
Source of truth: `domains/lending/decisions.yaml`
Vocabulary + ontology: `domains/lending/knowledge_base.json`

---

## Tech stack

```
Backend:   Python 3.11 + FastAPI
Models:    Pydantic v2
Database:  Postgres (Supabase managed)
Cache:     Redis
Blob:      S3-compatible
Frontend:  Next.js + Tailwind
AI:        Anthropic Claude via API
Deploy:    Docker Compose → Railway / Render
```

---

## ACTUAL BUILD STATUS — verified against repo

Files confirmed in repo as of May 2026:

```
✅  domains/lending/decisions.yaml       12 decisions, boundaries, modes, hard rules,
                                         atomic_tool, context_window_days, reflection block
✅  domains/lending/knowledge_base.json  vocabulary, synonyms, ontology, dependency graph
✅  core/semantic_layer/__init__.py
✅  core/semantic_layer/resolver.py      synonym resolver, term classifier, threshold lookup
✅  core/policy_engine/evaluator.py      boundary evaluator + all 8 hard rules enforced
✅  core/trace/__init__.py
✅  core/trace/trace_schema.py           WorkJournalEntry + DecisionTrace Pydantic models
✅  core/trace/critic_agent.py           independent critic, SelfReviewError enforcement
✅  core/normalizer/__init__.py
✅  core/normalizer/models.py            13 typed event models, 8 entity models,
                                         normalize_event() + EVENT_REGISTRY
✅  core/ontology/__init__.py
✅  core/ontology/object_types.py        8 lending object types (Applicant, Application,
                                         Property, Loan, CreditProfile, IncomeProfile,
                                         FraudProfile, ComplianceRecord) with semantic
                                         links, cardinality, decisions_that_read_it,
                                         to_context_bundle() projection
✅  core/context_store/__init__.py
✅  core/context_store/base.py           ContextStore abstract + ContextRecord + Lineage
                                         + Snapshot. no_context_without_lineage enforced.
✅  core/context_store/lending.py        LendingContextStore + DecisionScopedStore.
                                         Risk-driven TTL policy (low=1h, med=24h, high=7d).
✅  core/context_store/redis_cache.py    RedisHotCache + InMemoryHotCache. Decision-scoped
                                         keys so leaky reads can't cross decisions.
✅  core/context_store/postgres_store.py PostgresDurableStore + InMemoryDurableStore.
                                         Append-only with version bump, supersession
                                         chain, tombstone semantics, point-in-time reads.
✅  core/context_store/schema.sql        context_records + context_snapshots tables.
                                         Partial unique index for the active row,
                                         version uniqueness per scope, self-FK on
                                         supersession chain.
✅  core/context_store/context_builder.py ContextBuilder + ContextBundle. Resolves
                                         readable object types per decision, snapshots
                                         the store, projects through ontology to enforce
                                         no_agent_without_permissions at the data layer.
✅  core/connectors/__init__.py
✅  core/connectors/base.py              BaseConnector + PushConnector (source initiates)
                                         + PullConnector (we initiate). EventSink protocol,
                                         ConnectorHealth states, single emit() pipeline that
                                         routes every adapter through normalize_event().
✅  core/connectors/mock_csv.py          Push reference: file-drop / CSV adapter with cell
                                         coercion. Same path exercises seed_events fixtures
                                         and real partner drops.
✅  core/connectors/mock_http.py         Pull reference: RecordedResponse fixtures keyed by
                                         query so 'Experian returned this XML for X' is
                                         deterministic across runs.
✅  core/decision_agents/__init__.py
✅  core/decision_agents/base.py         DecisionAgent ABC + AgentReasoning. Subclasses only
                                         own reason(); cannot touch context store, policy,
                                         trace, or queue directly.
✅  core/decision_agents/atomic_tool.py  AtomicTool.run() — the single bundled call from
                                         PRD §7. context_build → policy pre-check →
                                         agent.reason → final policy_check (against agent's
                                         computed values) → critic (medium+ risk) →
                                         trace_write → mode_route. Policy engine has the
                                         last word; LLM cannot decompose the steps.
✅  core/decision_agents/mode_router.py  RouteAction (AUTO_WRITEBACK / QUEUE_HUMAN /
                                         SHADOW_RECORD / BLOCK), HumanQueue protocol +
                                         InMemoryHumanQueue. Decision-record writeback
                                         through DecisionScopedStore.
✅  core/execution/__init__.py
✅  core/execution/dag_executor.py       Walks execution_order in waves (parallel within,
                                         sequential across). InMemoryEventBus. Enforces
                                         fraud_block_stops_pipeline (short-circuits all
                                         downstream waves) and skips dependents whose
                                         upstreams aren't satisfied.
✅  core/trace/trace_writer.py           TraceWriter Protocol + InMemoryTraceWriter.
                                         Append-only contract; enforced by raising on
                                         duplicate trace_id. Session 5 added
                                         attach_human_review() — the one allowed mutation,
                                         used by POST /override to record a human review
                                         on an immutable trace.
✅  core/trace/reflection.py             STEP 8. AgentLearning model + LearningStore
                                         protocol + InMemoryLearningStore +
                                         ReflectionService.capture(trace, review) →
                                         recall(agent, decision, similarity_tags).
                                         365-day retention from decisions.yaml.
                                         derive_similarity_tags() helper extracts tags
                                         from a trace's output_payload.
✅  core/policy_engine/loader.py         DecisionsSpec — single load+validate path for
                                         decisions.yaml. Validates owner_team
                                         (no_decision_without_owner), mode/risk enum
                                         values, depends_on integrity, execution_order
                                         references, and known hard_rules. Smoke-tested
                                         against the live decisions.yaml. ContextBuilder
                                         and PolicyEvaluator still accept raw dicts so
                                         existing call sites are unchanged.
✅  api/__init__.py
✅  api/main.py                          create_app(platform=...) factory. Mounts the
                                         router on FastAPI, exposes /health.
✅  api/deps.py                          Platform container — assembles
                                         LendingContextStore + ContextBuilder +
                                         PolicyEvaluator + AtomicTool + CriticAgent +
                                         DAGExecutor + ReflectionService + EventLog +
                                         EntityHydrator + sink. agents and connectors
                                         registries. _default_resolver walks the
                                         InMemoryDurableStore's record list.
✅  api/ingest.py                        EventLog (append-only buffer) +
                                         EntityHydrator. Hydrator maps 8 event types
                                         (lead, application, kyc, income_declared,
                                         payroll, credit, fraud, property) onto 6
                                         ontology entities under SHARED scope.
                                         income_declared + payroll merge into one
                                         IncomeProfile per (applicant, application).
                                         build_event_sink() composes log + hydrator
                                         into one EventSink.
✅  api/routes.py                        POST /events, POST /override, POST
                                         /connectors/webhook/{source}, GET
                                         /decisions/{application_id}/{decision_id},
                                         GET /trace/{trace_id}, GET
                                         /applications/{id}/traces, POST
                                         /applications/{id}/run (E2E helper).
✅  domains/__init__.py
✅  domains/lending/__init__.py
✅  domains/lending/personas/__init__.py LENDING_PERSONA_CLASSES (decision_id → class),
                                         build_lending_personas(use_anthropic=False),
                                         register_with_platform(platform).
✅  domains/lending/personas/base.py     LendingPersona base + Anthropic mixin.
                                         Deterministic offline path computes the
                                         canonical output_payload (intent_score, dti,
                                         ltv, fraud_score, ...). LLM path is opt-in
                                         (use_anthropic=True), uses cache_control on
                                         the system block, falls back to offline when
                                         no API key. Helpers: first_object,
                                         latest_object, upstream_payload, make_signal.
✅  domains/lending/personas/{12 files}  One persona per decision_id:
                                           lead_scoring        → LeadQualificationAgent
                                           income_verification → IncomeVerificationAgent
                                           credit_assessment   → CreditRiskAgent
                                           fraud_screening     → FraudDetectionAgent
                                           compliance_check    → ComplianceAgent
                                           dti_calculation     → DTICalculationAgent
                                           ltv_assessment      → LTVAssessmentAgent
                                           product_eligibility → ProductEligibilityAgent
                                           rate_pricing        → PricingAgent
                                           underwriting_decision → SeniorUnderwritingAgent
                                           approval_routing    → WorkflowRoutingAgent
                                           closing_readiness   → ClosingAgent
✅  domains/lending/seed_events/__init__.py
                                         SCENARIOS manifest + csv_connector(scenario,
                                         sink), http_connector(scenario, sink),
                                         load_extra_entities(scenario).
✅  domains/lending/seed_events/runner.py
                                         run_scenario(platform, scenario) — full E2E
                                         replay: pushes events.csv through
                                         MockCSVConnector.listen(), pulls
                                         credit + fraud through MockHTTPConnector.fetch(),
                                         seeds Loan + ComplianceRecord direct entities,
                                         runs the DAG.
✅  domains/lending/seed_events/happy_path/
                                         events.csv + bureau_responses.json +
                                         entities.json. 12/12 decisions complete.
✅  domains/lending/seed_events/fraud_block/
                                         watchlist_match=True →
                                         fraud_block_stops_pipeline halts pipeline,
                                         7 dependents skipped.
✅  domains/lending/seed_events/contamination/
                                         self_employed without payroll →
                                         income_verification confidence 0.50, ESCALATE.
                                         dti_calculation BLOCKs via
                                         contamination_guard.reject_if_upstream_confidence_below.
✅  domains/lending/seed_events/compliance_block/
                                         fair_lending_violation=True → compliance_check
                                         BLOCK; closing_readiness BLOCKs via
                                         compliance_block_stops_closing.
✅  ui/__init__.py                       STEP 11 — UI package, exports router + templates.
✅  ui/views.py                          View-model helpers: list_applications(),
                                         application_detail(), decision_detail(),
                                         queue_view(). OUTCOME_STYLES palette.
                                         Jinja filters: currency, pct, confidence, dt.
                                         Reads in-memory durable store + trace writer
                                         + human queue + learning store directly via
                                         the Platform.
✅  ui/routes.py                         5 GET routes (/, /ui/applications/{id},
                                         /ui/applications/{id}/decisions/{decision},
                                         /ui/queue) + POST override with HTMX swap
                                         (returns _override_result partial on success,
                                         _override_card partial with inline error on
                                         same-outcome submission).
✅  ui/templates/base.html               Layout. Tailwind via CDN
                                         (cdn.tailwindcss.com), HTMX via CDN
                                         (unpkg.com/htmx.org@1.9.12). Nav: Applications
                                         | Human queue | Health | API docs.
✅  ui/templates/index.html              Application list. Outcome counts as colored
                                         dots, status pill (halted / pending review /
                                         complete).
✅  ui/templates/application.html        DAG visualization. Decisions grouped by
                                         execution_order waves; each card color-coded
                                         by outcome with persona, mode, risk,
                                         confidence, matched_clause. Click → decision
                                         detail.
✅  ui/templates/decision.html           Three-column layout. Left: bundle objects
                                         (per ObjectType, projected through
                                         to_context_bundle), upstream outputs (with
                                         click-through), boundary clauses (matched
                                         clause labelled). Right: work journal
                                         (hypothesis / conclusion / confidence_basis /
                                         summary), signals (direction-coded dots),
                                         contradictions, policy outcome + reasons,
                                         critic review, output payload, override
                                         workbench, recalled lessons.
✅  ui/templates/_override_card.html     Three states: human_review attached (locked-in
                                         display) | queueable outcome (form with
                                         radios for new_outcome, reviewer_role,
                                         reviewer_id, override_reason,
                                         override_reason_code) | auto-executed
                                         (no review needed banner). HTMX target:
                                         #override-card.
✅  ui/templates/_override_result.html   HTMX swap target after successful override.
                                         Renders attached review + AgentLearning with
                                         similarity tags.
✅  ui/templates/queue.html              Cross-application queue table.
✅  api/main.py                          Updated for STEP 11. Added asynccontextmanager
                                         lifespan that runs _bootstrap_demo (registers
                                         all 12 personas + replays 4 seed scenarios)
                                         when seed_demo_data=True. Added mount_ui flag
                                         (default True) for the ui router. Added
                                         _known_application_ids() helper used by
                                         /health. get_app() defaults to
                                         seed_demo_data=True so uvicorn boots with
                                         data.
✅  docs/PRD.md                          v0.6 — §17 file-structure block reconciled,
                                         §19 build sequence rewritten to mark
                                         STEPS 1-10 done and shift STEP 11+ to
                                         UI / outcome_tracker / simulation / tests.
                                         §20 resume prompt rewritten.
✅  docker-compose.yml                   Postgres 16 + Redis 7 services with healthchecks.
✅  requirements.txt                     pydantic v2, redis, asyncpg, PyYAML, fastapi,
                                         uvicorn, anthropic, structlog, httpx, pytest,
                                         pytest-asyncio, python-dotenv (Session 12).
✅  README.md
✅  core/edms_store.py                   STEP 12. EdmsContextStore — reads
                                         vw_<decision_id>_context views into
                                         ContextBundle-shaped EdmsSnapshot. Lazy
                                         asyncpg pool tuned for batch (Session 12).
                                         FULL_ROW projection for
                                         underwriting_decision view.
✅  core/decision_store.py               STEP 12. DecisionStore — append-only
                                         writes to decision_outputs +
                                         decision_timeline; version + supersession
                                         per (application_id, decision_id,
                                         tenant_id). get_upstream, get_pending,
                                         get_pipeline_status read helpers.
✅  core/cron/runner.py                  STEP 12. PersonaRunner — wave-by-wave
                                         executor (5 waves) that reads EDMS,
                                         runs persona._compute_offline, writes
                                         decision_outputs + decision_timeline.
                                         Connection resilience (Session 12):
                                         per-app try/except → _reset_pools() on
                                         transient errors → retry once; pools
                                         cycle every 500 rows.
                                         CLI: python -m core.cron.runner [persona].
✅  ui/edms_routes.py                    STEP 12. Persona-centric /workbench —
                                         11 personas grouped by stage; 4 tabs
                                         (queue / completed / auto / analytics);
                                         pipeline / audit / governance pages;
                                         approve + override POST writes through
                                         to decision_outputs + decision_timeline.
                                         Date range filter (Session 12) on every
                                         persona page.
✅  ui/edms_templates/                   10 Jinja2 templates: base_workbench,
                                         persona_home, persona_workbench,
                                         review_detail, completed_detail,
                                         pipeline_dashboard, pipeline_app,
                                         audit_dashboard, audit_app, governance.
                                         Tailwind CDN + Tabler Icons CDN.
✅  scripts/_verify_edms_writes.py       Session 12 write-side smoke — counts
                                         decision_outputs + decision_timeline
                                         rows for a given decision and dumps the
                                         five most recent.
```

Also: in Session 5 the Applicant ObjectType was extended with
lead-stage fields (channel, lead_source, utm_params, session_behavior,
prior_inquiries, ambiguous_identity, identity_match_confidence,
applicant_dispute_flag, preferred_channel) so lead_scoring's persona
can read them through to_context_bundle's projection. lead_scoring
runs before an Application exists, so the lead data lives on the
Applicant until the ApplicationSubmittedEvent fires.

Files not yet built (next up):

```
⬜  tests/                                STEP 14. Persistent test suite — only
                                          context_store has scaffolding today;
                                          cover api/, personas/, seed_events,
                                          ui/ view-models, simulation/replayer.
⬜  core/trace/outcome_tracker.py        STEP 12. Post-decision outcome scoring +
                                          live A/B comparisons.
⬜  core/semantic_layer/flow.py          Event → entity → metric → signal mapper.
                                          Currently the EntityHydrator in
                                          api/ingest.py covers the event → entity
                                          mapping; flow.py would add the
                                          entity → metric → signal layer.
⬜  .env.example
```

```
✅  core/simulation/__init__.py          STEP 13 DONE.
✅  core/simulation/replayer.py          Replayer + ReplayResult /
                                          ReplayComparison / DecisionComparison.
                                          _ReadOnlyAtTimeShim wraps the live
                                          durable so reads pin to replay_at and
                                          writes raise; _ShadowModeRouter blocks
                                          all writeback (auto + BLOCK both go
                                          to SHADOW_RECORD). Two entry points:
                                          replay_application(persona_overrides)
                                          and replay_decision(persona_override).
                                          Replayer.from_platform() avoids the
                                          core->api import direction; takes the
                                          components directly otherwise.
✅  scripts/smoke_replayer.py            End-to-end smoke for STEP 13: as-is
                                          parity, persona swap, validation,
                                          full-DAG override; asserts live
                                          trace_writer + durable fingerprint
                                          unchanged after every replay.
```

---

## Key architectural decisions (locked)

```
Atomic tool pattern
  context_build + policy_check + decision bundled into one tool call per agent.
  LLM reasons within boundaries. Code enforces hard rules. Cannot be called separately.

Reflection loop
  Every human override → AgentLearning record → fed back to same agent next similar event.
  System improves without model retraining.

WorkJournalEntry trace
  Not a log. A structured work journal:
  hypothesis_tested | signals_evaluated | contradictions_found |
  conclusion | confidence_basis | human_readable_summary
  Independent critic reviews medium+ risk before execution.
  SelfReviewError blocks agent from critiquing its own output.

context_window_days
  Each decision loads only history within its defined window.
  Prevents context contamination from irrelevant history.
  Defined per decision in decisions.yaml.

Contamination guard
  Dependent decisions refuse to run if upstream confidence is below threshold
  or any upstream decision is blocked.
  upstream_block_propagates_to_dependents is a hard rule.

WHO vs WHAT-NOW (ontology)
  Applicant = WHO — persists across time and applications.
  Application = WHAT THEY ARE ASKING FOR NOW — lifecycle-bound, new each request.
  CreditProfile, IncomeProfile, FraudProfile → belong to Applicant.
  DTI, LTV, product eligibility, underwriting → belong to Application.
  Re-application: same Applicant, new Application, fresh decisions,
  Applicant profiles carried forward within retention window.

Shared-vs-scoped writes in the context store
  Two write conventions live side-by-side in LendingContextStore:
    1. Entity records (Applicant, Application, Property, Loan, CreditProfile,
       IncomeProfile, FraudProfile, ComplianceRecord) → write to the SHARED
       scope, i.e. lineage.decision_id = None. Snapshot reads them via the
       shared scope so every decision sees the same world.
    2. Decision outputs → write under entity_type = "decision",
       entity_id = f"{application_id}:{decision_id}", and
       lineage.decision_id = decision_id. Snapshot reads these via
       upstream_decision_ids so a dependent decision pulls only its
       declared upstream outputs (no peeking at sibling decisions).
  Use DecisionScopedStore.set() only for decision outputs, not entities.
  See core/context_store/lending.py:snapshot() for the read paths.

Connector layering — push vs pull (STEP 4 design)
  One canonical event vocabulary lives in core/normalizer/models.py — the
  interlingua every source converges on. core/connectors/ holds N adapters,
  one per source, each doing source-specific parsing. Adapters split into
  two base classes:

    PushConnector   — source initiates, we react.
                      Examples: borrower portal webhooks, e-sign callbacks,
                                payroll provider events, file drops.
                      Method: listen() — long-running consumer.

    PullConnector   — we initiate, source responds.
                      Examples: bureau pulls (Experian/TransUnion/Equifax),
                                Plaid/Argyle income, AVM lookups, title search,
                                The Work Number.
                      Methods: fetch(query) → BaseEvent, poll(schedule).

  Both feed normalize_event(raw_dict) → typed BaseEvent → context store.
  The normalizer is source-agnostic; only the adapter knows the source's
  shape and request semantics.

  Pull patterns need request↔response correlation. STEP 4 adds:
    BaseEvent.correlation_id : Optional[UUID]   # links request → response
    BaseEvent.request_id     : Optional[UUID]   # the outbound call id

  Simulation strategy:
    Push sources → JSON/CSV fixtures in domains/lending/seed_events/ replayed
                   through the adapter's emit() path.
    Pull sources → recorded response fixtures + a mock HTTP server (respx /
                   vcrpy / a stub) so "Experian returned this XML for X" is
                   deterministic across runs. Each PullConnector ships a
                   MockClient variant for tests.
```

---

## Session history

### Session 20 — June 20 2026 (cont.)

**Theme:** Start **Phase 13 Explanation Engine (EX2-A)** — turn the decision
trace into audience-specific human-readable narratives. `decision-os` `main`.

**Commits — decision-os (pushed to `main`):**
  - `b0117ac` — feat(explanation): AI explanation engine (EX2-A).

**1. EX2-A — AI explanation engine.**
   - `core/explanation/ExplanationEngine.explain(app_id, tenant_id, audience)`:
     loads `decision_trace` (TR-A/TR-B) + open conditions + fraud_signals, builds
     a structured summary, calls Claude with an audience-specific prompt
     (loan_officer / underwriter / regulator), and falls back to a deterministic
     template. AsyncAnthropic, awaited; model from `CLAUDE_MODEL_ID` (default
     `claude-sonnet-4-6`, the codebase persona convention).
   - API: `GET /api/accord/trace/{app_id}/explain?audience=...` (Accord
     convention: JWT tenant, _require_db/_get_pool).
   - **Consulted the claude-api skill before writing** (LLM-shaped Anthropic code).
   - Deviations from spec (runtime/data-driven, all flagged):
     - Client is **lazy + key-gated** — the spec's `Anthropic(api_key=None)` raises
       in __init__ with no key, breaking even the fallback. Local-first: with no
       `ANTHROPIC_API_KEY` the engine returns template narratives.
     - `evidence_trace` is **flat by fact_type** (qualifying_income /
       verified_assets / governing_credit_score / employment_continuity), not
       nested by income/assets/credit → `_build_summary` adapted.
     - **Omitted** the `decision_reviewed` audit write the spec did on every
       render — an AI explanation isn't a human review; logging it would corrupt
       the regulator audit trail.
   - **Local verification = template path only** (no API key in env): SC07
     escalate, SC09 block; loan_officer + regulator narratives render. The Claude
     path is wired per the SDK reference but unexercised until a key is set.
   Next: **EX2-B** (explanation workbench UI).

### Session 19 — June 20 2026 (cont.)

**Theme:** **Decision Trace — Phase 12 COMPLETE (TR-A → TR-C)**: the immutable,
regulator-facing record that reconstructs any decision from the trace alone.
Plus the **title_assessment cron wiring fix** (the IN-D open item from Session
18) and the stale persona-count test bump. All against the live RDS;
`decision-os` `main`. Score held **15/16**.

**Commits — decision-os (pushed to `main`):**
  - `b343721` — feat(trace): decision trace schema + builder (TR-A).
  - `98b5b22` — fix(cron): add title_assessment to wave 0 in cron runner.
  - `25e3e06` — test(personas): persona registry count 13 → 15.
  - `269d415` — feat(trace): policy trace (TR-B).
  - `c9ef100` — feat(trace): trace API + export endpoints (TR-C).

**1. TR-A — decision trace schema + builder.**
   - `decision_trace` (immutable per-decision record: input_snapshot,
     persona_traces, policy_trace, evidence_trace, conditions_snapshot,
     final_outcome, loan data, audit fields, superseded_by) + `decision_audit_log`
     (append-only, 12 action types). RLS; partial-unique on decision_id.
   - `DecisionTraceBuilder` assembles from decision_outputs (per-decision rows —
     **no `persona_outputs` col, no `context_snapshot` table**), entity_states,
     fact_nodes, loan_condition_instances, fraud_signals. Headline =
     `underwriting_decision`. All 16 traced; SC09 captures the fraud signal in
     input_snapshot; idempotent (one trace per decision generation).
   - Spec fixes: `final_outcome VARCHAR(20)→(30)` ('approve_with_conditions' is
     23 chars); reads `confidence`/`reasoning.summary` (no outcome_reason col);
     property_type from loan_terms.urla.
   - NB: trace `final_outcome` follows underwriting_decision (block for 13/16) —
     distinct from the per-scenario KEY decisions the 15/16 evaluate checks.

**2. title_assessment cron wiring (IN-D resolved).**
   - TL-A..TL-E were built but title_assessment was **never wired into the
     runner** (0 decision rows). Adding it needed **three** registries, not just
     WAVE_CONFIG (the other two would crash the runner): WAVE_CONFIG/WAVES[0]/
     DECISION_DEFAULTS (runner), LENDING_PERSONA_CLASSES (personas/__init__ — else
     `_get_agent` fails), and VIEW_MAPPINGS['title_assessment'] (edms_store — else
     `snapshot()` raises). Now 16 decision rows; **SC16 generates
     [TITLE_IRS_LIEN, TITLE_HOA_LIEN]**. Title is a leaf → 15/16 preserved.
   - Side note: title escalates on 15/16 (title_clear unset on most loans — data
     seeding, not wiring). Persona count → 15; the two stale `==13` count tests
     bumped to 15 (had been red since S16/S18).

**3. TR-B — policy trace.**
   - `PolicyTraceBuilder` populates the policy_trace JSONB: agency_guidelines
     (va/fha/fannie/freddie), tenant overlay_rules, 15 platform_guardrails;
     evaluates dti/ltv/credit against the **effective limit** (stricter of agency
     baseline + overlay), surfacing both. All 16 updated. SC07 3/3 pass — bound by
     meridian overlays (dti 43 / ltv 95 / credit 660), not just fannie.
   - Spec fixes: overlay_rules/platform_guardrails real columns differ from the
     draft; entity_states.loan_type read from loan_terms.urla; used real overlays
     for effective limits (more accurate than the draft's hardcoded fannie 97/620).

**4. TR-C — trace API + export.**
   - 5 endpoints under `/api/accord/trace/` (JWT tenant, _require_db/_get_pool —
     Accord convention, not the spec's app.state.pool): GET full / summary /
     export / audit, POST review. Export bundles input + evidence + policy +
     persona + conditions + fraud + audit (repurchase / CFPB). JSON-safe
     serialization; review in a txn with 404 pre-check. 15 routers mounted;
     policy_trace populated 16/16.
   - **JSON only** (the title said "PDF/JSON" but body specs JSON; a `format`
     param is echoed in metadata as a hook — no PDF renderer added).

### Session 18 — June 20 2026

**Theme:** Resolver subsystems end-to-end — finish **Title conditions (TL-E)**,
build the full **Credit Resolver (Phase 3, CR-A → CR-E)**, **Asset Engine
(Phase 4, AV-A → AV-E)**, **Fraud Engine (Phase 5, FR-A → FR-E)**, **Collateral
Engine (Phase 6, CO-A → CO-C)**, and **Conditions Engine (Phase 11, CN-A →
CN-C)**. All work against the live EDMS RDS; commits to `decision-os` `main`.
Score held at **15/16** throughout (SC12 the one known miss — rental income /
Schedule E not built yet). `conditions_library` grew **15 → 44 rows**; new
`loan_condition_instances` now tracks live conditions (5 across SC07/08/09/15
after the funds-to-close data cleanup).

**Commits — decision-os (pushed to `main`):**
  - `1c8bb47` — feat(conditions): `conditions_library` table + 15 title conditions (TL-E).
  - `ac5ce8f` — feat(credit): `credit_tradelines` + `credit_findings` entity model (CR-A).
  - `8122fda` — feat(credit): `CreditFindingsResolver` with agency waiting periods (CR-C).
  - `c561945` — feat(credit): `TradelineAnalyzer` + 12 credit conditions (CR-D).
  - `51ef023` — feat(credit): wire resolvers into `credit_assessment` persona (CR-E).
  - `9cade8c` — feat(assets): `asset_accounts` + `asset_deposits` entity model (AV-A).
  - `0fe706c` — feat(assets): `AssetResolver` + 8 asset conditions (AV-B).
  - `07c9f91` — feat(assets): `DepositAnalyzer` large-deposit analyzer (AV-C).
  - `851997c` — feat(assets): wire resolvers into `asset_verification` persona (AV-D).
  - `cff8b66` — feat(assets): funds-to-close wired + gift chain (3 conds) complete (AV-E).
  - `0ea055f` — feat(fraud): `fraud_signals` entity model (FR-A).
  - `686616c` — feat(fraud): `IncomeMismatchDetector` + 6 fraud conditions (FR-B).
  - `bc80d92` — feat(fraud): `EmploymentFraudDetector` (employment + occupancy) (FR-C).
  - `84ed793` — feat(fraud): `UndisclosedDebtDetector` (FR-D).
  - `d887ce7` — feat(fraud): wire detectors into `fraud_screening` persona (FR-E).
  - `f67c2f7` — feat(collateral): `PropertyEligibilityResolver` + table (CO-A).
  - `47d197d` — feat(collateral): `AppraisalAnalyzer` gap analysis (CO-B).
  - `5e4617b` — feat(collateral): wire resolvers into `product_eligibility` persona (CO-C).
  - `dd970d3` — feat(conditions): `loan_condition_instances` schema + `ConditionEngine` (CN-A).
  - `349e121` — feat(conditions): `ConditionCollector` from decision outputs (CN-B).
  - `fce94bd` — feat(conditions): conditions views + API endpoints (CN-C).

(CR-B — credit report tradeline extractor — lives in **edms-simulator**, not here.)
(After CN-C: a data-cleanup pass waived the SC07/SC15 false-positive
`ASSET_INSUFFICIENT` conditions and set `purchase_price = 98% of appraised` so
funds-to-close stops over-counting the down payment — DB-only, no commit.)

**1. Title conditions — TL-E (Phase 2 Title & Liens COMPLETE).**
   - New `conditions_library` (code unique, category CHECK incl. title/credit/
     asset/fraud, `template_text`, `agency_citation`, `prior_to`, `sla_hours`,
     `assignee`, `edms_document_type`, `auto_satisfy`). 15 title conditions seeded.
   - `TitleAssessmentAgent._get_conditions()` fetches templates from the library
     and fills `${amount}`/`${holder}`. The `LienResolver` emits two legacy codes
     (`TITLE_EASEMENT`, `TITLE_OTHER_LIEN`); added a `_CODE_ALIASES` map →
     `TITLE_EASEMENT_REVIEW` / `TITLE_OTHER_ENCUMBRANCE` so every resolver code
     resolves to a seeded row.
   - **Deferred (→ EV-F):** `_get_conditions` is async/conn-bound but
     `_compute_offline` is sync and conn-less, so it's an enrichment helper for
     the context view / EDMS — **not yet on the persona hot path**.

**2. Credit Resolver — Phase 3 COMPLETE (CR-A → CR-E).**
   - **CR-A** `credit_tradelines` (account/balance/payment-status/flags/student-loan)
     + `credit_findings` (16 finding types, severity, agency wait years, blocks/LOE).
     RLS + partial derogatory indexes. Seeded SC08 (2 collections + 1 finding).
   - **CR-C** `CreditFindingsResolver` + `WAITING_PERIODS` for all derogatory types
     (BK7 4/2/2yr, foreclosure 7/3/2yr, collections 0yr+LOE, mortgage_late_12mo =
     Fannie HARD BLOCK, etc.). Added a leap-day-safe `_add_years()` (the spec's
     `date(y+n,m,d)` crashes on Feb-29 refs). SC08 → conditions (Fannie eligible).
   - **CR-D** `TradelineAnalyzer`: authorized-user flag, disputed-derogatory → block
     (B3-5.3-09), student-loan 1% deferred rule, ≤10mo excludable, medical-collection
     excluded. 12 credit conditions seeded. SC08 obligations $0 (medical excluded).
   - **CR-E** extended `vw_credit_assessment_context` (tradelines[]/credit_findings[]/
     derogatory + disputed counts — **reproduced all 19 existing cols verbatim then
     appended**, since `CREATE OR REPLACE VIEW` can't drop/reorder; kept the live
     top-level `co_borrowers` governing-score expr, not the spec's wrong
     `borrower->'co_borrowers'`). Mapped 4 cols into `CreditProfile` (edms_store).
     Persona runs both resolvers; branches **only escalate to BLOCK, never relax**.
     SC08 still blocks via existing path (governing 578 < 580 FHA floor).

**3. Asset Engine — Phase 4 COMPLETE (AV-A → AV-E).**
   - **AV-A** `asset_accounts` (17 account types, qualifying_factor, seasoning,
     gift/business/crypto flags, large-deposit fields) + `asset_deposits` (FK,
     per-deposit sourcing). RLS. Seeded SC15 ($42K checking + $47K unsourced
     deposit) and SC07 (clean).
   - **AV-B** `AssetResolver`: QUALIFYING_FACTORS (liquid 1.0 / stocks 0.70 /
     retirement 0.60 / crypto 0.0 / business by pct), three questions
     (sufficient / seasoned / sourced). 8 asset conditions. **Found the prompt's
     SC15/SC07 fixture was insufficient** ($42K single acct < $63K funds-to-close)
     → both blocked; resolver itself correct (escalate/allow once funded).
   - **AV-C** `DepositAnalyzer`: per-deposit, 50%-of-qualifying threshold, skips
     payroll/sourced, gift track, severity by amount. SC15 → [MAJOR] $47K. (Transfer
     double-count detection is flagged-only; no active matching loop yet.)
   - **AV-D** **fixed SC15 seed** (added Chase Savings $30K → $72K total) so it
     escalates, not blocks. Extended `vw_asset_verification_context`
     (asset_accounts[]/unsourced_deposits[]/totals; existing 13 cols preserved +
     appended); mapped into `AssetProfile`; persona runs AssetResolver +
     DepositAnalyzer (escalate/block only). SC15 → escalate. 15/16.
   - **AV-E** appended funds-to-close inputs to the view (`loan_amount`,
     `piti_monthly`, `qualifying_monthly`, `down_payment_computed` =
     `GREATEST(purchase_price - loan_amount, 0)` off the **top-level
     `es.purchase_price` column** — the spec's `loan_terms->'urla'->>'purchase_price'`
     key doesn't exist). Persona now passes real loan data → insufficiency path is
     live. Gift chain: 3 conds (`ASSET_GIFT_DONOR_BANK_STMT`, `ASSET_GIFT_NO_REPAYMENT`,
     `ASSET_BRIDGE_LOAN_EXCLUDED`). SC15 funds_needed $18K < $72K → escalate. 15/16.
   - **purchase_price gap (later resolved in CO-C):** AV-E shipped with
     `purchase_price` NULL on the Meridian loans, so `down_payment_computed = 0`.
     CO-C seeded `purchase_price` (= appraised, then the cleanup set it to 98% of
     appraised), which lit the funds-to-close path up. `conditions_library` **38 rows**
     here (15 title + 12 credit + 11 asset); reaches **44** after FR-B's 6 fraud rows.

**4. Fraud Engine — Phase 5 COMPLETE (FR-A → FR-E).**
   - **FR-A** `fraud_signals` (15 signal types, severity, variance, `source_docs[]`,
     auto_block, resolution fields). RLS read/write + UPDATE restricted to
     edms_admin/governance_admin (only governance resolves signals). Indexes incl.
     partial high/critical + auto_block. Seeded SC09 `income_inflation` (URLA $145.6K
     vs W2 $112K, +30%, high, review).
   - **FR-B** `IncomeMismatchDetector`: reads income + cross-validation evidence_nodes,
     compares W2 vs URLA, tiered thresholds (>10% mismatch/medium, >25% inflation/high,
     >50% inflation/critical→auto_block). Idempotent (dedup on existing income signals;
     SC09 already seeded → no dup). 6 fraud conditions → `conditions_library` **44 rows**.
   - **FR-C** `EmploymentFraudDetector`: (1) employer-name mismatch across W2/paystub/
     URLA (stop-word-normalized key-word intersection) → `employer_inconsistency`;
     (2) occupancy risk (vacation market HI/FL/NV/AZ/CO as primary, or rental income on
     primary purchase) → `occupancy_risk`. Both idempotent. **0 new signals on current
     Meridian data** — employers consistent and URLA extraction lacks occupancy/rental
     fields (TX etc.), so the occupancy detector is wired but inert until those land.
     Only 2 of the 4 spec'd occupancy signals implemented (address/distance need
     unavailable data).
   - **FR-D** `UndisclosedDebtDetector`: credit obligations vs URLA-stated. Two
     data-driven fixes vs spec: reads `credit.monthly_obligations` (spec's
     `total_monthly_obligations` is NULL in every row → dead code), and **abstains
     when no disclosed baseline exists** (no Meridian URLA carries a liabilities
     field; treating absent as $0 would false-positive on all 16). 0 signals on
     current data — correct (no baseline), fires once URLA liability extraction lands.
   - **FR-E** wired all detectors into `fraud_screening`: extended
     `vw_fraud_screening_context` (fraud_signal_records[]/high+auto_block counts),
     persona reads + conditions per signal. **Key:** persona escalate alone was
     overridden because the **policy engine has the last word** — added
     `fraud_signal_count == 0` to the `automate_if` boundary in decisions.yaml so a
     loan with an unresolved signal can't auto-clear and falls to the persona's
     proposed outcome. **SC09 fraud_screening: allow → escalate.** 15/16.
   - Detectors are async + DB-bound and run as a batch upstream (they write
     `fraud_signals`); the sync persona consumes the rollup via the view.

**5. Collateral Engine — Phase 6 COMPLETE (CO-A → CO-C).**
   - **CO-A** `property_eligibility` table + `PropertyEligibilityResolver`:
     ineligible types (vacant_land/commercial), special (condo warrantability,
     multi-unit rents, manufactured, mixed_use, coop), investment→VA ineligible,
     flood zones A/AE/V/VE→insurance. All 16 → SFR primary eligible. NB: there is
     **no `property_type`/`property_state` column** (urla JSON only; both NULL), so
     scenarios fell to defaults until CO-C seeded them.
   - **CO-B** `AppraisalAnalyzer`: Fannie B4-1.1-01 LTV on lesser-of value/price;
     at_value / above_purchase / minor_gap(>3%) / major_gap(>10% → block);
     borrower_must_cover; LTV flags >95/>97. Proven via synthetic tests ($480K vs
     $535K → $55K major gap).
   - **CO-C** seeded `purchase_price` (= appraised) + `property_type=sfr` (into
     `loan_terms.urla` JSONB — no column exists) for all 16; extended
     `vw_product_eligibility_context` (collateral inputs + LEFT JOIN
     property_eligibility); persona runs both resolvers (escalate/block only).
     All SFR/at_value → no collateral conditions fire on clean loans. 15/16
     (SC13 block / SC14 escalate undisturbed). **Collateral is surfaced in the
     payload but not yet a boundary gate** (no decisions.yaml clause reads it).

**6. Conditions Engine — Phase 11 COMPLETE (CN-A → CN-C).**
   - **CN-A** **name clash resolved by user choice:** `loan_conditions` is already
     the underwriter workbench's table (6 live summit rows + UI/API consumers), so
     the resolver-driven engine uses **`loan_condition_instances`** (workbench table
     untouched). Schema: status lifecycle, prior_to, sla_hours+due_date, assignee,
     blocks_closing, UNIQUE(app,tenant,code), + `condition_documents` (FK cascade).
     `ConditionEngine`: create/bulk-create (idempotent), get_open, satisfy, summary.
   - **CN-B** `ConditionCollector`: reads each decision's `context_snapshot`
     (decision_outputs has **no `persona_outputs` column** — one row per decision_id),
     extracts conditions per persona, writes to `loan_condition_instances`. Real
     pipeline output: SC07 ASSET_INSUFFICIENT, SC08 CREDIT_LOE_COLLECTION, SC09
     FRAUD_INCOME_MISMATCH, SC15 ASSET_LARGE_DEPOSIT+INSUFFICIENT.
   - **CN-C** `vw_loan_condition_summary` (days_until_due/is_overdue/docs count) +
     `vw_loan_conditions_aggregate`; API under **`/api/accord/conditions`** (JWT
     tenant, `_require_db`/`_get_pool` — matches Accord convention, not the spec's
     `app.state.pool`): GET list, GET summary, PATCH satisfy, PATCH waive (both
     PATCH tenant-guarded — closed a cross-tenant write hole in the spec). Router
     registered in `api/accord/__init__.py`.
   - **Data cleanup (post-CN-C, DB-only):** waived SC07/SC15 false-positive
     `ASSET_INSUFFICIENT` (from CO-C's `purchase_price = appraised` overstating
     funds-to-close) and set `purchase_price = 98% of appraised`. Verified durable —
     re-run asset_verification reports `funds_sufficient=True`, no longer generates
     ASSET_INSUFFICIENT. SC07 clean (0 open), SC15 escalate on ASSET_LARGE_DEPOSIT
     only. 15/16.

**Cross-cutting open items (carried forward):**
   - **`title_assessment` is NOT in the cron WAVES** — TL-A..TL-E built but the
     persona has **0 decision_outputs rows**, so title conditions never reach the
     pipeline/collector. Needs a WAVES-config add before title conditions flow.
   - Collateral (CO-A/B/C) and the FR detectors surface signals/conditions but
     several are **wired-not-gating** or **inert until data lands** (occupancy
     fields, undisclosed-debt baseline). Capabilities exist; they don't yet change
     outcomes on current Meridian data beyond SC09 (fraud) and SC15 (assets).
   - Two conditions tables now coexist (workbench `loan_conditions` vs resolver
     `loan_condition_instances`) — convergence is a future refactor.

### Session 17 — June 19 2026

**Theme:** Close out the three diagnosed scenario failures from Session 16
(→ **15/16**), lay the **P0 pricing/catalogue foundation**, build **Phase 1 of
the Evidence Graph end-to-end** (EV-A → EV-E), and start the **title
subsystem** (TL-A, TL-C). All work against the live EDMS RDS; commits to both
`decision-os` and `edms-simulator` `main`.

**Commits — decision-os (pushed to `main`):**
  - `429c1de` — fix(closing): read mapped `all_conditions_cleared`/`title_clear`
    from the bundle → SC16 escalates → **15/16**.
  - `de89bf1` — feat(guardrails): `platform_guardrails` table (15 rows) +
    `ThresholdResolver.validate_overlay_within_bounds()` (P0-B).
  - `b2a1e80` — feat(overlays): seed `overlay_rules` for Meridian + Summit (P0-C).
  - `033094c` — feat(llpa): `llpa_adjustments` grid (57 rows) + `scripts/pipeline_math.py` (P0-E).
  - `75cce81` — feat(catalogue): `catalogue_staging` + `refresh_county_limits.py` / `refresh_llpa_grid.py`.
  - `79f56f1` — feat(evidence-graph): EV-A schema (`evidence_nodes`/`evidence_edges`/`fact_nodes`).
  - `d02ec22` / `459db78` / `eaab1e3` / `0865244` — EV-B1..B4 fact resolvers
    (income / asset / credit / employment).
  - `06bb92d` — feat(evidence-graph): EV-C cross-document validator (SC09 fraud caught).
  - `6b0f164` — feat(evidence-graph): EV-D evidence trace builder + `decision_outputs.evidence_trace`.
  - `f7b2fd9` — feat(evidence-graph): EV-E context enricher + SC08 confidence backfill.
  - `a883b2a` — feat(title): TL-A entity model (`property_encumbrances`/`title_findings`/`ownership_chain`).
  - `36addad` — feat(title): TL-C lien resolver per type.

**Commits — edms-simulator (pushed to `main`):**
  - `efdfd88` — fix(identity): emit `DRIVERS_LICENSE`/`SSN_VALIDATION`/`OFAC_REPORT`
    for SC02–SC16 (SC01 excluded → stays fraud BLOCK).
  - `483cb00` — fix(scenarios): SC14/SC16 DTI obligations corrected (both → 42%).

**1. SC14 + SC16 fixed → 15/16.** Root causes were a *chain*, not the cascade
   logic: (a) **DTI** — SC14/SC16 obligations were calibrated to 43% (= tenant
   cap) and intermittently blocked; recomputed via `pipeline_math.py` to **42%**
   so `dti_calculation=recommend`. (b) **Fraud was systemic** — the generator
   emitted **no identity docs**, so `_derive_identity_enrichment` scored
   `fraud_score≈0.8` / `identity_match_confidence=0.0` for **all 16**;
   fraud_screening BLOCK cascaded through `underwriting_decision` into
   closing/product. Fixed at the source (generator emits the 3 identity docs;
   SC01 excluded by design). (c) **closing_readiness persona** defaulted
   `all_conditions_cleared`/`title_clear` to `True` (read a nested checklist /
   absent Property instead of the mapped `ComplianceRecord` fields) → `automate_if`
   wrongly matched → `allow`; now reads the mapped fields → SC16 falls through to
   the safe-default **escalate**. Did **not** add `escalate_if` OR-semantics — the
   evaluator AND-s clause items (`if all_ok`), so the spec's "separate items = OR"
   was wrong; the persona fix alone reaches escalate. SC12 remains the one fail
   (data: stated == verified income).

**2. P0 pricing/catalogue foundation.**
   - **P0-B** `platform_guardrails`: two-sided outer bounds (agency_floor /
     platform_ceiling) per (product, parameter); `validate_overlay_within_bounds()`
     on `ThresholdResolver` (not the `SemanticResolver` the prompt named — that
     has no DB conn). All 7 validation tests pass.
   - **P0-C** `overlay_rules` seeded (Meridian 660/43/95 + fha 50; Summit 680/43);
     `resolve_credit_floor()` now returns the overlay (660/680), not the agency
     floor. Each overlay validated against the guardrails before seeding.
   - **P0-E** `llpa_adjustments` (57-row Fannie FICO×LTV grid) + `pipeline_math.py`
     (`get_llpa_adjustment` / `get_total_rate` / provisional `get_rate_for_product`
     off `rate_sheet_entry`). SC07 (712, 90% LTV) → base 6.75 + LLPA 1.00 = **7.75%**.
     NB: the live `rate_pricing` persona still uses a hardcoded LLPA formula —
     swapping it to this table is **P0-D** (not done).
   - **Catalogue staging**: `catalogue_staging` (download → pending →
     governance_admin approve → promote) + FHFA county-limits and Fannie-LLPA
     refresh scripts. FHFA auto-download 404s (URL changed; 2026 limits publish
     in Nov) — documented manual `--from-file` path.

**3. Evidence Graph — Phase 1 COMPLETE (EV-A → EV-E).**
   - **EV-A** schema: `evidence_nodes`, `evidence_edges`, `fact_nodes` (RLS;
     FK → `document_index`; partial unique index = one current fact per
     `(app,tenant,fact_type)`; **deferrable** `superseded_by` self-FK so
     supersede+insert runs in one txn).
   - **EV-B** four fact resolvers, run across all 16: `qualifying_income`
     (box1/12; paystub YTD **annualized** before cross-validate — the spec compared
     YTD to the annual W2, a false conflict on every borrower), `verified_assets`
     (honors `large_deposit_documented`; SC15 flags the $47K undoc deposit),
     `governing_credit_score` (`min(primary,co)` via the **borrower_role column**;
     fixed the spec's class-level-indentation `return` SyntaxError + `derogatory_count`
     int handling; SC08 → 578), `employment_continuity` (sourced from the
     `entity_states` reconciliation block since document_index has no tenure/status;
     SC03 → self_employed via box1=0).
   - **EV-C** cross-document validator: income (W2 vs URLA `monthly_income_stated`×12),
     employer, property value. **SC09 caught**: URLA $145,600 vs W2 $112,000 = +30%
     → `income_inflation` fraud signal. URLA has no employer field and no
     purchase_price exists, so those checks are partial (flagged).
   - **EV-D** trace builder: assembles the evidence chain into
     `decision_outputs.evidence_trace` JSONB for the AI explanation engine; fixed
     case-sensitive fraud detection ("FRAUD SIGNAL" uppercase) + Decimal/UUID JSON
     serialization.
   - **EV-E** context enricher (parallel, non-destructive layer over the persona
     context) + **SC08 confidence backfill** (docs were `NULL` not `0` — spec's
     `WHERE confidence_score=0` matched nothing; backfilled `0 OR NULL → 0.97`).
     `IncomeFactResolver.resolve()` now returns a dict for parity with the other
     three. Evaluate still **15/16** (parallel layer; personas don't READ evidence yet).
   **Still open (persona migration):** personas don't consume the evidence layer
   yet, so SC09's fraud signal is *available* but the fraud persona doesn't act on
   it; SC15 `verified_assets` $42K (ending_balance) vs $52K entity_states
   `liquid_assets_total`; SC04 `stable` fact vs `escalate` persona.

**4. Title subsystem — start.**
   - **TL-A** entity model: `property_encumbrances` (13 lien types), `title_findings`
     (severity clear→fatal), `ownership_chain` (vesting). RLS + FK → document_index.
     Seeded SC16 (IRS $28,400 blocks + HOA $4,200 resolvable) and SC10 (clear).
   - **TL-C** `LienResolver` + `LIEN_RULES` (priority, blocks_closing,
     resolution_method, condition_code/text, required_docs, Fannie/FHA/VA
     treatment). SC16 → `block` ($28,400 payoff); lis_pendens → `fatal_block`;
     fixed the easement `priority: None` sort crash (None → 999).
   Next: **TL-B** (commitment extractor), **TL-D** (title_assessment persona).

### Session 16 — June 18–19 2026

**Theme:** Harden transaction-data security (Phase 1, non-breaking) on the live
EDMS RDS, add the **13th** lending decision (`asset_verification`, SC15) with a
**reusable persona-onboarding script**, make SC15's data durable through the
real EDMS S3 pipeline, and diagnose (not yet fix) the three remaining meridian
scenario failures.

**Commits — decision-os (pushed to `main`):**
  - `c339ccc` — feat(auth): app-level RBAC from `role_permissions`.
  - `8dc7caf` — feat(persona): `asset_verification` (SC15) + onboarding script.
  - `260ccf2` — feat(security): DB roles + RLS migration script.

**Commit — edms-simulator (pushed to `main`):**
  - `0a61b57` — fix(sc15): durable asset fields in the ingest pipeline.

**1. Transaction-data security — Phase 1 (safe foundation, NO enforcement).**
   Applied to the **live RDS** via `scripts/migrations/security_foundation.py`
   (idempotent, all **inert** so nothing in production changed):
   - Roles `accord_app`, `accord_readonly`, `governance_admin` (NOLOGIN
     NOINHERIT); grants on source tables + persona views + writables (no
     DELETE); `governance_admin` owns `regulatory_rules`/`agency_guidelines`;
     11 department roles inherit the service roles.
   - RLS **policies** (`rls_*`) on 8 tables (`entity_states`, `applications`,
     `applicants`, `decision_outputs`, `decision_timeline`, `document_index`,
     `tenant_rules`, `rate_sheet_entry`) — created but **dormant**: no
     `ENABLE`/`FORCE ROW LEVEL SECURITY`, and the app connects as `edms_admin`
     which is **`rolbypassrls=TRUE`**, so isolation is not yet enforced.
   - `role_permissions` table (JSONB action flags) seeded for 5 roles
     (`underwriter`, `senior_uw`, `compliance`, `admin`, `read_only`).
   **App-level RBAC** (`api/accord/auth.py`): `get_current_user` now attaches the
   role's action permissions via a cached, fail-safe loader (never breaks the
   auth hot path); `require_permission(perm)` dependency returns 403. Gated:
   `override_decision` (pipeline override — was wide open), `manage_users`
   (invite/role/deactivate), `manage_policy` (rules PUT + `/approve`),
   `export_reports` (audit report data). `/auth/me` exposes `action_permissions`
   additively (product `permissions` list unchanged). Verified locally vs live
   RDS: underwriter→403, senior_uw/admin→pass.
   **Phase 2 (deferred, NOT done):** `ENABLE`/`FORCE RLS`, switch the app to the
   non-bypass `accord_app` login, set `app.tenant_id` per pool-acquire. These
   three together are what would actually enforce DB-level tenant isolation —
   and the GUC-per-acquire rework is the part that would break the current
   per-query/no-transaction asyncpg pattern, so it stays deferred.

**2. `asset_verification` persona (SC15) — the 13th lending decision.**
   `domains/lending/personas/asset_verification.py` (`AssetVerificationAgent`, a
   real `LendingPersona` with `_compute_offline`). A wave-1 **independent leaf**
   (nothing depends on it → zero cascade risk). Outcome model: ESCALATE on a
   large unsourced deposit (> $5K) or undocumented gift funds (UW sources them —
   Fannie Mae B3-4.3-04/09); BLOCK on reserves < 2 months (B3-4.4-01); ALLOW
   when verified. **Deliberately dropped** the prompt's "deposit > 50% of liquid
   → block" rule, which would have blocked SC15 (deposit is 90% of liquid),
   contradicting the expected escalate. SC15 (Maria Santos / "Rachel Green"):
   $47K undocumented deposit, 3.2mo reserves → **escalate** ✅.
   **Six real wiring points** (there is **no `infra/schema.sql`** — views are
   live `CREATE OR REPLACE`): (1) `vw_asset_verification_context` projecting
   `borrower.assets` (`scripts/migrations/add_asset_verification_view.py`);
   (2) `EdmsContextStore.VIEW_MAPPINGS` → `AssetProfile`; (3) the persona class;
   (4) `LENDING_PERSONA_CLASSES`; (5) `core/cron/runner.py` `WAVE_CONFIG`/`WAVES`/
   `DECISION_DEFAULTS`; (6) `decisions.yaml` boundary
   (`automate/block/escalate_if`). Meridian now **13/16** (was 12/15 + 1 no-persona).

**3. Reusable persona onboarding** (`scripts/onboard_persona.py` +
   `scripts/create_asset_verification.py`). Reflects the **real** architecture
   (the 6 wiring points above, not a naive view+file model): generates + applies
   the view DDL, writes a real `LendingPersona` stub (or caller-supplied code),
   appends the `decisions.yaml` boundary, prints the exact edits for the 3 Python
   registries, and smoke-tests projection + `_compute_offline`. Honest RLS note —
   isolation is **not** asserted (BYPASSRLS app role). Idempotent.

**4. EDMS durability for SC15** (`0a61b57`). SC15's asset data now flows through
   the real S3 ingest instead of only the Decision-OS manual patch:
   `scripts/meridian_scenarios_data.py` (SC15 asset fields, 47K to match the
   patch) → `scripts/simulate_meridian_s3.py` `BANK_STATEMENT_M1` carries them
   (defaults keep non-asset scenarios clean) → `core/aggregation/
   entity_state_builder.py` new `_derive_asset_enrichment` extracts them into
   `borrower.assets` (mirrors the income/identity enrichment pattern).
   Re-ingest: `python scripts/simulate_meridian_s3.py --date 2026-06-20 --scenario SC15`.
   NB: `scripts/patch_meridian_scenario_data.py` also re-applies SC15 (47K) so
   the Decision-OS evaluate run stays green without a full re-ingest.

**5. SC12/SC14/SC16 — diagnosed, NOT fixed (awaiting fix direction).** Three
   distinct root causes:
   - **SC12** `income_verification=recommend` (want block) — **data**: stated ==
     verified (74400/74400 → 0% discrepancy); persona blocks only at > 25%. Fix =
     lower SC12 verified income (~52K → ~30% > 25%).
   - **SC14** `product_eligibility=block` (want escalate) — **upstream cascade**:
     the VA gate proposes escalate (remaining 107325 > loan×0.25), but upstream
     `dti_calculation=block` (DTI ≈ 42.99 vs meridian-v1 cap 43 — itself worth a
     look) force-blocks via `upstream_block_propagates_to_dependents`.
   - **SC16** `closing_readiness=block` (want escalate) — **data + policy
     precedence**: SC16 carries `title_defect=True` + insurance gap + an upstream
     underwriting block (trips BLOCK before the rate-lock escalate); and even with
     clean data, closing's `automate_if` would match → `allow` and the
     `escalate_if: rate_lock_expiring_soon == true` clause can't override it.
     Fix = clean SC16 data + add `rate_lock_expiring_soon == false` to `automate_if`.

### Session 15 — June 5–13 2026

**Theme:** Build **Accord** — the customer-facing lending workbench on top of the
EDMS/Decision-OS engine — and ship it live on AWS. Auth + multi-tenancy, a
marketing front door, a three-layer Rules Dashboard with full versioning, a
document-source viewer, and a rule-boundary validation suite. Every slice was
headless-verified (Puppeteer against the live ALB) and committed + deployed.

**Live deployment.** Dedicated **`accord` ECS Fargate cluster + ALB** at
`http://accord-alb-588286075.us-east-1.elb.amazonaws.com` (NOT `edms-simulator`,
which doesn't exist in the account). Account `621646470377`, `us-east-1`. ECR
repos `accord-api` / `accord-frontend`. Redeploy: **`bash deploy/deploy.sh`**
(ECR login → buildx amd64 → register task defs → roll services → wait stable).
Frontend builds with empty `VITE_API_URL` → relative `/api` through nginx/ALB.
Currently at task-def revision **:14**.

**⚠ The `.env` `DATABASE_URL` points at the live AWS RDS** (`edms-postgres-rds…`),
and `docker-compose` wires the local API to the same URL — so the local docker
stack AND any `python scripts/…` read/write **production data**. All migrations
this session were additive (`CREATE TABLE / ADD COLUMN IF NOT EXISTS`); seeds
populate new tables; summit demo data was reset to a clean state after each test.

**Frontend stack note:** Accord is a **Vite + React + React-Router** SPA under
`frontend/` (NOT the Next.js in the older stack table), Tailwind brand `#0F6E56`
(`bg-brand`/`text-brand`/`bg-brand-dark`/`bg-brand-light`). API client in
`frontend/src/api/client.ts` (getJSON/postJSON/putJSON, JWT in localStorage).

**What landed (committed + pushed + deployed):**

1. **Auth + multi-tenancy + seed.** JWT (PyJWT HS256, 24h) + bcrypt; tenant comes
   from the JWT, never the client. 8-role enum (admin/manager/processor/
   underwriter/senior_uw/closer/compliance/viewer). `scripts/migrations/
   seed_tenants_and_users.py`: 5 tenants (summit/atlas=enterprise, pacific=
   business, heartland=growth, legacy=starter), ~33 users, 200 curated loans
   (50 each to summit/pacific/heartland/atlas), ~8.6k remainder under `demo`.
   All passwords `accord2026`. Real creds incl. `processor1@summit.com` (Mike),
   `senioruw@summit.com` (Karen), `admin@summit.com`.

2. **Loan-detail / queue UX overhaul.** My Queue as the role-based landing,
   summary-led loan detail grouped by blocking issue, context-aware actions,
   action confirmations, conversational AI text (`conversational_summary`).

3. **Marketing front door** (`frontend/src/pages/Landing.tsx`, `Security.tsx`,
   `ComplianceDocs.tsx`). Public routes `/`, `/login`, `/pricing` (scrolls to
   pricing), `/security`, `/compliance`; app routes require auth. Animated hero
   evaluation card; copy rules enforced (no agent counts, "SOC 2 ready", "Built
   to integrate with", "You own your data"). **Interactive Simulation section**:
   multi-select scenario cards → dynamic single-sim (DTI/rates/debate/health) or
   combined-impact summaries + code-driven animated previews. **Embedded demo
   video** ("Watch the demo") — self-hosted `frontend/public/accord_demo.mp4`
   (captioned 1:33 walkthrough generated by `frontend/record_demo.cjs` via
   puppeteer-screen-recorder + bundled ffmpeg) with a poster + click-to-play.

4. **Demo assets.** Admin-only `/demo` control room with bookmarkable moments +
   a DEMO watermark; `scripts/demo_data_check.py` (verifies the demo tenant);
   `docs/DEMO_SCRIPT.md`.

5. **Rules Dashboard — foundation** (the "trust layer", three layers):
   - DB: `scripts/migrations/create_rules_tables.sql` — `regulatory_rules` 🔒,
     `agency_guidelines` 📋, `tenant_rules` 🔧 (versioned overlays),
     `data_source_status`, `rule_change_alerts`; `decision_outputs.rule_version_id`.
   - Seeds (`scripts/compliance/`): 19 regulatory (federal QM/ECOA/TRID/OFAC/BSA/
     HMDA + 11 states), 15 agency (Fannie/Freddie/FHA/VA), per-tenant v1 overlays,
     8 data sources + 2 alerts.
   - API `api/accord/rules.py`: GET `/rules` (3 layers + freshness + validation),
     `/history`, PUT `/rules` (admin/manager → pending; blocks values below hard
     regulatory/agency floors, warns on soft guideline breaches), POST `/approve`,
     GET `/lookup?date`, `/data-freshness`, `/alerts`.
   - Frontend `RulesSettings.tsx` (Settings "Decision Rules" tab + `/settings/rules`
     for admin+manager): per-category 3-layer tables (regulatory locked grey,
     agency read-only blue, customer editable with live red/amber validation),
     `DataFreshness.tsx` (+ app-wide stale banner), `RuleHistory.tsx` (versions +
     examiner date lookup), client-side PDF export.

6. **Rules versioning** (advanced):
   - DB `create_rules_versioning.sql`: tenant_rules versioning cols (change_type,
     scheduled_for, expires_at, rolled_back_from, pipeline_policy, ratified_by,
     channel…); `shadow_evaluations`, `examination_periods`, `rescreen_events`,
     `retrospective_analyses`; `entity_states` pinning cols.
   - API (rules.py): rollback, schedule, shadow + shadow-report, emergency +
     ratify, examination-mode (freezes edits with 403; emergency still allowed),
     retrospective, reconstruct, pipeline-policy, impact, loan-note.
   - Frontend: submit modal (timing immediate/schedule/shadow + pipeline policy +
     live impact preview), version history with type badges + rollback, scheduled/
     shadow/expiring sections, emergency modal + ratification banner, examination
     toggle, retrospective + audit-reconstruction panels, loan-detail "Rules Note"
     for version-pinned loans. **Pricing-tier gating** (view all plans; edit/
     rollback/scheduled/shadow Business+; emergency/examination/retrospective/
     reconstruction Enterprise). Cron jobs `scripts/rules_cron.py` (scheduled
     activation, 24h emergency auto-revert, expiration, shadow completion).
   - Demo history seeded for summit: v1→v2→v3 (active, + FTHB waiver expiring
     Sep 30) → v4 (scheduled Jul 1); 30 loans pinned (3→v1, 5→v2).

7. **Document viewer** (`api/accord/documents.py` + DocumentChecklist /
   ExtractionDetail / SourceMatch): connects the existing EDMS `document_index`
   (262k real indexed docs with `extracted_fields`) to loan detail — checklist
   (on-file + missing), extraction-detail slide-over (fields, →used tags, "what
   AI did", cross-references), and a source-match table tracing every
   `entity_states` value to its source doc with real discrepancy detection
   (income gap, value shortfall, expired DL). Matched by application_id (EDMS docs
   live under `tenant_id='default'`); loan tenant-checked via entity_states. No
   seeding needed — real data exists and is consistent with entity_states.

8. **Rule validation suite** (`core/compliance/rule_validator.py` +
   `api/accord/validation.py`): a deterministic engine + **108 boundary test
   cases** across 10 categories, expectations specified independently of the
   engine and adaptive to each tenant (caught a real ordering bug — credit
   checked before DTI). 108/108 for all four tenants. POST `/rules/validate`,
   GET `/rules/validation-report`; PUT `/rules` auto-runs the suite and blocks
   activation on any failure. `RuleValidation` dashboard tab (pass bar, per-
   category expand with input/expected/actual, warnings, run-now, examiner PDF,
   dashboard-wide red banner on failure).

**Verification:** every feature headless-verified (Puppeteer, system Chrome at
`C:\Program Files\Google\Chrome\Application\chrome.exe`, `--no-sandbox`) against
both a local API (`uvicorn api.main:get_app --factory --port 8001`, vite pointed
at it via `VITE_API_URL`) and the live ALB after each deploy. Test gotchas
preserved: write Puppeteer scripts with the Write tool (heredocs mangle the
backslash Chrome path); CSS `uppercase` makes innerText UPPERCASE (case-insensitive
regex); isolate logins with `createIncognitoBrowserContext` (pages share
localStorage); wait for `load()` fetches to settle before asserting button state.

### Session 14 — June 5–6 2026

**Theme:** Make the `/workbench` review surface trustworthy — finish the
human-review path (revert + stale), give every persona a story-driven
review screen with ONE data-driven explanation generator, then fix
routing personas reading applicant vocabulary on declined/blocked files.
**Commits (pushed to `main`):**
  - `82bbd56` — Fix human-review workflow for recommend-mode personas
    (committed the Session-13 working-tree edits: auto-execute stamping,
    `can_act` gating, pricing_analyst → human kind).
  - `e633d9a` — Story-driven persona review UI + revert/stale workflow.
  - `fa75b12` — Ignore runtime artifacts (`.health.json`, `.uvicorn.log`).
  - `5e46512` — Persona kind + vocabulary so routers stop speaking
    applicant language.
  - `339fbda` — PRD v0.14: decision-flow semantics (§11.3 canonical
    underwriting states + halt policy; new §13.1 review-workbench model;
    revert/stale/request-info edges in the §13 outcome-routing diagram).
**Tests:** new `tests/ui/test_explanations.py` (15) + `tests/ui/test_vocab.py`
(17); full `tests/ui/` suite **77 passing**. Live-verified via `curl` against
the running server (EDMS PG mode) + EDMS DB queries.
**Server:** `uvicorn api.main:get_app --factory --port 8000` in the
background, still WITHOUT `--reload` (StatReload unreliable on the
OneDrive path) — manual restart after each Python change; Jinja templates
hot-reload.
**Remote:** origin moved to `https://github.com/krishnamami/Decision-OS.git`
(capitalised) — `git remote set-url` applied so pushes no longer rely on
the redirect.

**What landed:**

Revert + stale + request-info (`ui/edms_routes.py`, `_revert_form.html`)
  - `POST /workbench/{persona}/review/{app}/revert` reopens a finalized
    decision as a fresh un-acted version (AI outcome restored, human
    fields cleared → back to pending), appends a `human_revert`
    `decision_timeline` row (who/why/notes in `waiting_on` jsonb), and
    flags every downstream decision `stale=true` via the forward
    `UPSTREAM` walk. Idempotent `_ensure_stale_column()` migration runs
    once on pool create (`ADD COLUMN IF NOT EXISTS stale`).
  - `POST …/request-info` logs a `human_request_info` timeline row and
    keeps the loan pending. Reviewed tab gained PROPOSED-vs-FINAL columns
    (proposed = first human-action `from_state`) + a per-row revert
    popover; amber "stale" badges; an outdated-decision banner.
  - Two asyncpg bugs fixed in testing: bare `$n` params in the
    `INSERT … SELECT` need casts + sequential numbering from `$1`.

Story-driven review UI (`ui/explanations.py` + 5 template partials)
  - Review/completed pages lead with a "Why this needs your review"
    banner, a green/red/amber signal checklist, documents-on-file (from
    `document_index`), an upstream grid, and clear actions
    (Approve / Override / Request info / Revert). Partials: `_why_card`,
    `_signals`, `_documents`, `_special_banners` (fraud/compliance/closing
    hard-stop banners), `_revert_form`.

ONE explanation generator (`ui/explanations.py`)
  - Replaced per-persona narrative code (`EXPLANATION_TEMPLATES` +
    `DERIVERS`, deleted) with a single `explain(outcome, matched_rule,
    signals, labels)`. It names ONLY the driving signals — the matched
    rule's gated conditions that fail (adverse) or satisfy (allow) —
    never an ungated or passing signal; dedupes; renders empty-sample
    inputs as "no data" (per-signal `data_gate`), never 0. Persona = data
    (`SIGNAL_SPECS` + `DECISION_LABELS`). `action_label()` gives
    outcome-correct verbs ("Confirmed block", not "approved"). The matched
    `boundary_rule` is an evidence string (`score=660, band='near_prime',
    … → recommend`) — that's what makes driver-from-rule detection work.
  - `_entity_summary` treats a DTI of exactly 0 as missing ("—"); the DB
    stores `entity_states.dti_back = 0.0` (not computed) so it had read as
    a misleading 0.0% on every persona.

Persona kind + vocabulary (`ui/explanations.py`, `5e46512`)
  - `PERSONA_KIND` (`approval_routing` → routing, rest decision) +
    `VOCAB[kind][outcome]{badge,tone,banner_verb,action_label}`. Every
    user-facing verb/badge/button comes from vocab; removed hardcoded
    approve strings + the green fallback (unknown → neutral). Routing
    vocab is Auto-execute / Hold for ack / Escalate / Halted with NEUTRAL
    tone (slate, never green). `explain()` branches by kind: routing
    banner names what is routed — "Routing a DECLINE: emailing the decline
    / adverse-action notice." — surfacing `underwriting_outcome` +
    `routing_target`; never approve/allow.
  - `canonical_underwriting_state()` — one mapping layer to {approve,
    conditional_approve, decline, block}; Senior UW raw `block` renders
    "Decline" (matching the router), no silent rename. Parses the
    stringified `underwriting_decision` (`"{'outcome': 'decline'}"`).
  - `halts_pipeline()` / `downstream_should_run()` — one tested policy
    (user-confirmed): fraud/compliance block and an underwriting hard-block
    halt downstream; an underwriting **decline** does NOT (routing must run
    to send the adverse-action notice). Surfaced as a rose
    "Ran under an upstream hard block" banner. Policy + UI only — engine
    (`core/cron/runner.py`) and data untouched (the data actually shows
    downstream rows DO exist under fraud blocks; not regenerated).
  - `badge_for()` Jinja global renders kind-aware pills on every list
    (pending / reviewed / all / by_outcome / analytics / upstream), so a
    routing persona never shows "allow". Post-Closer copy → "Routes
    finalized decisions — approvals and declines".

**Known follow-ups (NOT done):**
  - DTI is its own decision (`dti_calculation`) with no workbench page;
    `entity_states.dti_back = 0.0` is upstream seed/ETL data, not fixed at
    source (only masked in the UI summary).
  - `halts_pipeline` is enforced at the UI/policy layer only — the
    decision engine still generates downstream rows under a hard block.

### Session 13 — June 4 2026

**Theme:** Bring up the EDMS workbenches locally and fix the broken
human-review path on the `/workbench` (EDMS) surface — auto-execute
finalization, the Approve/Override gating, and the pricing_analyst
landing tab.
**Commits:** none yet — all changes are uncommitted working-tree edits.
**Tests:** unit suite not re-run this session; fixes verified live via
`curl` against the running server (EDMS PostgreSQL mode) + EDMS DB
queries. `ast.parse` / Jinja compile checks on every edited file.
**Server:** `uvicorn api.main:get_app --factory --port 8000` run in the
background (EDMS PG mode — `DATABASE_URL` in `.env` points at the AWS
RDS `edms` instance, and it is reachable). NB: `--reload` proved
unreliable on this OneDrive path (StatReload missed later edits, worker
kept stale code) — running WITHOUT `--reload`; a manual restart is
required after each code change.

**What landed (working tree, uncommitted):**

`core/decision_store.py` — `write_decision()` stamps auto-execute rows
  - The `INSERT INTO decision_outputs` gained three columns —
    `human_action, human_reviewer, acted_at` — taking it from 19 to 22
    bind params (`$20–$22` appended at the end).
  - When `mode == 'auto_execute'`: `human_action='auto_approved'`,
    `human_reviewer='system'`, `acted_at=now`. Otherwise all three
    `None` (a human finalizes via the workbench later).
  - Why: downstream dependent personas gate on `human_action IS NOT
    NULL` to confirm an upstream decision is finalized. Auto-execute
    rows previously wrote `human_action = NULL` and silently blocked the
    DAG. Transaction + version logic left intact.

`ui/edms_templates/review_detail.html` — Approve/Override gated on `can_act`
  - Actions block restructured into three mutually-exclusive states:
    `{% if can_act %}` → Approve + Override forms · `{% elif
    decision.human_action %}` → the existing emerald "reviewed" banner ·
    `{% else %}` → a neutral "Decision is final. No human action is
    required." banner.
  - Old logic gated only on `{% if decision.human_action %}`, so the
    forms rendered for ANY null `human_action` regardless of mode
    (e.g. auto_execute rows wrongly showed action forms).
  - NB: the literal "Decision is final." string referenced in the task
    actually lived in `completed_detail.html`, not here.

`ui/edms_routes.py` — `_render_review()` now computes + passes `can_act`
  - Root cause of "no Approve button": the EDMS `/workbench` review
    route never put `can_act` in the template context, so the new
    `{% if can_act %}` gate was always falsy and the button vanished.
    (The `can_act` at `ui/views.py:~3842` belongs to the *legacy* `/ui`
    path, not the EDMS `/workbench` path.)
  - Added `can_act = not readonly and decision_dict is not None and
    mode in ('human_approval','recommend') and human_action is None`,
    passed into both the review and completed template contexts.

`ui/edms_routes.py` — `PERSONA_KPIS["pricing_analyst"]` fixed to human kind
  - The actual "why I don't see the Approve button on Pricing Analyst"
    bug. pricing_analyst's `mode` is `recommend` (a human-review
    persona) but its KPI config was `kind="auto"` with tabs
    `[all, by_outcome, analytics]` — no Pending review tab. So the
    default landing (`tab=queue` → normalized to `all` for auto kind)
    listed rows as read-only `/completed/` links; the In Queue tab that
    links to `/review/` (where the Approve form lives) was never shown.
    Only manually typing `?tab=pending` surfaced it.
  - Changed to `kind="human"` with tabs `[pending, reviewed,
    analytics]`, keeping pricing-relevant KPI cards (swapped "Total
    priced" → "Pending review"). Default page now opens on In Queue and
    links to `/review/`.

**Known follow-ups (NOT done — left intentionally):**
  - `credit_underwriter` has the same `mode='recommend'` vs
    `kind='auto'` mismatch in `PERSONA_KPIS` — its Approve button is
    likewise unreachable from the UI. User scoped this session to
    pricing only ("for now fix pricing"). Sweep the remaining personas
    for mode-vs-kind mismatches when picking this up.
  - None of this is committed; no migration run. If `decision_outputs`
    lacks `human_action / human_reviewer / acted_at` columns the
    `write_decision` INSERT will fail — schema not verified this
    session (PRD references the columns on `decision_outputs`).

### Session 12 — May 18 2026

**Theme:** Move every UI read off the in-memory Platform onto live EDMS
PostgreSQL, ship a persona-centric workbench operators can actually
run a shop from, and harden the cron runner for thousand-app batches.
**Commits:** 8 pushed —
`4236f18` `cbbfe67` `50f2e9e` `80ff1a8` `59d6fe7` `b7488fb` `df0c391` `9f542bd`.
**Tests:** 351/351 green throughout — the in-memory path is byte-
identical when `DATABASE_URL` is unset, so the unit suite never sees
the EDMS overlay.

**What landed:**

EDMS-backed persona workbench at `/workbench` (`4236f18` → `cbbfe67`)
  - `ui/edms_routes.py` (~1.7k lines) + `ui/edms_templates/` (10
    templates) — sibling to the legacy `/ui` that reads only from
    EDMS PG (`vw_pipeline_status`, `vw_<decision_id>_context`,
    `decision_outputs`, `decision_timeline`, `entity_states`).
  - 11 lending personas grouped by stage (Pre-underwriting /
    Underwriting / Decision / Post-decision):
      Pre-underwriting:  credit_underwriter, fraud_analyst,
                         compliance_officer, employment_specialist
      Underwriting:      income_underwriter, collateral_analyst,
                         product_specialist, pricing_analyst
      Decision:          senior_underwriter
      Post-decision:     closer, post_closer
  - Each persona gets a 4-tab workbench:
      In Queue · Completed · Auto Cleared · Analytics
  - Approve / Override POST endpoints update
    `decision_outputs.human_action / human_reviewer /
     human_override_reason / outcome / acted_at` and append a
    `decision_timeline` row with trigger `human_approve` or
    `human_override`. Auto-advances to the next pending app in the
    queue.
  - Pipeline dashboard, audit dashboard (per-app trail at
    `/workbench/audit/{id}`), governance page with CSV export of
    `decision_outputs` round out the surface.
  - SQL alias bug caught: `do` is a reserved Postgres keyword
    (DO blocks). Aliased everywhere as `dout`.
  - 12 routes total. All 11 personas × 4 tabs = 44 combos green
    via TestClient against live EDMS.

Legacy `/ui` rewired for EDMS (`50f2e9e`)
  - `ui/views.py` got an EDMS overlay appended below the existing
    sync helpers (which stay byte-identical). Module-level
    `DATABASE_URL` detection + lazy `EdmsContextStore` /
    `DecisionStore` singletons + six async dispatchers:
      list_applications_async
      application_detail_async
      decision_detail_async
      queue_view_async
      list_persona_workbenches_async
      persona_workbench_view_async
  - Each dispatcher: if `DATABASE_URL` → read from PG; else →
    delegate to the existing sync helper. Sync helpers are
    untouched, so the 351 tests still pass.
  - `ui/routes.py` route handlers `await` the dispatchers.
  - Override POST has an EDMS branch that writes to
    `decision_outputs` + `decision_timeline` directly (no
    trace_writer in EDMS mode).
  - `_edms_jsonify` walks dicts to ISO-encode datetime / UUID /
    Decimal so `{{ ... | tojson }}` doesn't choke on JSONB
    columns that contain raw datetimes.
  - Stubs on the EDMS path: policy_panel, evidence_panel,
    audit_panel, learnings, atomic_steps, upstream_status,
    read_permissions — all return None / [] / {} so templates
    render unchanged. Migrating these is a follow-up.

Sidebar polish + Platform EDMS wiring (`80ff1a8`, `59d6fe7`)
  - Tabler Icons via CDN. Each persona has its actual icon:
      ti-shield, ti-coin, ti-briefcase, ti-alert-triangle,
      ti-clipboard-check, ti-home, ti-package, ti-trending-up,
      ti-user-check, ti-check-circle, ti-send.
  - Sidebar groups personas by stage with section headers.
  - Orange count badge per persona whose queue is non-empty.
    One grouped query per request. For auto_execute personas the
    badge = apps in `entity_states` without a decision row;
    everyone else = pending decisions with human_action IS NULL.
  - `_base_ctx` is now async so it can fan the badge query into
    every page. All 9 callsites await it. Sync `_not_configured`
    inlines a zero-queue sidebar fallback.
  - `Platform` gained optional `edms_store` + `decision_store`
    attributes. `build_default_platform` wires them when
    `DATABASE_URL` is set; tests with no env var leave them None.
  - Lifespan prints `[startup] EDMS PostgreSQL mode — /workbench
    reads from EDMS` (or the in-memory equivalent), with
    `flush=True` so uvicorn's buffered stdout actually surfaces it.

Date range filter on persona workbench (`b7488fb`)
  - Dropdown in the KPI-strip area. Options:
      Today · This week · This month (default) · This quarter ·
      This year · All time · Custom range (from/to date inputs).
  - URL params: `?range=this_quarter` or
    `?range=custom&from=2026-05-01&to=2026-05-16`.
  - Selection survives tab switches via a query-string suffix the
    template appends to every tab link.
  - Quarter math: Q1=Jan–Mar … Q4=Oct–Dec. Week starts Monday.
    All bounds tz-aware UTC.
  - Filters Completed / Auto Cleared rows, Analytics aggregates,
    and 3 of 4 KPI cards (Completed / Auto cleared / Avg review
    time). The **In Queue** KPI card and the **sidebar queue
    badges stay unfiltered** — they reflect work waiting right
    now, not historical throughput.
  - Bad range keys + bad date strings silently fall back to
    `this_month`.

asyncpg pool tuning + cron runner resilience (`df0c391`)
  - Both `EdmsContextStore` and `DecisionStore` now `create_pool`
    with: `min_size=2, max_size=10, command_timeout=60,
    max_inactive_connection_lifetime=300, statement_cache_size=0`.
    Tuned identically on both sides so a long runner can't end up
    with one tuned pool and one default.
  - `core/cron/runner.py` gains three pieces of hygiene:
      `_process_one(...)` — per-app body extracted so the retry
        path re-runs it without duplicating the snapshot →
        reasoning → write_decision flow.
      `_reset_pools()` — closes + nulls both pools so the next
        `_get_pool()` rebuilds. Called on transient errors AND
        pre-emptively every 500 rows.
      `_looks_like_conn_error(exc)` — classifies by both class
        (`asyncpg.PostgresConnectionError` / `InterfaceError`,
        builtin `ConnectionError` / `ConnectionResetError`) AND
        message ("connection is closed", "ConnectionReset",
        "server closed the connection", …).
  - Main loop wraps each app in try/except; transient errors
    reset pools + retry once before logging the row.
  - CLI `batch_size`: 100 → 9000 so
    `python -m core.cron.runner credit_assessment` processes every
    pending app in one pass.
  - Verified live-EDMS: cold `_reset_pools` no-ops; snapshot
    instantiates a pool; hot `_reset_pools` closes both cleanly;
    follow-up snapshot rebuilds and returns rows.

Tooling commit (`9f542bd`)
  - `requirements.txt` pins `python-dotenv>=1.0`. Every EDMS-
    touching module (`ui/edms_routes.py`, `ui/views.py`,
    `api/deps.py`, `core/cron/runner.py`) calls `load_dotenv()`;
    fresh clones now resolve the dep cleanly.
  - `scripts/_verify_edms_writes.py` ships as a short write-side
    smoke (counts rows in `decision_outputs` + `decision_timeline`
    for a given decision and dumps the five most recent).

**Run locally:**
```
uvicorn api.main:get_app --factory --port 8000
```
Open http://localhost:8000/workbench — sidebar shows real EDMS
queue counts; pick a persona; pick a date range; approve / override
writes land in `decision_outputs` + `decision_timeline`.

**EDMS schema reads/writes this session:**
```
vw_pipeline_status           — application rollup
vw_<decision_id>_context     — per-decision projection
                               (FULL_ROW for underwriting_decision)
decision_outputs             — append-only versioned decision rows
                               (mode, outcome, confidence, boundary_rule,
                                reasoning JSONB, human_action, ...)
decision_timeline            — state-transition log
                               (from_state, to_state, trigger,
                                transition_at, pipeline_position)
entity_states                — applicant + loan summary
                               (mid_credit_score, ltv, dti_back,
                                loan_amount, status, borrower JSONB,
                                loan_terms JSONB, ...)
```

**Still pending (next session):**

  1. Migrate the rich panels (policy / evidence / audit /
     learnings / atomic-steps / upstream-status / read-permissions)
     onto EDMS reads. Today the EDMS path returns empty defaults
     for these; templates guard with `{% if %}` so the page still
     renders, but the audit-trail story is incomplete.
  2. Run the cron runner end-to-end against the full ~8,740-app
     EDMS dataset and verify the connection-resilience path holds
     up over a multi-hour batch.
  3. Smoke the persona Approve / Override flow on `/workbench`
     against live EDMS (read paths verified; mutation paths not
     yet exercised on real data because doing so on the live demo
     would corrupt the seed).
  4. UI: make the persona detail screen surface upstream decisions
     (already returned by the route but not yet rendered).
  5. Wire the Audit page's CSV export through StreamingResponse
     for the 100k+ row case — current export is fine for
     <10k rows but loads the whole result set into memory.

### Session 11 — May 4 2026

**Theme:** PRD review + multi-source income verification track.
**Commits:** 4 (`723411c`, `d90930d`, `0febead`, `4f661b5`). All pushed.

**What landed:**

PRD review + repair (`723411c`)
  - Front matter (lines 2–84) was an exploded H1 block (every line
    started with `#` → ~80 stacked H1s). Replaced with a single H1
    title + bold version line + Session-deltas as proper bullets.
  - §23 (Audit Engine) prose blocks (schema / four-checks / outcomes /
    store-tables / report-types / file-structure / hard-rules) all
    wrapped in fenced code blocks so significant indentation renders.
  - §23.8 stale TODO markers replaced with ✅ status (every audit
    file actually shipped in Session 10). Added missing alerts.py /
    pii_log.py / adverse_action.py / export.py rows.
  - §17 file-structure tree got the synthetic factory + Session-10
    test files + audit submodules.
  - 227 → 350 test count reconciled across 5 sites; preserved
    Session-9-ended-at-227 as historical context.
  - §20 resume prompt rewritten to Session 10 reality (was frozen at
    Session 6 — "STEPS 1-11 complete, STEP 14 TODO").
  - Orphan "8 core/audit/" line removed from bottom of TIER 6 (TIER 4
    already documents audit completion in detail).
  - §23 heading style: `## 23. Audit Engine` (sentence case) →
    `## 23. AUDIT ENGINE` (matches every other §heading).

Brainstorm 1 — EDMS document collation
  Real EDMS pain: docs arrive with mismatched join keys (W-2 has
  employee_id, bank statement has account_id, tax return has SSN-
  last-4, pay stub has name only). Need entity resolution to attach
  documents to the right Application before any persona reads them.
  Architectural answer: an `evidence_collation` decision as a DAG
  node (NOT inside the retriever) so the trace shows every match
  decision with its confidence + basis. Slice not yet shipped.

Brainstorm 2 — multi-source income verification
  Real flow: TWN / Argyle / Plaid / VOE / 1099 / bank deposits each
  return partial pictures with different schemas + employer-name
  variants ("ACME CORPORATION INC" vs "Acme Corp"). Underwriter
  reconciles across providers, checks 24-month continuity, escalates
  to manual VOE on partial coverage. Architectural answer: two-stage
  pattern — STAGE A parallel `VerificationAttempt` writes via
  EntityHydrator (preserves multi-provider data); STAGE B
  `employment_reconciliation` decision joins attempts into an
  EmploymentTimeline, drives `income_verification` downstream.

Slice 1 — `employment_continuity/` seed scenario (`d90930d`)
  Demonstrates the gap concretely. 8th seed scenario.
  - Two `payroll_received` events: TWN-style "ACME CORPORATION INC"
    @ $100k + Argyle-style "Acme Corp" @ $92k. Both verified.
  - EDMS holds an unattached Beta Inc W-2 (`applicant_id=null`,
    `status=ocr_extracted`) representing a 16-month prior-employer
    coverage gap.
  - Pending 2022 1099 representing the gig year that would normally
    trigger 4506-C tax-transcript fetch + send_back outcome.
  - `scripts/smoke_employment_continuity.py` enumerates every gap
    the system can't currently see.

Slice 2 — VerificationAttempt + EmploymentRecord + new decision (`0febead`)
  - Two new ObjectTypes in `core/ontology/object_types.py`:
    - `VerificationAttempt` — append-only per (provider, applicant,
      time). Captures source, employer_name_raw, gross_amount,
      period_start/end, status. Preserves multi-provider data that
      IncomeProfile's last-write-wins merge collapsed.
    - `EmploymentRecord` — reconciled employer-window per applicant.
      Output projection of the new decision (SHARED-store writeback
      is a follow-up).
  - `EntityHydrator._hydrate_payroll` now writes ONE
    VerificationAttempt per `PayrollReceivedEvent` IN ADDITION to
    merging into IncomeProfile (so two payroll feeds for the same
    applicant land as two distinct rows; IncomeProfile keeps the
    existing last-write-wins shape — no ripples).
  - New decision `employment_reconciliation` in `decisions.yaml`.
    Initially mode=shadow. PolicyVersion auto-seeded by the existing
    YAML seeder (no seeder change).
  - `domains/lending/personas/employment_reconciliation.py` —
    deterministic offline reasoning. Joins attempts by canonical
    employer name (entity-suffix normalization → "ACME CORPORATION
    INC" and "Acme Corp" both resolve to "acme") and overlapping
    date ranges. Computes 24-month continuity coverage, max gap,
    employer-name match vs stated, comp drift, stated/verified drift.
    Produces reconciliation_status + employer_records[] +
    structured remediation flags (manual_voe_required,
    gap_letter_required, tax_transcript_required).

Slice 3 — wire upstream of income_verification + mode_router fix (`4f661b5`)
  - `employment_reconciliation` mode shadow → recommend.
  - `income_verification` becomes type=dependent, depends_on
    [employment_reconciliation]. Moved from `parallel_independent`
    to its own `sequential_dependent` wave.
  - `income_verification` persona refactored — reads
    `upstream_payload(bundle, "employment_reconciliation")` as the
    primary signal. Confidence anchored to reconciliation_status
    (auto_verified=0.95, partial-clean=0.95, partial-conflict=0.82,
    conflict=0.55, missing=0.4). Verified income aggregated from
    reconciled employer_records. Pass-through of remediation flags
    into IV's own output_payload.
  - `income_verification` boundary in YAML updated:
    automate_if requires `reconciliation_status in [auto_verified,
    partial]`; escalate_if fires on `[conflict, missing]`.
  - **mode_router writeback fix** — recommend / human_approval modes
    now writeback to scoped store IN ADDITION to enqueueing for
    human review. Without this, downstream decisions saw empty
    upstream_outputs because only `auto_execute + ALLOW` triggered
    writeback. Latent gap masked by entity-store fallbacks (DTI etc.
    fall back to IncomeProfile). The fix means upstream payloads
    always flow.

**Demo scenario after slice 3:**
```
employment_continuity (TWN $100k vs Argyle $92k, both verified)
  employment_reconciliation → RECOMMEND
    status=partial, comp_drift=8.3%, manual_voe_required=True,
    employer_windows=1 (canonical "acme")
  income_verification        → RECOMMEND
    verified=$96k (avg), confidence=0.84, status=partial passed
    through. (Was: ALLOW with 0.95 confidence on $92k from one
    provider — multi-provider conflict was invisible.)
```

**Tests + smokes:**
  351/351 unit tests green (~7s). All 7 smokes green
  (employment_continuity, replayer, audit_reports, ui_all_panels,
  persona_workbench, fha_scenario, workbench).

**On the plate (next session, ranked by leverage):**

  1. Persist EmploymentRecord rows to SHARED store. Today they live
     only in the reconciliation trace's output_payload. ~1h.
  2. Extend IncomeDeclaredEvent with `stated_employer` so
     employer_name_match_confidence stops reading 0.0 in real data.
     Touches event schema + hydrator + 8 fixture CSVs. ~30min.
     Recommendation: bundle 1 + 2 in one slice (~1.5h).
  3. Structured HumanQueue sub-tasks — manual VOE / tax transcript /
     gap letter as separate queue items, not flat booleans. ~3h.
  4. send_back outcome (PRD §13 "planned"). Async path for 4506-C
     tax-transcript fetch + applicant gap-letter request. ~3-4h.
  5. EvidenceLink ObjectType + evidence_collation decision (EDMS
     entity resolution from brainstorm 1; only the gap-demo
     scenario has shipped). ~3-4h.
  6. Real Anthropic persona path (one persona smoke with
     cache_control on system block; journal side-by-side with
     offline path). ~30min.
  7. Real PullConnectors — TWN / Argyle / Plaid Income with
     RecordedResponse fixtures. ~½ day each.
  8. Real-backend verification — Postgres + Redis swap. Routine
     `trig_013QhFbYJaViJfNybCbr3KUX` was scheduled May 3; status
     not checked.
  9. Async pass on `ui/views.py` — current sync `_records` walks
     block the Postgres swap.

---

### Session 10 — May 4 2026

**What was built (PRD §23 Audit Engine, end to end):**

PRD §23 spec landed
  Section 23 (9 subsections — 23.1 What it is through 23.9 Hard rules)
    appended to docs/PRD.md. Defines AuditRecord schema, four checks
    (compliance / security / ethics / fairness), pipeline position, store
    tables, six report types, file structure, and four hard rules.
  §17 file-structure block added for core/audit/.
  §19 build sequence row 8 — "Build after core/trace; engine.py first
    then four checkers then schema.sql; AuditRecord must be created
    before any writeback executes."

core/audit/ scaffold
  schema.py — AuditRecord Pydantic v2 with decision / compliance /
    security / ethics blocks. Sub-models: PolicyApplied, AccessRecord,
    FairnessFlag, CheckResult.
  compliance_checker.py — regulation-tag coverage, consent gate,
    TRID/RESPA disclosure timing, data-source ↔ tag alignment.
    DEFAULT_REGULATION_TAGS by decision_id.
  security_checker.py — PII permission gating (no permissions for
    PII fields → FAIL), velocity anomaly (N reads in window → WARN),
    encryption requirement for confidential/restricted data.
  ethics_checker.py — protected-attribute leak detection (any attr
    in used + not in excluded → FAIL), bias_score thresholds (0.15
    monitoring / 0.30 action per PRD §23.4).
  fairness_checker.py — segment vs overall approval-rate deviation,
    flips disparate_impact_flag at >15% drift.
  engine.py — AuditEngine.evaluate(trace, **inputs) fans out four
    checkers via asyncio.gather, aggregates worst-of statuses.
  store.py — AuditStore Protocol + InMemoryAuditStore (append-only,
    duplicate audit_id raises) + PostgresAuditStore (asyncpg pool +
    JSONB codec, mirrors warn/fail per-check status into audit_flags).
  schema.sql — three append-only tables (audit_records,
    audit_access_log, audit_flags) with self-FK supersession,
    partial index on warn/fail, and audit_flags resolution columns.

atomic_tool gate (PRD §23.9 audit_record_required_before_writeback)
  AtomicTool.run() now invokes engine.evaluate + store.write between
  trace_write and mode_route. If the gate raises, mode_route never
  runs — no writeback fires without an AuditRecord. Audit inputs
  derived from the bundle + system-wide store reads:
    consent_status from Applicant.consent_obtained
    protected_attrs detected across bundle ∪ Applicant entity (system-
      wide so leaks fire even when the running decision can't read
      Applicant)
    disclosure_sent defaults True when ComplianceRecord isn't in
      this decision's read perms (only fails on POSITIVE evidence)
    regulation_tags + data_sources_used from per-decision defaults
    applicant_segment from CreditProfile.credit_band
  Platform.audit_engine + Platform.audit_store on the deps surface.

API + UI + reports
  api/routes — GET /audit/flags, /audit/application/{app_id},
    /audit/{audit_id} (with implicit access_log entry), POST
    /audit/{audit_id}/access. Route order ensures literal segments
    win over the {audit_id} path parameter.
  ui/views — list_audit_flags / list_audit_for_application /
    audit_record_detail (dry-runs all four checkers so the drilldown
    shows the same findings the engine produced).
  ui/templates/audit_flags.html — KPI cards (total / warn / fail) +
    per-flag table with 4-check status columns.
  ui/templates/audit_detail.html — 4-check strip with findings + 4
    detail panels (decision / compliance / security / ethics) +
    access-log section.
  base.html — "Audit flags" entry on the top nav.
  core/audit/reports/ — 6 generators per PRD §23.7 (hmda monthly,
    fair_lending quarterly with EEOC 4/5 ratio, ai_trail weekly,
    security daily, bias weekly, overrides weekly). All return the
    same Report shape (name + cadence + window + summary + rows +
    flags).

domains/lending/synthetic/ + smoke
  factory.build_synthetic_applicants(n, seed=42) — deterministic
    profile generator with weighted draws (4 segments, 7 states,
    4 loan types), 3 audit overlays (consent_missing /
    protected_attr_leak / no_disclosure), 5 EDMS docs per profile
    (W-2, paystub, 1040, ID, appraisal) with W-2 + appraisal Claims.
  factory.inject_into_platform — bulk-seeds via store.set; bypasses
    the event sink for performance (24 applicants in <2s).
  scripts/smoke_audit_reports.py — boots platform, generates 24
    synthetic applicants, runs DAG, generates all 6 reports. Status
    mix: 264 pass / 24 fail (matches 1 consent_missing + 1
    protected_attr_leak × 12 decisions each).

Bug catchers fired during writing
  HMDA had application_form listed as expected data source — every
    lead_scoring audit warned. Fixed: HMDA is reporting, not data
    sourcing — dropped from DEFAULT_DATA_SOURCES_BY_TAG.
  age was in Applicant entity AND in PROTECTED_ATTRIBUTES — every
    applicant tripped ethics. Fixed: factory keeps age as profile
    metadata, doesn't write it to the entity.
  disclosure_sent_from_bundle defaulted False when ComplianceRecord
    wasn't in scope — every TRID/RESPA-tagged decision failed
    everywhere. Fixed: default True; fail only on positive evidence.
  Bundle-only protected attr scan missed leaks on decisions whose
    read perms exclude Applicant. Fixed: AtomicTool now reads
    Applicant directly via the resolver + store for audit input
    (system-wide), not via the per-decision bundle.

Tests (294/294, ~8s)
  tests/core/audit/test_engine.py        29 — schema, 4 checkers,
    engine fan-out + aggregation, store invariants.
  tests/core/audit/test_reports.py       14 — six generators with
    aggregation correctness + EEOC 4/5 + bias action threshold.
  tests/api/test_routes.py                +9 — audit endpoints + UI
    rendering smoke (mount_ui=True).
  tests/ui/test_views.py                  +4 — audit view-models.
  tests/domains/lending/test_seed_scenarios.py +4 — AuditGateTests
    (12 records per happy_path, decision provenance, executed-only
    coverage, append-only invariant).
  tests/domains/lending/test_synthetic.py 10 — factory determinism
    / distribution / overlay proportions + 3-applicant integration
    suite asserting clean = pass / consent_missing = compliance fail
    on every decision / leak = ethics fail with race in
    protected_attrs_used and not in excluded.

Deferred items closed in same session (slices 5–8):
  ✓ Embedded audit panel on decision + persona detail pages —
    _audit_panel_for_trace + decision.html section + _persona_detail.html
    compact card. Tone-aware (emerald/amber/rose), 4-check status grid,
    "full record →" link to /ui/audit/{id}.
  ✓ Alert sink — AlertSink Protocol + InMemoryAlertSink + LoggingAlertSink
    in core/audit/alerts.py. AuditEngine fires synchronously on FAIL; sink
    errors swallowed so the audit gate stays up. Wired through Platform.
    PRD §23.9 audit_fail_alerts_compliance_immediately ✓
  ✓ HMDA by_state — atomic_tool reuses _policy_scope_hints to plumb
    property_state into context_used + execution_result; falls back to
    a system-wide Application read when per-decision perms exclude it.
    Smoke now shows by_state populated across 7 states.
  ✓ Store-level PII logging — core/audit/pii_log.py PII_FIELDS +
    PIIAccessEntry + PIIAccessLog Protocol + InMemoryPIIAccessLog +
    detect_pii_fields. LendingContextStore.get() instrumented best-
    effort. PRD §23.9 pii_access_always_logged ✓ (456 PII reads
    logged on the 24-applicant smoke). API surface:
    /audit/pii-log/recent + /audit/pii-log/application/{id}.

Slices 9–11 (same session, after ✓ items above):
  ✓ Persona-input completeness — synthetic factory now writes the
    field names personas actually read (credit_score not score,
    watchlist_match not watchlist_hit, income_confidence_score,
    payroll_verified, employment_type, etc). Equity multiplier tuned
    per credit band so LTV outcomes track real underwriting. Jumbo
    loans only assigned to super_prime + reduced base from $1.2M →
    $800k so DTI stays under 0.50 BLOCK. Income tier bumped for
    super_prime/prime. fair_lending now treats both ALLOW + RECOMMEND
    as approvals (matches real ECOA / FHA originations semantics).
    Smoke output: underwriting 21 recommend / 3 block (was 4 / 20),
    fair_lending 87.5% overall approval rate, EEOC 4/5 flag fires
    on subprime as expected.
  ✓ Adverse action notice generator — core/audit/adverse_action.py
    with 13 canonical reason codes (FCRA §615), is_adverse_action()
    gate (BLOCK / late-stage ESCALATE / compliance|fraud FAIL),
    generate_notice(record, trace, applicant_value) walks
    policy_reasons + check failures + decision-type defaults.
    GET /audit/{audit_id}/adverse-action returns 200/409/404.
    UI: rose alert + "generate notice →" link on /ui/audit/{id}
    when is_adverse_action is true. PRD §19 TIER 4 ✓
  ✓ Audit log export — core/audit/export.py streams CSV (34-column
    header frozen for examiner ingestion) + JSONL (re-ingestable).
    Filters: decision_type / status / after / before. Both stream
    via FastAPI StreamingResponse. GET /audit/export.csv +
    /audit/export.jsonl. PRD §19 TIER 4 ✓

Slice 12 (same session — closes PRD STEP 12):
  ✓ Outcome tracker — core/trace/outcome_tracker.py with OutcomeType
    enum (funded / withdrawn / declined_by_borrower / default /
    charged_off / paid_in_full / modified). OutcomeRecord append-only
    with both recorded_at AND occurred_at so late-arriving signals
    (default 6mo after funding) become first-class. OutcomeTracker
    Protocol + InMemoryOutcomeTracker (raises on duplicate id).
    DecisionOutcomeCorrelation + correlate() pure helper joins a
    decision trace with outcome trajectory — picks final outcome,
    computes days_to_first_outcome (occurred_at if present, else
    recorded_at). API: POST /outcomes, GET /outcomes/application/{id},
    GET /outcomes/application/{id}/correlate?decision_id=…
    9 unittests + 4 API integration tests. PRD STEP 12 ✓

Still deferred:
  - PostgresAuditStore + Postgres PII log + alert sink + Postgres
    audit export production swap — code paths exist; tests stay on
    InMemory. Run via docker-compose up postgres when ready to flip.
  - Real critic agent (PRD TIER 5) — current critic is a heuristic
    stub; production needs Anthropic-backed implementation with rubric.
  - Reflection ↔ outcomes integration — outcome_tracker shape is in
    place but ReflectionService.capture() doesn't yet read latest_for_
    application to score AgentLearning quality. Small follow-up.
  - Quarterly FFIEC submission scheduling (PRD TIER 4 last item) —
    cron + S3 archive on top of /audit/export.csv.
  - API auth (PRD TIER 3) — OIDC / OAuth2 / API key + per-user
    scoping. Today the API has no auth.
  - Multi-tenancy (PRD TIER 3) — tenant_id through Lineage + every
    read scoped by tenant. Schema migration to add tenant_id column.
  - Real EDMS connectors (PRD TIER 2.5) — Encompass / DocuTech +
    OCR + claim extractor. Synthetic factory + smoke prove the shape.

Session 10 final tally:
  19 commits. 350/350 tests green (~9s).
  Audit Engine end-to-end (PRD §23): atomic_tool gate + alert sink +
  property_state plumbing + store-level PII logging + embedded UI
  panels + six §23.7 reports + ECOA/FCRA §615 adverse action notices +
  CSV/JSONL export + outcome tracker (STEP 12). PRD §19 TIER 4
  substantially closed (HMDA + fair_lending + adverse_action +
  audit_log_export all done). Synthetic factory tuned to produce
  realistic outcome distributions (87.5% fair_lending approval rate
  with EEOC 4/5 disparate-impact flag firing on subprime).

### Session 9 — May 3 2026

**What was built (5 streams + 1 fixture set; all smokes green):**

STREAM C — Policies as Type-2 versioned shared object (3 phases)
  Phase 1: Policy + PolicyVersion ObjectTypes; PolicyStore facade over
    LendingContextStore (`core/policy_engine/store.py`); decisions.yaml
    seeder writes one Policy + one PolicyVersion per decision under
    agency=lender_overlay (`core/policy_engine/seeder.py`).
    Idempotent (preserves created_at/ingested_at on re-runs).
  Phase 2: PolicyEvaluator.evaluate became async; takes
    policy_store / at / agency_chain / product / state. Resolves
    active PolicyVersion FIRST so every return path (including
    fraud_block_stops_pipeline / contamination_guard / boundary
    matches) carries the version stamp. DecisionTrace +
    PolicyDecision gained policy_version_id + policy_chain.
    AtomicTool wired (both pre and post policy_check); DAGExecutor
    + Replayer thread evaluation_at = replay_at end-to-end.
  Phase 3: _AGENCY_CHAIN_BY_LOAN_TYPE in atomic_tool —
    conforming → [lender_overlay, freddie]; fha → [lender_overlay,
    fha]; va/usda likewise; jumbo/non_qm → [lender_overlay].
    AtomicTool.run derives chain from loan_type unless caller
    supplied one. _policy_scope_hints pulls loan_type from the
    Loan in the bundle.

STREAM E v0 — Knowledge Context Layer
  Document + Claim ObjectTypes (`core/ontology/object_types.py`).
  KnowledgeStore facade (`core/knowledge/store.py`) — DocumentRecord +
    ClaimRecord typed via Pydantic. put_document / put_claim /
    verify_claim / reject_claim / list_*. Type-2 supersession +
    lineage from the underlying durable.
  Retriever Protocol + MetadataRetriever (`core/knowledge/retriever.py`)
    — filters claims by the doc_type → decisions matrix in
    knowledge_base.json#document_types (14 doc types with
    feeds_decisions + claim field names). verified_only=True default.
    PgVectorRetriever / QdrantRetriever / HybridRetriever stubbed as
    comments — STREAM E2.
  ContextBundle gains claims (simple field→value), claim_records (full
    provenance), documents. ContextBuilder.build() fans out to the
    Retriever in addition to the resolver path; Document/Claim/Policy/
    PolicyVersion ObjectTypes are excluded from bundle.objects (own
    lanes).
  AtomicTool._policy_context layers claims between bundle objects
    (lower) and output_payload (highest). Boundary clauses can read
    claim values directly.
  Seed scenarios got mock Documents + Claims:
    happy_path: 2 verified Documents (W-2, appraisal) + 3 verified
      Claims (verified_income, employer, appraised_value).
    contamination: 1 Document with low ocr_confidence + 1 pending
      Claim (exercises verified_only filter).
  Pre-existing bug surfaced: api/deps._default_resolver returns ALL
    FraudProfile/CreditProfile/IncomeProfile records when entities
    have application_id=None (cross-contaminates when scenarios
    share a platform). Fix tracked under TIER 1 in PRD §19; not
    blocking.

STREAM A — Per-persona workbench (12 routes)
  /ui/personas index page — 12 persona cards grouped by owner_team.
  /ui/personas/{decision_id} workbench — header tabs (siblings within
    owner_team) + agent identity + time-range selector + 4-KPI strip
    (Decisions completed · Pending review · Auto-decided % · Avg time
    to decide on human reviews) + Workbench/History/Analytics tabs +
    two-column layout (queue OR recently-completed for auto personas
    on the left, focused-app detail on the right).
  POST .../ack — positive ack (HumanReview overridden=False).
  POST .../decline — overrides outcome to BLOCK + captures
    AgentLearning via existing reflection.capture path.
  POST .../send_back — stub for the planned send_back outcome
    (PRD §13). Returns a flash; no backend yet.
  Designed against user-supplied screenshot (Encompass-class layout).

UI surfacing — Policy + Evidence panels on persona detail AND original
  decision detail pages. _policy_panel resolves PolicyVersion + Policy
  by id; renders agency, source_revision, valid_from/valid_to,
  multi-version chain. _evidence_panel walks KnowledgeStore for
  verified Claims with provenance (source doc + page + verifier +
  extraction confidence) gated by the doc_type matrix.

STREAM B — FHA scenario added (5th scenario)
  domains/lending/seed_events/fha/ — FTHB profile, $289.5k FHA loan
    on $300k purchase in TX, 96.5% LTV, 665 credit, salaried $72k.
  seed_fha_demo_policies — hand-crafted FHA agency PolicyVersion for
    ltv_assessment with FHA-specific block_if (ltv > 0.965 vs the
    overlay's 0.97). Wired into `_bootstrap_demo` so the UI starts
    with both seeders run + 5 scenarios.
  First end-to-end proof of multi-agency policy chain:
    ltv_assessment trace.policy_chain = [
      "lender_overlay::ltv_assessment::v1",
      "fha::ltv_assessment::v1"
    ]
    Chosen policy_version_id = lender_overlay (overlay-first).
  Verified the FHA seed didn't pollute non-FHA scenarios — happy_path
    ltv_assessment still has 1-entry chain.

PRD update (docs/PRD.md → v0.9)
  §1 header: Session 9 deltas summary.
  §4 pipeline diagram: added Knowledge Context Layer as a sibling
    input to the Context Agent.
  §5 hard rules: added no_unverified_claim_without_explicit_optin
    and doc_type_permission_via_matrix.
  §9.2 ObjectTypes: added Document, Claim, Policy, PolicyVersion.
  §10 storage: added rows for the new types; reframed decisions.yaml
    as the lender_overlay seed.
  §17 file structure: added core/policy_engine/store.py +
    seeder.py, core/knowledge/, all new smoke scripts.
  §19 build sequence: STREAMs A/B(partial)/C/E v0 logged as complete;
    new TIER 2.5 — STREAM E2 block (EDMS adapter, OCR pipeline,
    claim extractor, document upload UI, vector retriever, hybrid
    retriever).

**Smoke suites verified end-to-end (all green):**
  smoke_replayer        STEP 13 + replay parity through STREAM C+E
  smoke_policies        STREAM C phase 1 (5 phases — seed +
                        idempotency + point-in-time + supersession)
  smoke_policy_evaluator STREAM C phase 2 (5 phases — outcome
                        parity, version stamping, replay)
  smoke_knowledge       STREAM E v0 (6 phases — doc-type matrix,
                        verified-only default, verify_claim flips)
  smoke_persona_workbench STREAM A (12 phases — index, all 12
                        personas, drill-down, ack/decline/send-back,
                        Policy + Evidence panels, agency_chain)
  smoke_fha_scenario    STREAM B FHA (5 phases — multi-agency chain
                        on ltv_assessment; FHA didn't leak into
                        non-FHA scenarios)
  smoke_workbench       9 owner-team workbenches × 4 scenarios
  smoke_ui_all_panels   12 persona panels × 3 scenarios

**Architectural state at end of Session 9:**

The Knowledge Context Layer wiring is in place end-to-end:
  Mini Context Stores ──┐
                        ├──► Context Agent ──► Atomic Tool ──► Trace
  Knowledge Context ────┘
    EDMS adapter (stub) · Claim store · MetadataRetriever ·
    permission filter via doc_type matrix

Decision agents read `bundle.claims["verified_income"]` directly. The
trace stamps `policy_version_id`, `policy_chain`, and (when
applicable) human_review. Replay correctness is point-in-time across
both axes (durable shim pins `at`; PolicyStore.active_version filters
by valid_from / valid_to; KnowledgeStore reads via the same shim).

Same code ships at credit-union scale and Rocket-class scale — the
Retriever Protocol abstracts metadata vs vector retrieval; only the
implementation behind it changes.

**Still pending (from PRD §19 TIER 1 + 2.5):**
  - More seed scenarios (jumbo, VA, USDA, cash-out, investment, etc.)
  - tests/ pytest suite (foundational — replaces smokes for CI)
  - Real-backend verification (Postgres + Redis swap)
  - Async pass on ui/views.py (currently sync _records walks)
  - Postgres-aware resolver
  - Pre-existing FraudProfile cross-contamination resolver fix
  - DecisionTrace.claim_provenance field (which claim_ids drove
    the outcome — closes the audit loop)
  - UI: full /ui/policies route to inspect a PolicyVersion's clauses
  - UI: claim verification queue (pending claims → underwriter
    review → verify/reject)
  - STREAM D: real agency-guideline connectors
  - STREAM E2: real OCR + extraction + EDMS adapters + pgvector

**Session 9 — additional work landed late session (all 210 tests green):**

  STREAM B continued — 2 more seed scenarios:
    domains/lending/seed_events/jumbo/ — $1.2M, loan_type=jumbo,
      agency_chain=[lender_overlay] only.
    domains/lending/seed_events/va/ — $425k, loan_type=va,
      agency_chain=[lender_overlay, va] (no VA overlay seeded yet).
    Bootstrap seeds 7 scenarios total now.

  Pre-existing FraudProfile cross-contamination bug FIXED:
    api/deps._default_resolver now looks up the Application's
    applicant_id and filters Applicant-bound entities (Applicant,
    FraudProfile, CreditProfile, IncomeProfile) by matching applicant_id.
    Previously matched on application_id=None as a wildcard, leaking
    cross-application data.

  UI polish round (cosmetic only, no schema impact):
    - Loan-type capitalization: VA / FHA / Conforming / Jumbo / Non-QM
      via LOAN_TYPE_LABELS map.
    - Deterministic friendly-name generation from applicant_id
      (_friendly_name_from_id helper).
    - Backdated scenario timestamps in _bootstrap_demo so persona
      workbench rows show "14m / 31m / 1h 3m ago" instead of all "0m".
    - Per-persona risk pill (_risk_pill_for_persona): credit_band
      for credit_assessment, fraud_score for fraud_screening, ltv for
      ltv_assessment, dti for dti_calculation, etc.
    - Auto-decided KPI fix: counts only mode=auto_execute AND
      outcome=allow AND human_review=None — reconciles with Pending
      review (1 + 6 = 7).
    - Outcome pill + amber "Pending review" badge + sort-queued-to-top
      on persona-workbench rows.

  TIER 1 — pytest test suite (210 tests / 9 modules):
    tests/core/context_store/test_in_memory.py        9 (existing)
    tests/core/policy_engine/test_loader.py          15
    tests/core/policy_engine/test_store.py           19
    tests/core/policy_engine/test_seeder.py          10
    tests/core/policy_engine/test_evaluator.py       17
    tests/core/decision_agents/test_atomic_tool.py   15
    tests/core/trace/test_reflection.py              14
    tests/core/knowledge/test_store.py               16
    tests/core/knowledge/test_retriever.py           10
    tests/core/simulation/test_replayer.py           17
    tests/api/test_routes.py                         13
    tests/ui/test_views.py                           40
    tests/domains/lending/test_seed_scenarios.py     15
    Pattern: stdlib-only unittest.IsolatedAsyncioTestCase, explicit
    sys.path injection per file. No pytest dependency. Discovered via
    scripts/run_tests.py which enumerates TEST_MODULES. ~3 sec total.

  Bug fixes surfaced by tests:
    PolicyEvaluator._check_hard_rules ordering: generic
      upstream_block_propagates_to_dependents check was firing BEFORE
      specific fraud_block_stops_pipeline / compliance_block_stops_closing,
      so traces stamped the generic reason. Reordered: specific rules
      check first. PRD §5 hard rules are now distinct in trace.policy_reasons.

  STREAM E2 starter — claim_provenance:
    ClaimProvenance Pydantic model in core/trace/trace_schema.py.
    DecisionTrace.claim_provenance: list[ClaimProvenance] — frozen
      list of evidence consumed at decision time.
    AtomicTool._freeze_claim_provenance(bundle) snapshots
      bundle.claim_records into the typed model. Decoupled from live
      KnowledgeStore so a later re-extraction can't retroactively
      change what the trace said.
    UI: _evidence_panel(platform, app_id, decision_id, trace=trace)
      prefers trace.claim_provenance over live retrieval; renders a
      "frozen at decision time" indigo badge so the operator sees
      the difference. Both persona detail and decision detail pages.

**Session 9 file inventory:**

  Added:
    core/policy_engine/store.py
    core/policy_engine/seeder.py
    core/knowledge/__init__.py
    core/knowledge/store.py
    core/knowledge/retriever.py
    domains/lending/seed_events/fha/{events.csv, bureau_responses.json,
                                     entities.json}
    domains/lending/seed_events/jumbo/{events.csv, bureau_responses.json,
                                       entities.json}
    domains/lending/seed_events/va/{events.csv, bureau_responses.json,
                                    entities.json}
    ui/templates/persona_index.html
    ui/templates/persona_workbench.html
    ui/templates/_persona_detail.html
    scripts/smoke_policies.py
    scripts/smoke_policy_evaluator.py
    scripts/smoke_knowledge.py
    scripts/smoke_persona_workbench.py
    scripts/smoke_fha_scenario.py
    scripts/run_tests.py
    tests/core/policy_engine/test_loader.py
    tests/core/policy_engine/test_store.py
    tests/core/policy_engine/test_seeder.py
    tests/core/policy_engine/test_evaluator.py
    tests/core/decision_agents/test_atomic_tool.py
    tests/core/trace/test_reflection.py
    tests/core/knowledge/test_store.py
    tests/core/knowledge/test_retriever.py
    tests/core/simulation/test_replayer.py
    tests/api/test_routes.py
    tests/ui/test_views.py
    tests/domains/lending/test_seed_scenarios.py

  Modified:
    core/ontology/object_types.py (added Document, Claim, Policy,
                                   PolicyVersion ObjectTypes)
    core/ontology/__init__.py (exports)
    core/policy_engine/__init__.py (re-exports)
    core/policy_engine/evaluator.py (async + policy_store + chain)
    core/context_store/context_builder.py (retriever wiring +
                                           knowledge/policy exclusions)
    core/decision_agents/atomic_tool.py (policy_store + agency_chain
                                         + claim layering)
    core/execution/dag_executor.py (evaluation_at parameter)
    core/simulation/replayer.py (policy_store + retriever_factory +
                                 evaluation_at)
    core/trace/trace_schema.py (policy_version_id + policy_chain
                                fields on DecisionTrace)
    api/deps.py (Platform gains policy_store + knowledge_store +
                 retriever; default builder constructs all)
    api/main.py (lifespan seeds policies + FHA overlays + 5 scenarios)
    api/routes.py (no changes)
    ui/views.py (persona workbench view-models + _policy_panel +
                 _evidence_panel + cross-page surfacing)
    ui/routes.py (persona workbench routes + ack/decline/send_back)
    ui/templates/base.html (Personas nav link)
    ui/templates/decision.html (Policy + Evidence sections)
    domains/lending/knowledge_base.json (document_types matrix —
                                         14 doc types)
    domains/lending/seed_events/__init__.py (FHA in SCENARIOS)
    domains/lending/seed_events/runner.py (FHA in APPLICATION_IDS)
    domains/lending/seed_events/happy_path/entities.json (W-2 +
                                                          appraisal docs)
    domains/lending/seed_events/contamination/entities.json (pending
                                                             W-2)
    docs/PRD.md (v0.8 → v0.9)

**Late-session slices (single autonomous run after "yes and don't wait
for my approval" — the user explicitly delegated continuous shipping):**

  TIER 1 expanded to 213 tests (was 154 mid-session):
    + tests/api/test_routes.py (13)        — POST /events, /trace/{id}, GET
                                             /decisions, POST /override,
                                             POST /applications/{id}/run via
                                             FastAPI TestClient
    + tests/ui/test_views.py (40)          — pure-fn helpers (loan-type label,
                                             friendly name, initials, risk pill,
                                             minutes-ago) + Platform-driven
                                             view-models
    + claim_provenance tests (3 added to test_seed_scenarios.py)
    + queue resolve tests (3 added to test_atomic_tool.py)

  STREAM E2 starter — DecisionTrace.claim_provenance:
    ClaimProvenance Pydantic model in core/trace/trace_schema.py.
    DecisionTrace.claim_provenance: list[ClaimProvenance] — frozen
      list of evidence consumed at decision time.
    AtomicTool._freeze_claim_provenance(bundle) snapshots
      bundle.claim_records into the typed model. Decoupled from live
      KnowledgeStore so a later re-extraction can't retroactively
      change what the trace said.
    UI: _evidence_panel(... trace=trace) prefers trace.claim_provenance
      over live retrieval and renders a "frozen at decision time"
      indigo badge so the operator sees the difference.

  PolicyVersion inspection UI:
    /ui/policies — agency-grouped index of all active Policy +
      PolicyVersion records.
    /ui/policies/{policy_version_id} — boundary clauses per clause
      type (block/escalate/recommend/automate), contamination_guard,
      hard_rules_subscribed, supersession chain (version history).
    Clickable policy_version_id in persona_detail + decision detail
      panels. Top nav adds "Policies".

  HumanQueue.resolve() + HumanQueueResolution:
    Protocol + InMemoryHumanQueue gain resolve(item_id, *, resolution,
      reviewer_id, reviewer_role, notes), find_open(*, application_id,
      decision_id), list_resolved().
    Persona workbench Approve/Decline endpoints now call resolve()
      after attach_human_review — items move from open → resolved
      with an audit receipt.
    queue_view returns dict with both open + resolved sections.
    queue.html shows "X open / Y resolved this session" with reviewer
      trail. PRD §19 TIER 3 HumanQueue.resolve() item resolved.

  Document inspection UI:
    /ui/applications/{id}/documents — all docs uploaded for an app
      with status pills, claim counts, OCR confidence, verifier.
    /ui/documents/{doc_id} — single doc detail: metadata + all
      extracted claims with full provenance (claim_id, source_page,
      extraction_method, extraction_confidence, verifier, extracted_at).
    Clickable source_doc_id in claim rows on persona_detail +
      decision detail templates.
    Application detail page gets "Documents →" link in header.

  Pending-claim verification UI:
    /ui/claims/pending — cross-app pending claim queue with verify
      and reject buttons. POST /ui/claims/{id}/verify and reject
      hit KnowledgeStore.verify_claim/reject_claim. Closes the
      contamination-scenario verification loop end-to-end:
      pending W-2 claim → operator clicks Verify → next
      income_verification run sees the claim in bundle.claims.

  Bug fix: PolicyEvaluator._check_hard_rules ordering. Generic
  upstream_block_propagates_to_dependents was firing BEFORE specific
  fraud_block_stops_pipeline / compliance_block_stops_closing, so
  traces stamped the generic reason. Reordered: specific rules check
  first. PRD §5 hard rules now distinct in trace.policy_reasons.
  Surfaced by tests/core/policy_engine/test_evaluator.py.

  Memory hygiene: feedback_collaboration_style.md updated with the
  user's stronger autonomy directive ("yes and don't wait for my
  approval"). Future sessions: ship continuously, don't re-ask after
  ack tokens, propose 2-3 next moves and pick one without permission.

**Final session 9 totals:**
  - 213 tests across 13 test modules; all green; ~2.5s total.
  - 8 smoke scripts; all green.
  - 7 seed scenarios (4 hard-rule + 3 loan-type).
  - PRD v0.9 reflects architecture; CONTEXT.md (this) reflects
    full session deltas including UI surfacing + tests.
  - UI fully navigable end-to-end:
      / → app list
      /ui/personas → persona index → workbench (per-persona)
      /ui/workbench → 9 team workbenches
      /ui/policies → policy index → version detail
      /ui/applications/{id}/documents → docs list → doc detail
      /ui/claims/pending → verify/reject queue
      /ui/queue → open + resolved
      /ui/applications/{id}/decisions/{decision_id} → original
        decision detail (now with policy + evidence panels)

**Tomorrow's concrete starting point:**

  Read CONTEXT.md (this file) + docs/PRD.md (v0.9). Then verify what
  exists:
    find . -name "*.py" -o -name "*.yaml" -o -name "*.json" -o -name "*.sql" \
      | grep -v .git | grep -v __pycache__ | sort

  Run test suite to confirm ground truth:
    python -X utf8 scripts/run_tests.py

  Boot UI:
    uvicorn api.main:get_app --factory --port 8000

  Outstanding work, ranked by leverage:

    Real Anthropic personas — personas have use_anthropic=True path
      but unproven. Single smoke that runs ONE persona on the LLM
      path with prompt caching, journal side-by-side with offline.
      Requires ANTHROPIC_API_KEY. ~30 min.

    STREAM D — first real agency connector. Freddie Mac selling-guide
      RSS pull → PolicyVersionIngestedEvent → EntityHydrator writes a
      new PolicyVersion. Replaces the seeded lender_overlay for
      conforming loans. ~2 hours.

    STREAM E2 real OCR + extraction — Claude Vision against synthetic
      W-2 image, structured-extract claims, lands them in
      KnowledgeStore with status=pending → operator verifies via
      /ui/claims/pending → claim becomes consumable. ~2-4 hours.

    Real-backend verification — Postgres + Redis swap. Apply
      schema.sql, swap PostgresDurableStore + RedisHotCache in
      api/deps.py, re-run all smokes against live DB. Routine
      trig_013QhFbYJaViJfNybCbr3KUX may have already done this on
      May 3 — check first.

    Persona offline reasoning tests — tests/core/decision_agents/
      test_personas/ for each of 12 personas' _compute_offline()
      against canonical fixtures. ~50 tests. Bug-catcher value
      vs. medium effort.

    UI: live-refresh of decision detail post-override (currently
      requires manual reload).

    UI: persona workbench History + Analytics tabs (currently
      stubbed).

---

### Session 1 — April 30 2026

**What was designed and built:**
- Full architecture defined across all 15 layers
- decisions.yaml — all 12 lending decisions, boundaries, hard rules, execution order
- Atomic tool pattern adopted (context + policy + decision in one call)
- WorkJournalEntry trace schema designed
- Independent critic agent designed with SelfReviewError
- context_window_days added per decision
- Reflection block added to decisions.yaml
- Claude Code generated: normalizer models, ontology classes, semantic resolver,
  policy evaluator, trace schema, critic agent

**What did NOT get pushed to GitHub:**
- core/normalizer/models.py — generated but not committed
- core/ontology/object_types.py — generated but not committed
- .env.example — generated but not committed

**Resume command (session expired — start fresh):**
```
/c/Users/bkgou/AppData/Roaming/npm/claude
```

---

### Session 2 — May 1 2026

**What was designed:**
- PRD v0.1 → v0.5 written and refined
- All 5 Mermaid diagrams embedded in PRD
- Domain pack concept formalised (lending as Domain Pack 1)
- Marketing domain explored — Decision Inventory document created
- Data Engineering Specification document created
- Ontology deepened — WHO vs WHAT-NOW distinction formalised
- Entity relationship map completed (Applicant → Application semantic links)
- Business entity storage model documented (Redis TTLs per entity)
- CONTEXT.md corrected — removed inaccurate build status

**No new code committed this session.**

---

### Session 3 — May 1 2026

**What was built (STEP 3 of the build sequence — context store):**
- `core/context_store/redis_cache.py`
  - `RedisHotCache` (production, via `redis.asyncio`) and `InMemoryHotCache`
    (asyncio-locked dict, same TTL semantics for tests)
  - Records serialize via `ContextRecord.model_dump_json()` so datetimes
    and UUIDs round-trip; both backends round-trip through JSON so model
    drift surfaces in unit tests, not in prod
  - Keys namespaced `context:{entity_type}:{entity_id}:{decision_id}`
    with `_shared` for shared writes — leaky key in one decision can
    never return another decision's bytes
- `core/context_store/postgres_store.py`
  - `PostgresDurableStore` (asyncpg) and `InMemoryDurableStore`
  - Append-only: `insert_record` finds the active row in a transaction,
    sets `superseded_at` + `superseded_by`, inserts the new row at
    `version + 1`
  - `tombstone()` writes a tombstone row that is itself superseded at
    insert, so a single `superseded_at IS NULL` predicate covers active
    reads — no special-casing in get_latest / get_at_time
  - `get_at_time(at)` for point-in-time replay (filters created_at and
    superseded_at against the requested timestamp)
  - JSONB codec installed at connection init so dicts/lists pass through
    asyncpg without manual `json.dumps`
- `core/context_store/schema.sql`
  - `context_records` — partial unique index on the active row,
    version uniqueness per scope, history index DESC, point-in-time
    index, self-FK on the supersession chain
  - `context_snapshots` — UUID array of constituent record_ids so a
    snapshot pins the exact rows the agent saw (replay-safe)
- `core/context_store/context_builder.py`
  - `ContextBuilder.build(application_id, decision_id, resolver)` —
    looks up decision spec, resolves readable object types via
    `decisions_that_read_it`, expands entity keys via caller-supplied
    resolver callback, snapshots the store, projects each entity through
    `ObjectType.to_context_bundle` to drop unauthorized fields
  - Returns typed `ContextBundle` with `upstream_outputs` keyed by
    upstream decision_id, `context_window_days` from the spec, and
    `snapshot_id` for trace replay
- `core/context_store/__init__.py` — re-exports all new public symbols

**Smoke-tested end-to-end with the in-memory backends:**
versioning, supersession chain, hot-cache hit, history ordering,
snapshot, tombstone + cache invalidation, ContextBuilder permission
filtering (verified: `fraud_screening` cannot see `CreditProfile`),
upstream decision output round-trip through the bundle.

**Hard rules backed in this session:**
- `no_context_without_lineage` — schema enforces `lineage JSONB NOT NULL`,
  base.py validates `written_by` and confidence at write time
- `no_agent_without_permissions` — ContextBuilder drops object types not
  in `decisions_that_read_it` and `to_context_bundle()` raises
  `PermissionError` for unauthorized projections

**Still pending (next session):**
1. Populate `requirements.txt` with `pydantic>=2`, `redis>=5`, `asyncpg`,
   `pyyaml`, `fastapi`, `structlog` so a fresh dev can install
2. Populate `docker-compose.yml` for local Redis + Postgres
3. Build STEP 4: `core/connectors/base.py` + mock CSV adapter
4. Build STEP 5: `core/decision_agents/` (base + atomic_tool + mode_router)

---

### Session 4 — May 2 2026

**What was built (STEPS 4, 5, 6 of the build sequence):**

- `core/connectors/` — STEP 4
  - `base.py` — `BaseConnector` (abstract), `PushConnector` (source
    initiates: webhooks / file drops / streams; subclasses implement
    `stream()`, framework drives `listen()`), `PullConnector` (we
    initiate: bureau / Plaid / AVM / TWN; subclasses implement
    `_perform()`, framework provides `fetch()` and `poll()`).
  - `EventSink` protocol — narrow contract every adapter routes to.
  - Single `emit()` pipeline forces every event through
    `normalize_event()` so a misbehaving adapter cannot corrupt the
    pipeline (only emits validated `BaseEvent`s).
  - `mock_csv.py` — push reference. CSV with cell coercion (`true` /
    `false` → bool, JSON-shaped cells decoded, empty → None). Drives
    seed-events fixtures and partner-drop replays through the same
    path.
  - `mock_http.py` — pull reference. `RecordedResponse` rows keyed by
    a query-derived key so 'Experian returned this XML for X' is
    deterministic across runs.
  - **BaseEvent gained `correlation_id` + `request_id`**
    (`core/normalizer/models.py`). Both optional UUIDs; the
    PullConnector stamps them automatically. Push events leave them
    null. This is what links a pull request to its eventual response
    event in the trace layer.

- `core/decision_agents/` — STEP 5
  - `base.py` — `DecisionAgent` ABC. Subclasses (one per persona, one
    per decision_id) implement `reason(bundle, policy)` returning an
    `AgentReasoning` (`WorkJournalEntry` + proposed_outcome +
    confidence + output_payload). Constructor enforces that
    agent_id + persona + decision_id are non-empty
    (no_agent_without_permissions).
  - `atomic_tool.py` — `AtomicTool.run(agent, application_id,
    resolver, upstream)` is the single bundled call from PRD §7. The
    flow: context_build (ContextBuilder) → policy pre-check
    (PolicyEvaluator) → agent.reason() → **final policy_check against
    agent's computed `output_payload`** (so boundary clauses like
    `dti <= 0.36` evaluate against what the agent actually computed)
    → critic.review() if risk_level ∈ {medium, high} → trace_write →
    mode_route. The LLM only sees `agent.reason()`; everything else
    is code-enforced. The policy engine's outcome wins over the
    agent's proposed_outcome — `_reconcile()` applies
    no_action_without_policy. SelfReviewError from the critic is
    re-raised; it's a config bug, not a soft signal.
  - `mode_router.py` — `RouteAction` enum, `HumanQueue` protocol +
    `InMemoryHumanQueue`. BLOCK always writes back so dependents see
    the block (upstream_block_propagates_to_dependents needs
    visibility). SHADOW writes nothing. RECOMMEND / HUMAN_APPROVAL /
    ESCALATE outcomes go to the queue. AUTO_EXECUTE + ALLOW writes
    back through `DecisionScopedStore` so the decision record lands at
    `decision:{application_id}:{decision_id}` for downstream
    `upstream_outputs`.

- `core/execution/dag_executor.py` — STEP 6
  - Walks `execution_order` from decisions.yaml in waves (parallel
    within, sequential across). Each wave parallelizes via
    `asyncio.gather`.
  - `InMemoryEventBus` (Protocol + reference impl) — emits
    `decision_started/completed/blocked/skipped/failed`,
    `record_updated`, `pipeline_halted` per PRD §13. Subscribers can
    register on event types; production swap is a real broker.
  - `fraud_block_stops_pipeline` enforced at the executor: if
    fraud_screening returns BLOCK, every later decision is recorded as
    `DECISION_SKIPPED` with reason `fraud_block_stops_pipeline` and
    `PIPELINE_HALTED` is published. Same wave as fraud_screening
    (compliance_check) is NOT short-circuited because they ran in
    parallel — that matches the PRD intent that compliance_check is
    independent.
  - Missing-upstream skip — if a dependent's `depends_on` isn't fully
    satisfied (because an upstream was skipped or failed), the
    dependent is skipped with reason `upstream_missing`. The policy
    engine still gets called for upstreams that DID run, so
    `upstream_block_propagates_to_dependents` fires through the
    normal path.
  - Returns `ExecutionResult` with completed / skipped / failed /
    halted + per-decision outcomes + per-decision serialized
    AtomicToolResult under `results` (mode='json' so it's
    JSON-serializable for the API layer to come).

- `core/trace/trace_writer.py` — supporting scaffold for the
  atomic_tool's trace_write step. `TraceWriter` Protocol +
  `InMemoryTraceWriter`. Enforces append-only by raising on duplicate
  trace_id. Production swap will be a Postgres-backed writer; the
  protocol is intentionally narrow (`write` / `get` /
  `list_for_application`).

**Smoke-tested end-to-end (in-memory backends only):**
- `AtomicTool.run()` against `income_verification` agent with a clean
  payload → outcome=allow, mode=human_approval routes to queue,
  critic verdict=approved, trace persisted.
- `AtomicTool.run()` against `dti_calculation` agent with an upstream
  `income_verification` BLOCK → final_outcome=BLOCK,
  action=BLOCK, decision record written for downstream propagation.
- `DAGExecutor.run_application()` happy path → all 12 decisions
  complete with outcome=allow, 0 skipped, 7 record_updated events
  fired (one per AUTO_WRITEBACK; human_approval modes queued
  instead).
- `DAGExecutor.run_application()` fraud-block path → fraud_screening
  blocks, halted=True, halt_reason=fraud_block_stops_pipeline, 7
  dependents (dti_calculation, ltv_assessment, product_eligibility,
  rate_pricing, underwriting_decision, approval_routing,
  closing_readiness) correctly short-circuited.

**Real-backend verification is scheduled — not yet executed.**

A one-time remote agent fires Sun May 3 2026 at 9am PT to:
1. Bring up Postgres + Redis (docker-compose preferred, apt fallback),
2. Apply `core/context_store/schema.sql`,
3. Re-run the same DAGExecutor smoke against `PostgresDurableStore` +
   `RedisHotCache` (real connections, not the InMemory variants),
4. Update CONTEXT.md with the result + any deltas vs in-memory,
5. Open a PR titled "Session 4 — STEP 4-6 verified against real
   Postgres/Redis" on branch `session-4-real-backend-verification`.

Routine ID: `trig_013QhFbYJaViJfNybCbr3KUX`
Manage: https://claude.ai/code/routines/trig_013QhFbYJaViJfNybCbr3KUX

If GitHub auth isn't connected by then the agent will push the branch
and print the manual PR-open URL + full diff in the run log instead of
opening a PR. Connect via `/web-setup` or the GitHub App if needed.

**Hard rules backed in this session:**
- `no_action_without_policy` — `AtomicTool._reconcile()` lets the
  policy engine win over the agent's proposed_outcome. The agent's
  outcome is informational; policy is authoritative.
- `fraud_block_stops_pipeline` — `DAGExecutor` short-circuits all
  later waves when fraud_screening blocks; emits PIPELINE_HALTED.
- `compliance_block_stops_closing` — `PolicyEvaluator._check_hard_rules`
  already covered this; the executor passes the upstream summary
  through so closing_readiness blocks via the normal policy path.
- `upstream_block_propagates_to_dependents` — same path as compliance.
  The mode router writes the BLOCK record to the store so downstream
  policy evaluations can see it.
- `no_execution_without_trace` — every AtomicTool.run() writes one
  DecisionTrace before mode_route fires. No trace, no writeback.

**Still pending (next session):**
1. Wait for / review the Sunday PR from the scheduled agent. If the
   real-backend smoke fails, look at what differs from the in-memory
   path (likely candidates: asyncpg JSONB codec, Redis JSON
   round-trip, schema.sql apply on a fresh DB).
2. Build STEP 7: `api/` — FastAPI surface.
3. Build `core/trace/reflection.py` — human override → `AgentLearning`.
4. Build `core/policy_engine/loader.py` — single load+validate path.
5. Build `domains/lending/personas/` — 12 concrete DecisionAgent subclasses.
6. Build `domains/lending/seed_events/` — fixtures for end-to-end replay.
7. PRD §17 file-structure block is out of sync — schedule a reconcile pass.

---

### Session 5 — May 2 2026

**What was built (STEPS 7, 8, 9, 10 + parallel jobs — full STEP 7-10
sweep in a single session):**

- `core/policy_engine/loader.py` — parallel job
  - `DecisionsSpec` Pydantic model wraps decisions.yaml. Loads via
    `from_path()` or `validate()`. Builds a `decision_index` and
    pre-computed `execution_waves`.
  - Validates: every decision has `owner_team`
    (no_decision_without_owner), `mode` ∈ DecisionMode enum,
    `risk_level` ∈ RiskLevel enum, every `depends_on.decision`
    references a known decision, `execution_order` references only
    known decisions and uses each at most once, `parallel_independent`
    decisions have no `depends_on`. Hard-rule names checked against
    `KNOWN_HARD_RULES`.
  - Existing call sites unchanged — `PolicyEvaluator` and
    `ContextBuilder` still accept raw dicts via `to_dict()`.

- `core/trace/reflection.py` — STEP 8
  - `AgentLearning` Pydantic model — agent_id, persona, decision_id,
    trace_id, original_ai_decision, human_decision, override_reason,
    override_reason_code, reviewer_role, lesson, similarity_tags,
    captured_at, expires_at. Mirrors knowledge_base.json
    `system_object_types.AgentLearning`.
  - `LearningStore` Protocol + `InMemoryLearningStore` (append-only;
    rejects duplicate ids).
  - `ReflectionService.capture(trace, review)` — refuses if
    `review.overridden=False` or original==final. Auto-tags by
    `decision_id`, `reviewer_role`, `override_reason_code`. Body is a
    plain-language summary the next agent can read verbatim.
  - `ReflectionService.recall(agent_id, decision_id, similarity_tags,
    limit=5)` — pulls active lessons (filters expired at recall, no
    destructive deletes), ranks by tag overlap then recency.
  - `derive_similarity_tags(trace)` helper extracts tags from
    `output_payload` (employment_type, credit_band, loan_purpose,
    loan_type) so the API doesn't need a per-decision tag function.
  - `TraceWriter` Protocol gained `attach_human_review(trace_id,
    review)` — the one allowed mutation. `InMemoryTraceWriter`
    implements via `model_copy(update={"human_review": review})`.

- `api/` — STEP 7
  - `api/main.py` — `create_app(platform=None)` factory. Mounts
    router, exposes `/health`. `get_app()` for `uvicorn
    api.main:get_app --factory`.
  - `api/deps.py` — `Platform` container. Holds spec, store, builder,
    evaluator, critic, trace_writer, learning_store, reflection,
    event_log, hydrator, sink, atomic_tool, mode_router, human_queue,
    entity_resolver. Two registries (`agents`, `connectors`) plus a
    lazy DAGExecutor that rebuilds when agents change.
    `build_default_platform()` wires every in-memory backend; the
    Postgres + Redis swap replaces just that one call.
  - `api/ingest.py` — `EventLog` (in-memory append-only) +
    `EntityHydrator`. Hydrator handles 8 event types →
    Applicant / Application / IncomeProfile / CreditProfile /
    FraudProfile / Property writes under SHARED scope
    (lineage.decision_id=None). `income_declared` and
    `payroll_received` MERGE into one IncomeProfile per
    (applicant, application) — fixed a determinism bug from the
    initial cut where two competing rows produced a 100% income
    discrepancy. `build_event_sink(log, hydrator)` composes the
    canonical sink.
  - `api/routes.py` — six routes:
      POST /events                                   ingest canonical event
      POST /connectors/webhook/{source}              push-connector entry; falls back to
                                                     normalize_event() if no adapter is
                                                     registered for source
      GET  /decisions/{application_id}/{decision_id} read DecisionRecord
      GET  /trace/{trace_id}                         read DecisionTrace
      GET  /applications/{id}/traces                 list traces for an application
      POST /override                                 human override → reflection.capture
      POST /applications/{id}/run                    DAG E2E helper (not in original
                                                     STEP 7 list; trivial to add and
                                                     lets seed_events drive end-to-end)
    `POST /override` rejects when new_outcome==trace.outcome (that's
    a confirmation, not an override). Updates trace via
    attach_human_review then captures the AgentLearning.

- `domains/lending/personas/` — STEP 9
  - `base.py` — `LendingPersona(DecisionAgent)` with two reasoning
    paths:
      offline (default) — `_compute_offline(bundle, policy)` returns
                          `OfflineReasoning(output_payload, signals,
                          contradictions, ...)`. Smoke tests + the
                          scheduled real-backend verification run on
                          this path (no API key required).
      anthropic (opt-in) — `_reason_anthropic()` calls AsyncAnthropic
                          with cache_control on the system block.
                          Falls back to offline narrative if the
                          response can't be parsed or no API key.
  - 12 concrete subclasses, one per decision_id (see `__init__.py`
    `LENDING_PERSONA_CLASSES` map). Each computes the canonical
    output_payload values the boundary clauses in decisions.yaml
    care about (intent_score, channel; income_confidence_score,
    employment_type, payroll_verified, income_discrepancy_pct;
    credit_score, credit_band, active_bankruptcy; fraud_score,
    watchlist_match, synthetic_identity_flag; etc.).
  - `register_with_platform(platform)` — bulk-registers all 12.

- `domains/lending/seed_events/` — STEP 10
  - 4 scenario directories: `happy_path/`, `fraud_block/`,
    `contamination/`, `compliance_block/`. Each contains
    `events.csv` (push events for MockCSVConnector),
    `bureau_responses.json` (pull responses for MockHTTPConnector),
    `entities.json` (Loan + ComplianceRecord direct seeds).
  - `runner.py` — `run_scenario(platform, scenario)` replays a
    scenario end-to-end: `MockCSVConnector.listen()` →
    `MockHTTPConnector.fetch({key: credit})` and
    `fetch({key: fraud})` → seed direct entities → DAG run.
  - `__init__.py` — manifest + connector loaders + entity loader.

- `core/ontology/object_types.py` — incidental fix
  - Applicant ObjectType properties extended with lead-stage fields
    (channel, lead_source, utm_params, session_behavior,
    prior_inquiries, ambiguous_identity, identity_match_confidence,
    applicant_dispute_flag, preferred_channel) so lead_scoring's
    persona can read them through `to_context_bundle`. lead_scoring
    runs before an Application exists, so the lead data lives on the
    Applicant until ApplicationSubmittedEvent fires.

- `docs/PRD.md` — v0.6
  - §17 file-structure block reconciled with the actual repo state.
  - §19 build sequence rewritten — STEPS 1-10 marked done, next
    steps shifted to 11 (UI), 12 (outcome_tracker), 13
    (simulation/replayer), 14 (tests).
  - §20 resume prompt rewritten to match.

**Smoke-tested end-to-end (in-memory backends only):**

All 4 scenarios via `runner.run_scenario`:

  scenario             completed  skipped  failed  halted  halt_reason
  happy_path           12         0        0       no      —
  fraud_block          5          7        0       yes     fraud_block_stops_pipeline
  contamination        12         0        0       no      —
  compliance_block     12         0        0       no      —

  - `contamination` proves `contamination_guard.reject_if_upstream_confidence_below: 0.75`
    fires at the policy engine. dti_calculation trace.policy_reasons
    reads: "upstream income_verification confidence 0.50 below
    contamination_guard threshold 0.75" with contamination=True.
  - `compliance_block` proves both `compliance_block_stops_closing`
    and `upstream_block_propagates_to_dependents`.
  - `fraud_block` proves the executor-level
    `fraud_block_stops_pipeline` short-circuit halts every later
    wave.
  - `happy_path` mixes `allow` (auto modes) with `recommend`
    (human_approval-mode decisions): income_verification + compliance
    don't writeback under human_approval, so underwriting +
    approval_routing legitimately recommend pending human review.
    This is the realistic outcome — not a bug.

API liveness:
  - GET /health 200, lists agents/connectors counts.
  - POST /events 201 with hydration; 422 on missing event_type.
  - GET /trace/<unknown> 404.
  - POST /override 201, returns updated trace with human_review +
    AgentLearning. ReflectionService.recall returns the lesson on
    the next similar event, ranked by overlap on
    (decision_id, reviewer_role, override_reason_code).

**Hard rules backed in this session:**
- The reflection block in decisions.yaml — `human_override` →
  `AgentLearning` → `feed_back_to: same_agent_next_similar_event` is
  now a runtime path: `POST /override` calls
  `ReflectionService.capture` which writes the learning, and the next
  call to `ReflectionService.recall(agent_id, decision_id, tags)`
  pulls it back ranked by tag overlap.

**Real-backend verification still scheduled** — Sun May 3 2026 9am PT,
routine `trig_013QhFbYJaViJfNybCbr3KUX`. Should open
`session-4-real-backend-verification` PR. STEPS 1-6 verification (not
yet 7-10).

**Still pending (next session):**
1. Review the Sunday PR (real-backend verification of STEPS 4-6) when
   it lands. STEPS 7-10 were not in scope of that scheduled run.
2. STEP 14: `tests/` — persistent pytest suite. Today only
   `tests/core/context_store/test_in_memory.py` exists; cover
   `core/policy_engine/loader.py`, `core/trace/reflection.py`, the
   API surface (TestClient against each route), each persona's
   `_compute_offline()` against canonical fixtures, and the 4
   seed_events scenarios as canonical regressions. Two of the bugs
   surfaced this session (income hydrator double-write, default
   resolver shape) would have been single failing tests.
3. STEP 11: `ui/` — event stream / context view / trace viewer /
   human queue. Highest-leverage user-visible thing.
4. STEPS 12-13: outcome_tracker, simulation/replayer.
5. Architecture follow-up: `human_approval` mode currently does not
   writeback (matches PRD §13 "human's resolution drives the eventual
   writeback"), so downstream sees missing upstream output for
   queued decisions. The senior_underwriting persona handles this
   correctly by recommending instead of approving when upstream is
   missing. Decide: should there be a "simulate human approvals" mode
   for tests, or do all tests need an explicit human-approval step?

---

### Session 8 — May 2 2026

**What was built (UI iteration on STEP 11):**

User direction: "build UI for each persona who actually works on
individual loan applications — workbench with KPIs and per-app
drill-down. Then show me the entire data flow start to end."

The decision detail page had earlier picked up cross-cutting strips
(routing pill, read-permission chips, atomic-tool pipeline, upstream
status, boundary lit) and the credit_assessment persona panel.
This session pushed it the rest of the way:

- 11 remaining persona panels — one Jinja partial + one
  view-model helper each. Domain-shaped visuals per persona:
    lead_scoring         intent meter (0-1) + channel/source pills
    income_verification  stated vs verified bars + confidence ring
    fraud_screening      traffic-light gauge + halt warning when block
    compliance_check     HMDA checklist + halts_closing warning
    dti_calculation      DTI bar with thresholds + contamination guard
    ltv_assessment       appraised vs loan stack + LTV bar with PMI/cap
    product_eligibility  eligible products + exception products lists
    rate_pricing         base + LLPA waterfall vs usury cap
    underwriting_decision 6-input synthesis grid + risk_score gauge
    approval_routing     routing target + channel + timeline cards
    closing_readiness    closing checklist + outstanding conditions

  Cross-cutting helpers added in ui/views.py:
    _routing_target(mode, outcome) — derives routing label from
      (mode, outcome) mirroring ModeRouter (trace doesn't persist
      routed.action; we derive for the UI)
    _evaluate_boundary(boundary, output_payload, bundle_objects)
      — runs every YAML rule against current values via
      core.policy_engine.evaluator._evaluate_rule, returns ✓/✗
      per rule. Used to "light" the boundary section for ALL 12
      decisions, not just credit_assessment.
    _atomic_pipeline(trace, routing_target) — 7-step descriptor
      list for the PRD §7 pipeline strip.
    _read_permissions(decision_id) — list of ObjectType ids per
      decisions_that_read_it for the chip row.
    _persona_view dispatcher reads from PERSONA_PANELS map and
      _PERSONA_VIEW_BUILDERS dict — adding a new persona panel
      is one map entry + one builder + one partial.

  Verified all 12 panels via scripts/smoke_ui_all_panels.py
  across app_happy + app_fraud + app_comp + app_contam (covering
  the fraud-block warning, compliance-block warning, contamination
  guard fired badge).

- 9 owner-team workbenches — operator-centric views.
  /ui/workbench (index of 9 teams) +
  /ui/workbench/{owner_team}?application_id=... with a KPI strip,
  application picker, queue table OR focused-app view.

  Per the user's spec the focused view splits into:
    - What I finished
    - Pending for me (queue items)
    - Waiting on upstream
    - Downstream waiting on me

  KPIs per team: open_queue, completed, auto_cleared, blocked,
  portfolio_value, applications_touched, downstream_pending,
  avg_duration_ms, sla_pct, decisions_per_loan_avg.

  Workbench design choice: per owner_team (9), not per persona
  (12) — because in real lending one team handles multiple
  decisions (Underwriting owns 4 decisions). The team's daily
  view aggregates all of their work.

  Verified all 4 scenarios via scripts/smoke_workbench.py:
    happy_path through Underwriting
    fraud_block through Fraud Ops
    contamination through Underwriting (DTI guard fires)
    compliance_block through Compliance + Closing Ops

  Side fix during smoke: kept block-cascaded downstream decisions
  visible in "Downstream waiting on me" so a compliance officer
  can see they blocked closing too. Was filtering them out as
  "terminal" — corrected to filter only `allow` (cleanly cleared)
  but keep `block` visible so the impact is auditable.

- Top nav reorganized — "Workbench" added as the primary entry,
  before "Applications", "Human queue", "Health", "API docs".

**What was discussed (no code, but locked in):**

- Walked through Growth Ops workbench in detail with user.
- Q&A on data flow, context, production readiness:
  - Confirmed event-driven model (no scheduled refresh; push +
    pull connectors with on-demand fetch; batch is one connector
    pattern not the only one)
  - Clarified the 3-layer mental model:
      Layer 1: shared world (8 ObjectTypes, append-only with
               lineage)
      Layer 2: per-decision context bundle (focused projection,
               snapshotted)
      Layer 3: decision output (decision record + trace +
               becomes upstream input)
  - Defined "context" precisely: the curated, focused, frozen
    view of the world that ONE decision needs to reason. Each
    of the 12 decisions builds its own bundle; there's no
    global context.
  - Production readiness assessment: architecture is
    production-grade; what's missing is integrations and
    operational hardening. Three deployment paths laid out
    (shadow pilot 3mo, co-pilot 5-6mo, full system-of-record
    12-18mo).

**STRATEGIC DIRECTION LOCKED: PATH C — full DecisionOS as system
of record (12-18 months). The build sequence in PRD §19 is
broken into 6 tiers; complete a tier before opening the next.**

**Files added this session:**
  ui/templates/personas/_lead_scoring.html
  ui/templates/personas/_income_verification.html
  ui/templates/personas/_fraud_screening.html
  ui/templates/personas/_compliance_check.html
  ui/templates/personas/_dti_calculation.html
  ui/templates/personas/_ltv_assessment.html
  ui/templates/personas/_product_eligibility.html
  ui/templates/personas/_rate_pricing.html
  ui/templates/personas/_underwriting_decision.html
  ui/templates/personas/_approval_routing.html
  ui/templates/personas/_closing_readiness.html
  ui/templates/workbench_index.html
  ui/templates/workbench.html
  scripts/smoke_ui_all_panels.py
  scripts/smoke_workbench.py
  (also from earlier in session: ui/templates/personas/_credit_assessment.html
   and scripts/smoke_ui_credit.py)

**Files modified:**
  ui/views.py            — workbench view-models + 11 persona view-models +
                           cross-cutting helpers (routing target, boundary
                           eval, atomic_steps, persona dispatcher)
  ui/routes.py           — /ui/workbench + /ui/workbench/{owner_team}
  ui/templates/base.html — Workbench nav link added as primary entry
  ui/templates/decision.html — cross-cutting strips + persona panel
                               dispatcher block at top of right column
  docs/PRD.md            — v0.8 (workbench + panels + path-C tier breakdown
                           in §19)

**Tomorrow's concrete starting point:**

  1. Read CONTEXT.md (this file) + docs/PRD.md
  2. Check status of routine trig_013QhFbYJaViJfNybCbr3KUX
     (real-backend verification PR scheduled for Sun May 3 9am PT).
     If the PR landed on branch session-4-real-backend-verification,
     review it. If not, fire it manually:
       docker compose up -d postgres redis
       psql ... -f core/context_store/schema.sql
       swap PostgresDurableStore + RedisHotCache in api/deps.py
       re-run all smoke scripts + run_scenario for the 4 scenarios
  3. Begin TIER 1 — STEP 14 pytest scaffolding. Bug-catchers first:
       tests/core/policy_engine/test_loader.py
         (decisions.yaml structural validation against the real file)
       tests/core/trace/test_reflection.py
         (capture + recall + retention + duplicate-id rejection)
       tests/domains/lending/test_seed_scenarios.py
         (4 scenarios as canonical regressions: happy_path, fraud_block,
          contamination, compliance_block — assert outcome counts +
          halt reasons + contamination_guard fires)
     Then expand to:
       tests/api/  via fastapi.testclient
       tests/ui/   view-model functions + workbench rollups
       tests/core/decision_agents/ each persona's _compute_offline()
       tests/core/simulation/ replayer + invariants
  4. Async pass on ui/views.py (replace _records walks) and
     Postgres-aware resolver — needed before the live DB swap.

**Then TIER 2 (real connectors) — see PRD §19 for full sequence.**

OPEN ARCHITECTURAL QUESTIONS for path C:
  - Tenant model: row-level (recommended for first 10 tenants) vs
    schema-per-tenant (cleaner isolation but more ops overhead).
    Decide before TIER 3 multi-tenancy work.
  - LOS integration order: Encompass (~50% US mortgage market) vs
    Blend (newer, growing). Driven by first design partner's stack.
  - Critic model: separate Anthropic call per critique? PRD §8 says
    independent critic; recommend Sonnet for persona, Opus for
    critic so SelfReviewError can never fire.
  - Borrower portal: separate frontend project consuming the API,
    NOT in this repo. Decide naming + ownership.
  - human_approval simulate-mode for tests: still open from
    Session 6 — do test fixtures auto-approve queued items mid-DAG,
    or do they explicitly POST /override? Recommend: option (a) for
    seed-scenario regressions (faster, reads like real lender),
    option (b) for one dedicated override-flow test (exercises the
    actual override path).
  - HumanQueue.resolve(): still open from Session 6. Add when
    wiring the dequeue flow in TIER 3.

---

### Session 7 — May 2 2026

**What was built (STEP 13 — simulation / replayer):**

User direction: "lets finish simulation." STEP 13 from the resume
prompt — replay traces at point-in-time for backtesting personas,
hooking into InMemoryDurableStore.get_at_time.

- `core/simulation/__init__.py` — re-exports `Replayer`,
  `ReplayResult`, `ReplayComparison`, `DecisionComparison`.

- `core/simulation/replayer.py` — the simulation layer.

  Building blocks (all internal `_`-prefixed, file-local):

    `_ReadOnlyAtTimeShim`
        Wraps a durable backend (InMemoryDurableStore today, the
        Postgres path will work the same once the resolver supports
        SQL). `get_latest(...)` proxies to
        `inner.get_at_time(..., at=replay_at)`; `get_at_time(at)` caps
        at the replay frame so callers can never see records newer
        than the pinned moment. `insert_record` and `tombstone` raise
        — replays may NOT mutate the live durable. `insert_snapshot`
        is captured on the shim only (not propagated) so the bundle
        still gets a valid snapshot_id without polluting production
        history.

    `_ShadowModeRouter`
        Duck-types `ModeRouter`. Routes every decision as
        `RouteAction.SHADOW_RECORD` regardless of mode/outcome — even
        BLOCK and AUTO_WRITEBACK. Replays don't need writeback for
        downstream propagation because the executor's
        `UpstreamSummary` state already carries each wave's outcomes
        forward. Note string `"replay: shadow only, no writeback"` is
        appended to `routed.notes` so the trace is honest about it.

  Public surface:

    `Replayer.from_platform(platform)` — convenience constructor that
        duck-types Platform via attributes (store, evaluator, spec,
        trace_writer, agents, critic). Keeps `core/simulation/`
        independent of `api/` — no import cycle.

    `Replayer.__init__(*, store, evaluator, spec, trace_writer,
                       agents, critic=None)` — the explicit form for
        anyone wiring without a Platform.

    `replay_application(application_id, *, at=None,
                        persona_overrides=None,
                        include_critic=False) -> ReplayResult`
        Re-run the full DAG against a fresh shadow trace_writer.
        `at` defaults to the latest known trace timestamp for the
        application — so the natural meaning of
        `replay_application(app_id)` is "re-run as if at the moment
        the live pipeline finished", reproducible across calls.
        `persona_overrides` is a `{decision_id: DecisionAgent}` map;
        each agent's `decision_id` must match the override key (else
        ValueError).

    `replay_decision(application_id, decision_id, *, at=None,
                     persona_override=None,
                     include_critic=False)
                     -> tuple[AtomicToolResult, DecisionComparison]`
        Re-run a single decision at the snapshot the original saw.
        Upstream summaries are reconstructed from the live trace
        writer (filtered to `started_at <= at`), not from a fresh
        simulation — so the decision sees what it actually saw.

  Result types:

    `DecisionComparison` — original vs simulated for one
        decision_id. Carries both outcomes, both confidences,
        confidence_delta, both matched_clauses,
        original/simulated payloads, payload_diff
        ({added, removed, changed}), persona_swapped flag, notes.

    `ReplayComparison` — application-level wrapper. total /
        agreements / disagreements counters + per-decision list.

    `ReplayResult` — adds executor outputs (completed / skipped /
        failed / halted / halt_reason / outcomes) plus the
        comparison.

- `core/context_store/lending.py` — small fix in `snapshot()`. Was
  always reading upstream decision outputs via `get_latest(...)`,
  which means an at-aware snapshot would mix point-in-time entity
  reads with current-time upstream reads. Now: when `at` is set, the
  upstream read uses `get_at_time(..., at=at)`. Live path is
  unchanged — no live caller passes `at` today; replay correctness
  depends on it.

- `scripts/smoke_replayer.py` — runnable smoke (
  `python -X utf8 scripts/smoke_replayer.py`) covering 4 phases:

    1. As-is replay of happy_path → 12/12 agreements; live trace
       writer + durable store fingerprint byte-identical before and
       after.
    2. `replay_decision("credit_assessment", persona_override=
       StrictCreditAgent())` → comparison surfaces `credit_band`
       payload diff `'prime' -> 'near_prime'`, persona_swapped=True,
       outcome unchanged (the strict downgrade still lands within
       the same boundary clause).
    3. `replay_decision("fraud_screening", persona_override=
       StrictCreditAgent())` → ValueError as expected
       (decision_id mismatch).
    4. `replay_application(persona_overrides={"credit_assessment":
       ...})` → swap visible at credit_assessment with
       payload_changed=True; live state still byte-identical after
       all 4 phases (12 traces / 17 records throughout).

  Observation worth noting (NOT a bug): downstream personas
  (ltv_assessment, rate_pricing, underwriting_decision) didn't show
  payload_changed in phase 4. They re-derive their inputs from the
  bundle's entity reads rather than consuming `credit_band` from
  upstream output, so band downgrade alone doesn't cascade. Real
  cascading requires either (a) upstream personas to write the
  derived band into the entity store, or (b) downstream personas to
  read the upstream output payload directly. Worth investigating
  before judging whether the replayer is "useful enough" for
  backtesting persona changes — a different override (e.g. credit
  score thresholding) would cascade through the LTV/pricing chain.

**Hard rules backed in this session:**

  no_action_without_policy / no_execution_without_trace are
  preserved in replay because the AtomicTool runs unchanged — only
  the trace_writer + router are swapped.

  The "replays must not mutate live state" invariant is enforced
  in two layers:
    - `_ReadOnlyAtTimeShim.insert_record` / `.tombstone` raise.
    - `_ShadowModeRouter` never calls `store.set()`.
  The smoke test asserts both layers are tight by fingerprinting the
  live trace writer + durable store before/after every replay.

**Tradeoffs noted:**

  - Resolver is in-memory only. `_build_replay_resolver` mirrors
    `api.deps._default_resolver` and walks `inner._records` directly;
    Postgres backend will need a SQL implementation. Same limitation
    the live resolver has — not a regression.

  - Critic is OFF by default (`include_critic=False`). Replay is
    observational; critic findings on the same trace twice would
    double-count. Opt in for "compare critic verdicts across
    persona V1 and V2" workflows.

  - Single-decision replay's upstream is reconstructed from the
    live trace writer. If the live pipeline didn't run an upstream
    (e.g. fraud_screening was skipped), the replayed decision sees
    no upstream summary for it and the contamination_guard /
    fraud_block_stops_pipeline rules don't fire — which is correct,
    because they didn't fire originally either.

**Still pending (next session):**

  1. STEP 14 tests/ — now also covers `core/simulation/replayer`.
     The smoke script is good for ad hoc, but a pytest suite would
     pin the live-state-not-mutated invariant on every CI run.
  2. Postgres-aware resolver — both for the live path (api.deps)
     and the replay path. Single SQL statement; just needs writing.
  3. Real Anthropic calls — STEP 13 is more useful with persona V2
     being an actual LLM-backed persona to compare against the
     deterministic offline path.
  4. STEP 12 outcome_tracker — natural follow-on. If replays
     produce simulated outcomes and we have a per-decision
     ground-truth feed, the comparison shape from STEP 13
     (`DecisionComparison`) is most of what an outcome A/B
     tracker needs.

---

### Session 6 — May 2 2026

**What was built (STEP 11 — local UI):**

User direction: "build UI to see things running locally per persona,
focus end-to-end on in-memory, go to cloud only once we see value."
Picked FastAPI + Jinja2 + HTMX + Tailwind-via-CDN over Next.js for
~2-session-to-v0 instead of ~5. Mounted into the existing api/main.py
so it's all one process.

- `api/main.py` — extended with an asynccontextmanager `lifespan` that
  runs `_bootstrap_demo(platform)` when `seed_demo_data=True`. Bootstrap
  registers all 12 personas via
  `domains.lending.personas.register_with_platform` and replays the 4
  seed scenarios via `domains.lending.seed_events.runner.run_scenario`
  so the UI has 4 applications, ~48 traces, ~16 queued items waiting
  on first page load. `get_app()` now defaults to
  `seed_demo_data=True`. New `mount_ui` flag (default True) for the ui
  router; tests can set False to skip. `_known_application_ids()`
  helper walks the durable store for distinct Application entity_ids.

- `ui/__init__.py` — exports router + templates.

- `ui/views.py` — view-model helpers separate from routes so
  templates stay legible. `list_applications`, `application_detail`,
  `decision_detail`, `queue_view`. `OUTCOME_STYLES` palette
  (allow → emerald, recommend → amber, escalate → orange, block →
  rose, skipped → slate) keeps the CSS classes in one place. Jinja
  filters: `currency`, `pct`, `confidence`, `dt`. View-models read
  the in-memory durable store, trace writer, human queue, and
  learning store directly via the `Platform` — synchronous reads on
  the in-memory backends; will need an async pass for the Postgres
  swap.

- `ui/routes.py` — 5 GET routes:
    /                                                       app list
    /ui/applications/{id}                                    DAG view
    /ui/applications/{id}/decisions/{decision_id}            decision detail
    /ui/queue                                               cross-app queue
    POST /ui/applications/{id}/decisions/{decision_id}/override
                                                             HTMX form
  Override flow: validates the trace, builds a HumanReview, calls
  `trace_writer.attach_human_review` and `reflection.capture` (same
  path as POST /override). Returns the `_override_result` partial as
  HTMX swap target. Same-outcome submissions render
  `_override_card` partial with an inline error message and stay in
  place.

- `ui/templates/base.html` — single layout. Tailwind via
  `cdn.tailwindcss.com`, HTMX via `unpkg.com/htmx.org@1.9.12`. Nav:
  Applications · Human queue · Health · API docs. Footer reminds the
  reader that hard rules are code, traces are append-only, backend is
  in-memory.

- `ui/templates/index.html` — application list. Outcome counts as
  colored dots inline; status pill is halted (rose) /
  pending review (amber) / complete (emerald). Empty state instructs
  the user to boot with seed_demo_data=True.

- `ui/templates/application.html` — DAG view. Application metadata
  card on top (loan_purpose, requested_amount, state, submitted_at).
  Below, the 12 decisions grouped by execution_order waves —
  parallel_independent first, then dependent waves 1-7 in order. Each
  decision card is color-coded by outcome and shows persona, mode
  (auto/human/rec/shadow), risk, confidence, matched_clause. Click →
  decision detail.

- `ui/templates/decision.html` — the workhorse. Three-column layout.
  Left aside: bundle objects (per ObjectType, with field projection
  visible — `_object_type`, `_primary_key`, `_decision_id` filtered
  in the template), upstream outputs (with outcome pill and JSON
  payload in `<details>`), boundary clauses (each clause's rules
  listed; `matched` label on the clause that fired). Right column:
  work journal (hypothesis, conclusion, confidence_basis, plain-
  language summary), signals evaluated (direction-coded dots —
  emerald supports / rose contradicts / slate neutral),
  contradictions (resolved/unresolved status), policy outcome
  (engine_outcome, matched_clause, contamination flag, policy
  reasons), critic review (verdict + findings), output payload as
  JSON, override workbench, recalled past learnings (with similarity
  tags).

- `ui/templates/_override_card.html` — partial covering 3 states.
  human_review already attached → locked-in review card showing
  reviewer + role + original + final + override reason. queueable
  outcome → form with radio-pill outcome selector
  (new_outcome ∈ {allow, recommend, escalate, block}), select for
  reviewer_role, free-text reason, optional reason_code. auto-
  executed → emerald banner "no review needed". The form submits via
  HTMX (`hx-post` + `hx-target="#override-card"`) — never leaves the
  page.

- `ui/templates/_override_result.html` — HTMX swap target on
  successful override. Shows attached review + the captured
  AgentLearning with similarity tags + an explanation of what will
  happen on the next similar event ("ReflectionService.recall() will
  return this lesson ranked by overlap"). Closes the reflection loop
  visually.

- `ui/templates/queue.html` — cross-application queue table. App
  link + decision id + persona (small mono) + proposed outcome pill +
  confidence + enqueued_at + Review→ link. Footer explains queue
  mechanics: "decisions land here when mode ∈ {recommend,
  human_approval} or outcome ∈ {recommend, escalate} — the
  ModeRouter chose QUEUE_HUMAN over auto-writeback."

**Smoke-tested end-to-end (TestClient):**
- GET /                                          200, 4 applications rendered
- GET /health                                    agents=12, applications=4
- GET /ui/applications/app_happy                 200, 12 decision cards
- GET /ui/applications/app_happy/decisions/underwriting_decision
                                                 200, override form shown
- GET /ui/queue                                  200, 16 queued items
- POST override → 200, response contains "AgentLearning captured" +
  "Override recorded" sections
- Reload decision detail post-override          shows attached review
- Same-outcome submission                       inline error rendered
                                                 ("matches the AI")

**Run locally:**
```bash
uvicorn api.main:get_app --factory --reload --port 8000
```
Open http://localhost:8000/. seed_demo_data is on by default in
get_app() so the 4 scenarios are pre-loaded.

**Dependencies added:**
- `jinja2>=3.1` (already had it but pinned now)
- `python-multipart>=0.0.9` (FastAPI form parsing)

**Tradeoffs noted:**
- View-models read the in-memory store synchronously. The Postgres
  swap will need an async pass — every helper in views.py becomes
  async and the routes need `await`. Easy migration, but flagged.
- Override doesn't dequeue. The HumanQueue's design has no "resolve"
  method yet — items stay in `list_open()` until the queue itself is
  reset. Functionally fine for v0; real human-queue UX needs a
  resolved/dismissed state.
- Tailwind via CDN means no purge — payload is fine for local but
  not for production. When this goes to a polished demo, swap for a
  built CSS bundle.
- HTMX target replaces `#override-card` only. Other parts of the
  page (bundle, journal, recalled lessons) don't refresh — a full
  page reload is needed to see the new attached review propagate
  upstream. Acceptable; reload link is in the result partial.

**Still pending (next session):**
1. Real hands-on use — boot the UI, walk through scenarios, find
   what's confusing or missing. Likely surface area for changes:
   per-persona signal renderers (e.g. lead_scoring's intent score
   could be a meter, ltv could be an appraised-vs-loan diagram), live
   refresh of decision detail post-override.
2. STEP 14 tests — UI view-models are pure functions of Platform
   state and would test cleanly. Cover list_applications,
   application_detail.waves, decision_detail.bundle_objects projection,
   queue_view ordering.
3. STEPS 12-13: outcome_tracker, simulation/replayer.
4. Real Anthropic calls — the personas have the path but it's
   unproven. Would let users see the Anthropic-driven journal
   side-by-side with the offline path.

---

### Session 14–20 — June 5–10 2026 — Accord customer product + Dockerization

Built **Accord**, the customer-facing lending-decision product on top of the
Decision OS engine, end-to-end, and Dockerized it for AWS.

**MiroFish multi-agent simulation engine** — `core/mirofish/`
  - `DebateEngine` (12 agents, 3 rounds, wave-directional + hard-block-aware
    cross-agent contamination), `PolicySimulator` (what-if rule changes across
    the book), `SwarmAnalyzer` (portfolio-wide pattern scan). Deterministic-first
    with optional Claude (`claude-sonnet-4-6`). CLI: `scripts/mirofish.py`.

**Accord API** — `api/accord/` (mounted via `api.accord.routers`)
  - Endpoints: pipeline (list + KPIs), loans/{id}, mirofish (debate / simulate /
    swarm + prebuilt + history + latest), analytics (overview / funnel / agents /
    risk), audit (compliance-health / {app} trail / adverse-action / reports).
  - asyncpg pool over `DATABASE_URL` (AWS RDS); `DISTINCT ON … version DESC` for
    latest-version reads; 60s in-process TTL aggregate cache w/ write-invalidation.
  - Fix: `mirofish_routes` simulate INSERT is idempotent (`ON CONFLICT DO UPDATE`)
    so re-running a scenario no longer 500s on the deterministic simulation_id.

**React frontend** — `frontend/` (Vite 6 + React 18 + TS + Tailwind v4 + recharts)
  - 4 products behind one nav (`components/Header.tsx`): **Pipeline · Analytics ·
    Simulation · Audit**. Products dropdown; exactly one nav "Pipeline".
  - **Pipeline**: 5 lifecycle stage columns (VERIFY / UNDERWRITE / ELIGIBILITY /
    DECIDE / CLOSE, with tooltips) summarising the 12 personas; colored word-chip
    status cells + legend; typeahead `LoanSearch`; dynamic loan-type + colored-dot
    status filters (synced with KPI cards); date-range filter; `ExportMenu`
    (CSV / PDF-print / JSON); single-status KPI cards (Total / Clear to Close /
    Blocked / Halted); server-side pagination (`?limit=&offset=`, 25/50/100);
    skeleton / error-retry / empty states.
  - **Analytics**: 5 KPIs + recharts — funnel stacked bar, approval donut, agent
    allow/block grouped bars, employer concentration bar, product-mix pie.
  - **Simulation**: Agent Debate (plain-English verdict + editable question),
    Policy Simulator (plain-English summary → impact cards → status-change table →
    per-loan WHY/WHAT-TO-DO → recommendation), **Portfolio Health Check**
    (renamed from "Swarm"; findings grouped Urgent/Warning/Info in plain English,
    expandable agent summaries).
  - **Audit**: compliance-health KPIs, trail search (version timeline + authority
    chain + SLA bars), adverse-action tracker, reports library + examiner export.
  - Status "Pipeline Halted" → "Halted". Loading/error/empty via
    `components/states.tsx`; `components/Pagination.tsx`; `utils/export.ts`.

**Dockerization** (this session)
  - `Dockerfile` (API: `uvicorn api.main:get_app --factory`), `frontend/Dockerfile`
    (Vite build → nginx), `frontend/nginx.conf` (proxies `/api/` → `api:8000`,
    SPA fallback). Frontend built with empty `VITE_API_URL` → same-origin `/api`
    (client.ts uses `??` not `||`). `.dockerignore` keeps `.env`/secrets out.
  - `docker-compose.yml` — merged the existing postgres/redis infra with new
    `api` + `frontend` services. `.env.example` template; `scripts/deploy.sh`
    (ECR login → build/push → ECS force-redeploy; prerequisites documented).
  - Verified the full local stack on **http://localhost** (port 80) end-to-end
    through nginx → api → RDS (8,896 loans, charts, real data). API endpoints
    all 200, no 500s. (`?format=csv` returns JSON — CSV export is client-side.)
  - Env note: this machine blocks CloudFront, so Docker Hub / ECR-Public base
    image pulls fail (`EOF`); workaround = pull via `mirror.gcr.io` and re-tag.
    To persist: add `registry-mirrors: ["https://mirror.gcr.io"]` to daemon.json.
  - `.env` currently holds only `DATABASE_URL`; add `ANTHROPIC_API_KEY` to enable
    the Claude-enhanced MiroFish paths (deterministic fallbacks run without it).

**Open / next:** actual AWS deploy (ECR/ECS/ALB + domain + SSL); optional
backend `?format=csv` for full-portfolio export; donut is approval-rate 2-way
(no per-loan review split in the analytics payload).

---

### Session 21 — June 10 2026 — Accord interactivity polish + container verified

Drove every interactive element to spec and verified the full stack end-to-end
(12/12 headless click-through). All changes committed + pushed to main and the
frontend container rebuilt so http://localhost reflects them.

- **Loan Detail** (`/pipeline/:appId`): PersonaAccordion regrouped into 5 stage
  cards (VERIFY/UNDERWRITE/ELIGIBILITY/DECIDE/CLOSE) with a per-stage "Overall"
  status; "Decision Journey" header; block/halt action bars show the blocking
  reason + a "🐟 Run MiroFish Debate" button that scrolls to the debate; back =
  "All Applications"; 22px name; empty sections say "No data available".
- **Pipeline**: clicking a stage chip expands an inline detail row (colored
  left border by status) with each persona's explanation/signals/rule.
- **Agent Debate**: plain-English verdicts — Approve this loan / Approve with
  conditions / Investigate further before deciding / Do not approve.
- **Policy Simulator REBUILT** as 12 dropdown cards in 3 categories (4 smart
  options + range-validated Custom each; Combined Stress takes rate bps + price
  %). Run posts overrides via `custom` (NOT `scenario_name` — backend 404s on
  unknown names; `runSimulationCustom` → `{custom:{name,type,overrides}}`).
  Backend currently applies 6 of 10 override keys (DTI back_dti_max, credit
  min_score, LTV max_ltv, _stress rate_delta/price_delta_pct, conforming_limit);
  min_dcr, unemployment_rate, fha_eligibility.*, usury_cap run but flip 0 loans
  (UI complete, backend application TODO).
- **Audit trail**: version history now uses vN badges + block/approve tint;
  authority chain gained a Level column + "⚠ Exceeds" + an issues banner;
  "No audit records found for {id}"; reports section = "Compliance Reports"
  with a "Coming in next release" toast on every action button.

**Container note:** Docker stack runs on http://localhost (nginx :80 → api :8000
→ RDS; redis :6379; postgres skipped). Rebuild after frontend changes with
`docker-compose up --build -d frontend` (base images are cached, so no
CloudFront pull). `docker-compose down` to stop.

---

### Session 22 — June 11–12 2026 — Auth + multi-tenancy + first AWS deployment

Accord went from local-only to **live on AWS** behind JWT auth with real
multi-tenant isolation. Every slice committed, pushed, and verified live
(API 10/10, frontend role-gating, MiroFish debate, headless on the ALB).

**Auth data model** (`685a677`) — `scripts/migrations/create_auth_tables.sql`
+ `core/auth/{models,security}.py`. Two tenants (`demo` enterprise = all 4
products; `default` starter = pipeline only) + 4 users
(admin/underwriter(uw@)/compliance/viewer @demo.com, pw `accord2026`, bcrypt).
Runner `run_auth_migration.py` substitutes the `HASH_IN_CODE` placeholder with
a real bcrypt hash — so NEVER `psql -f` the raw .sql (it would store the literal
placeholder as the hash and break login). `--retenant` later moved all **8,896**
loans `default` → `demo`.

**JWT backend** (`e9be460`) — `core/auth/service.py` (`AuthService`:
login/signup/create_token/verify_token/get_user/get_tenant; module-level
`create_token`/`decode_token`) + `api/accord/auth.py` (`POST /auth/login`,
`/auth/signup` public; `GET /auth/me`; `POST /auth/logout`). `get_current_user`
(Bearer → 401, pure-crypto decode, no DB hit) + `get_tenant_id` deps.
**Tenant isolation:** every pipeline/analytics/audit/mirofish query swapped
`Query("default")` → `Depends(get_tenant_id)` so the tenant comes from the JWT,
never the client. `JWT_SECRET` in `.env` (gitignored). Deps: pyjwt 2.13,
bcrypt 3.2.2, python-multipart.

**Frontend auth** (`e9be460`, viewer gating `52b9ddc`) — `AuthContext` (token
in localStorage, `/me` verify on load, `login`/`logout`/`hasProduct`),
`Login.tsx`, `client.ts` (Bearer header on every call; any 401 → `accord:
unauthorized` event → auto-logout), `App.tsx` route guards (unauth → Login),
`Header.tsx` user-menu (avatar "KM" → name/role/tenant, Settings admin-only,
Sign out) + role/plan gating on the product tabs (viewer→Pipeline only;
compliance→Pipeline+Audit; underwriter→Pipeline+Simulation; lock + "Upgrade to
Business/Enterprise plan" when the plan lacks a product). `LoanDetail` hides the
approve/override/SAR/doc-request buttons for `role=viewer` (shows "View only").

**Workbench schema** (`5a849b1`) — `scripts/migrations/create_workbench_tables.sql`
+ runner. Six tables (loan_assignments, communications, attention_requests,
loan_notes, conditions, notifications) + lifecycle cols on `entity_states`
(loan_status, current_stage, assigned_to). Applied to RDS; purely additive,
re-runnable (IF NOT EXISTS throughout). Empty until the workbench API writes to
them.

**AWS deployment** (`06cde1f`, deploy.sh fixes `760f730`) — first cloud deploy,
on Accord's **own dedicated `accord` ECS Fargate cluster + ALB**, NOT the EDMS
infra (there is no `edms-simulator` cluster in the account). ECR repos
accord-api/accord-frontend; `deploy/ecs-{api,frontend}-task.json` (X86_64,
awslogs; API secrets are `${VAR}` rendered from `.env` at register time — never
committed); `deploy/deploy.sh` (idempotent: ECR login → build+push amd64 →
register task def → create-or-update services with subnets/SG/target-groups →
wait stable → print URL). Public `GET /api/accord/health` for the ALB target
group. `nginx.conf` made ECS-safe — resolves the `api` upstream at request time
(resolver + variable) so the standalone frontend task boots with no `api` host
(ALB routes `/api/*` to the API TG in prod). `.gitattributes` forces LF on
`*.sh`. Two Windows/Git-Bash deploy.sh bugs fixed: `command -v python3` grabbed
the MS Store stub (now test-executes candidates); `mktemp` MSYS `/tmp` path
unreadable by native `aws.exe` (now a repo-relative gitignored rendered file).
Frontend builds with **VITE_API_URL empty** (relative `/api`) — do NOT set
api.useaccord.com (no cert/domain; would break it).

**Live:** http://accord-alb-588286075.us-east-1.elb.amazonaws.com
(admin@demo.com / accord2026). Both services 1/1 on task-def rev `:2` (rev `:2`
carries the viewer-gating fix). Redeploy = `bash deploy/deploy.sh`.

**NOT done:** custom domain + SSL — no `useaccord.com` / ACM cert / HTTPS
listener yet; access is over http via the ALB DNS. That's the only open item
from the deploy spec (ACM cert → HTTPS listener → Route 53 → set VITE_API_URL).

See memory `project-aws-deployment` for the canonical topology + the deviations
to preserve against generic deploy prompts.

---

### Session 23 — June 12 2026 — The full multi-tenant workbench

Accord went from "demo with one tenant" to a **real, role-based loan-ops
workbench across 5 tenants**, then deployed live. Every slice committed, pushed,
verified live on the container stack (and finally on the ALB). Commits:
`4dfff44` `3784273` `71c197f` `9fa7b72` `2720916` `84bac32` `82b7df8`, then a
deploy to task-def **rev :3**.

**5 tenants + 33 users + curated loans** (`4dfff44`,
`scripts/migrations/seed_tenants_and_users.py`) — summit (enterprise) / pacific
(business) / heartland (growth) / atlas (enterprise) each get 8 users + 50
curated loans; legacy (starter) holds nothing; the **~8,696 remainder stays
under `demo`** so the original showcase still works. User-confirmed adaptations
to the spec: **role enum extended** (users_role_check + ROLE_PERMISSIONS +
frontend ROLE_PRODUCTS gained processor/senior_uw/closer); loan-type quotas
dropped (data is ~97% conforming) so curated 50s vary by lifecycle status with
backdated `assigned_at`; remainder kept under demo. Idempotent (delete-then-
reinsert named tenants). **Also fixed a latent bug**: the workbench `conditions`
table never created — an EDMS `conditions` table pre-existed, so it was renamed
**`loan_conditions`**.

**Role-based landing** (`3784273`) — `GET /pipeline/my-queue` (loans assigned to
the JWT user, grouped active/pending/decided, each card with plain-English AI
finding + data sources + recommendation, templated per blocking persona +
outcome + entity numbers) and `GET /pipeline/team`. `Pipeline.tsx` became a
role-aware shell: ops roles → My Queue | All Applications; manager/admin → Team
Overview | All Applications; compliance → Audit by default. `MyQueue.tsx`,
`TeamOverview.tsx`.

**Loan detail reframed** (`71c197f`, decide `82b7df8`) — AI **recommends**, the
user **decides**: borrower story, 🧠 AI-recommendation card (driving decision +
confidence), 📄 evidence (docs on file + key data points incl. income stated vs
verified), and a 6-action "Your Decision" block. `POST /pipeline/decide` makes
approve→decided / deny→denied / escalate→Senior-UW real (were demo toasts);
request-info / internal-review open modals.

**Comms + notifications, persisted** (`9fa7b72`) — `POST /communications`
(request docs → loan to pending_borrower), `…/simulate-response` (→ active /
RETURNED + activity-log row), `POST /attention-requests` (target sees 🔵 even on
loans they aren't assigned), `GET/POST /loans/{id}/notes`, and a notification
system (`GET /notifications`, mark-one/all-read) with a Header bell. Modals:
RequestInfoModal, AttentionModal, NotesSection, NotificationBell.

**Manager experience + governance reports** (`2720916`) — team KPIs + per-member
oldest-loan + **Reassign modal** (`POST /pipeline/reassign`); a manager-only
**Team Performance** table on Analytics (`/analytics/team-performance`); the
Audit "Compliance Reports" table replaced by a **Governance Reports** card grid
(HMDA / Fair Lending w/ disparate-impact flag / Audit Trail / Override
Justification / AI Model) exporting real tenant-scoped CSV/PDF/package via
`GET /audit/reports/{id}/data`.

**Super Admin** (`84bac32`) — `Settings.tsx` (admin only, `/settings`): company
info · user management (`/users/invite`, `/role`, `/deactivate`) · read-only
decision rules · **impersonation** (AuthContext `viewAs`/`effectiveUser` — identity
stays real, experience follows the target; "Viewing as X — Exit" banner). My
Queue's Simulate-response is now a modal with doc checkboxes.

**Compliance read-only** (`82b7df8`) — viewer AND compliance can't decide
(LoanDetail `canAct`; `/pipeline/decide` 403s them).

**Verified** the whole workbench across all 5 roles + Pacific isolation (the
spec's emails are jumbled vs the seed — real creds: processor=processor1@,
underwriter=underwriter@, manager=manager@, compliance=compliance@, admin=admin@
summit.com, all `accord2026`). Then **deployed** — both ECS services rolled to
**rev :3**, every new endpoint confirmed live on the ALB.

**Live:** http://accord-alb-588286075.us-east-1.elb.amazonaws.com — 5 tenants,
role-based queues, AI-recommends/user-decides, comms + notifications, manager
team view, governance exports, admin settings. Pilot-ready. Still open: custom
domain + SSL; per-tenant decision-rule editing; Override still a demo toast.

---

### Session 24 — June 13–15 2026 — Underwriter workbench, marketing landing, governance/audit stack (Prompts A–F)

Two themes: a **customer-facing rebuild** (underwriter workbench + marketing
landing) and the **governance/audit "claims stack"** (every decision tied to the
rule version + regulation that governed it, with rate-lock protection and a
dynamic policy studio). All deployed to the `accord` ECS cluster (frontend +
api task-def revs climbed `:49 → :58`); each slice was headless-verified against
the live ALB before moving on.

**Customer-facing**
- **Underwriter workbench** — rebuilt `pages/LoanDetail.tsx` as a two-column
  decision cockpit (Briefing → Decision Snapshot → Attention Items → tabs
  [Checks/Evidence/Notes/Audit] → sticky ActionPanel + AuditStrip), ~13 new
  `components/workbench/*`. New `loan_actions` table + `api/accord/workbench.py`
  (documented actions w/ ≥25-char reason, similar-cases). Carried OFAC/QM badges,
  EvidenceDocumentPanel, metric chips, RuleLayerBadge unchanged. Hid
  "View in EDMS" in the workbench via `showEdms` prop.
- **Marketing landing** — full rebuild under `components/landing/*` (15 sections:
  hero w/ in-code product mockup, integrations, video, persona strip, how-it-works
  flow [Row 2 ← arrows], features/compliance/products grids, **animated**
  Simulation [auto-cycle + typewriter], dark-green impact, pricing, FAQ, CTA,
  footer). Brand greens `#0F4D37`, Plus Jakarta Sans, hero mockup animates on a
  loop. Logo iterated to **match the app nav exactly** (`Header.tsx` `bg-brand`
  "A" square + "accord" via shared `AccordLogo`). Routing unchanged (unauth `/`
  → Landing, auth `/` → `/pipeline`).

**Governance / audit stack (the claims)**
- **A — rule_version_id on every decision.** `decision_store.write_decision` +
  importer + revert paths stamp the active `tenant_rules` version at decision
  time; loan-detail + examiner expose it; backfilled 2,482 rows (demo tenant has
  no rules → NULL by design). `_get_active_rule_version_id` never blocks a write.
- **B — rain check (rate-lock pinning).** `entity_states.pinned_rule_version` +
  `application_date`; `resolve_applicable_rules` (pin → pipeline_cutoff → current);
  `compute_rain_check` on loan-detail + examiner; workbench "Rate lock active"
  badge. Backfilled application_date on all 8,896 loans + pinned 25 locked loans.
- **C — state rules + regulation transparency.** `vw_compliance_check_context`
  now evaluates `state_rules_passed` from `regulatory_rules` by property_state
  (URLA_1003); 313 loans now fail state rules (TX cash-out LTV>80, home-equity
  cooling). New `vw_regulation_transparency` + `/regulation-transparency` admin
  page (federal 8 / agency 15 / state 11 + lender overlays + pipeline-protection),
  gated admin/compliance ("Policy Rules" nav tab).
- **D — decisions.yaml citations + dynamic thresholds.** Every threshold boundary
  in `decisions.yaml` tagged with `governed_by` (regulation + citation);
  evaluator parses string|dict clauses; new `ThresholdResolver`
  (tenant_rules → agency_guidelines → yaml default, with agency floor
  enforcement). `governed_by` column + backfilled 27,295 decisions; Decision
  Journey + examiner show the citation per decision. 61 policy_engine tests pass.
- **E — Policy Studio backend.** Hardened `validate_overlay` (DTI>57, LTV>97 hard);
  `PUT /rules/overlay` (422 on floors, force/warnings); `POST
  /rules/overlay/preview-impact` (proposed rules vs active decisions) + "Preview
  Impact" button; `POST /rate-sheet/upload` (CSV → new `rate_sheet_entry` table,
  the existing `rate_schedule_period` is an incompatible ARM table) + Rate Sheet
  panel.

**Architecture notes worth remembering:** the live 119k decisions are **seeded**,
not produced by the PolicyEvaluator at runtime — the cron writer uses
`agent._compute_offline(bundle, None)`. So D's governed_by + resolver are wired as
mechanisms (verified directly) and the seeded rows are backfilled from the
decisions.yaml governance map. `entity_states.ltv` is a **percent**, `dti_back` a
**fraction**; `tenant_rules`/`agency_guidelines` thresholds are **percents** — the
resolver scales YAML fractions accordingly. Still open: custom domain + SSL
(accordlend.com cert pending); demo video re-record (workbench changed the loan
page); `BrandMark` now unused in landing.

---

## How to resume next session

Open Claude Code:
```bash
/c/Users/bkgou/AppData/Roaming/npm/claude
```

Paste this at the `>` prompt:
```
Read these files in this order before doing anything:
1. docs/PRD.md
2. CONTEXT.md
3. domains/lending/decisions.yaml
4. domains/lending/knowledge_base.json

Then verify what actually exists:
  find . -name "*.py" -o -name "*.yaml" -o -name "*.json" -o -name "*.sql" \
    | grep -v .git | grep -v __pycache__ | sort

Do not ask what the project is. Do not ask what was built.
Read the files and know.

STEPS 1-11 + 13 + Session-8 UI expansion are complete:
  ✅ STEP 1  core/normalizer/models.py
  ✅ STEP 2  core/ontology/object_types.py
  ✅ STEP 3  core/context_store/{base,lending,redis_cache,
             postgres_store,context_builder}.py + schema.sql
  ✅ STEP 4  core/connectors/{base,mock_csv,mock_http}.py
             + correlation_id / request_id on BaseEvent
  ✅ STEP 5  core/decision_agents/{base,atomic_tool,mode_router}.py
             + core/trace/trace_writer.py
  ✅ STEP 6  core/execution/dag_executor.py
             + InMemoryEventBus + fraud_block_stops_pipeline
  ✅ STEP 7  api/{deps,ingest,routes,main}.py
  ✅ STEP 8  core/trace/reflection.py
  ✅ STEP 9  domains/lending/personas/ — 12 concrete persona classes
  ✅ STEP 10 domains/lending/seed_events/ + runner.py
  ✅ STEP 11 ui/ — local FastAPI + Jinja2 + HTMX + Tailwind via CDN.
  ✅ STEP 13 core/simulation/replayer — point-in-time replay, persona
             swap surface, never mutates live state. Smoke at
             scripts/smoke_replayer.py.
  ✅ Session 8 UI expansion:
       ui/templates/personas/*.html — 12 per-persona panels
       ui/templates/decision.html cross-cutting strips (routing,
         read-perms, atomic-tool pipeline, upstream status, lit
         boundary)
       ui/templates/workbench{,_index}.html — 9 owner-team
         workbenches with KPI strip + app picker + queue / focused
         view (finished / pending / waiting / downstream impact)
       Top nav reorganised — Workbench is the primary entry.
  ✅ STEP 13 core/simulation/{__init__,replayer}.py
             — Replayer + ReplayResult/ReplayComparison/
               DecisionComparison. _ReadOnlyAtTimeShim wraps the live
               durable so reads pin to replay_at and writes raise.
               _ShadowModeRouter forces every action to SHADOW_RECORD.
               Two entry points: replay_application(persona_overrides)
               for full-DAG backtests, replay_decision(persona_override)
               for single-decision swap. Replayer.from_platform()
               keeps core/simulation independent of api/.
             — Side fix in core/context_store/lending.py snapshot:
               when at is set, upstream decision reads now use
               get_at_time too (was always get_latest). Live path
               unchanged; replay correctness depends on it.
             — Smoke: scripts/smoke_replayer.py
               (run with `python -X utf8 scripts/smoke_replayer.py`)
               4 phases: as-is parity, persona swap surfaces credit
               band downgrade, validation raises on decision_id
               mismatch, full-DAG override; live trace_writer +
               durable store fingerprint byte-identical before & after
               every replay.
  ✅ ALSO    core/policy_engine/loader.py (DecisionsSpec).
             docs/PRD.md §17/§19 reconciled (v0.7).

Run the UI locally:
  uvicorn api.main:get_app --factory --reload --port 8000
  → http://localhost:8000/

End-to-end verified (in-memory backends only):
  - All 4 seed scenarios pass via run_scenario(platform, name).
  - UI smoke (TestClient): /, /ui/applications/{id}, decision detail,
    /ui/queue, override POST returning AgentLearning swap, reload
    showing attached review, same-outcome rejection rendering inline
    error in the form partial.
  - POST /override (the API route) and /ui/.../override (the HTMX
    route) both call ReflectionService.capture and produce identical
    AgentLearning records.
  - Replayer: as-is replay produces 12/12 outcome agreements;
    persona-swap surfaces payload diffs without touching live state.

Real-backend verification (STEPS 4-6 only) was scheduled for
Sun May 3 2026 9am PT, routine trig_013QhFbYJaViJfNybCbr3KUX.
If the PR has landed on branch session-4-real-backend-verification,
start by reviewing it; otherwise check
https://claude.ai/code/routines/trig_013QhFbYJaViJfNybCbr3KUX
for status. Note: STEPS 7-11 + 13 are NOT in scope of that scheduled
run — they need a separate verification when ready.

STRATEGIC DIRECTION (locked Session 8): PATH C — full DecisionOS as
system of record, 12-18 month roadmap. Build sequence in PRD §19 is
broken into 6 tiers; complete a tier before opening the next.

═══════════════════════════════════════════════════════════════════
SESSION 9 SETUP (user direction at end of Session 8 — READ FIRST)
═══════════════════════════════════════════════════════════════════

User said:
  "I would research UIs for workbench for all personas and we can
   design UI accordingly. Lets simulate with more applicants and
   get more confident about it. One thing we missed are the
   rules/policies — every decision needs to validate against a
   rule active at that time, may be a Type 2 kind of design and
   a shared object. Lets come up with Policies for different
   types of rules for Freddie Mac and others and also have
   connectors defined so we pull these external sources
   periodically."

That reshapes tomorrow into 4 work-streams. The third is the big
architectural one — DON'T jump to STEP 14 tests until the policy
data model is decided, because the schema + trace shape changes.

  STREAM A — UI research (USER doing this, not Claude)
    User will bring industry references (Encompass workstation,
    Blend underwriter UX, etc.). Wait for designs before iterating
    further on the workbench.

  STREAM B — More seed scenarios for confidence
    Today only 4 scenarios (happy_path, fraud_block, contamination,
    compliance_block). Add 6-10 more applicants covering:
      - jumbo loan (loan_amount > conforming limit)
      - self-employed with 2-yr tax returns vs 1-yr (income confidence)
      - first-time homebuyer with FHA (different agency rules)
      - VA loan (zero-down, different LTV cap)
      - investment property (lower LTV cap, higher rate adjustment)
      - cash-out refinance (different LTV math)
      - HELOC / second-lien (different priority)
      - mixed-use property (compliance edge)
      - co-applicant scenarios (joint income, joint credit)
      - re-application (same Applicant, new Application — tests the
        WHO vs WHAT-NOW ontology distinction in PRD §9.1)
    Each scenario lives in domains/lending/seed_events/<name>/ with
    events.csv + bureau_responses.json + entities.json + an
    expected_outcome map.

  STREAM C — Policies as Type-2 versioned shared object (BIG)
    The architectural gap the user surfaced: today decisions.yaml
    is static config. PolicyEvaluator reads it once at startup. A
    DecisionTrace doesn't reference which version of the policy
    was in effect when the decision was made. For real lending
    this is insufficient because:
      - Agency guidelines change ~6x/year (Freddie Mac selling
        guide, Fannie Mae selling guide, FHA HUD handbook, VA
        circulars, USDA HB-1-3555 updates)
      - Regulators want to see "what rule was in effect when you
        decided this loan" — Type 2 SCD answers that
      - Different products use different agency rules for the same
        decision (e.g. LTV cap for conforming vs FHA vs VA)
      - A lender may have their own OVERLAY rules on top of the
        agency rules (stricter than agency)
      - Replay correctness: a 2024 decision must be replayed
        against the 2024 rule, not today's rule

    Architectural sketch (decide together at start of Session 9):

      Policy (new ObjectType, top-level entity)
        primary_key: policy_id
        properties:
          policy_id, name, description, owner_team,
          agency (enum<freddie|fannie|fha|va|usda|lender_overlay|state>),
          decision_id (which of the 12 lending decisions this rule
                       applies to; nullable for cross-cutting),
          product_scope (list of loan_type values this applies to),
          state_scope (list of states; null = all states)
        decisions_that_read_it: [whichever decisions the policy gates]

      PolicyVersion (new ObjectType, versioned)
        primary_key: policy_version_id
        properties:
          policy_version_id, policy_id (FK to Policy),
          version_number, valid_from, valid_to (null = current),
          source_url (link to agency guideline document),
          source_revision (e.g. "Freddie Selling Guide Bulletin 2026-04"),
          boundary (the actual clauses — same shape as
                    decisions.yaml today, but per-version),
          contamination_guard, hard_rules_subscribed,
          ingested_at, ingested_by (connector id),
          superseded_at, superseded_by (Type 2 chain)

      PolicyEvaluator refactor:
        evaluate(decision_id, context, *, at, agency_chain)
          → looks up the active PolicyVersion at `at`, walks the
            agency_chain (e.g. [lender_overlay, freddie] — overlay
            wins), evaluates clauses against context, returns
            PolicyDecision with policy_version_id stamped.

      DecisionTrace gets a new field:
        policy_version_id: UUID  # exactly which rule version fired
        policy_chain: list[UUID] # agency stack consulted

      Connector pattern (PullConnector subclass):
        FreddieMacGuidelineConnector — schedule weekly poll of
          their bulletin RSS, fetch new selling-guide chapters,
          parse boundary clauses (or feed to LLM for extraction),
          insert as new PolicyVersion with valid_from = bulletin
          effective date, valid_to = null. Old version's valid_to
          gets set to (new.valid_from - 1 day).
        FannieMaeGuidelineConnector — similar.
        FHAHandbookConnector, VACircularConnector, USDAHandbookConnector.
        LenderOverlayConnector — internal; pulls from a config
          repo or DB the lender maintains.

      Migration path for the existing decisions.yaml:
        - Option 1: keep decisions.yaml as the lender_overlay seed
          (load once, write as PolicyVersion rows)
        - Option 2: split decisions.yaml into per-decision policy
          files indexed by agency, version-stamped
        - Option 3: deprecate decisions.yaml entirely; everything
          comes from the policy store
        Decide tomorrow.

      Replayer interaction (already correct architecturally):
        Replayer pins reads to `at` via _ReadOnlyAtTimeShim. Once
        PolicyEvaluator looks up policies by (decision, at),
        replays automatically use the right rule version. No
        Replayer changes needed beyond passing `at` through.

  STREAM D — Connectors for periodic agency-guideline pulls
    Concrete sources to define connectors for:
      Freddie Mac Selling Guide:
        https://guide.freddiemac.com/app/guide/
        publishes Bulletins (~6/year) with effective dates
      Fannie Mae Selling Guide:
        https://selling-guide.fanniemae.com/
        publishes Selling Guide Announcements
      FHA HUD Handbook 4000.1:
        https://www.hud.gov/program_offices/housing/sfh/handbook_4000-1
        published as a single document, revised periodically
      VA Lender's Handbook (M26-7):
        https://benefits.va.gov/warms/pam26_7.asp
        circulars issued as updates
      USDA HB-1-3555:
        https://www.rd.usda.gov/resources/directives/handbooks
      State regulators: 50 of them, varying formats

    Connector design:
      class AgencyGuidelineConnector(PullConnector):
        - schedule: weekly (most agencies bulletin monthly-ish but
          weekly poll catches mid-cycle releases)
        - fetch: scrape RSS / API / HTML index, diff against last
          ingested revision
        - normalize: extract effective_date, source_url, revision_id,
          and the boundary clause text
        - emit: PolicyVersionIngestedEvent → EntityHydrator writes
          a new PolicyVersion row, sets old version's valid_to

      Big open question for tomorrow: how to extract boundary
      clauses from natural-language guidelines. Two paths:
        (a) Manual SME translation (slow, accurate, defensible)
        (b) LLM extraction with a structured rubric (fast, needs
            review, less defensible to a regulator)
      Probably (a) for v1 — at least until we have a flow for
      reviewing LLM-extracted rules before activating them.

═══════════════════════════════════════════════════════════════════
EFFECT ON TIER 1 PRIORITY
═══════════════════════════════════════════════════════════════════

Original Session 8 plan was: STEP 14 tests → real-backend
verification → async pass.

Reordered for Session 9:
  1. Design policy data model (STREAM C above) — DECIDE the
     ObjectType shape, the PolicyEvaluator refactor, the trace
     field, and the migration path for decisions.yaml. This
     happens BEFORE any code so we don't write code we'll
     immediately rewrite.
  2. Write more seed scenarios (STREAM B) — these double as
     test fixtures. Build the scenarios to be policy-aware
     (each scenario can reference an agency_chain).
  3. THEN STEP 14 tests, with the new schema in mind.
  4. Real-backend verification + async pass slot in after.

UI work (STREAM A) is unblocked from Claude's side — wait for
user's research before any further workbench iteration.

═══════════════════════════════════════════════════════════════════


Build next — TIER 1 (FOUNDATION — nothing else proceeds without these):
  STEP 14 tests/                Persistent pytest suite. Today only
                                tests/core/context_store/test_in_memory.py
                                exists. Bug-catchers first:
                                - tests/core/policy_engine/test_loader.py
                                - tests/core/trace/test_reflection.py
                                - tests/domains/lending/test_seed_scenarios.py
                                Then expand to api/, ui/views.py,
                                personas, replayer.

  REAL-BACKEND VERIFICATION     Check status of routine
                                trig_013QhFbYJaViJfNybCbr3KUX (May 3
                                scheduled). If PR landed on
                                session-4-real-backend-verification,
                                review. If not, fire it manually:
                                  docker compose up -d postgres redis
                                  apply core/context_store/schema.sql
                                  swap PostgresDurableStore +
                                    RedisHotCache in api/deps.py
                                  re-run all smokes against live DB.

  ASYNC PASS on ui/views.py     Replace synchronous _records walks
                                with async store calls — needed for
                                Postgres swap. Same applies to
                                api.deps._default_resolver and
                                core.simulation._build_replay_resolver
                                (both walk _records today).

After TIER 1, see PRD §19 for tiers 2-6:
  TIER 2 — Real connectors (web form push + Experian pull + outbound
           writeback skeleton)
  TIER 3 — Operational hardening (auth + HumanQueue.resolve() +
           multi-tenancy)
  TIER 4 — Regulatory (HMDA + audit export + adverse action notice)
  TIER 5 — Production deploy (observability + DR + real critic)
  TIER 6 — Persona enrichment (real Anthropic + outcome_tracker +
           send_back outcome + semantic_layer/flow.py)

OPEN ARCHITECTURAL QUESTIONS for path C:
  - Tenant model: row-level (recommended) vs schema-per-tenant.
    Decide before TIER 3.
  - LOS integration order: Encompass (~50% US mortgage) vs Blend.
    Driven by first design partner's stack.
  - Critic model: Sonnet for persona / Opus for critic so
    SelfReviewError can never fire.
  - Borrower portal: separate frontend project, NOT in this repo.
  - human_approval simulate-mode for tests: option (a) auto-approve
    queued items mid-DAG for scenario regressions, plus option (b)
    one dedicated override-flow test.
  - HumanQueue.resolve(): add when wiring TIER 3 dequeue flow.
  - Replayer downstream-cascade reach: persona swap on
    credit_assessment didn't propagate to LTV / pricing / UW because
    downstream personas re-derive inputs from entity reads, not
    upstream output payloads. Either upstream personas write derived
    signals into the entity store, or downstream personas read
    upstream output payload directly.

How to run the local UI:
  uvicorn api.main:get_app --factory --reload --port 8000
  → http://127.0.0.1:8000/ui/workbench  (primary entry)

How to run smoke tests:
  python -X utf8 scripts/smoke_replayer.py
  python -X utf8 scripts/smoke_ui_all_panels.py
  python -X utf8 scripts/smoke_workbench.py
```

---

## Open questions (unresolved)

```
1. First design partner — org type, domain, workflow, volume?
2. Pricing model — per-decision / per-application / platform fee?
3. Single-tenant v1 or multi-tenant v1?
4. Which connectors live at launch vs mock?
5. AI model strategy — hosted API / bring-your-own / self-hosted?
6. Override authority — single approver or dual-control for high-risk decisions?
7. Connector marketplace — build all integrations or open SDK?
8. "Request more evidence" outcome — needed for human bounce-back to upstream personas?
```

---

*Decision OS · CONTEXT.md · Updated June 20 2026 (Session 20 — Phase 13 Explanation Engine started EX2-A: `core/explanation/ExplanationEngine` turns the decision trace into loan_officer/underwriter/regulator narratives via Claude (env `CLAUDE_MODEL_ID`, default sonnet-4-6) with a deterministic template fallback; `GET /api/accord/trace/{app}/explain`. Lazy key-gated client (works offline → templates), evidence_trace read flat by fact_type, no misleading audit write. Local verify = template path only (no API key set). Prior Session 19 completed Decision Trace Phase 12 TR-A→TR-C + wired title_assessment into the cron runner (IN-D) + persona count tests 13→15; Session 18 shipped 5 resolver subsystems (Title/Credit/Asset/Fraud/Collateral/Conditions). Score 15/16 (SC12 rental income the miss). Open items: Claude explanation path unexercised until ANTHROPIC_API_KEY set; trace export JSON-only; title escalates on 15/16 (title_clear unseeded); collateral/fraud wired-not-gating; two conditions tables coexist. Next: EX2-B (explanation workbench UI).)*

---

*Decision OS · CONTEXT.md · Updated June 21 2026 (Session 21 — Repurchase-Audit track RA-1→RA-2, score now 16/16. Tracker 10 done / 18 pending.*

*__Phase 1 — Catalogue + rule_loader (RA-1A→RA-1D):__ `agency_guidelines` seeded to a canonical 55-row set (asset/credit/income/property, every row cited) + 8 `platform_guardrails` risk thresholds; migrated to __Type 2 SCD__ (`valid_from`/`valid_to`/`version_id`/`downloaded_at`/`source_revision`, `vw_guidelines_current`, `agency_guidelines_at(date)`). Built `scripts/catalogue/refresh_fannie_guidelines.py` — Playwright headless fetch (Fannie Selling Guide is a JS SPA; old `/sel/b3/4.3/04` paths 404, live format is `/sel/{id}/{slug}`) → Claude extract → Type 2 upsert. Extraction gated on `ANTHROPIC_API_KEY` (now set); constrained to a `CANONICAL_NAMES` set so extracted rows match the resolver contract (free-form names deleted). Built `core/catalogue/rule_loader.py`: `get_rule` (3-layer regulatory/agency/overlay; overlay applied, others as GREEN/AMBER/RED risk refs), `get_catalogue_value`, `load_rules`, `SAFE_DEFAULTS`. Schema gotchas baked in: `overlay_rules` keys on `rule_type` (OVERLAY_ALIASES bridges canonical→lender names), `overlay_value` is NUMERIC→Decimal, `as_of` MUST default to DB `CURRENT_DATE` (rows stamped UTC; local clock a day behind excludes every current row).*

*__Phase 2 — Golden record + audit (RA-2A→RA-2D):__ Built `scripts/audit/senior_uw_audit.py` — 9-phase senior-UW repurchase-defense audit across all 16 meridian loans (schema-corrected for real columns). NOTE: there is no document→entity_states builder; meridian `entity_states` are hand-seeded fixtures (`scripts/seed_meridian_tenant.py`) intentionally tuned for scenario outcomes. Created `core/pipeline/golden_record_builder.py` as production-correct derivation primitives (`compute_ltv` lesser-of B4-1.1-01, `compute_mid_score` 3-bureau B3-5.1-01, `extract_flood_zone`/`property_type`/`purchase_price`/`occupancy_type`/`loan_purpose`/`monthly_obligations`), 15/15 unit tests — but did NOT blanket-run it over the tuned fixtures. Applied only SAFE additive/non-breaking corrections to live data (`scripts/fixes/apply_safe_fixes*.py`): LTV lesser-of on 15/16 (SC06 skipped — would cross the 95% limit & flip), flood_zone on SC08/14/16, verified obligations into `loan_terms.obligations` (all 16). Audit finding lineage: 178→160→177; the RA-2D rise (CRITICAL 20→36) is the audit becoming DTI-accurate (now counts real `total_monthly_obligations`) — this confirms stored DTI was right (the RA-2A "DTI mismatch→golden_record bug" was the audit understating, downgraded) and surfaces 16 real DTI-over-43%-overlay findings. Deliberately NOT touched: SC08 mid-score 578 (intended credit block), SC06 LTV (real over-limit). Remaining real findings drive later phases: 38 hardcoded resolvers → RA-4, 14 `vw_*_context` views not reading `fact_nodes` → RA-3, 14 P3 asset-reserve data-completeness. Audit outputs: `audit_results.txt`/`_v2`/`_v3`. Next: RA-3.)*

*__Phase 3 — Evidence wiring (RA-3A→RA-3B):__ RA-3A audit confirmed `fact_nodes` ARE populated (75 rows, 4 doc-derived types across all 16 apps: `qualifying_income`/`verified_assets`/`governing_credit_score`/`employment_continuity` — note the live names differ from the earlier-assumed qualifying_assets/governing_credit/employment_status), good confidence (0.88–0.95), 9 conflict rows (SC03/SC08/SC15), resolved from documents (W2 box1, bank balances, mid-score) not entity_states. The `ContextEnricher` (EV-E) existed but was NEVER called, and `vw_*_context` views expose zero fact_nodes columns — so all personas ran off raw entity_states. There is NO fraud fact type (RA-3E gap). RA-3B (EV-F) wired it: added `ContextEnricher.evidence_facts()` (direct `superseded_by IS NULL` query → exactly 7 keys: `evidence_qualifying_monthly`/`_governing_score`/`_verified_assets`/`_employment_status`/`_overall_confidence`=min/`_any_conflicts`/`_populated`; employment uses fact_text, others fact_value; graceful empty never raises) and called it in `core/cron/runner._process_one` — enriches `snapshot.context['evidence'][app_id]` before any persona reads the bundle, best-effort try/except. Non-destructive, no persona/policy/resolver logic changed (that's RA-3D/RA-4). Verified: evidence_populated=True all 16; evidence_any_conflicts=True for SC03/SC08/SC15; min-confidence correct (SC03 0.85, SC08/SC15 0.97, SC01 1.0). Tests 370 pass / 13 pre-existing fail (unchanged — the prompt's "all tests pass" was wrong; established baseline, zero new failures). 16/16 holds. Next: RA-3C (views) / RA-3D (personas consume evidence).)*

*__RA-3C — evidence columns on all 14 `vw_*_context` views:__ `scripts/migrations/add_evidence_columns_to_views.py` makes the SQL layer mirror the RA-3B runtime enricher. Per-fact columns `ev_{income,credit,asset,employment}_value/_confidence/_method/_conflicts/_conflict_ids` (assigned per view by relevance) + aggregates on every view (`evidence_populated`/`evidence_any_conflicts`/`evidence_overall_confidence`=MIN), all `WHERE superseded_by IS NULL`, null-safe correlated scalar subqueries. Implementation WRAPS each view (`CREATE OR REPLACE VIEW v AS SELECT base.*, <ev subqueries on base.application_id> FROM (<orig def>) base`) — robust for the views with nested subqueries (credit/title have 6 FROMs) where a string-append before `FROM entity_states` would misfire; `base.*` preserves existing columns/order so CREATE OR REPLACE only appends. Idempotent; originals backed up to `scripts/migrations/_view_defs_backup_ra3c.sql` for reversibility. Prompt named a non-existent `vw_collateral_assessment_context` and assumed `applications AS a` joins — real 14 views are single-table `FROM entity_states` and meridian apps aren't in `applications`; mapped relevance to the actual views. Verified: evidence_populated=true all 16 in every view, any_conflicts=true SC03/SC08/SC15, overall_confidence matches RA-3B. 16/16 holds (additive; nothing reads ev_* yet — that's RA-3D); 370 pass / 13 pre-existing fail. One transient RDS connection drop on first eval run; clean re-run 16/16. Next: RA-3D (personas consume evidence).)*

---

## RA-SEED-A Findings — 2026-06-22

Read-only catalogue-vs-resolver audit before the RA-4 resolver rewrites. No code changes.

### 1. Catalogue dump (what exists)
- **agency_guidelines**: 60 current rows. fannie 38, fha 12, va 8, freddie 2. Covers: asset qualifying factors (`qualifying_factor_*`), `minimum_reserves_months`, `large_deposit_threshold_pct`, `seasoning_days_required`; per-agency waiting periods (ch7/ch13/foreclosure/short_sale/deed_in_lieu) for fannie+fha+va; `student_loan_deferred_rate_pct`, `medical_collection_excluded`, `rental_vacancy_factor_pct`, `se_income_years_required`, `se_declining_use_lower_year`; `ineligible_property_types`, `flood_zones_requiring_insurance`, `condo_warrantability_required`, `max_units_conventional`; `income_mismatch_{medium,high,critical}_pct` (RA-3E), `income_documentation_confidence_{min,floor}` (RA-3D); plus human-named LTV/DTI/MI/score rows.
- **regulatory_rules**: 23 rows (cfpb/federal/state/qm/ofac/bsa) — incl `QM Safe Harbor DTI Maximum`, `Texas Cash-Out Refinance LTV`, `New York Usury Cap`, TRID/HMDA/OFAC.
- **overlay_rules (meridian)**: 4 — credit_floor 660, dti_back_max 43 (conv) / 50 (fha), ltv_max_purchase 95. All legitimately *stricter* than agency floors → none is a mis-set agency standard.
- **platform_guardrails**: 24 — per-product credit/dti/ltv outer bounds (legit) PLUS `platform/appraisal_gap_{major,minor}_pct`, `platform/income_mismatch_*`, `platform/undisclosed_debt_{medium,high,critical}_mo`.

### 2. Gap table (rule needed → in agency_guidelines via rule_loader?)
```
RESOLVER/PERSONA      RULE NEEDED                       IN CAT?  NOTES
AssetResolver         qualifying_factor_checking/sav/cd  YES     Fannie B3-4.3-04 (resolver key 'liquid' differs)
AssetResolver         qualifying_factor_retirement       YES     (resolver maps ira/401k/403b/pension/annuity)
AssetResolver         qualifying_factor_stocks_bonds     YES     (resolver key 'brokerage'/'stocks')
AssetResolver         minimum_reserves_months            YES     Fannie B3-4.3-04
DepositAnalyzer       large_deposit_threshold_pct        YES     Fannie B3-4.3-04
DepositAnalyzer       seasoning_days_required            YES     (resolver const LOOKBACK_DAYS=60)
CreditFindingsResolver bankruptcy_ch7_waiting_years f/fha/va YES  all three agencies present
CreditFindingsResolver bankruptcy_ch13_waiting_years     YES
CreditFindingsResolver foreclosure_waiting_years         YES
CreditFindingsResolver short_sale_waiting_years          YES
TradelineAnalyzer     student_loan_deferred_rate_pct     YES     Fannie B3-6-05 (resolver inline *0.01)
TradelineAnalyzer     medical_collection_excluded        YES     Fannie LL-2023-02
AppraisalAnalyzer     appraisal_gap_major_pct            NO*     in platform_guardrails only (gap_pct>10 inline)
AppraisalAnalyzer     appraisal_gap_minor_pct            NO*     in platform_guardrails only (gap_pct>3 inline)
PropertyEligibility   ineligible_property_types          YES     Fannie B2-1.3-01
PropertyEligibility   flood_zones_requiring_insurance    YES     Fannie B7-3-02
RentalIncomeResolver  rental_vacancy_factor_pct          YES     Fannie B3-3.1-08 (resolver inline *0.75)
SelfEmployedResolver  se_income_years_required           YES     Fannie B3-3.4-01
SelfEmployedResolver  se_depreciation_addback            NO      MISSING everywhere (Fannie B3-3.4-02)
UndisclosedDebt       undisclosed_debt_medium_mo         NO*     platform_guardrails only
UndisclosedDebt       undisclosed_debt_high_mo           NO*     platform_guardrails only
UndisclosedDebt       undisclosed_debt_critical_mo       NO*     platform_guardrails only
LienResolver          LIEN_RULES (title lien priority)   NO      not catalogued (structured title rules)
```
`NO*` = value exists in platform_guardrails (and rule_loader SAFE_DEFAULTS) but NOT as a cited agency_guidelines row, so `get_rule` returns it via the using_default WARNING path, not authoritatively.

### 3. Hardcoded violations (file:line → should be)
```
core/assets/asset_resolver.py:41   QUALIFYING_FACTORS {checking 1.0..crypto 0.0}  -> agency_guidelines.qualifying_factor_*  (Fannie B3-4.3-04)
core/assets/asset_resolver.py:62   MIN_RESERVES_MONTHS = 2.0                      -> minimum_reserves_months
core/assets/asset_resolver.py:66   LARGE_DEPOSIT_PCT = 0.50                       -> large_deposit_threshold_pct
core/assets/deposit_analyzer.py:36 LOOKBACK_DAYS = 60                             -> seasoning_days_required
core/assets/deposit_analyzer.py:39 LARGE_DEPOSIT_PCT = 0.50                       -> large_deposit_threshold_pct (dup)
core/credit/findings_resolver.py:70 WAITING_PERIODS {ch7 f4/fha2/va2 ...}         -> agency_guidelines.*_waiting_years (B3-5.3-07)
core/credit/tradeline_analyzer.py:150 balance * 0.01 (student loan 1%)            -> student_loan_deferred_rate_pct (B3-6-05)
core/credit/tradeline_analyzer.py    is_medical exclusion                          -> medical_collection_excluded (LL-2023-02)
core/collateral/appraisal_analyzer.py:146 gap_pct > 10 (major)                    -> appraisal_gap_major_pct (B4-1.3-09)
core/collateral/appraisal_analyzer.py:148 gap_pct > 3 (minor)                     -> appraisal_gap_minor_pct (B4-1.3-09)
core/collateral/property_eligibility_resolver.py:40 FANNIE_INELIGIBLE_TYPES       -> ineligible_property_types (B2-1.3-01)
core/collateral/property_eligibility_resolver.py:64 FLOOD_ZONE_RULES              -> flood_zones_requiring_insurance (B7-3-02)
core/title/lien_resolver.py:17     LIEN_RULES {...}                               -> NOT catalogued (decide: catalogue vs config)
core/fraud/income_mismatch_detector.py:27 MISMATCH_THRESHOLDS 0.10/0.25/0.50      -> income_mismatch_*_pct (now catalogued, RA-3E)
core/fraud/undisclosed_debt_detector.py:45 UNDISCLOSED_THRESHOLDS 200/500/1000    -> undisclosed_debt_*_mo (platform only)
core/income/rental_income_resolver.py:211 lease * 0.75 (25% vacancy)             -> rental_vacancy_factor_pct (B3-3.1-08)
core/income/self_employed_resolver.py /24 (2yr avg)                               -> se_income_years_required (B3-3.4-01)
core/compliance/rule_validator.py:19-29 FHA_MIN_3_5/FHA_ABS_MIN/CONV_MIN/DU_DTI_MAX/
   QM_DTI/FHA_DTI_AUS/CONV_LTV_MAX/FHA_LTV_MAX/VA_LTV_MAX/TX_CASHOUT_LTV/NY_USURY  -> all have catalogue equivalents (agency_guidelines + regulatory_rules)
```
NOT violations (algorithm classifiers, keep): `tradeline_analyzer.DEROGATORY_STATUSES`, `deposit_analyzer.TRANSFER_MATCH_DAYS`, `rule_validator.STATES_WITH_RULES`.

### 4. platform_guardrails rows that are agency standards → move to agency_guidelines
- `platform/appraisal_gap_major_pct` (10), `platform/appraisal_gap_minor_pct` (3) — Fannie B4-1.3-09.
- `platform/undisclosed_debt_{medium,high,critical}_mo` (200/500/1000) — Fannie QC.
- `platform/income_mismatch_*` — already duplicated into agency_guidelines (RA-3E); platform copies now redundant.
- KEEP in platform_guardrails: per-product credit_floor/dti_back_max/ltv ceilings (genuine outer bounds, not agency standards). overlay_rules: nothing to move (all 4 meridian overlays are legit stricter-than-agency).

### 5. Counts
- Distinct rules resolvers need: **24** (gap-table rows).
- In agency_guidelines/regulatory (authoritative via rule_loader): **18**.
- Not authoritative: **6** — 5 live in platform_guardrails only (appraisal_gap x2, undisclosed_debt x3), 1 genuinely missing (`se_depreciation_addback`); plus `LIEN_RULES` uncatalogued (structured).
- RA-SEED-B work: seed the 5 platform→agency moves with citations + `se_depreciation_addback`, then RA-4 rewrites the ~17 hardcoded constant sites to `rule_loader`.

---

## RA-3D / RA-3E / RA-SEED-B — 2026-06-22

**RA-3D — income_verification reads evidence quality (commit 1948bc4) + catalogue-threshold correction (d43676c).** First persona to consume `bundle.objects['evidence']` (RA-3B). Prefers evidence-qualified income (`income_source=evidence`) when confidence ≥ the catalogue threshold; emits advisory `CONTRADICTS` signals `INC_LOW_CONFIDENCE` (0.50–min), `INC_VERY_LOW_CONFIDENCE` (<floor→stated), `INC_CONFLICT_DETECTED`, `EMP_CONTINUITY_CONFLICT`; logs `income_source/method/evidence_income_confidence/threshold_trace` in `output_payload`. **Outcome-neutral by design** — the gate stays reconciliation/discrepancy/confidence-driven and `verified_income` (downstream DTI) is untouched, so 16/16 holds. Thresholds (`income_documentation_confidence_min`=0.75 / `_floor`=0.50, Fannie B3-3.1-01) seeded to agency_guidelines; persona `_compute_offline` is sync+DB-less so the **enricher** resolves them via rule_loader and attaches `income_confidence_min/floor`+`threshold_trace` to the bundle. Reality gaps vs prompt: no flat ctx/add_flag/flags-column; get_rule sig is `(conn, guideline_name, tenant_id, …)`. SC03 recommend + EMP_CONTINUITY_CONFLICT; SC09 escalate, clean income (conf 1.0).

**RA-3E — fraud_indicator fact resolver (commit 9a1263e).** `core/evidence/resolvers/fraud_resolver.py` reads the `fraud_signals` table (IncomeMismatchDetector / UndisclosedDebtDetector output) → emits a `fact_type='fraud_indicator'` FactNode (confidence from catalogue severity cutoffs via rule_loader, `conflicts_found=True`, resolution_method citing Fannie B3-3.1-01 QC). No live orchestrator exists (the 4 prior fact types were batch-seeded) → added `scripts/evidence/backfill_fraud_facts.py`. ContextEnricher exposes `fraud_populated`/`fraud_indicator_{confidence,conflicts,method}`. SC09: value=30, **conf 0.75** (30% is HIGH not critical — real cutoffs medium 10/high 25/critical 50, so the prompt's 0.95 was wrong); clean apps: no fact. Migration `add_fraud_indicator_fact_type.sql` (CHECK omitted it; reserved fraud_risk_score). conflict_ids is UUID[] → detail in resolution_notes. fraud_screening persona untouched (RA-4G).

**RA-SEED-A — catalogue-vs-resolver gap audit (commit c13df9c, read-only).** 24 rules needed: 18 authoritative, 6 not (5 platform-only, 1 missing), LIEN_RULES uncatalogued; ~17 hardcoded constant sites documented (see section above). **RA-SEED-B — seeded the gaps (commit 7f263c3).** `scripts/compliance/seed_missing_agency_rules.py` seeds 10 cited agency rows (appraisal_gap ×2 B4-1.3-09, undisclosed_debt ×3 B3-6-02, se_depreciation_addback B3-3.4-02, lien_{solar,irs,hoa,mechanics}_treatment B8-1-01/02 — LIEN_RULES decided = catalogue, agency-published guidance), removes 8 redundant platform_guardrails rows (platform bucket now empty; per-product ceilings kept). rule_loader returns governed_by=agency for all 10 (numeric/boolean/string-treatment values). Catalogue now complete for RA-4 (rewrite the ~17 hardcoded resolver sites to read rule_loader). Tests 370 pass / 13 pre-existing throughout. NOTE: flaky network (DNS/connection drops) blocked full eval runs; 16/16 confirmed via direct decision_outputs verification (SEED-B is outcome-neutral). Caveat to fix later: `evaluate_meridian_scenarios.py` runs `asyncio.run(main())` at import (no `__main__` guard) — importing it re-runs the full eval.

---

## RA-4A → RA-4E + RA-SEED-C — 2026-06-22

**Architecture Rule 1:** every threshold that governs a lending decision must come from `agency_guidelines`/`regulatory_rules`/`overlay_rules` via `rule_loader.get_rule` — not a Python constant. RA-4 removes the hardcoded constants from each resolver in sequence.

**Injection pattern (established RA-4A, applied A→D).** Resolvers are sync + DB-less (called from the sync persona `_compute_offline`). Each domain gets a module-level `async load_<domain>_rules(conn, tenant_id, agency='fannie')` co-located in the resolver file; `core/cron/runner._process_one` calls it (guarded by `decision_id == "<persona>"`) inside its existing `pool.acquire()` block and attaches `snapshot.context["<domain>_rules"]` BEFORE the `ContextBundle` is built; the persona reads via `first_object(bundle, "<domain>_rules")` and passes `rules['values']` into the resolver constructor; logs `<domain>_rule_trace` (governed_by + layers) in `output_payload`. Every rewrite proven byte-identical to the old constants via a standalone value-equivalence check, so **16/16 is preserved by construction**.

- **RA-4A — assets (commit per-slice).** `asset_resolver.py` + `deposit_analyzer.py`: removed QUALIFYING_FACTORS / MIN_RESERVES_MONTHS / LARGE_DEPOSIT_PCT; added ACCT_TYPE_TO_FACTOR_KEY, `load_asset_rules`, `_factor()`/`_reserves_months`/`_large_deposit_frac` (÷100)/`_seasoning_days`. Wired `asset_verification`.
- **RA-4B — credit.** `findings_resolver.py` (WAITING_PERIODS→WAITING_META structural + EVENT_RULE_KEY→catalogue keys, per-agency `_years`) + `tradeline_analyzer.py` (`_student_loan_rate` ÷100, gated `_medical_excluded`, replaced `balance*0.01`). Wired `credit_assessment`. Judgment 7/3/2 left structural + flagged (now seeded in RA-SEED-C).
- **RA-4C — collateral.** `property_eligibility_resolver.py` (COLLATERAL_RULE_KEYS, `load_collateral_rules`, `_ineligible_types`/`_flood_zones`; kept INELIGIBLE_REASONS UI text + FANNIE_SPECIAL_TYPES + FLOOD_ZONE_SEVERITY classifiers) + `appraisal_analyzer.py` (`_gap_major_pct`/`_gap_minor_pct`). Wired `product_eligibility`.
- **RA-4D — title liens (commit 75c5848).** `lien_resolver.py`: LIEN_RULES→LIEN_META, `LIEN_TYPE_TO_RULE_KEY` (irs/hoa/mechanics/solar), `load_lien_rules`, `_blocks_closing` derives block from the catalogue treatment string for catalogued types / structural+`logging.warning` for uncatalogued. 4 lien treatments centralised into `SAFE_DEFAULTS`. Wired `title_assessment`. Did NOT touch the lien-priority algorithm.

**RA-4E — rule_validator reads all constants from catalogue (commit 2e2adfb).** Structurally different: `core/compliance/rule_validator.py` is a **boundary self-test harness** (generates synthetic loans at each rule boundary, runs them through a local `evaluate()` to prove the boundaries behave as documented), NOT a domain resolver — and it's NOT in the meridian 16/16 path (used only by `api/accord/validation.py` + `importer.evaluate_imported`). Removed 11 module constants; the clean injection point was the resolved-rule dict `R` (already threaded through `evaluate()` + every `gen_*`). `VALIDATOR_RULE_SPECS` maps each canonical key → its REAL catalogue row (the prompt's snake_case keys like `ltv_purchase_max` mostly don't exist — the live rows are human-named: `FHA Minimum Score (3.5% down)`, `DU Maximum DTI`, `Primary Residence 1-Unit Max LTV`, + regulatory `QM Safe Harbor DTI Maximum`/`Texas Cash-Out Refinance LTV`/`New York Usury Cap`). New `async load_validator_rules(conn, tenant_id)→{values,trace}`; `resolve()` gains an optional catalogue arg, falls back to `SAFE_DEFAULTS` (value-for-value identical) on the conn-less path; `run_all()` emits `rule_validator_trace`. Dropped dead constant `FHA_DTI_AUS`. These are the AGENCY baseline — the tenant overlay stays layered separately via `resolve(tenant_rules)` (R['dti_max']/'ltv_max'/'credit_min'); the human catalogue names don't alias to any overlay rule_type, so get_rule returns the agency/regulatory value cleanly (verified on tenant `pacific`: governed_by stayed agency/reg). Verified: boundary suite **108/108** both offline and against the live catalogue, all 10 resolved values byte-equivalent. Only `FHA_ABS_MIN`=500 was uncatalogued → safe_default (closed by RA-SEED-C).

**RA-SEED-C — pre-RA-4F mini seed pass (commit 71834b4).** `scripts/compliance/seed_pre_ra4f_rules.py` seeds 11 cited `agency_guidelines` rows flagged uncatalogued during RA-4A→E, so RA-4F (fraud) / RA-4G (income) can read them instead of hardcoding: `FHA Absolute Minimum Score (10pct down)`=500 (HUD 4000.1 — closes the last `rule_validator` safe_default), `Judgment Waiting Period`=7 (B3-5.3-07), `Installment Debt Months Remaining Exclusion`=10 (B3-6-05), `Self-Employed Business Ownership Majority/Full/Partial`=25/100/50 (B3-3.4-01), + 5 lien treatments `lien_{tax_property,state_tax,judgment,child_support,lis_pendens}_treatment`=blocks_closing (B8-1-02). **Naming is per-family, verified vs live RDS not assumed** (the RA-4E lesson generalised wrong): FHA/credit/income/asset families are human-named, the lien family is snake_case (`lien_<type>_treatment`) to match the 4 RA-SEED-B rows + `LIEN_TYPE_TO_RULE_KEY` values + `SAFE_DEFAULTS` keys. User decisions on two forks: (1) **child_support seeded `blocks_closing` not `requires_payoff`** — `_blocks_closing` only blocks on the exact string `"blocks_closing"`, so `requires_payoff` would have flipped its structural `auto_block=True` block→non-block (a decision-logic change); (2) **snake_case for all 5 lien rows**. Wiring: `VALIDATOR_RULE_SPECS` FHA-abs name aligned (`10pct down`) → now governed_by=agency; `LIEN_TYPE_TO_RULE_KEY` +5 types (all blocks_closing = each type's structural LIEN_META value → no decision change, verified each still blocks, lis_pendens still fatal/unresolvable); `SAFE_DEFAULTS` +5 lien keys; readiness gate `verify_catalogue_ready.py` 48→**59/59 exit 0**. Boundary suite still 108/108 with `fha_abs_min_score` now governed_by=agency. Tests **13 failed / 370 passed** (== pre-existing baseline, zero new). Additive catalogue + spec-map wiring only — no resolver logic / persona / evidence-graph changes; 16/16 unaffected by construction. Catalogue now ready for RA-4F/G. Latent tidy-up: the 5 newly-wired LIEN_META entries still carry a now-redundant structural `blocks_closing: True` (ignored once catalogued). Remaining: **RA-4F (fraud)**, **RA-4G (income)** resolvers.

---

## RA-4F + RA-0-ARCH + RA-3F + RA-4G + RA-4H — 2026-06-22

**RA-4F — fraud detectors read thresholds from catalogue (commit 9a88ad7).** `core/fraud/income_mismatch_detector.py` (removed `MISMATCH_THRESHOLDS` → `income_mismatch_{medium,high,critical}_pct`, percent ÷100) + `undisclosed_debt_detector.py` (removed `UNDISCLOSED_THRESHOLDS` → `undisclosed_debt_{medium,high,critical}_mo`). New `core/fraud/fraud_rules.py:load_fraud_rules(conn,tenant_id)→{values,trace}`. **Reality gap vs prompt:** detectors are ASYNC + hold `self.conn` (RA-4F-style self-load, NOT the sync RA-4A-D bundle-injection — the prompt's "detectors stay sync" was wrong); they lazy-load + cache. `employment_fraud_detector.py` UNTOUCHED — it has no catalogued numeric threshold (stop-words / vacation-state set / severity labels are classifier logic; confirmed no employment-fraud rows in catalogue). Structural `(signal_type,severity,auto_block)` tier maps kept in Python; only numeric cutoffs moved. Value-equivalence: 0 mismatches across a boundary sweep (10/25/50÷100==0.10/0.25/0.50; 200/500/1000); all 6 keys governed_by=agency. APP-MRID-SC09 still income_inflation/high (30%≥25%), 15 apps clean; fraud_signals write path + FraudFactResolver untouched (RA-3E). 13 failed / 370 passed.

**RA-0-ARCH — docs/ARCHITECTURE.md permanent flow reference (commit 6ac17ed).** Mandatory-read-before-every-task: complete data flow (document→entity_states/fact_nodes→14 views→runner→bundle→persona→decision_outputs→persona_bundles), 10 architecture rules, real file paths, table reference, persona status, catalogue state, done/pending list, never-do list. Verified vs live repo+RDS, corrected 4 draft errors: RA-4F marked done (not pending); overlay_rules=6 rows (Meridian 4 / Summit 2) not 4/Meridian-only; agency breakdown Fannie 58 / FHA 13 / VA 8 / Freddie 2 (total 81); golden_record_builder flagged design-vs-runtime (meridian entity_states are hand-seeded fixtures, not golden_record-populated).

**RA-3F — persona_bundles audit snapshot table + runner wiring (commit 6fbccf2).** `scripts/migrations/create_persona_bundles.sql` (id, application_id, tenant_id, persona_id==decision_id, version, is_current, created_at, {entity,evidence,rules,upstream}_snapshot JSONB; UNIQUE current/version scoped by tenant) + `decision_outputs.bundle_id` FK. `runner._process_one` captures `write_decision`'s returned row id, then best-effort `_write_persona_bundle()` AFTER the decision commits: freezes the REAL ContextBundle (`objects` = evidence + `*_rules` + entity/view projection; `upstream_outputs`), bumps version + flips old is_current=false, stamps `decision_outputs.bundle_id` on the EXACT row id (decision_outputs is versioned — superseded_by is NEVER set, so "current" = MAX(version), and the all-versions UPDATE the draft proposed was wrong). **Schema corrected vs draft:** application_id/tenant_id are TEXT not UUID; "same transaction" reconciled to best-effort-after per the "decision already committed, never block" rule; snapshots from the real bundle shape, not the draft's non-existent flat attrs. Verified: full eval wrote 224 current bundles (16 apps × 14 personas), all current decision_outputs.bundle_id populated, one is_current per (app,persona).

**RA-4G — rental + SE income resolvers read from catalogue (commit 3234426).** `rental_income_resolver.py` (removed `lease*0.75` — the COMPLEMENT of 25% vacancy, not a literal 0.25 — → `rental_vacancy_factor_pct`/100; occupancy=1-vacancy) + `self_employed_resolver.py` (removed always-on depreciation add-back + always-use-lower-year → `se_depreciation_addback` / `se_declining_use_lower_year`; surfaces `se_income_years_required` informationally — there was NO `YEARS_REQUIRED=2` constant; the resolver never gated on years). Async + self-load (hold conn, like RA-4F; resolve() already queries DB — the prompt's "resolve() sync" was wrong); SAFE_DEFAULTS only fallback (in load_rules). Value-equivalence: 0 mismatches (25/true/true/2 reproduce old outputs); all 4 governed_by=agency. **Flagged:** the resolver CLASSES have no importers (only `core/income/__init__.py`); STEP 6 (income rules in income_verification.rules_snapshot) is N/A — that persona doesn't receive runner-injected income rules; did NOT cargo-cult unused injection. (Caveat surfaced later in RA-4H: SC12's eval note shows rental Schedule-E logic IS reachable in the income_verification path via an equivalent route — so "dead code" was too strong; to trace in a follow-up.)

**RA-4H — title gap fix + rule_validator already-done + runner retry (commit abd4966).** TASK A: the RA-4G 15/16 title_assessment rules_snapshot gap = APP-MRID-SC03, a TRANSIENT `load_lien_rules` blip during the flaky RA-3F eval (before-state `has_evidence=True, has_rules=False` proved evidence succeeded then the rule load failed in the shared try). Not missing data (lien rules are catalogue-level, app-independent), not a logic bug (both calls succeed now); decision correct (LienResolver→SAFE_DEFAULTS==catalogue). Re-ran SC03 title → v2 with lien_rules → 16/16 coverage. TASK B: **already complete in RA-4E** — rule_validator has zero hardcoded constants, boundary suite 108/108, all governed_by agency/regulatory; nothing to redo (the prompt's premise was stale). Step B6 N/A (rule_validator is the validation-API/importer self-test harness, not in the compliance_check decision path; its rules_snapshot is empty by design). **The actual code change (committed):** extracted `runner._inject_decision_rules()` with a ONE-SHOT RETRY around the catalogue rule load (per user request) so a transient blip no longer drops a decision's rules (+ empties its rules_snapshot); evidence enrichment unchanged. Helper unit-tested (normal inject ×4, no-op for non-rule decisions, retry-success, both-fail best-effort no-raise). Full eval through the new path: **16/16 (errors 0)**; all 4 rule personas now 16/16 rules_snapshot coverage; 13 failed / 370 passed. Remaining: **RA-4I** (student loan), **RA-4J** (business debt/HELOC), **RA-PERSONA-A/B/C** (personas read evidence).

---

## RA-4I + RA-4J + RA-PERSONA-A + RA-PERSONA-B — 2026-06-22/23

**RA-4I — student loan IBR/PSLF treatment per Fannie B3-6-05 (commit 7d19974).** `core/credit/tradeline_analyzer.py` RULE 3: removed hardcoded `balance * 0.01` in the IBR-$0 branch. Deferred branch already catalogue-driven (`_student_loan_rate` ← `student_loan_deferred_rate_pct`/100). IBR/PAYE/SAVE now use the documented `ibr_payment` directly even when $0 (the prompt's "DO NOT hardcode 0.01 if IBR field exists"); PSLF with documented $0 payment → EXCLUDED from DTI (`included_in_dti=False`). Unit-tested all branches (0 mismatches). **0 meridian apps carry student-loan tradelines** → RULE 3 unreached by the 16 → 16/16 by construction; verified vs the user's stated B3-6-05 treatment, not scenario coverage. (Behavior change flagged: IBR-$0 and PSLF-$0 are lending-policy changes, not pure de-hardcoding.)

**RA-4J — months-remaining DTI exclusion from catalogue (commit 9d3889c).** Verification pass on business-debt / HELOC / months-remaining in tradeline_analyzer. Only real hardcode: RULE 4 `months_rem <= 10` → catalogue `Installment Debt Months Remaining Exclusion`=10 (human-named, RA-SEED-C, governed_by=agency), wired via `load_credit_rules` → canonical key `months_remaining_exclusion` + `SAFE_DEFAULTS`=10 + `_months_remaining_exclusion` property. HELOC = structural classifier only (mortgage/heloc excluded from RULE 4) — no threshold, kept in Python. Business-debt ownership has NO code path here (the 25/100/50 SE rules live in self_employed_resolver, RA-4G). Value-equivalent (<=10 unchanged); 0 meridian apps carry months_remaining/heloc/business → 16/16 by construction. 13/370.

**RA-PERSONA-A — credit + asset + fraud read evidence (commit fcc3012).** First batch of personas to consume the enricher's evidence facts and raise QUALITY signals — ADVISORY + OUTCOME-NEUTRAL (the RA-3D pattern: append signals + output_payload, never move proposed_outcome → 16/16 by construction). **Extended `context_enricher.evidence_facts()`** to expose per-fact credit + asset detail (`ev_credit_value/confidence/conflicts`, `ev_asset_value/confidence/conflicts`) — it previously exposed per-fact detail only for income/employment (+ fraud). credit_assessment → `CREDIT_EVIDENCE_CONFLICT`/`CREDIT_LOW_CONFIDENCE`; asset_verification → `ASSET_EVIDENCE_CONFLICT`/`ASSET_LOW_CONFIDENCE`; fraud_screening → `FRAUD_EVIDENCE_PRESENT`/`FRAUD_LOW_CONFIDENCE` (reads the RA-3E fraud_indicator fact). **Real API (vs the prompt's wrong `self.make_signal(severity=)`):** `OfflineReasoning(signals=[make_signal(name, value, direction=SignalDirection.X)])`. **Threshold:** only ONE catalogue confidence rule exists (`income_documentation_confidence_min`=0.75, Fannie B3-3.1-01, governed_by=agency), attached to every bundle by the enricher — reused as the generic documentation-confidence floor across all domains (no new seeds; flagged that per-domain thresholds could be seeded later). Verified full eval **16/16 (errors 0)**: signals fire precisely (SC08 credit conflict, SC15 asset conflict, SC09 fraud present), absent on clean apps. 13/370. Out-of-scope flag: asset_verification `LARGE_DEPOSIT_THRESHOLD`/`MIN_RESERVES_MONTHS` + fraud-score constants are pre-existing persona BOUNDARY thresholds (SC15 depends on them) — a separate de-hardcoding target, not touched.

**RA-PERSONA-B — dti + ltv + product read evidence (commit 9f9e42d).** Same advisory/outcome-neutral pattern. dti_calculation → `DTI_INCOME_CONFLICT`/`DTI_INCOME_LOW_CONFIDENCE` (DTI only as reliable as its income evidence); ltv_assessment → `LTV_EVIDENCE_CONFLICT`/`LTV_EVIDENCE_WEAK` (`ev_asset_confidence` as appraisal-quality proxy); product_eligibility → `PRODUCT_MISSING_PROPERTY_DOCS`/`PRODUCT_EVIDENCE_CONFLICT` (main path only — the deterministic VA-entitlement early-return left untouched, so SC14/VA has no evidence block). Same catalogue threshold reused. Caught pre-commit: ltv_assessment imports `first_object` not `latest_object` → used first_object (single-entry evidence object, equivalent). Verified **16/16** (decision_outputs — eval verify phase hit the known transient network drop AFTER all writes; 224/224 bundles); dti 16/16 + ltv 16/16 + product 15/16 (SC14 VA path) carry the new provenance; signals fire where warranted (SC08 → LTV/PRODUCT_EVIDENCE_CONFLICT, clean income → no DTI signal). 13/370. Remaining: **RA-PERSONA-C** (employment_reconciliation, title_assessment, compliance_check, approval_routing, closing_readiness, rate_pricing, underwriting_decision, lead_scoring).

**RA-PERSONA-C — 8 remaining personas read evidence (commit c2c718e).** Completes the persona-evidence wave — **all 14 personas now read the evidence graph**. Same advisory/outcome-neutral pattern. employment_reconciliation → `EMPLOYMENT_EVIDENCE_CONFLICT`/`_LOW_CONFIDENCE` (ev_employment_*); title_assessment → `TITLE_MISSING_EVIDENCE`/`_EVIDENCE_CONFLICT`; compliance_check → `COMPLIANCE_INCOME/CREDIT_UNCERTAIN`/`_EVIDENCE_CONFLICT`; approval_routing → `ROUTE_CONFLICT_PRESENT`/`_LOW_CONFIDENCE` (advisory ONLY — routing outcome NOT changed; the conflict→manual-review preference is a deliberate future outcome change, out of scope); closing_readiness → `CLOSING_EVIDENCE_INCOMPLETE`/`_CONFLICT`; rate_pricing → `PRICING_LOW_CONFIDENCE`; underwriting_decision → `UW_EVIDENCE_CONFLICTS`/`_LOW_EVIDENCE`; lead_scoring → `LEAD_LOW_EVIDENCE` (INFO/NEUTRAL, off the meridian path → graceful no-op). Same catalogue threshold reused (income_documentation_confidence_min). Caught pre-commit: underwriting_decision imported neither first_object nor latest_object → added first_object (the import lesson, checked all 8 up front). Verified clean full eval **Result: 16/16 (errors 0)**; all 7 meridian-path personas carry the new provenance 16/16; signals fire across ALL waves on SC08 (EMPLOYMENT/TITLE/COMPLIANCE/ROUTE/CLOSING/UW `_*CONFLICT`). 8 files py_compile+import checked. 13/370. **Full RA arc complete:** every threshold catalogue-driven (RA-4A–J), persona_bundles audit trail (RA-3F), all 14 personas reading the evidence graph (RA-PERSONA-A/B/C). Latent follow-ups flagged across the arc: asset_verification `LARGE_DEPOSIT_THRESHOLD`/`MIN_RESERVES_MONTHS` + fraud-score constants (persona boundary thresholds, separate de-hardcode); per-domain evidence-confidence thresholds (only the shared income-doc floor exists); approval_routing conflict→manual-review preference; SE business-ownership rules seeded-but-unwired.

---

## RA-6B — Re-Arch Core Complete — 2026-06-23

### What Was Built (RA-0 through RA-6B)

**ARCHITECTURE:** `docs/ARCHITECTURE.md` (RA-0-ARCH) — permanent reference; 10 architecture rules locked; zero hardcoded lending values in Python (one documented exception, gap c); three-layer rule model regulatory/agency/overlay.

**CATALOGUE (RA-1 + RA-SEED):** agency_guidelines 81 rows (Fannie 58 / FHA 13 / VA 8 / Freddie 2); regulatory_rules 23; overlay_rules 6 (Meridian 4 / Summit 2); verify gate 59/59 exit 0; `rule_loader.get_rule` returns `{applied, governed_by, layers}`.

**RESOLVERS (RA-4A→RA-4J):** all domain resolvers catalogue-driven; zero hardcoded lending thresholds (except gap c, SE business-ownership); all return findings IN MEMORY to the persona.

**BUNDLES (RA-3F):** persona_bundles 224 current rows (14 personas × 16 apps); entity_snapshot + evidence_snapshot populated 16/16 each (rules_snapshot 16/16 on the 4 rule-injecting personas); decision_outputs.bundle_id set for every CURRENT decision (0 NULL among latest versions); replay-safe (JSONB → _compute_offline).

**PERSONAS (RA-PERSONA-A/B/C):** all 14 personas read evidence quality from the bundle; advisory signals where evidence warrants; OUTCOME-NEUTRAL (append signals, never change proposed_outcome); threshold reused income_documentation_confidence_min=0.75 (Fannie B3-3.1-01).

**AUDIT (RA-6A):** Stage 1 audit — all 8 checks PASS; 8 known gaps documented (none blocking demo); 16/16 confirmed. CHECK detail: CHECK 7's 6 "fails" were non-context views (out of scope; all 14 vw_*_context have ev_* cols); CHECK 8's 1283 NULL-bundle_id are all SUPERSEDED versions (0 NULL among current).

### Known Gaps
See the **Known Gaps** section in docs/ARCHITECTURE.md (gaps a–h). Headlines: (c) SE business-ownership hardcoded/unwired in asset_resolver — the one remaining hardcoded lending value; (d) student-loan 1.0% vs current Fannie 0.5% floor — production review; (h) NULL bundle_id on superseded versions — self-heals, optional cleanup.

### Verification (RA-6B)
16/16 confirmed directly from decision_outputs (no logic changed since RA-PERSONA-C's clean `Result: 16/16 errors 0` eval; network too degraded for a no-op re-run). Tagged `rearch-core-complete`.

### Next Steps (post-demo, backlog)
RA-P0/EX (pipeline + extraction infra), RA-AUS-A/B/C (DU + LP), RA-5 (policy transparency), RA-7A/B/C (ATR/QM + adverse action + HMDA), Stage 2 audit (full production readiness).

---

## RA-AUS-B — AUS reconciliation engine — 2026-06-24

**RA-AUS-B — AUS reconciliation engine (commit 1d947ff).** SHIPPED. Layers a detailed classifier on top of RA-AUS-A's lightweight `detect_aus_conflict` boolean. `core/aus/reconciliation.py:AUSReconciliationEngine.reconcile(accord_outcome, aus_result)` — pure + DB-less — turns an Accord-vs-DU disagreement into one of **4 named conflict cases**, each carrying `risk` / `title` / `explanation` / `uw_action` / `hmda_implication` from the `CONFLICT_EXPLANATIONS` map (strings never inlined at call sites):
  - `ACCORD_BLOCK_DU_APPROVE` — HIGH risk (confidence LOW)
  - `ACCORD_RECOMMEND_DU_REFER` — HIGH risk (DU refer/ineligible)
  - `ACCORD_ESCALATE_DU_APPROVE` — MEDIUM risk
  - `ACCORD_RECOMMEND_DU_REFER_ELIGIBLE` — LOW risk
  Agreement cases → `reconciliation_required=False, agreement=True, confidence=HIGH`. No AUS response → `reconciliation_required=False` (not all lenders run DU). `_classify` treats `allow` (clean approve) like `recommend`.

**Wiring — approval_routing persona.** Reconciles against the raw UNDERWRITING outcome (`uw_outcome` from `bundle.upstream_outputs["underwriting_decision"]`, falling back to the routing outcome label), NOT this persona's routing outcome — a decline routes as ALLOW and would misclassify. Emits via the real `SignalDirection.CONTRADICTS` enum: **`AUS_CONFLICT_HIGH_RISK`** (HIGH, weight 2.0) / **`AUS_CONFLICT_REVIEW`** (MEDIUM/LOW), plus a positive **`AUS_ACCORD_AGREEMENT`** SUPPORTS signal when a DU result exists and agrees. `output_payload.aus_reconciliation` + `aus_confidence` logged on every decision. **Advisory only — `proposed_outcome` untouched.**

**Verification.** 9/9 reconciliation unit tests pass (`tests/test_aus_reconciliation.py`). Full-suite failures (9, in policy_engine / seed_scenarios / ui-views) are **pre-existing** — reproduced identically at clean HEAD with the AUS-B files stashed (e.g. seed_scenarios `15 != 13` is persona-count staleness, DB-state dependent); **zero new**. Demo (`block` + DU Approve/Eligible) → `ACCORD_BLOCK_DU_APPROVE` / HIGH / LOW. Meridian eval **16/16** (no DU data → `reconciliation_required=False` for all, no signal fires). Closes AU-B. Remaining: **RA-AUS-C** (LP / Loan Product Advisor).

---

## RA-AUS-C — LP (Loan Prospector) parser — AUS phase complete — 2026-06-24

**RA-AUS-C — LP parser (commit af95db1).** SHIPPED. Closes the AUS phase (RA-AUS-A/B/C): Accord now parses, stores, and reconciles BOTH agency AUS systems — Fannie DU + Freddie LP. `core/aus/lp_parser.py:LPParser` mirrors the DUParser shape so the shared engine + persona consume DU and LP identically. Recommendation map `Accept/Caution/Ineligible/Out of Scope` (+ `A+/A/B/C/D/E` grade shorthand) → `ACCEPT/CAUTION/INELIGIBLE/OUT_OF_SCOPE`; risk-class map `A+..E` → `exceptional..not_eligible`; feedbacks + conditions parsed (dict and string). **LP Caution = ELIGIBLE-but-not-accept** (the DU Refer/Eligible analogue) — never conflated with Refer/Ineligible.

**`approve` alias for engine compatibility.** The reconciliation engine reads `aus_result.get("approve")`/`eligible`, and the spec required BOTH "don't change the engine" AND `LP Accept + block → ACCORD_BLOCK_DU_APPROVE`. Resolved by exposing `approve` as an alias for the LP-native `accept` in the parsed dict — AUSReconciliationEngine UNCHANGED, LP handled identically to DU.

**Store + enricher.** `store.ingest_lp_response` upserts under `aus_system='LP'` (idempotent ON CONFLICT). The `aus_responses` table has **no `feedbacks` column** (only `findings`/`conditions`) → LP feedbacks stored in the shared `findings` JSONB, full LP dict preserved in `parsed_response`; no migration. Enricher `_attach_aus_result` now loads BOTH `aus_result` (DU) + `aus_result_lp` (LP) for approval_routing only.

**`_more_conservative` (DU + LP).** New helper in approval_routing reconciles against the MORE CONSERVATIVE of the two systems when both ran — ranked by permissiveness (approve=2 > eligible-not-approve=1 > ineligible=0), ties favour DU — so an **LP Caution is never masked by a DU Approve**. `output_payload` gains `aus_result_lp` + `aus_reconciled_system`. RA-AUS-A's DU-anchored `AUS_ACCORD_CONFLICT` signal kept unchanged. Advisory only — `proposed_outcome` untouched.

**Verification.** 39 AUS tests pass (24 new `tests/test_lp_parser.py` + 15 existing DU/reconciliation). Full suite **13 failed / 474 passed** — the 13 failures (4 api + 2 policy_engine + 5 seed_scenarios + 2 ui-views) reproduced identically at clean HEAD with the RA-AUS-C files stashed, all DB-state/environment dependent; **zero new**. Demo: DU Approve + LP Caution both parse; LP Caution vs Accord recommend → `ACCORD_RECOMMEND_DU_REFER_ELIGIBLE` / LOW. Meridian eval **16/16** (no LP data → `aus_result_lp=None`, no reconciliation fires). **AUS phase RA-AUS-A/B/C COMPLETE.**

---

## RA-P0-A — S3 document storage (MISMO) — FINAL re-arch prompt — 2026-06-24

**RA-P0-A — S3 folder structure aligned to MISMO (commit 6609f52).** SHIPPED. The FINAL re-arch prompt. `core/storage/` is the new canonical object-storage layer; **RE-ARCH TRACKER: ALL PROMPTS COMPLETE**.

**`core/storage/s3_keys.py`** — pure key builder (no I/O), the single source of truth for the MISMO-aligned, tenant-isolated hierarchy: `{tenant}/{app}/uploads/raw/{doc_type}/{filename}` + `uploads/processed/{doc_type}.json` + `mismo/raw/{version}.xml` + `mismo/parsed/canonical.json` + `aus/du/{casefile_id}.json` + `aus/lp/{key_number}.json` + `{tenant}/platform/onboarding/{filename}` + `exports/hmda/{year}/{month}/lar.csv` + `exports/dmn/{version}/rules.xml`. Discoverable (doc_type/system in the path, never UUIDs); a `_seg` helper slash-strips every segment so keys never carry a leading or double slash even from messy input.

**`core/storage/s3_client.py`** — async boto3 wrapper, server-side AES256 on every put. **Graceful no-credentials fallback** when AWS is unconfigured (local dev / CI / meridian): every op is a no-op (`put`→False, `get`→None, `exists`→False). **Deviation from spec (corrected):** `boto3.client('s3')` does NOT raise on missing creds (the failure only surfaces on the API call, as `NoCredentialsError`, which is a `BotoCoreError` NOT a `ClientError`) — the spec's `NoCredentialsError`-on-client + ClientError-only catch would have let it propagate. Fixed by detecting creds up front via `Session().get_credentials()` and broadening the per-op except. Same degrade-gracefully pattern as pdfplumber standing in for Textract.

**`api/accord/documents.py`** — the `/upload` endpoint, AFTER extraction succeeds, calls best-effort `_store_in_s3`: puts the raw file (`application/pdf`, AES256) + processed-fields JSON, then stamps `document_index.s3_key`. **Additive + non-blocking** — S3 is never a hard dependency. Wired in the endpoint, NOT inside `ingest_document`, so the extraction pipeline stays pure/unchanged. The `s3_key` UPDATE is **gated on a successful raw put** (S3 off → s3_key untouched, `s3_stored=False` in the response). `document_index.s3_key` already exists in live RDS (the documents viewer reads it); added idempotent `scripts/migrations/add_document_index_s3_key.sql` (`ADD COLUMN IF NOT EXISTS`) so a fresh DB matches prod.

**Verification.** 15 new tests (`tests/test_s3_storage.py`): every key-builder format, key hygiene (tenant isolation / no leading-or-double slash / stray-slash stripping), and the no-creds fallback paths. Full suite **13 failed / 489 passed** (489 = prior 474 + 15) — the 13 are the established pre-existing env/DB baseline (byte-identical set; none touch the upload/S3 path); **zero new**. Meridian eval **16/16** (S3 ops additive + no-op when unconfigured; seeded scenarios unaffected). **The full RA re-arch arc is COMPLETE.** Remaining future work is non-re-arch: RA-P0-B (parallel runner, perf only — gap g), RA-5 (policy transparency), Stage 2 audit (production readiness).

---

## Gap (c) CLOSED — SE biz-ownership from catalogue — 2026-06-24

**Gap (c) fix — wire SE business-ownership from catalogue (commit f35ae33).** The LAST hardcoded lending value is gone — **RULE 1 now has ZERO exceptions**. `asset_resolver.py` previously hardcoded `biz_pct >= 100 → 1.00`, `>= 50 → 0.50`, else `0.00`. Now all four values are catalogue-driven via the existing RA-4A property pattern (sync, DB-less — deliberately NOT RA-4G's async self-load, which would violate RULE 6 / "never make a resolver async"): 4 names added to `ASSET_RULE_KEYS` (so `load_asset_rules` injects them), 4 `@property` accessors (`_biz_sole_threshold`, `_biz_majority_threshold`, `_biz_full_factor`, `_biz_majority_factor`), literals replaced in `resolve()` (exclusion message threshold also de-hardcoded), 4 `SAFE_DEFAULTS` added (raw percents 100/50/100/50; factor properties `/100`).

**The catalogue did NOT match the prompt (or the old gap-c note).** The prompt claimed rows `Full=100/Majority=50/Partial=25`; querying the live RDS first (per "DO NOT guess") revealed the ACTUAL rows: `Self-Employed Full Business Asset Credit`=100 + `Self-Employed Partial Business Asset Credit`=50 (the usable-credit FACTORS, RA-SEED-C) and `Self-Employed Business Ownership Majority`=25 (an SE-definition threshold). The two **ownership cutoffs** the code gates on (100%/50%) had **no catalogue backing**. Surfaced the discrepancy and (user picked Option 1) **seeded 2 NEW rows** rather than repurposing the 25% row (which would have moved the gate 50→25 and changed behavior):
  - `Self-Employed Business Ownership Sole Threshold` = 100 (Fannie B3-3.4-02)
  - `Self-Employed Business Ownership Majority Threshold` = 50 (Fannie B3-3.4-02)
  via `scripts/compliance/seed_gap_c_ownership_thresholds.py` (idempotent; matches the RA-SEED-C `_gv` JSON shape). **agency_guidelines: 81 → 83 active rows** (Fannie 58 → 60; FHA 13 / VA 8 / Freddie 2 unchanged).

**Verification.** Value-equivalent: **0 mismatches** across 10 ownership levels (0/10/25/49/50/51/75/99/100/150) in BOTH modes (SAFE_DEFAULTS fallback + catalogue-injected). All 4 rows resolve `governed_by=agency, using_default=False`. Catalogue gate **59/59** exit 0. Full suite **13 failed / 489 passed** (same pre-existing env/DB baseline; zero new). Meridian eval **16/16** — SC15 `asset_verification=escalate` preserved (the scenario that depends on these thresholds). **AREA 3 (zero hardcodes) is now a clean PASS with zero exceptions.**

---

## INC-A + INC-B — income entity model + W2 base resolver (UW OS) — 2026-06-24

First two UW OS prompts. Doc update batched across both (per user) so the income picture lands once.

**INC-A — income entity model + DB tables (commit 3099364).** New RDS tables `income_sources` (one row per income stream per borrower: type/subtype, monthly_amount + `annual_amount GENERATED ALWAYS AS monthly*12 STORED`, frequency, dates, is_current, confidence, method, fact_node_ids[], doc_references[]) and `employment_history` (per-job; is_self_employed/ownership_pct; FK income_source_id), plus view `vw_employment_gaps` (gaps > 30 days, Fannie). `scripts/migrations/create_income_tables.sql` (additive, IF NOT EXISTS — applied to RDS). `core/income/income_aggregator.py`: `get_qualifying_income()` (sum current streams across roles, per-role/stream breakdown), `get_employment_gaps()`, `INCOME_TYPES`(10)/`BORROWER_ROLES`(3)/`DEFAULT_QUALIFYING_ROLES` constants (no magic strings); read-only. `golden_record_writer.apply_golden_record(write=True)` now additively writes the primary W2 stream into income_sources (best-effort, idempotent on re-ingest); `entity_states.qualifying_monthly` UNTOUCHED (14 personas still read it). No RLS (deferred). Wired in the writer, NOT the pure builder (builder has no conn and doesn't derive income — the documented DESIGN-vs-RUNTIME gap). meridian income_sources stays EMPTY (write path hard-refused — seeded fixtures).

**INC-B — W2 base salary resolver + employment-history check (commit 5e348d2).** Pre-work diagnostic confirmed: qualifying_monthly = seeded `entity_states` scalar (meridian); W2 `box1_wages` + paystub `gross_pay` live in `document_index.extracted_fields`; overtime/bonus/commission/hourly DO NOT EXIST anywhere; income_sources EMPTY for meridian. So INC-B scope = **W2 base + paystub gross only**. `core/income/w2_income_resolver.py:W2IncomeResolver` (SYNC + DB-LESS, SAFE_DEFAULTS fallback in __init__ like AssetResolver): `qualify_from_w2_doc` (box1/12, conf 0.97), `qualify_from_paystub` (gross×freq_multiplier/12, conf 0.90), `check_employment_history` (24-month requirement), `select_qualifying_income` (lesser-of W2 vs paystub). `VARIABLE_INCOME_TODO` documents the missing paystub extraction fields.

**Catalogue (RULE 8, not SAFE_DEFAULTS-only).** The 24-month employment-history requirement had NO catalogue row (only `se_income_years_required`=2 existed), so per RULE 8 it was SEEDED: `employment_history_months_required`=24 (Fannie B3-3.1-01, snake_case to match the resolver key + `se_income_years_required` sibling) via `scripts/compliance/seed_inc_b_employment_history.py`, plus added to `rule_loader.SAFE_DEFAULTS`. **agency_guidelines: 83 → 84** (Fannie 60 → 61). No hardcoded 24 in the resolver — reads `self._rules`.

**Persona wiring (ADVISORY, additive).** income_verification gains `output_payload.income_analysis` (resolver method/citation + employment-history check + variable-income TODO + PATH-1/PATH-2 data-path notes + enricher TODO). `proposed_outcome`, `verified_income`, and the seeded `qualifying_monthly` are UNCHANGED. The enricher does NOT attach W2/PAYSTUB extracted_fields to the income bundle today, so the doc-level resolver functions run on the real-tenant PATH 2 only (flagged ENRICHER TODO); they are unit-tested standalone.

**Two data paths (both work):** PATH 1 meridian/seeded → `entity_states.qualifying_monthly` (unchanged); PATH 2 real tenants → `income_sources` via the INC-A pipeline → `get_qualifying_income()`.

**Verification.** 14 new W2 resolver tests (`tests/test_w2_income_resolver.py`; thresholds proven to come from the rules dict). Full suite **13 failed / 503 passed** (489 + 14; the 13 are the established pre-existing env/DB baseline, zero new). Meridian eval **16/16** (income_analysis additive; persona still uses seeded qualifying_monthly). Closes INC-A + INC-B. Next: variable income needs a paystub-extraction prompt first.

---

## INC-E + INC-F — retirement/SS/depletion/investment + alimony/child-support (UW OS) — 2026-06-24

INCOME phase complete (INC-A → INC-F). Doc update batched across INC-E + INC-F (per user). Both are FOUNDATION passes (catalogue + pure resolver + unit tests; advisory only) — same pattern as INC-B, because diagnostics confirmed no live data for these income types in meridian.

**INC-E — retirement / SS / asset-depletion / investment (commit a236577).** `core/income/retirement_income_resolver.py:RetirementIncomeResolver` (separate module, sync + DB-less, reads rule_loader.SAFE_DEFAULTS fallback): `qualify_ss` (1.25× gross-up if non-taxable + 3yr continuance), `qualify_pension` (3yr continuance), `qualify_asset_depletion` (eligible-with-haircuts / 360-month divisor), `qualify_dividends_interest` (2yr avg if 24mo history). **8 catalogue rows seeded** (Fannie B3-3.1-09): ss_non_taxable_gross_up_factor=1.25, ss/retirement_continuance_months_required=36, asset_depletion_divisor_months=360, asset_depletion_{retirement,cash,equity}_haircut_pct=70/100/70, dividend_interest_history_months_required=24 (seed_inc_e_retirement_rules.py + rule_loader.SAFE_DEFAULTS). **Asset depletion runs on REAL data**: new enricher `_attach_income_entity` surfaces `entity_states.total_liquid_assets` to the income bundle (e.g. SC01 24500 → ~$68/mo); SS/pension/investment foundation-only (no source docs). agency_guidelines 84→92.

**INC-F — alimony / child support (commit 97abda6).** `core/income/alimony_resolver.py:AlimonyChildSupportResolver` (separate module, sync + DB-less): `qualify_alimony_received` / `qualify_child_support_received` (3yr continuance gate), `treat_alimony_paid` (monthly_debt | reduce_income per catalogue) / `treat_child_support_paid` (always monthly_debt). **3 catalogue rows seeded** (B3-3.1-09 / B3-6-05): alimony_continuance_months_required=36, child_support_continuance_months_required=36, alimony_paid_dti_treatment=monthly_debt (seed_inc_f_alimony_rules.py + rule_loader.SAFE_DEFAULTS). Input = the DIVORCE_DECREE Vision extractor fields (RA-EX-D); meridian has no decree docs → all 4 methods return not_applicable (correct foundation). agency_guidelines 92→95 (Fannie 72). NOTE: the prompt's 4th 'alimony_received_min_continuance_note' was prose, not a code-read rule, so NOT seeded (3 functional rules, not 4). DTI breakout of alimony/child-support PAID deferred to OB-A/B; dti_calculation unchanged.

**Wiring (both):** all income resolvers share ONE `income_rules` bundle key — `w2_income_resolver.INCOME_RULE_KEYS` now aggregates employment(1) + retirement(8) + alimony(3) = 12 keys; the runner's existing income_verification branch loads them all (no runner change). income_verification gains `output_payload.retirement_income_analysis` (INC-E) + `alimony_child_support_analysis` (INC-F), both ADVISORY — proposed_outcome / verified_income / qualifying_monthly UNCHANGED.

**Deviations (surfaced, consistent across both):** seed via proper scripts not the prompts' inline python -c (agency_guidelines has no `governed_by` column; guideline_value is JSONB); resolvers use rule_loader.SAFE_DEFAULTS not local dup dicts (RULE 9 / passes the INC-B-style architecture audit).

**Verification.** INC-E 16 tests + INC-F 15 tests (thresholds proven to flow from the rules dict). Full suite after INC-F: **13 failed / 534 passed** (the 13 are the established pre-existing env/DB baseline; zero new). Meridian eval **16/16** for both (additive analyses; persona still uses seeded qualifying_monthly). All catalogue rules resolve governed_by=agency, using_default=False. **INCOME phase (INC-A→F) COMPLETE.** Remaining income follow-ups are extraction/wiring prompts: variable income (overtime/bonus/commission), and document→income_sources population for SS/pension/dividend/decree.

---

## OB-A + OB-B — student-loan rate fix + obligation resolver (UW OS) — 2026-06-24

Doc update batched across OB-A + OB-B (per user). OB-A had two parts; OB-B extended the resolver.

**OB-A Part 1 — gap (d) closed (commit 1c7b2b4).** student_loan_deferred_rate_pct updated 1.0 → 0.5 (current Fannie B3-6-05: 0.5% floor for $0/unreported deferred payments) via `scripts/compliance/update_gap_d_student_loan_rate.py` (jsonb_set, shape preserved — a bare '0.5' string would break get_rule). Read by tradeline_analyzer._student_loan_rate (value/100); 0 meridian student-loan tradelines → 16/16 held. **Gap (d) CLOSED.**

**OB-A Part 2 — ObligationResolver (commit 09154af).** New `core/obligations/` subsystem. `ObligationResolver` (sync + DB-less, rule_loader.SAFE_DEFAULTS fallback): decomposes monthly obligations by type — student_loan (PRE-COMPUTED by TradelineAnalyzer, not recomputed), alimony/child-support paid (delegates to INC-F resolver), installment (actual or balance/months, excluded ≤10mo), revolving (min or 5% of balance), heloc (actual or 1% of balance/limit). `resolve(list)` → total + per_type + excluded. 2 catalogue rows seeded (revolving_payment_factor_pct=5, heloc_payment_factor_pct=1; Fannie B3-6-02). Wired into dti_calculation via runner `obligation_rules` bundle key → advisory `output_payload.obligation_breakdown`. **DTI math UNCHANGED.** agency_guidelines 95→97.

**OB-B — business debt exclusion + rental offset (commit 2068645).** Extended ObligationResolver: `compute_business_debt` (EXCLUDE only if business-paid ≥ business_debt_exclusion_months=12 AND no 30-day delinquency, B3-6-05; else INCLUDE + docs_needed — is_business_paying/months_business_paid default False/0 so debt is included until the UW supplies 12mo cancelled-check/bank evidence); `compute_rental_offset` (net = rental_net_monthly − pitia_monthly, B3-3.1-08; ≥0 positive offset not a DTI obligation, <0 shortfall added; both inputs default 0 → not_applicable since RA-4G isn't bundle-wired + per-property PITIA absent). Routes business_debt + rental_property. 1 catalogue row seeded (business_debt_exclusion_months=12, B3-6-05). HELOC was already complete in OB-A (no change). agency_guidelines 97→98 (Fannie 75). Reused RA-4G net rental + INC-F alimony; no logic rebuilt; graceful missing-input handling per spec.

**Wiring (both):** runner._inject_decision_rules dti_calculation → obligation_rules (+ bundle rules_snapshot). dti_calculation gains output_payload.obligation_breakdown — ADVISORY; dti/dti_front/dti_back/total_obligations UNCHANGED (folding the breakdown into the ratio is a later OB slice). Meridian dti bundle carries only the aggregate existing_debt_obligations, so the breakdown is foundation there; live per-obligation inputs flow on PATH 2.

**Deviations (surfaced, consistent with prior phases):** Part 1 via jsonb_set script not bare-string UPDATE; resolver uses rule_loader.SAFE_DEFAULTS not a local dup (RULE 9 / audit pattern); citations via proper seed scripts (no governed_by column; JSONB values).

**Verification.** 25 obligation tests (17 OB-A + 8 OB-B; thresholds proven from the rules dict). Full suite after OB-B: **13 failed / 559 passed** (the 13 are the established pre-existing env/DB baseline; zero new). Meridian eval **16/16** on all three commits (1c7b2b4, 09154af, 2068645). All new rules resolve governed_by=agency. **Gap (d) CLOSED; core/obligations/ subsystem live.** Remaining: fold the breakdown into the DTI ratio (later OB slice); evidence extraction (is_business_paying, cancelled checks, per-property PITIA) + RA-4G rental→bundle wiring (PATH 2).
