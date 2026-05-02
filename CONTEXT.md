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
                                         duplicate trace_id.
✅  docs/PRD.md                          full product spec v0.5 (file-structure block in
                                         §17 still shows STEPS 4-6 as ⬜ — out of sync until
                                         next PRD pass; CONTEXT.md is authoritative).
✅  docker-compose.yml                   Postgres 16 + Redis 7 services with healthchecks.
✅  requirements.txt                     pydantic v2, redis, asyncpg, PyYAML, fastapi,
                                         uvicorn, anthropic, structlog, httpx, pytest,
                                         pytest-asyncio.
✅  README.md
```

Also: BaseEvent in core/normalizer/models.py gained two optional fields
this session — `correlation_id` and `request_id` — so pull-pattern
connectors can pair an outbound request with the inbound response on
the canonical event.

Files not yet built (next up):

```
⬜  api/                                  STEP 7. POST /events | GET /decisions/:id |
                                          GET /trace/:id | POST /override |
                                          POST /connectors/webhook/:source
⬜  core/policy_engine/loader.py         Loads + validates decisions.yaml at startup
                                          (currently parsed ad hoc by ContextBuilder
                                          and PolicyEvaluator).
⬜  core/semantic_layer/flow.py          Event → entity → metric → signal mapper.
⬜  core/trace/reflection.py             Override → AgentLearning → replay into next
                                          decision. Persistent TraceWriter swap-in for the
                                          in-memory variant.
⬜  core/trace/outcome_tracker.py
⬜  core/simulation/replayer.py
⬜  domains/lending/personas/             12 concrete DecisionAgent subclasses (currently
                                          only mocked in smoke tests).
⬜  domains/lending/seed_events/          JSON/CSV fixtures replayed through MockCSVConnector
                                          + MockHTTPConnector for end-to-end testing.
⬜  ui/                                   Event stream | context view | trace viewer | queue
⬜  tests/                                Only context_store has test scaffolding so far.
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
2. Build STEP 7: `api/` — FastAPI surface. Routes:
   `POST /events` (ingest, hands to connector + normalizer),
   `GET /decisions/:id`, `GET /trace/:id`, `POST /override`,
   `POST /connectors/webhook/:source` (push connectors).
3. Build `core/trace/reflection.py` — human override → `AgentLearning`
   → replay into next similar decision (per decisions.yaml `reflection`
   block).
4. Build `core/policy_engine/loader.py` — single load+validate path
   for decisions.yaml so ContextBuilder and PolicyEvaluator stop
   parsing it ad hoc.
5. Build `domains/lending/personas/` — 12 concrete DecisionAgent
   subclasses (currently only mocked in smoke tests).
6. Build `domains/lending/seed_events/` — fixtures for end-to-end
   replay through MockCSVConnector + MockHTTPConnector.
7. PRD §17 file-structure block is out of sync — schedule a pass to
   reconcile it with what's now in the repo.

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

STEPS 1-6 are complete:
  ✅ STEP 1 normalizer/models.py
  ✅ STEP 2 ontology/object_types.py
  ✅ STEP 3 context_store/{base,lending,redis_cache,postgres_store,
            context_builder}.py + schema.sql
  ✅ STEP 4 connectors/{base,mock_csv,mock_http}.py + correlation_id /
            request_id on BaseEvent
  ✅ STEP 5 decision_agents/{base,atomic_tool,mode_router}.py +
            trace/trace_writer.py
  ✅ STEP 6 execution/dag_executor.py with InMemoryEventBus and
            fraud_block_stops_pipeline short-circuit

Real-backend verification is scheduled for Sun May 3 2026 9am PT
(routine trig_013QhFbYJaViJfNybCbr3KUX). It will open a PR on branch
session-4-real-backend-verification with the result. If that PR has
already landed, start by reviewing it; otherwise check
https://claude.ai/code/routines/trig_013QhFbYJaViJfNybCbr3KUX for
status.

Build next, in this order:
  STEP 7: api/                  FastAPI surface.
          Routes:
            POST /events                       — ingest, push through
                                                 normalize_event() +
                                                 connector EventSink
            GET  /decisions/:id                — read DecisionRecord
            GET  /trace/:id                    — read DecisionTrace
            POST /override                     — human override; feeds
                                                 trace/reflection.py
            POST /connectors/webhook/:source   — push-connector entry
  STEP 8: core/trace/reflection.py
          Human override → AgentLearning record (per decisions.yaml
          reflection block) → replayed to same agent on next similar
          event. 365-day retention.
  STEP 9: domains/lending/personas/
          12 concrete DecisionAgent subclasses (currently only mocked
          in smoke tests). One file per persona; subclass calls into
          Anthropic SDK with the bundle + policy and returns
          AgentReasoning.
  STEP 10: domains/lending/seed_events/
          JSON / CSV fixtures replayed through MockCSVConnector +
          MockHTTPConnector for end-to-end tests.

PARALLEL (small jobs):
  - core/policy_engine/loader.py — single load+validate path so
    ContextBuilder and PolicyEvaluator stop parsing decisions.yaml ad
    hoc.
  - PRD §17 file-structure block is out of date — bring it in sync
    with the repo (CONTEXT.md is currently authoritative).
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

*Decision OS · CONTEXT.md · Updated May 2026*
