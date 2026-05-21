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
- **Governed actions** — a boundary engine that decides whether to automate, recommend, escalate, or block.
- **Lineage everywhere** — every context value is traceable to its source.
- **Human-in-the-loop by design** — overrides are captured as evidence and fed back as agent memory.
- **Operational, not analytical** — the output is a workflow action, not a dashboard.

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
| **Governance & Observability** | Lineage and audit trace on every value, DataOps quality monitoring across pipelines, and a registry of policies and hard rules. |

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

Decision OS is an actively evolving reference architecture. The ontology model and decision
specifications are defined; the connector framework, DAG executor, decision agents, and
persona workbench are being built out incrementally. See [`docs/PRD.md`](docs/PRD.md) for
the full product requirements and [`domains/`](domains/) for vertical-specific decision packs.

---

## Repository Layout

```
decision-os/
├── core/
│   ├── ontology/           # object types, semantic links
│   ├── policy_engine/      # boundary evaluation, hard rules
│   ├── decision_agents/    # agents, critics, reflection
│   └── connectors/         # typed source connectors
├── domains/
│   └── lending/            # lending decision pack (decisions.yaml)
├── docs/
│   ├── PRD.md              # product requirements
│   └── architecture.md     # editable Mermaid diagram
└── README.md
```