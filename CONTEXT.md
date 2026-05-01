# Decision OS — Project Context

## What this is
A governed, explainable, human-in-the-loop decision platform.
Inspired by Palantir but modular, no-code configurable, mid-market pricing.

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
- [x] domains/lending/decisions.yaml — 12 decisions fully specced
- [x] core/normalizer/models.py — Pydantic event models
- [x] domains/lending/knowledge_base.json — vocabulary + ontology
- [x] core/semantic_layer/resolver.py — synonym resolver
- [x] README.md, requirements.txt, docker-compose.yml, .env.example
- [ ] core/context_store/ — next to build
- [ ] core/policy_engine/
- [ ] core/decision_agents/
- [ ] core/trace/
- [ ] api/
- [ ] ui/

## How to continue in a new chat
Share https://github.com/krishnamami/decision-os and say:
"Continue building Decision OS — read CONTEXT.md and the repo first"
