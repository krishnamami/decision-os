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

12 decisions covering the full mortgage cycle.
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
                                         pytest-asyncio.
✅  README.md
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
                                          ui/ view-models.
⬜  core/trace/outcome_tracker.py        STEP 12. Post-decision outcome scoring +
                                          live A/B comparisons.
⬜  core/simulation/replayer.py          STEP 13. Replay traces at point-in-time
                                          for backtesting personas.
⬜  core/semantic_layer/flow.py          Event → entity → metric → signal mapper.
                                          Currently the EntityHydrator in
                                          api/ingest.py covers the event → entity
                                          mapping; flow.py would add the
                                          entity → metric → signal layer.
⬜  .env.example
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

STEPS 1-11 are complete (sessions 3, 4, 5, 6):
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
             Mounted in api/main.py via the create_app(mount_ui=True)
             flag. Bootstrap lifespan auto-replays the 4 seed
             scenarios on boot when seed_demo_data=True. 5 GET routes
             (/, /ui/applications/{id},
             /ui/applications/{id}/decisions/{decision}, /ui/queue,
             /health) + POST /ui/.../override with HTMX swap.
             Deliberately picked HTMX over Next.js for ~2-session-to-v0
             instead of ~5; user wants to validate value locally
             before any cloud / polished-demo work.
  ✅ ALSO    core/policy_engine/loader.py (DecisionsSpec).
             docs/PRD.md §17/§19/§20 reconciled (v0.6).

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

Real-backend verification (STEPS 4-6 only) was scheduled for
Sun May 3 2026 9am PT, routine trig_013QhFbYJaViJfNybCbr3KUX.
If the PR has landed on branch session-4-real-backend-verification,
start by reviewing it; otherwise check
https://claude.ai/code/routines/trig_013QhFbYJaViJfNybCbr3KUX
for status. Note: STEPS 7-11 are NOT in scope of that scheduled run
— they need a separate verification when ready.

Build next, in this order:
  STEP 14 tests/                Persistent pytest suite. Today only
                                tests/core/context_store/test_in_memory.py
                                exists. Cover:
                                - core/policy_engine/loader.py against
                                  the real decisions.yaml.
                                - core/trace/reflection.py capture +
                                  recall + retention.
                                - Each persona's _compute_offline()
                                  against canonical input fixtures.
                                - The 4 seed_events scenarios as
                                  canonical end-to-end regressions.
                                - api/ via fastapi.testclient on every
                                  route, including the override flow.
                                - ui/views.py view-models as pure
                                  functions of Platform state.
                                Three bugs found in sessions 5 + 6
                                (income hydrator double-write,
                                _default_resolver shape, view-model
                                async/sync mismatch) would have been
                                single failing tests instead of full
                                DAG / full UI runs to debug.

  AFTER UI HANDS-ON      Real Anthropic calls. Personas have the path
                         (use_anthropic=True, cache_control on the
                         system block) but it's unproven. Boot the UI
                         with one persona on the LLM path, see the
                         work journal side-by-side with the offline
                         baseline. Surfaces:
                           - prompt-cache hit rate
                           - JSON-parse robustness on the journal
                           - latency per persona

  STEP 12 core/trace/outcome_tracker.py
                                Post-decision outcome scoring + live
                                A/B comparisons. Needs a per-decision
                                ground-truth feed.

  STEP 13 core/simulation/replayer.py
                                Replay traces at point-in-time for
                                backtesting personas. Hook into
                                InMemoryDurableStore.get_at_time
                                (already supports it).

OPEN ARCHITECTURAL QUESTIONS:
  - human_approval mode currently doesn't writeback (per PRD §13
    "human's resolution drives the eventual writeback"). Downstream
    decisions see missing upstream output for queued decisions and
    recommend rather than approve. Decide: do tests need a
    "simulate human approvals" mode, or do all tests use an explicit
    POST /override step to mark the queued decisions resolved?
  - HumanQueue has no "resolved/dismissed" state. After override, the
    item stays in list_open(). UX-wise this is wrong; functionally
    it's fine for v0. Add a resolve() method on the HumanQueue
    Protocol when you wire the dequeue flow.
  - ui/views.py reads the in-memory store synchronously. Needs an
    async pass for the Postgres swap; flagged in Session 6 notes.
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

*Decision OS · CONTEXT.md · Updated May 2 2026 (Session 6 — local UI live)*
