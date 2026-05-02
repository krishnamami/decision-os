# DECISION OS — PRODUCT REQUIREMENTS DOCUMENT
# Version: 0.4 | Updated: May 2026 | Source of truth for Claude Code every session

---

## HOW TO USE THIS FILE

This file is the single source of truth for Claude Code.
At the start of every session, read this file + CONTEXT.md + decisions.yaml.
Do not ask what the project is. Do not ask what was built last. Read these files and know.

---

## 1. WHAT WE ARE BUILDING — ONE PARAGRAPH

Decision OS is a platform for structured, governed, AI-augmented decisioning.
Any business brings their domain, maps their decisions (independent and dependent),
connects their data sources, and the platform builds context, evaluates policy,
runs AI agents, enforces governance, and produces a complete explainable trace
for every decision made. Every decision has an owner, a boundary, a mode, and a trace.
No decision is a black box. No action happens without a policy. No context is untracked.

---

## 2. THE CORE INSIGHT

```
Decisions are not random.
They have STRUCTURE    — independent or dependent on other decisions
They have OWNERS       — a team accountable for every outcome
They have DATA         — own data + shared data + upstream outputs
They have DEPENDENCIES — some decisions gate others
They have RISK         — low / medium / high drives the decision mode
They have A TRACE      — every decision is a work journal, not a log
```

---

## 3. THE 6 BUILDING BLOCKS (applies to every domain)

```
┌─────┬──────────────────────────────┬──────────────────────────────────────────────────┐
│ 01  │ DATA LAYER                   │ Own data per decision. Shared data across domain. │
│     │                              │ External sources via connectors. Full lineage.    │
├─────┼──────────────────────────────┼──────────────────────────────────────────────────┤
│ 02  │ KNOWLEDGE BASE + SEMANTICS   │ Controlled vocabulary. Synonyms → canonical.     │
│     │                              │ Business definitions. Thresholds per term.        │
├─────┼──────────────────────────────┼──────────────────────────────────────────────────┤
│ 03  │ ONTOLOGY                     │ Object types + properties + semantic links.       │
│     │                              │ WHO vs WHAT-NOW. Permissioned reads per decision. │
├─────┼──────────────────────────────┼──────────────────────────────────────────────────┤
│ 04  │ CONTEXT ENGINE               │ Builds only the context each decision needs.      │
│     │                              │ context_window_days. Upstream outputs injected.   │
├─────┼──────────────────────────────┼──────────────────────────────────────────────────┤
│ 05  │ BOUNDARY + POLICY            │ automate_if / recommend_if / escalate_if /        │
│     │                              │ block_if — declarative, in config not code.       │
├─────┼──────────────────────────────┼──────────────────────────────────────────────────┤
│ 06  │ AGENTS + GOVERNANCE          │ AI reasons. Code enforces. Atomic tool pattern.   │
│     │                              │ Independent critic. Reflection loop. Full trace.  │
└─────┴──────────────────────────────┴──────────────────────────────────────────────────┘
```

---

## 4. ARCHITECTURE — FULL PIPELINE (text)

