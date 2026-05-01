from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel


class TermNotFoundError(KeyError):
    """Raised when a term cannot be resolved to a canonical vocabulary entry."""


class VocabularyEntry(BaseModel):
    canonical: str
    synonyms: list[str] = []
    definition: Optional[str] = None
    data_type: Optional[str] = None
    range: Optional[list[float]] = None
    allowed_values: Optional[list[Any]] = None
    owner_team: Optional[str] = None


class SemanticResolver:
    """Loads a domain knowledge base and resolves user-supplied terms to
    canonical names. Drives the semantic layer that sits between raw
    events and the policy / context layers — same business concept must
    arrive at the policy engine under one canonical key regardless of
    upstream system phrasing."""

    def __init__(self, knowledge_base: dict[str, Any]):
        self._kb = knowledge_base
        self._vocabulary = knowledge_base.get("vocabulary", {})
        self._decisions = knowledge_base.get("decisions", {})
        self._ontology = knowledge_base.get("ontology", {})
        self._dependency_graph = knowledge_base.get("dependency_graph", {})
        self._index = self._build_index()

    @classmethod
    def from_path(cls, path: str | Path) -> "SemanticResolver":
        with open(path, "r", encoding="utf-8") as f:
            return cls(json.load(f))

    def _build_index(self) -> dict[str, str]:
        index: dict[str, str] = {}
        for key, entry in self._vocabulary.items():
            canonical = entry.get("canonical", key)
            for alias in [key, canonical, *entry.get("synonyms", [])]:
                normalized = self._normalize(alias)
                if normalized in index and index[normalized] != canonical:
                    raise ValueError(
                        f"synonym collision: {alias!r} maps to "
                        f"{index[normalized]!r} and {canonical!r}"
                    )
                index[normalized] = canonical
        return index

    @staticmethod
    def _normalize(term: str) -> str:
        return term.strip().lower().replace("-", "_").replace(" ", "_")

    # ── Term resolution ────────────────────────────────────────────────

    def resolve(self, term: str) -> Optional[str]:
        return self._index.get(self._normalize(term))

    def resolve_strict(self, term: str) -> str:
        canonical = self.resolve(term)
        if canonical is None:
            raise TermNotFoundError(term)
        return canonical

    def is_known(self, term: str) -> bool:
        return self.resolve(term) is not None

    def entry(self, term: str) -> Optional[VocabularyEntry]:
        canonical = self.resolve(term)
        if canonical is None:
            return None
        raw = self._vocabulary.get(canonical)
        if raw is None:
            for key, value in self._vocabulary.items():
                if value.get("canonical") == canonical:
                    raw = value
                    break
        if raw is None:
            return None
        return VocabularyEntry(**raw)

    def definition(self, term: str) -> Optional[str]:
        entry = self.entry(term)
        return entry.definition if entry else None

    # ── Bulk normalization ─────────────────────────────────────────────

    def normalize_keys(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return a new dict with every known key rewritten to canonical
        form. Unknown keys pass through unchanged so callers can still see
        them — drop them later if strict mode is desired."""
        return {(self.resolve(k) or k): v for k, v in payload.items()}

    def unknown_keys(self, payload: dict[str, Any]) -> list[str]:
        return [k for k in payload if not self.is_known(k)]

    # ── Decision metadata ──────────────────────────────────────────────

    def decision(self, decision_id: str) -> Optional[dict[str, Any]]:
        return self._decisions.get(decision_id)

    def dependencies(self, decision_id: str) -> list[str]:
        return list(self._dependency_graph.get(decision_id, []))

    def transitive_dependencies(self, decision_id: str) -> list[str]:
        seen: list[str] = []
        stack = list(self.dependencies(decision_id))
        while stack:
            d = stack.pop()
            if d in seen:
                continue
            seen.append(d)
            stack.extend(self.dependencies(d))
        return seen

    def all_decisions(self) -> list[str]:
        return list(self._decisions.keys())

    # ── Ontology ───────────────────────────────────────────────────────

    def ontology(self) -> dict[str, Any]:
        return dict(self._ontology)

    def entity_attributes(self, entity_name: str) -> list[str]:
        node = self._ontology.get(entity_name, {})
        return list(node.get("attributes", []))
