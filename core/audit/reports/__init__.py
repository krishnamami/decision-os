"""Audit reports — PRD §23.7.

Six report generators. Each takes an iterable of AuditRecord plus a
window and returns a structured Report. The reports layer is
read-only: never mutates the audit_records table, never persists. The
audit_reports table (PRD §23.6) stores generated artefacts; the
schedule + S3 plumbing lands in TIER 4 (regulatory).
"""
from __future__ import annotations

from .ai_trail import generate_ai_trail_report
from .base import Report
from .bias import generate_bias_report
from .fair_lending import generate_fair_lending_report
from .hmda import generate_hmda_report
from .overrides import generate_exception_register, generate_overrides_report
from .repurchase_defense import generate_repurchase_defense_report
from .security import generate_security_report

__all__ = [
    "Report",
    "generate_ai_trail_report",
    "generate_bias_report",
    "generate_fair_lending_report",
    "generate_hmda_report",
    "generate_overrides_report",
    "generate_exception_register",
    "generate_repurchase_defense_report",
    "generate_security_report",
]
