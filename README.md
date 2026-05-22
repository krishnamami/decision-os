# Decision OS

**A governed, explainable, human-in-the-loop decision platform.**
A domain-agnostic decision engine with pluggable domain packs for each vertical.

Decision OS treats a decision as a first-class, auditable object: every decision has an
owner, every action is checked against policy, every piece of context carries lineage, and
every execution leaves a trace. It is inspired by the design principles of enterprise
ontology and operational-decisioning platforms, reimagined as an open, modular stack.

---

## Why Decision OS

Most "AI decisioning" stops at a model score. Decision OS is built around the parts that
actually make a decision safe to operate in production:

- **Ontology, not tables** — typed business objects with semantic links, so decisions reason over a shared model of the domain.
- **Governed actions** — a boundary engine that decides whether to automate, recommend, escalate, or block; the policy engine has the last word, never the LLM.
- **Lineage everywhere** — every context value and verified claim is frozen to its source on the trace.
- **Human-in-the-loop by design** — overrides are captured as evidence and fed back as agent memory.
- **Fair-lending aware** — protected-attribute leak detection and regulation tagging (FCRA, HMDA, ECOA) gate every decision before writeback.
- **Operational, not analytical** — the output is a workflow action, not a dashboard.

> **AI reasons. Code governs.** The LLM is consulted only inside the agent's `reason()`
> step; context assembly, policy evaluation, critic review, audit, and trace-writing are
> all code-enforced.

---

## Architecture

![Decision OS architecture](docs/architecture.svg)

> Data flows top-to-bottom through the pipeline; governance and lineage cross-cut every
> layer; human overrides are captured in the workbench and fed back to the decision agents
> as memory.

*An editable, text-based (Mermaid) version of this diagram lives in [`docs/architecture.md`](docs/architecture.md).*

### Layer responsibilities

| Layer | Responsibility |
|-------|----------------|
| **Connector & Ingestion** | Pull from CDC, XML, and API sources; normalize into typed events; hydrate context datasets that hold each entity's latest state via snapshotting. |
| **Ontology** | Typed business objects (the domain model) and system objects (decisions, traces) connected by semantic links. |
| **Decision Engine** | A boundary engine that applies policy to choose automate / recommend / escalate / block; a DAG executor that fires dependent workflows as data changes; decision agents with independent critics and a reflection loop. |
| **Persona Workbench** | Per-persona queues where humans review decisions, inspect supporting data as evidence, and override; snapshots surface bottlenecks. |
| **Governance & Observability** | Lineage and audit trace on every value, fair-lending checks, DataOps quality monitoring, and a registry of policies and hard rules. |

---

## The atomic decision

Every decision runs through one bundled, code-governed call (`AtomicTool.run()`):

1. **context_build** — assemble the typed `ContextBundle` for the application.
2. **policy pre-check** — hard rules + boundary clauses, before the agent reasons.
3. **agent reason** — the agent (LLM) produces a structured reasoning journal.
4. **policy re-check** — re-evaluate the boundary against the agent's *computed* values; the policy engine, not the agent, sets the final outcome.
5. **critic review** — an independent critic reviews medium+ risk decisions.
6. **trace_write** — persist the full `DecisionTrace` (append-only).
7. **audit gate** — build and persist an `AuditRecord` (consent, protected-attribute leak check, regulation tags) *before* any writeback.
8. **mode_route** — write back / queue / shadow per the decision's mode and outcome.

---

## Example: a real decision trace

Architecture explains *how the platform is organized*. This shows *how it operates* —
illustrated by the underwriting flow, then proven by a real trace pulled from the database.

![Underwriting workflow](docs/underwriter_flow.png)

### What a decision leaves behind

Every execution writes an append-only `DecisionTrace`. Below is **real output** from the
engine — a `compliance_check` decision on a synthetic loan application
([file](docs/decision_trace.json)):

```jsonc
{
  "id": "ae375173-3910-45a4-a9da-4e61b052d4e6",
  "application_id": "APP-LOAN-20260328-08700",
  "decision_id": "compliance_check",
  "outcome": "allow",
  "mode": "human_approval",
  "risk_level": "high",
  "confidence": 0.9,
  "boundary_matched": "allow",
  "boundary_rule": "hmda_complete=True, fair_lending_violation=False, missing_disclosures=False -> allow",
  "reasoning": {
    "hypothesis": "Application is compliant when all HMDA fields are present, no fair-lending flags exist, and state rules pass.",
    "signals": [
      { "name": "all_hmda_fields_complete", "value": true },
      { "name": "fair_lending_violation", "value": false },
      { "name": "missing_required_disclosures", "value": false },
      { "name": "cd_timing_compliant", "value": false }
    ],
    "conclusion": "hmda_complete=True, fair_lending_violation=False, missing_disclosures=False -> allow"
  },
  "context_snapshot": { "compliance_cleared": true, "no_fair_lending_flags": true, "mixed_jurisdiction": false },
  "sla_seconds": 60,
  "actual_seconds": 0.167,
  "version": 3,
  "tenant_id": "default",
  "decided_at": "2026-05-19T00:06:10Z"
}
```

Read it top to bottom and you can see the whole governance model: the **boundary rule**
that fired, the agent's **reasoning journal** (hypothesis → signals → conclusion), the
**fair-lending and HMDA signals** that were checked, the **SLA** (60s budget vs 0.167s
actual), append-only **versioning**, and **multi-tenancy** — all on one persisted,
replayable record. The `mode: human_approval` means this decision is queued for an
underwriter; when they act, a `human_action` / `human_reviewer` is attached to the same
trace without mutating its original reasoning.

This is the core thesis: Decision OS does not just *score* an application — it
**evaluates policy, records every signal and its outcome, and leaves an auditable,
replayable trace** with a human in the loop.

---

## Tech Stack

| Area | Technology |
|------|-----------|
| **Backend** | Python 3.11, FastAPI |
| **Data models** | Pydantic v2 |
| **Database** | Supabase (Postgres) |
| **Cache** | Redis |
| **Frontend** | Next.js, Tailwind CSS |

---

## Hard Rules

These constraints are enforced by the engine, not left to convention:

- **No decision without an owner.**
- **No action without a policy.**
- **No context without lineage.**
- **No agent without permissions.**
- **No execution without a trace.**

---

## Project Status

Decision OS is an actively evolving platform. The ontology model, policy engine, atomic
decision tool, critic, audit gate, and append-only trace store are implemented and
emitting real traces; the connector framework, DAG executor, and persona workbench UI are
being built out incrementally. See [`docs/PRD.md`](docs/PRD.md) for the full product
requirements and [`domains/`](domains/) for vertical-specific decision packs.

---

## Repository Layout

```
decision-os/
├── core/
│   ├── ontology/           # object types, semantic links
│   ├── context_store/      # ContextBuilder, ContextBundle, EntityResolver
│   ├── policy_engine/      # boundary evaluation, hard rules, policy versions
│   ├── decision_agents/    # atomic_tool, agents, critics, mode router
│   ├── trace/              # DecisionTrace, TraceWriter, claim provenance
│   ├── audit/              # AuditEngine, fair-lending / regulation checks
│   └── connectors/         # typed source connectors
├── domains/
│   └── lending/            # lending decision pack (decisions.yaml)
├── docs/
│   ├── PRD.md                  # product requirements
│   ├── architecture.md         # editable Mermaid diagram
│   ├── architecture.svg        # architecture diagram
│   ├── underwriter_flow.png    # underwriting workflow diagram
│   └── decision_trace.json     # real example decision trace
└── README.md
```