```
SOURCE SYSTEMS
  Apps | APIs | CRM | ERP | Streams | Files | Webhooks | Voice
           │
           ▼
  ┌─────────────────────────────┐
  │   FLOW LISTENER / ADAPTERS  │  One adapter per source type
  │   core/connectors/          │  Emits RawEvent objects only
  └──────────────┬──────────────┘
                 │
                 ▼
  ┌─────────────────────────────┐
  │   EVENT NORMALIZER          │  RawEvent → typed NormalizedEvent
  │   core/normalizer/          │  Pydantic v2. Strict validation.
  │   models.py                 │  Reject malformed → dead letter store
  └──────────────┬──────────────┘
                 │
                 ▼
  ┌─────────────────────────────┐
  │   SEMANTIC LANGUAGE LAYER   │  Synonym → canonical resolution
  │   core/semantic_layer/      │  "dti" → debt_to_income_ratio
  │   resolver.py               │  Loads knowledge_base.json
  └──────────────┬──────────────┘
                 │
                 ▼
  ┌─────────────────────────────┐
  │   SEMANTIC FLOW LAYER       │  Event → entity → metric → signal
  │   core/semantic_layer/      │  Maps raw events to business meaning
  │   flow.py                   │  Before context is built
  └──────────────┬──────────────┘
                 │
                 ▼
  ┌─────────────────────────────┐
  │   MINI CONTEXT STORES       │  Redis: hot cache, TTL per decision
  │   core/context_store/       │  Postgres: durable history + lineage
  │   base.py / lending.py      │  One store per entity type
  └──────────────┬──────────────┘
                 │
                 ▼
  ┌─────────────────────────────┐
  │   CONTEXT AGENT             │  Assembles context bundle for decision
  │   core/context_store/       │  Respects context_window_days
  │   context_builder.py        │  Injects upstream decision outputs
  └──────────────┬──────────────┘
                 │
          ┌──────┴──────────────────────────────┐
          │         ATOMIC TOOL (per decision)  │
          │  ┌──────────────────────────────┐   │
          │  │ 1. POLICY CHECK              │   │
          │  │    core/policy_engine/       │   │
          │  │    → allow/recommend/        │   │
          │  │      escalate/block          │   │
          │  ├──────────────────────────────┤   │
          │  │ 2. DECISION AGENT            │   │
          │  │    core/decision_agents/     │   │
          │  │    Produces WorkJournalEntry │   │
          │  ├──────────────────────────────┤   │
          │  │ 3. CRITIC AGENT (med+high)   │   │
          │  │    core/trace/               │   │
          │  │    SelfReviewError enforced  │   │
          │  └──────────────────────────────┘   │
          └──────┬──────────────────────────────┘
                 │
                 ▼
  ┌─────────────────────────────┐
  │   OWNERSHIP + MODE LAYER    │  shadow/recommend/human_approval/auto
  └──────────────┬──────────────┘
                 │
         ┌───────┴───────────────┐
         ▼                       ▼
  ┌────────────────┐    ┌────────────────────┐
  │  AUTO EXECUTE  │    │   HUMAN QUEUE      │
  │  Write-back    │    │   Persona workbench │
  └───────┬────────┘    └─────────┬──────────┘
          └──────────┬────────────┘
                     ▼
  ┌─────────────────────────────┐
  │   DECISION TRACE            │  Append-only. Never deleted.
  │   core/trace/trace_schema.py│  WorkJournalEntry + critic result
  └──────────────┬──────────────┘
                 │
                 ▼
  ┌─────────────────────────────┐
  │   OUTCOME LEARNING          │  Human override → AgentLearning
  │   core/trace/reflection.py  │  Fed back to same agent next time
  └──────────────┬──────────────┘
                 │
                 ▼
  ┌─────────────────────────────┐
  │   SIMULATION LAYER          │  Replay. Test. Compare. A/B.
  └─────────────────────────────┘

  CROSS-CUTTING:
  ┌────────────────────────────────────────────────────────────────────┐
  │  Governance | Security | Observability | Cost-per-decision | Perf  │
  └────────────────────────────────────────────────────────────────────┘
```

---

## 5. HARD RULES — ENFORCED IN CODE, NOT PROMPTS

```
┌──────────────────────────────────────────────┬───────────────────────────────────────────┐
│ RULE                                         │ ENFORCEMENT                               │
├──────────────────────────────────────────────┼───────────────────────────────────────────┤
│ no_decision_without_owner                    │ Validate owner_team at decision load time │
│ no_action_without_policy                     │ Default outcome = ESCALATE if no match    │
│ no_context_without_lineage                   │ Every ContextRecord carries Lineage obj   │
│ no_agent_without_permissions                 │ Agents read only decisions_that_read_it   │
│ no_execution_without_trace                   │ trace_required=true gated before writeback│
│ fraud_block_stops_pipeline                   │ fraud=BLOCK halts ALL downstream          │
│ compliance_block_stops_closing               │ compliance=BLOCK halts closing_readiness  │
│ upstream_block_propagates_to_dependents      │ contamination_guard in every dep decision │
└──────────────────────────────────────────────┴───────────────────────────────────────────┘
```

