"""Audit Engine — PRD §23.

Every decision that passes through the pipeline is evaluated by the
AuditEngine before any external writeback. The engine runs four
checks in parallel (compliance, security, ethics, fairness) and
produces an AuditRecord written append-only to the AuditStore.

Public surface:
  AuditEngine          — orchestrator, fans out to four checkers
  AuditRecord          — full audit artefact, one per decision
  CheckStatus          — pass | warn | fail
  CheckResult          — per-checker structured return
  AuditStore           — Protocol; persistence contract
  InMemoryAuditStore   — reference implementation

The Postgres-backed store + schema.sql + reports/ submodules land in
the next slice. atomic_tool wiring (gate writeback on AuditRecord)
follows once the store is durable.
"""
from __future__ import annotations

from .compliance_checker import ComplianceChecker
from .engine import AuditEngine
from .ethics_checker import EthicsChecker
from .fairness_checker import FairnessChecker
from .schema import (
    AccessRecord,
    AuditRecord,
    CheckResult,
    CheckStatus,
    ConsentStatus,
    DataClassification,
    EncryptionStatus,
    FairnessFlag,
    PolicyApplied,
)
from .security_checker import SecurityChecker
from .store import AuditStore, InMemoryAuditStore

__all__ = [
    "AccessRecord",
    "AuditEngine",
    "AuditRecord",
    "AuditStore",
    "CheckResult",
    "CheckStatus",
    "ComplianceChecker",
    "ConsentStatus",
    "DataClassification",
    "EncryptionStatus",
    "EthicsChecker",
    "FairnessChecker",
    "FairnessFlag",
    "InMemoryAuditStore",
    "PolicyApplied",
    "SecurityChecker",
]
