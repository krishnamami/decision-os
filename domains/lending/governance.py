"""Map a (decision_id, outcome) to the governing regulation citations declared
in decisions.yaml. Single source of truth for `decision_outputs.governed_by`,
used by both the cron writer (new decisions) and the backfill (existing ones).

A clause maps to the outcome it produces:
  automate_if → allow, recommend_if → recommend, block_if → block,
  escalate_if → escalate.
"""
from __future__ import annotations

import functools
from pathlib import Path
from typing import Any, Optional

import yaml

_YAML = Path(__file__).parent / "decisions.yaml"
_CLAUSE_FOR_OUTCOME = {
    "allow": "automate_if",
    "recommend": "recommend_if",
    "block": "block_if",
    "escalate": "escalate_if",
}


@functools.lru_cache(maxsize=1)
def _gov_map() -> dict[tuple[str, str], list[dict]]:
    with open(_YAML, encoding="utf-8") as f:
        spec = yaml.safe_load(f)
    out: dict[tuple[str, str], list[dict]] = {}
    for d in spec.get("decisions", []):
        did = d.get("id")
        boundary = d.get("boundary") or {}
        for outcome, clause_name in _CLAUSE_FOR_OUTCOME.items():
            items = boundary.get(clause_name) or []
            govs: list[dict] = []
            for it in items:
                if isinstance(it, dict) and it.get("governed_by"):
                    g = dict(it["governed_by"])
                    g.setdefault("expression", it.get("expression"))
                    govs.append(g)
            if govs:
                out[(did, outcome)] = govs
    return out


def governed_by_for(decision_id: str, outcome: str) -> Optional[list[dict]]:
    """Governing citations for this decision+outcome, or None."""
    return _gov_map().get((decision_id, outcome))


__all__ = ["governed_by_for"]