---

## 6. DECISION MODES

```
  shadow         → agent runs, outcome recorded, NOTHING executes
  recommend      → agent surfaces recommendation, human acts
  human_approval → agent decides, human must sign before writeback
  auto_execute   → agent decides and writes back immediately
```

---

## 7. ATOMIC TOOL PATTERN

```
  LLM: reasons within boundaries, produces WorkJournalEntry
       does NOT: validate data, enforce rules, write to DB

  CODE (one bundled tool call — cannot call steps separately):
    context_build  → assembles typed context bundle
    policy_check   → evaluates boundary clauses + all 8 hard rules
    trace_write    → persists WorkJournalEntry + DecisionTrace
    mode_route     → executes or queues based on mode
```

---

## 8. FOUR ARCHITECTURAL PRINCIPLES

```
  1. AI REASONS. CODE GOVERNS.
     Every hard rule backed by code, not a prompt instruction.

  2. CONTEXT IS FOCUSED, NOT FLOODED.
     context_window_days limits history. Agents get only what they need.

  3. EVERY OVERRIDE IS A LESSON.
     Human override → AgentLearning → fed back same agent next time.

  4. EVERY DECISION IS A WORK JOURNAL.
     WorkJournalEntry: hypothesis | signals | contradictions |
                       conclusion | confidence_basis | summary
     Independent critic reviews medium+ risk before execution.
```

---

## 9. ONTOLOGY — OBJECT TYPES AND RELATIONSHIPS

### 9.1 The key distinction

```
  APPLICANT = WHO
    Persists across time and across multiple Applications.
    CreditProfile, IncomeProfile, FraudProfile belong to Applicant.

  APPLICATION = WHAT THEY ARE ASKING FOR RIGHT NOW
    Lifecycle-bound. DTI, LTV, underwriting belong to Application.
    Re-application = same Applicant, brand new Application object.
```

### 9.2 Object types

```
┌──────────────────┬────────────┬──────────────────────────────────────────────────────┐
│ Object           │ Category   │ Semantic definition                                  │
├──────────────────┼────────────┼──────────────────────────────────────────────────────┤
│ Applicant        │ Business   │ WHO. Persists. Root of domain.                       │
│ Application      │ Business   │ WHAT-NOW. Lifecycle-bound.                           │
│ Property         │ Business   │ Collateral. Bound to one Application.                │
│ Loan             │ Business   │ Financing terms requested.                           │
│ CreditProfile    │ Business   │ Belongs to Applicant. One per bureau pull.           │
│ IncomeProfile    │ Business   │ Belongs to Applicant. verified_income authoritative. │
│ FraudProfile     │ Business   │ Belongs to Applicant. Shared across Applications.    │
│ ComplianceRecord │ Business   │ Belongs to Application. Regulatory artefact.         │
│ Decision         │ System     │ Runtime output per decision type per Application.    │
│ DecisionTrace    │ System     │ Work journal. Append-only. Never deleted.            │
│ AgentLearning    │ System     │ Lesson from human override. Replayed to same agent.  │
└──────────────────┴────────────┴──────────────────────────────────────────────────────┘
```

### 9.3 Semantic link map (text)

```
  Applicant  ──submits──────────────►  Application       (1 → many)
  Applicant  ──has──────────────────►  CreditProfile     (1 → many, one per pull)
  Applicant  ──has──────────────────►  IncomeProfile     (1 → many)
  Applicant  ──has──────────────────►  FraudProfile      (1 → many)
  Applicant  ──co_applies_with──────►  Applicant         (self-referential)
  Application ──secured_by──────────►  Property          (1 → 1)
  Application ──requests────────────►  Loan              (1 → 1)
  Application ──evaluated_by────────►  Decision          (1 → 12, one per type)
  Application ──governed_by─────────►  ComplianceRecord  (1 → 1)
  Decision    ──depends_on──────────►  Decision          (dependency graph)
  Decision    ──produces────────────►  DecisionTrace     (1 → 1)
  DecisionTrace ──triggers──────────►  AgentLearning     (on human override)
  AgentLearning ──feeds_back_to─────►  Decision          (same agent, next similar)
```

