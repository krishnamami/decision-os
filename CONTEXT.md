# Decision OS — Project Context

## What this is
A governed, explainable, human-in-the-loop decision platform.
Inspired by Palantir but modular, no-code configurable, mid-market pricing.

**For the full product spec — vision, goals, non-goals, target users,
architecture principles, open questions — see [docs/PRD.md](docs/PRD.md).
Read it before making architecture decisions.**

## Background
Builder has 2 years experience implementing Palantir for a lending company
across 12 decision personas covering the full mortgage cycle.
Some stages still manual. Pain points: cost, rigidity, no explainability,
can't configure without engineers.

## Product vision
- Customer brings their domain (lending, insurance, HR)
- They map N decisions — independent and dependent
- For each decision: data layer, knowledge base, semantics, ontology,
  context, boundaries, agents, trace, simulation, no-code UI
- Every decision is traceable, governed, human-in-the-loop capable
- Target: mid-market enterprises who can't afford Palantir

## Current domain: Lending (mortgage)
12 decisions — see domains/lending/decisions.yaml

## Tech stack
- Backend: Python 3.11 + FastAPI
- Models: Pydantic v2
- DB: Supabase / Postgres
- Cache: Redis
- Frontend: Next.js + Tailwind
- Deployment: Docker Compose

## Build status
- [x] domains/lending/decisions.yaml — 12 decisions fully specced (atomic_tool, context_window_days, reflection)
- [x] core/normalizer/models.py — Pydantic event models + normalize_event()
- [x] domains/lending/knowledge_base.json — vocabulary + ontology
- [x] knowledge_base.json ontology section updated with full link map
- [x] core/semantic_layer/resolver.py — synonym resolver
- [x] core/policy_engine/evaluator.py — boundary evaluator + hard-rule enforcement
- [x] core/trace/trace_schema.py — DecisionTrace with WorkJournalEntry
- [x] core/trace/critic_agent.py — independent critic, blocks self-review
- [x] core/ontology/object_types.py — 8 object types with semantic links
- [x] README.md, requirements.txt, docker-compose.yml, .env.example
- [ ] core/context_store/ — next to build tomorrow
- [ ] core/decision_agents/
- [ ] api/
- [ ] ui/

## Ontology decisions
- Applicant is WHO — persists across time and applications
- Application is WHAT THEY ARE ASKING FOR NOW — new lifecycle each time
- CreditProfile, IncomeProfile, FraudProfile belong to Applicant, not Application
- DTI, LTV, product eligibility, underwriting belong to Application (and to its Loan)
- ComplianceRecord and Property belong to Application (regulatory and asset snapshots are application-specific)
- Re-application: Applicant object reused, new Application created, decisions start fresh, profiles carried forward (within retention)

## How to continue in a new chat
Share https://github.com/krishnamami/decision-os and say:
"Continue building Decision OS — read CONTEXT.md and the repo first"

Update CONTEXT.md to add:

## Session 1 — April 30 2026
### Key architectural decisions made:
- Atomic tool pattern: context_build + policy_check + decision bundled into one tool call per agent
- Reflection layer: every human override extracted as agent learning, fed back to same agent
- Trace schema: WorkJournalEntry not log dump — hypothesis, signals, contradictions, conclusion
- Critic agent: independent review of medium-risk decisions, SelfReviewError blocks self-review
- context_window_days: added per decision to limit history loaded per agent

### Article alignment (4 principles for production-grade agents):
- Principle 1: atomic tool pattern — deterministic work in code, LLM reasons within boundaries
- Principle 2: context_window_days — focus agent attention, load only relevant history
- Principle 3: reflection.py — agents learn from human overrides
- Principle 4: WorkJournalEntry trace — visible reasoning, separate critic

### Build status:
- Done: decisions.yaml, normalizer, trace schema, critic agent
- Next: core/context_store/ then policy_engine then decision_agents

### Resume command:
claude --resume cde7c041-c35b-4c0b-94d9-51d50a7edddd

## Session 2 — May 1 2026

### Documentation landed
- docs/PRD.md (v0.1 draft, 18 sections + Appendix A) — full product spec
- §11 Visual flow with 5 Mermaid diagrams: end-to-end pipeline, atomic
  tool internals, outcome routing state machine, object lifecycle,
  connector data flow
- CONTEXT.md links PRD from top header
- Memory pointer saved so PRD loads in every future session

### Architectural confirmations
- Connector framework is the keystone for Foundry-without-Foundry —
  Postgres + S3 + Redis (no HDFS at mid-market scale)
- Coverage audit: spec ~95% in YAML, runtime ~25% built
- "Request more evidence" outcome missing — needed if humans should
  bounce work back to upstream personas (PRD §17 open question)
- 5 of 8 hard_rules still unenforced in code

### No new code today
- Foundation files unchanged from Session 1 build status above
- Pivoted from build to grounding (PRD + visuals)

### Resume options — pick one tomorrow
1. **Finish context_store** (original next-up) — redis_cache.py,
   postgres_store.py, schema.sql
2. **Start connectors** — core/connectors/base.py + 1 reference adapter;
   forces context_store interface to be defined by real demand
3. **Resolve PRD open questions first** — target customer, pricing,
   competitive wedge, before more architecture

### Open questions (highest impact, see PRD §17)
- Target customer profile + volume tier
- Pricing model
- Multi-tenancy timeline (v1 or v2?)
- AI model strategy (BYO LLM? self-host for regulated buyers?)
- "Request more evidence" outcome design

### Resume command
claude --resume <new-session-id>