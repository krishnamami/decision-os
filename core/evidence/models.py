"""Evidence Graph — core data models.

Architecture:
  Document fields -> EvidenceNode (raw evidence)
  EvidenceNodes   -> FactNode (resolved fact)
  FactNodes       -> Persona context (replaces raw fields)
  EvidenceEdges   -> relationships between nodes

Example flow for income:
  W2 box1_wages=$102,000          -> EvidenceNode
  Paystub YTD annualized=$104,000 -> EvidenceNode
  1040 wages=$101,500             -> EvidenceNode
  Cross-validate: agree within 3% -> edge (corroborates)
  Resolve: qualifying_income = $102,000/12 -> FactNode (confidence 0.97)

  If 1040 showed $75,000:
  conflict edge between W2 and 1040; FactNode.conflicts_found = True;
  persona sees the conflict -> escalate for UW review.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import List, Optional
from uuid import UUID


@dataclass
class EvidenceNode:
    application_id: str
    tenant_id: str
    node_type: str
    evidence_category: str
    field_name: str
    raw_value: Optional[str] = None
    numeric_value: Optional[float] = None
    confidence: float = 0.0
    source_document_id: Optional[str] = None
    source_document_type: Optional[str] = None
    extraction_method: str = "derived"
    tax_year: Optional[int] = None
    as_of_date: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    id: UUID = field(default_factory=uuid.uuid4)


@dataclass
class EvidenceEdge:
    application_id: str
    tenant_id: str
    from_node_id: UUID
    to_node_id: UUID
    relationship: str
    strength: float = 1.0
    notes: Optional[str] = None
    id: UUID = field(default_factory=uuid.uuid4)


@dataclass
class FactNode:
    application_id: str
    tenant_id: str
    fact_type: str
    fact_value: Optional[float] = None
    fact_text: Optional[str] = None
    confidence: float = 0.0
    resolution_method: str = ""
    evidence_ids: List[UUID] = field(default_factory=list)
    conflicts_found: bool = False
    conflict_ids: List[UUID] = field(default_factory=list)
    resolution_notes: str = ""
    agency_treatment: dict = field(default_factory=dict)
    id: UUID = field(default_factory=uuid.uuid4)

    def to_summary(self) -> str:
        """Human-readable summary for the decision trace."""
        lines = [
            f"{self.fact_type}: {self.fact_value if self.fact_value is not None else self.fact_text}",
            f"confidence: {self.confidence:.2f}",
            f"sources: {len(self.evidence_ids)} documents",
            f"method: {self.resolution_method}",
            f"conflicts: {'YES - escalate' if self.conflicts_found else 'none'}",
        ]
        return "\n".join(lines)


__all__ = ["EvidenceNode", "EvidenceEdge", "FactNode"]