### 9.4 Object lifecycle — Mermaid diagram

```mermaid
flowchart TD
    LEADEVT[LeadReceivedEvent] --> APPLICANT[Applicant<br/>WHO · persists across applications]
    SUBEVT[ApplicationSubmittedEvent] --> APPLICATION[Application<br/>WHAT-NOW · per-request lifecycle]

    APPLICANT -- submits --> APPLICATION
    APPLICANT -. co_applies_with .-> APPLICANT

    PAYROLL[PayrollReceivedEvent] --> INCOME[IncomeProfile<br/>belongs to Applicant]
    BUREAU[CreditPulledEvent] --> CREDIT[CreditProfile<br/>belongs to Applicant]
    FRAUDSIG[FraudSignalEvent] --> FRAUDP[FraudProfile<br/>belongs to Applicant]

    APPLICANT --> INCOME
    APPLICANT --> CREDIT
    APPLICANT --> FRAUDP

    APPRAISAL[PropertyAppraisedEvent] --> PROPERTY[Property<br/>belongs to Application]
    APPLICATION --> PROPERTY
    APPLICATION --> LOAN[Loan<br/>belongs to Application]
    APPLICATION --> COMP[ComplianceRecord<br/>belongs to Application]

    INCOME -.feeds.-> D_IV[income_verification]
    CREDIT -.feeds.-> D_CA[credit_assessment]
    FRAUDP -.feeds.-> D_FS[fraud_screening]
    COMP -.feeds.-> D_CC[compliance_check]
    PROPERTY -.feeds.-> D_LTV[ltv_assessment]
    LOAN -.feeds.-> D_RP[rate_pricing]
    APPLICATION -.feeds.-> D_UW[underwriting_decision]

    D_IV --> TRACE[DecisionTrace]
    D_CA --> TRACE
    D_FS --> TRACE
    D_CC --> TRACE
    D_LTV --> TRACE
    D_RP --> TRACE
    D_UW --> TRACE

    TRACE -. on human_override .-> AL[AgentLearning<br/>fed back to same agent]
```

---

## 10. ENTITY STORAGE MODEL

```
┌──────────────────┬───────────────┬──────────────────────────────────────────────────┐
│ Entity           │ Storage       │ Notes                                            │
├──────────────────┼───────────────┼──────────────────────────────────────────────────┤
│ RawEvent         │ Postgres      │ Immutable. Source of truth for replay.           │
│ NormalizedEvent  │ Postgres      │ Immutable. Indexed entity_id + event_type.       │
│ ContextBundle    │ Redis + PG    │ Redis: TTL per decision. PG: snapshot at decision.│
│ PolicyResult     │ Postgres      │ Every evaluation stored. Compliance artefact.    │
│ DecisionOutput   │ Postgres      │ Decisions table. WorkJournalEntry as JSONB.      │
│ DecisionTrace    │ Postgres      │ Append-only. Never deleted. Audit chain.         │
│ HumanQueueItem   │ Redis + PG    │ Redis: active queue. PG: full history.           │
│ AgentLearning    │ Postgres      │ 365-day retention. Similarity tags for retrieval.│
│ Applicant        │ Postgres      │ applicants table. Master record.                 │
│ Application      │ Redis + PG    │ Redis: active pipeline state. TTL 30 days.       │
│ CreditProfile    │ Redis + PG    │ Redis: latest score. TTL 90 days.               │
│ IncomeProfile    │ Redis + PG    │ Redis: verified_income + confidence. App TTL.    │
│ FraudProfile     │ Redis + PG    │ Redis: fraud_cleared flag. TTL 7 days.          │
│ Property         │ Postgres      │ No Redis — data changes infrequently.            │
│ ComplianceRecord │ Postgres      │ Regulatory artefact. Never deleted.              │
│ DecisionConfig   │ YAML file     │ decisions.yaml — source of truth for all rules.  │
└──────────────────┴───────────────┴──────────────────────────────────────────────────┘
```

