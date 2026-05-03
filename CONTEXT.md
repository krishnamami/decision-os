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

*Decision OS · CONTEXT.md · Updated May 2 2026 (Session 8 — workbench/persona UI live, PATH C locked)*
