"""Evidence Graph (EV-A) — schema-backed data model.

Document fields -> EvidenceNode (raw evidence)
EvidenceNodes  -> FactNode (resolved fact personas consume)
EvidenceEdges  -> relationships between nodes (corroborates / conflicts_with / ...)
"""
from .models import EvidenceEdge, EvidenceNode, FactNode
from .store import EvidenceStore

__all__ = ["EvidenceNode", "EvidenceEdge", "FactNode", "EvidenceStore"]