---

## 11. LENDING DOMAIN — 12 DECISIONS

### 11.1 End-to-end pipeline — lead to closing — Mermaid diagram

```mermaid
flowchart TD
    LEAD[Lead arrives] --> LS[lead_scoring<br/>auto · low risk]
    LS -->|allow| APP[Application created<br/>Applicant + Application objects]
    LS -.block: source on watchlist.-> STOPLEAD[Pipeline halts]

    APP --> SUBMIT[Application submitted]

    SUBMIT --> IV[income_verification<br/>human_approval · medium]
    SUBMIT --> CA[credit_assessment<br/>auto · medium]
    SUBMIT --> FS[fraud_screening<br/>auto · high]
    SUBMIT --> CC[compliance_check<br/>human_approval · high]

    IV --> DTI[dti_calculation<br/>auto · low]
    CA --> LTV[ltv_assessment<br/>auto · low]

    DTI --> PE[product_eligibility<br/>recommend · medium]
    LTV --> PE

    CA --> RP[rate_pricing<br/>auto · medium]
    DTI --> RP
    LTV --> RP

    IV --> UW[underwriting_decision<br/>human_approval · high]
    CA --> UW
    FS --> UW
    DTI --> UW
    LTV --> UW
    PE --> UW

    UW --> AR[approval_routing<br/>auto · low]
    UW --> CR[closing_readiness<br/>human_approval · high]
    CC --> CR

    CR --> FUND[Loan funded]

    FS -.fraud=block.-> STOPFS[fraud_block_stops_pipeline<br/>all downstream halts]
    CC -.compliance=block.-> STOPCC[compliance_block_stops_closing]
    UW -.any upstream block.-> STOPUW[contamination_guard:<br/>fail_if_any_upstream_blocked]
```

### 11.2 Decision table

```
┌────┬──────────────────────────┬──────────────────────────────────────┬────────┬────────┬─────────────────┐
│ #  │ Decision                 │ Depends on                           │ Mode   │ Risk   │ Owner           │
├────┼──────────────────────────┼──────────────────────────────────────┼────────┼────────┼─────────────────┤
│ 01 │ lead_scoring             │ —                                    │ auto   │ low    │ Growth Ops      │
│ 02 │ income_verification      │ —                                    │ human  │ medium │ Underwriting    │
│ 03 │ credit_assessment        │ —                                    │ auto   │ medium │ Credit Risk     │
│ 04 │ fraud_screening          │ —                                    │ auto   │ HIGH   │ Fraud Ops       │
│ 05 │ compliance_check         │ —                                    │ human  │ HIGH   │ Compliance      │
│ 06 │ dti_calculation          │ income_verification                  │ auto   │ low    │ Underwriting    │
│ 07 │ ltv_assessment           │ credit_assessment                    │ auto   │ low    │ Underwriting    │
│ 08 │ product_eligibility      │ dti_calculation + ltv_assessment     │ rec    │ medium │ Product Ops     │
│ 09 │ rate_pricing             │ credit + dti + ltv                   │ auto   │ medium │ Secondary Mkts  │
│ 10 │ underwriting_decision    │ ALL above                            │ human  │ HIGH   │ Underwriting    │
│ 11 │ approval_routing         │ underwriting_decision                │ auto   │ low    │ Loan Ops        │
│ 12 │ closing_readiness        │ underwriting + compliance            │ human  │ HIGH   │ Closing Ops     │
└────┴──────────────────────────┴──────────────────────────────────────┴────────┴────────┴─────────────────┘
```

### 11.3 Hard stops

```
  fraud_screening     = BLOCK  →  STOPS ALL downstream. No exceptions.
  compliance_check    = BLOCK  →  STOPS closing_readiness. No exceptions.
  any upstream        = BLOCK  →  contamination_guard blocks all dependents.
```

---

## 12. PER-DECISION PATTERN — ATOMIC TOOL — Mermaid diagram

