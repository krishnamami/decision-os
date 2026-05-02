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
✅  docs/PRD.md                          full product spec v0.5
✅  docker-compose.yml
✅  requirements.txt
✅  README.md
```

Files Claude Code generated in sessions but NOT yet pushed to repo:

```
⚠️  core/normalizer/models.py            generated in session 1, not in repo
⚠️  core/ontology/object_types.py        generated in session 1, not in repo
⚠️  .env.example                         generated in session 1, not in repo
```

Files not yet built:

```
⬜  core/normalizer/models.py            BUILD FIRST — everything depends on this
⬜  core/ontology/object_types.py        BUILD SECOND
⬜  core/context_store/                  BUILD THIRD
    base.py, redis_cache.py, postgres_store.py
    lending.py, schema.sql, context_builder.py
⬜  core/policy_engine/loader.py
⬜  core/semantic_layer/flow.py
⬜  core/decision_agents/
    base.py, atomic_tool.py, mode_router.py
⬜  core/execution/dag_executor.py
⬜  core/connectors/base.py
⬜  core/trace/trace_writer.py
⬜  core/trace/reflection.py
⬜  core/trace/outcome_tracker.py
⬜  core/simulation/replayer.py
⬜  domains/lending/personas/
⬜  domains/lending/seed_events/
⬜  api/
⬜  ui/
⬜  tests/
⬜  CONTEXT.md                           this file — push it
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

**What needs to happen next session:**
1. Push this CONTEXT.md to repo
2. Push PRD.md v0.5 to repo (replace docs/PRD.md)
3. Open Claude Code and use session start prompt from PRD section 20
4. Build core/normalizer/models.py first

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
2. domains/lending/decisions.yaml
3. domains/lending/knowledge_base.json

Then verify what actually exists:
  find . -name "*.py" -o -name "*.yaml" -o -name "*.json" | grep -v .git | grep -v __pycache__ | sort

Do not ask what the project is. Do not ask what was built.
Read the files and know.

Build in this exact order:
  STEP 1: core/normalizer/models.py
  STEP 2: core/ontology/object_types.py
  STEP 3: core/context_store/ (base.py, redis_cache.py, postgres_store.py, lending.py, schema.sql, context_builder.py)
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
