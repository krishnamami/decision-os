"""Synthetic data factory for the lending domain.

Generates diverse applicants programmatically — credit bands,
geographies, ages, doc sets — and a small library of overrides that
deliberately trigger audit findings (missing consent, protected-
attribute leak, segment deviation). Used by:

  - the audit reports smoke (scripts/smoke_audit_reports.py) so
    every report shows meaningful aggregations across many applicants,
    not just the 7 canonical scenarios.
  - tests that need a richer corpus than the hand-rolled scenarios.

The seven curated scenarios remain the canonical regression suite;
synthetic data is additive.
"""
from __future__ import annotations

from .factory import (
    EDMS_DOC_TYPES,
    SEGMENTS,
    STATES,
    ApplicantProfile,
    DocumentSpec,
    AuditOverlay,
    build_synthetic_applicants,
    inject_into_platform,
)

__all__ = [
    "ApplicantProfile",
    "AuditOverlay",
    "DocumentSpec",
    "EDMS_DOC_TYPES",
    "SEGMENTS",
    "STATES",
    "build_synthetic_applicants",
    "inject_into_platform",
]