```mermaid
flowchart LR
    EVT[Inbound event<br/>from connector] --> ATOMIC
    UPSTREAM[Upstream decision<br/>outputs] --> ATOMIC
    REFL[Reflection memory<br/>past overrides for this agent] --> ATOMIC

    subgraph ATOMIC[atomic_tool — single tool call per decision]
      direction TB
      CB[context_build<br/>load own_data + shared_data<br/>respect context_window_days<br/>filter via decisions_that_read_it<br/>stamp lineage on every record]
      PC[policy_check<br/>evaluate boundary clauses<br/>BLOCK > ESCALATE > RECOMMEND > ALLOW<br/>check contamination_guard<br/>check 8 hard_rules]
      RA[agent reasoning<br/>WorkJournalEntry:<br/>hypothesis · signals · contradictions ·<br/>conclusion · confidence basis · summary]
      CR{risk >= medium?}
      CRT[critic_agent reviews trace<br/>verdict: approved / flagged / escalated]
      CB --> PC --> RA --> CR
      CR -->|yes| CRT
      CR -->|no| OUT
      CRT --> OUT[outcome:<br/>allow / recommend / escalate / block]
    end

    ATOMIC --> TRACE[DecisionTrace persisted]
    ATOMIC --> CTX[ContextRecord written<br/>append-only · superseded_by chain]
```

---

## 13. OUTCOME ROUTING — Mermaid diagram

```mermaid
stateDiagram-v2
    [*] --> evaluating
    evaluating --> allow_outcome: boundary clear
    evaluating --> recommend_outcome: recommend_if matched
    evaluating --> escalate_outcome: ambiguity / contamination
    evaluating --> block_outcome: hard fail / upstream block
    evaluating --> send_back_planned: missing evidence (planned)

    allow_outcome --> mode_check
    mode_check --> auto_writeback: mode = auto_execute
    mode_check --> queue_human: mode = human_approval
    mode_check --> shadow_record: mode = shadow

    recommend_outcome --> queue_human
    escalate_outcome --> queue_human

    queue_human --> human_review
    human_review --> human_approves: approve
    human_review --> human_overrides: override
    human_review --> human_sends_back: request evidence (planned)

    human_approves --> writeback
    auto_writeback --> writeback

    human_overrides --> reflection_capture
    reflection_capture --> agent_learning_store: extract reason +<br/>reviewer role + original AI decision
    agent_learning_store --> writeback: human's choice executes
    agent_learning_store --> next_similar_event: replayed to same agent

    writeback --> publish_record_updated
    publish_record_updated --> wake_dependents: DAG executor + event bus
    wake_dependents --> [*]

    block_outcome --> trace_only: no writeback
    trace_only --> notify_downstream: upstream_block_propagates
    notify_downstream --> [*]

    shadow_record --> [*]: recorded only, no action

    send_back_planned --> upstream_persona_planned: route to upstream
    human_sends_back --> upstream_persona_planned
    upstream_persona_planned --> evaluating: re-runs with new evidence
```

---

## 14. CONNECTOR → DECISION DATA FLOW — Mermaid diagram

```mermaid
flowchart LR
    subgraph EXT[External sources]
        WEB[Web form / borrower portal]
        PLAID[Plaid · Argyle · Pinwheel]
        BUREAU[Experian · TransUnion · Equifax]
        FRAUD[Socure · Alloy · LexisNexis]
        TITLE[First American · CoreLogic]
        AVM[CoreLogic AVM · HouseCanary]
        AMC[AMC appraisal · MISMO XML]
        RATE[Optimal Blue · ICE]
        TWN[The Work Number]
        ESIGN[E-sign provider]
    end

    subgraph CONN[core/connectors/ — adapters]
        WEB --> CO_FORM[FormSubmit adapter]
        PLAID --> CO_INC[Income adapter]
        TWN --> CO_EMP[Employment adapter]
        BUREAU --> CO_CR[Credit adapter]
        FRAUD --> CO_FR[Fraud adapter]
        TITLE --> CO_TI[Title adapter]
        AVM --> CO_AVM[AVM adapter]
        AMC --> CO_AP[Appraisal adapter]
        RATE --> CO_RT[Rate sheet adapter]
        ESIGN --> CO_ES[E-sign adapter]
    end

    CONN --> NORM[normalize_event<br/>typed BaseEvent subclass]
    NORM --> ONT[Ontology hydration<br/>Applicant · Application · Property ·<br/>Loan · CreditProfile · IncomeProfile ·<br/>FraudProfile · ComplianceRecord]

    ONT --> DEC[12 lending decisions]
    DEC --> CTX[ContextRecord<br/>append-only · versioned · lineage stamped]

    CTX --> BUS[Event bus<br/>publish record_updated]
    BUS -->|wake dependents| DEC

    CTX --> BLOB[Blob storage<br/>S3-compatible<br/>raw documents · PDFs · IDs]

    DEC -. write-back .-> OUTBOUND[Outbound connectors<br/>Encompass · Blend · CRM ·<br/>borrower portal · HMDA reporting]
```

