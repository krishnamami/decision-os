"""Explanation subsystem — turns a decision_trace into audience-specific
human-readable narratives (loan officer / underwriter / regulator) via Claude,
with a deterministic template fallback when no API key is configured."""
from .explanation_engine import ExplanationEngine

__all__ = ["ExplanationEngine"]