---

## 15. DECISION TRACE — WORK JOURNAL SCHEMA

```
DecisionTrace {
  trace_id:               uuid
  event_id:               uuid          FK → normalized_events
  entity_id:              string
  decision_type:          string
  context_snapshot:       jsonb         complete immutable snapshot at decision time
  policies_evaluated:     jsonb[]       [{policy_id, name, result, reason}]
  work_journal: {
    hypothesis_tested:    string        what the agent believed before signals
    signals_evaluated:    jsonb[]       [{signal, value, weight, relevance}]
    contradictions_found: jsonb[]       [{signal, contradiction, resolution}]
    conclusion:           string        reasoned conclusion from evidence
    confidence_basis:     string        why confident / what would change it
    human_readable_summary: string      plain language, non-technical reader
  }
  critic_result:          jsonb         {verdict, reasoning, flagged_issues}
  agent_id:               string
  decision_mode:          enum          shadow|recommend|human_approval|auto_execute
  outcome:                enum          allow|recommend|escalate|block
  confidence:             float         0.0–1.0
  owner_team:             string
  human_resolution:       jsonb|null    {decision, reason, reviewer_role, time_seconds}
  decided_at:             timestamp
  latency_ms:             int
}
```

---

## 16. REFLECTION LOOP — HOW THE SYSTEM LEARNS

```
  Human overrides AI decision
           │
           ▼
  Extract: original_ai_decision | human_decision | override_reason
           override_reason_code | reviewer_role | context_fingerprint
           │
           ▼
  Structure as AgentLearning:
    agent_id, decision_type, trigger=human_override
    lesson (string), similarity_tags (jsonb), retention_until (365 days)
           │
           ▼
  Next similar event → AgentLearning injected into context bundle
  Agent reasons with lesson → accuracy improves without retraining
```

---

## 17. FILE STRUCTURE — CURRENT STATE

```
decision-os/
├── core/
│   ├── normalizer/
│   │   ├── __init__.py
│   │   └── models.py              ✅ DONE — all lending event types
│   ├── semantic_layer/
│   │   ├── resolver.py            ✅ DONE — synonym resolver
│   │   └── flow.py                ⬜ TODO
│   ├── ontology/
│   │   └── object_types.py        ✅ DONE — 8 object types + semantic links
│   ├── context_store/
│   │   ├── base.py                ⬜ TODO
│   │   ├── redis_cache.py         ⬜ TODO
│   │   ├── postgres_store.py      ⬜ TODO
│   │   ├── lending.py             ⬜ TODO
│   │   ├── schema.sql             ⬜ TODO
│   │   └── context_builder.py     ⬜ TODO
│   ├── policy_engine/
│   │   ├── loader.py              ✅ DONE
│   │   └── evaluator.py           ✅ DONE
│   ├── decision_agents/
│   │   ├── base.py                ⬜ TODO
│   │   ├── atomic_tool.py         ⬜ TODO
│   │   └── mode_router.py         ⬜ TODO
│   ├── trace/
│   │   ├── trace_schema.py        ✅ DONE
│   │   ├── critic_agent.py        ✅ DONE
│   │   ├── trace_writer.py        ⬜ TODO
│   │   ├── reflection.py          ⬜ TODO
│   │   └── outcome_tracker.py     ⬜ TODO
│   ├── simulation/
│   │   ├── replayer.py            ⬜ TODO
│   │   └── comparator.py          ⬜ TODO
│   ├── execution/
│   │   └── dag_executor.py        ⬜ TODO
│   └── connectors/
│       └── base.py                ⬜ TODO
│
├── domains/lending/
│   ├── decisions.yaml             ✅ DONE
│   ├── knowledge_base.json        ✅ DONE
│   ├── personas/                  ⬜ TODO
│   ├── policies/                  ⬜ TODO
│   └── seed_events/               ⬜ TODO
│
├── api/                           ⬜ TODO
├── ui/                            ⬜ TODO
├── infra/docker-compose.yml       ✅ DONE
├── tests/                         ⬜ TODO
├── docs/
│   ├── PRD.md                     ✅ DONE
│   └── CLAUDE_CODE_CONTEXT.md     ← THIS FILE
├── CONTEXT.md                     ✅ DONE
├── README.md                      ✅ DONE
├── requirements.txt               ✅ DONE
└── .env.example                   ✅ DONE
```

---

## 18. TECH STACK

```
  Backend:   Python 3.11 + FastAPI
  Models:    Pydantic v2
  Database:  Postgres via Supabase
  Cache:     Redis
  Blob:      S3-compatible
  Frontend:  Next.js + Tailwind
  AI:        Anthropic Claude via API
  Deploy:    Docker Compose → Railway / Render
```

---

## 19. BUILD SEQUENCE — NEXT STEPS IN ORDER

```
  1  core/context_store/          Redis + Postgres. TTL per decision. Lineage on all records.
  2  core/connectors/base.py      Base connector + mock CSV + one live adapter.
  3  core/decision_agents/        Base class + atomic_tool + 12 persona implementations.
  4  core/execution/dag_executor  Walks execution_order. Event bus. Wakes dependents.
  5  api/                         POST /events | GET /decisions/:id | GET /trace/:id
                                  POST /override | POST /connectors/webhook/:source
  6  core/trace/reflection.py     Override → AgentLearning → replay into next decision.
  7  ui/                          Event stream | context view | trace viewer | human queue
```

---

## 20. HOW TO START EACH SESSION

Paste this prompt at the start of every Claude Code session:

```
Read these files in this order before doing anything:
1. docs/CLAUDE_CODE_CONTEXT.md
2. CONTEXT.md
3. domains/lending/decisions.yaml
4. domains/lending/knowledge_base.json

Then run:
  find . -name "*.py" -o -name "*.json" -o -name "*.sql" | grep -v .git | grep -v __pycache__

Do not ask what the project is. Do not ask what was built.
Read the files and know.
The next thing to build is: core/context_store/
```

---

## 21. CODING STANDARDS

```
  - Pydantic v2 for ALL models. Type hints everywhere. No untyped functions.
  - Async for all I/O (FastAPI, Redis, Postgres).
  - structlog for logging. No print() in production code.
  - Every module has __init__.py.
  - Tests written alongside each module in tests/.
  - Append-only tables for events, traces, learnings. No deletes.
  - JSONB for flexible payloads. Typed columns for indexed fields.
  - Every ContextRecord has a lineage field. Non-negotiable.
  - decision_type must match decision id in decisions.yaml exactly.
  - Commit format: feat: / fix: / docs: / chore: / test:
  - Push before ending every session.
```

---

## 22. OPEN QUESTIONS

```
  1. First design partner — org type, domain, workflow?
  2. Pricing — per-decision / per-application / platform fee?
  3. Tenancy — single-tenant v1 or multi-tenant v1?
  4. Connectors — which must be live at launch vs mock?
  5. AI model — hosted API / bring-your-own / self-hosted?
  6. Override authority — single approver or dual-control for high-risk?
  7. Connector marketplace — build all or open SDK?
```

---

*Decision OS · CLAUDE_CODE_CONTEXT.md · v0.4 · Read at the start of every session*
