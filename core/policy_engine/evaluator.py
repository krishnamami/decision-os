from __future__ import annotations

import re
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────
# Outcomes
# ─────────────────────────────────────────────────────────────────────


class PolicyOutcome(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"
    RECOMMEND = "recommend"
    ESCALATE = "escalate"


# Mapping from boundary YAML clause to outcome.
# Order also encodes priority: block beats escalate beats recommend
# beats allow. Block always wins so a hard fail in one clause cannot
# be silently overridden by a permissive clause elsewhere.
_CLAUSE_PRIORITY: list[tuple[str, PolicyOutcome]] = [
    ("block_if",    PolicyOutcome.BLOCK),
    ("escalate_if", PolicyOutcome.ESCALATE),
    ("recommend_if", PolicyOutcome.RECOMMEND),
    ("automate_if", PolicyOutcome.ALLOW),
]


class UpstreamSummary(BaseModel):
    """Per-upstream-decision context the evaluator may need to enforce
    contamination_guard and the fraud/compliance hard rules."""

    decision_id: str
    outcome: PolicyOutcome
    confidence: float = 1.0


class BoundaryRule(BaseModel):
    raw: str
    matched: Optional[bool] = None
    error: Optional[str] = None


class PolicyDecision(BaseModel):
    decision_id: str
    outcome: PolicyOutcome
    matched_clause: Optional[str] = None
    matched_rules: list[BoundaryRule] = Field(default_factory=list)
    unmatched_rules: list[BoundaryRule] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    contamination: bool = False


# ─────────────────────────────────────────────────────────────────────
# Boundary expression parser
#
# Grammar covers exactly what appears in domains/lending/decisions.yaml:
#   <lhs> >= | <= | == | != | > | < <rhs>
#   <lhs> in [<value>, ...]
#   <lhs> in <var>
#   <lhs> is null
#   <lhs> is not null
# Where <lhs> is a dotted identifier (a.b.c) and <rhs> is a number,
# bool, null, bareword, or list literal.
# ─────────────────────────────────────────────────────────────────────


_RE_IS_NULL = re.compile(r"^(.+?)\s+is\s+(not\s+null|null)\s*$")
_RE_IN = re.compile(r"^(.+?)\s+in\s+(.+)\s*$")
_RE_CMP = re.compile(r"^(.+?)\s*(>=|<=|==|!=|>|<)\s*(.+)\s*$")


_MISSING = object()


def _normalize_for_lookup(token: str) -> str:
    return token.strip()


def _lookup(ctx: dict[str, Any], path: str) -> Any:
    """Dotted-path lookup against a context dict.

    Convention: ``<thing>.count`` returns ``len(thing)`` when ``thing``
    is a list/tuple — mirrors yaml clauses like
    ``eligible_products.count >= 1``."""

    cur: Any = ctx
    for part in path.split("."):
        part = _normalize_for_lookup(part)
        if cur is None:
            return _MISSING
        if isinstance(cur, dict):
            if part in cur:
                cur = cur[part]
                continue
            if part == "count":
                return _MISSING
            return _MISSING
        if isinstance(cur, (list, tuple)) and part == "count":
            cur = len(cur)
            continue
        if hasattr(cur, part):
            cur = getattr(cur, part)
            continue
        return _MISSING
    return cur


def _parse_value(token: str) -> Any:
    s = token.strip()
    if not s:
        return ""
    if s == "true":
        return True
    if s == "false":
        return False
    if s == "null" or s == "None":
        return None
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        return [_parse_value(p.strip()) for p in _split_top_level_commas(inner)]
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s  # bareword string


def _split_top_level_commas(s: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in s:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current))
    return parts


def _evaluate_rule(raw_rule: str, context: dict[str, Any]) -> bool:
    s = raw_rule.strip()

    m = _RE_IS_NULL.match(s)
    if m:
        lhs = m.group(1).strip()
        negate = m.group(2).strip().startswith("not")
        val = _lookup(context, lhs)
        is_null = (val is None) or (val is _MISSING)
        return (not is_null) if negate else is_null

    m = _RE_IN.match(s)
    if m:
        lhs = m.group(1).strip()
        rhs_raw = m.group(2).strip()
        lhs_val = _lookup(context, lhs)
        if lhs_val is _MISSING:
            return False
        if rhs_raw.startswith("[") and rhs_raw.endswith("]"):
            rhs_val = _parse_value(rhs_raw)
        else:
            rhs_val = _lookup(context, rhs_raw)
            if rhs_val is _MISSING:
                return False
        if not isinstance(rhs_val, (list, tuple, set, frozenset)):
            return False
        return lhs_val in rhs_val

    m = _RE_CMP.match(s)
    if m:
        lhs = m.group(1).strip()
        op = m.group(2)
        rhs_raw = m.group(3).strip()
        lhs_val = _lookup(context, lhs)
        if lhs_val is _MISSING:
            return False
        rhs_val = _parse_value(rhs_raw)
        try:
            if op == "==":
                return lhs_val == rhs_val
            if op == "!=":
                return lhs_val != rhs_val
            if op == ">=":
                return lhs_val >= rhs_val
            if op == "<=":
                return lhs_val <= rhs_val
            if op == ">":
                return lhs_val > rhs_val
            if op == "<":
                return lhs_val < rhs_val
        except TypeError:
            return False

    raise ValueError(f"unrecognized boundary rule: {raw_rule!r}")


# ─────────────────────────────────────────────────────────────────────
# PolicyEvaluator
# ─────────────────────────────────────────────────────────────────────


class PolicyEvaluator:
    """Reads boundary rules from decisions.yaml and evaluates a context
    bundle against them. Returns one of allow / block / recommend /
    escalate plus the matched clause and a per-rule trace.

    Hard rules enforced here (also encoded in decisions.yaml):
      - fraud_block_stops_pipeline      → if fraud_screening blocked,
                                          downstream block by default
      - compliance_block_stops_closing  → closing_readiness blocks if
                                          compliance_check is blocked
      - upstream_block_propagates_to_dependents → any blocked upstream
                                          dependent → block
      - contamination_guard             → reject if upstream confidence
                                          below threshold
    """

    def __init__(self, spec: dict[str, Any]):
        self._spec = spec
        self._decisions: dict[str, dict[str, Any]] = {
            d["id"]: d for d in spec.get("decisions", [])
        }
        self._hard_rules: list[str] = list(spec.get("hard_rules", []))

    @classmethod
    def from_path(cls, path: str | Path) -> "PolicyEvaluator":
        with open(path, "r", encoding="utf-8") as f:
            return cls(yaml.safe_load(f))

    def list_decisions(self) -> list[str]:
        return list(self._decisions.keys())

    def decision_spec(self, decision_id: str) -> dict[str, Any]:
        if decision_id not in self._decisions:
            raise KeyError(f"unknown decision: {decision_id!r}")
        return dict(self._decisions[decision_id])

    # ── Main entrypoint ───────────────────────────────────────────────

    def evaluate(
        self,
        decision_id: str,
        context: dict[str, Any],
        upstream: Optional[list[UpstreamSummary]] = None,
    ) -> PolicyDecision:
        if decision_id not in self._decisions:
            raise KeyError(f"unknown decision: {decision_id!r}")

        spec = self._decisions[decision_id]
        upstream = upstream or []
        upstream_by_id = {u.decision_id: u for u in upstream}

        # ── 1. Pipeline-level hard rules ──────────────────────────────
        hard_block = self._check_hard_rules(decision_id, upstream_by_id)
        if hard_block is not None:
            return hard_block

        # ── 2. contamination_guard from spec ──────────────────────────
        contamination = self._check_contamination(spec, upstream_by_id)
        if contamination is not None:
            return contamination

        # ── 3. Boundary clauses, in priority order ────────────────────
        boundary = spec.get("boundary", {}) or {}
        merged_context = self._merge_upstream_into_context(context, upstream)

        for clause_name, outcome in _CLAUSE_PRIORITY:
            rules = boundary.get(clause_name) or []
            if not rules:
                continue
            matched, unmatched, all_ok = self._evaluate_clause(rules, merged_context)
            if all_ok:
                return PolicyDecision(
                    decision_id=decision_id,
                    outcome=outcome,
                    matched_clause=clause_name,
                    matched_rules=matched,
                    unmatched_rules=unmatched,
                    reasons=[f"clause {clause_name} matched"],
                )

        # ── 4. No clause matched → escalate (safe default) ────────────
        return PolicyDecision(
            decision_id=decision_id,
            outcome=PolicyOutcome.ESCALATE,
            matched_clause=None,
            reasons=[
                "no boundary clause matched; escalating per safe default"
            ],
        )

    # ── Clause evaluation ─────────────────────────────────────────────

    @staticmethod
    def _evaluate_clause(
        rules: list[str], context: dict[str, Any]
    ) -> tuple[list[BoundaryRule], list[BoundaryRule], bool]:
        matched: list[BoundaryRule] = []
        unmatched: list[BoundaryRule] = []
        all_ok = True
        for raw in rules:
            try:
                ok = _evaluate_rule(raw, context)
                rule = BoundaryRule(raw=raw, matched=ok)
                if ok:
                    matched.append(rule)
                else:
                    unmatched.append(rule)
                    all_ok = False
            except Exception as err:
                unmatched.append(BoundaryRule(raw=raw, matched=False, error=str(err)))
                all_ok = False
        return matched, unmatched, all_ok

    # ── Hard-rule enforcement ─────────────────────────────────────────

    @staticmethod
    def _check_hard_rules(
        decision_id: str,
        upstream_by_id: dict[str, UpstreamSummary],
    ) -> Optional[PolicyDecision]:

        # upstream_block_propagates_to_dependents
        for u in upstream_by_id.values():
            if u.outcome == PolicyOutcome.BLOCK:
                # fraud_block_stops_pipeline / compliance_block_stops_closing
                # are special-cased below; the generic propagation still
                # applies to anything else.
                return PolicyDecision(
                    decision_id=decision_id,
                    outcome=PolicyOutcome.BLOCK,
                    reasons=[
                        f"upstream {u.decision_id} blocked "
                        "(upstream_block_propagates_to_dependents)"
                    ],
                )

        # closing_readiness specifically must not run if compliance is blocked
        if decision_id == "closing_readiness":
            comp = upstream_by_id.get("compliance_check")
            if comp and comp.outcome == PolicyOutcome.BLOCK:
                return PolicyDecision(
                    decision_id=decision_id,
                    outcome=PolicyOutcome.BLOCK,
                    reasons=["compliance_block_stops_closing"],
                )

        # fraud screening blocks fan out to every downstream
        fraud = upstream_by_id.get("fraud_screening")
        if fraud and fraud.outcome == PolicyOutcome.BLOCK and decision_id != "fraud_screening":
            return PolicyDecision(
                decision_id=decision_id,
                outcome=PolicyOutcome.BLOCK,
                reasons=["fraud_block_stops_pipeline"],
            )

        return None

    @staticmethod
    def _check_contamination(
        spec: dict[str, Any],
        upstream_by_id: dict[str, UpstreamSummary],
    ) -> Optional[PolicyDecision]:
        guard = spec.get("contamination_guard") or {}

        threshold = guard.get("reject_if_upstream_confidence_below")
        if threshold is not None:
            for u in upstream_by_id.values():
                if u.confidence < threshold:
                    return PolicyDecision(
                        decision_id=spec["id"],
                        outcome=PolicyOutcome.BLOCK,
                        contamination=True,
                        reasons=[
                            f"upstream {u.decision_id} confidence "
                            f"{u.confidence:.2f} below contamination_guard "
                            f"threshold {threshold:.2f}"
                        ],
                    )

        if guard.get("fail_if_any_upstream_blocked") is True:
            for u in upstream_by_id.values():
                if u.outcome == PolicyOutcome.BLOCK:
                    return PolicyDecision(
                        decision_id=spec["id"],
                        outcome=PolicyOutcome.BLOCK,
                        contamination=True,
                        reasons=[
                            f"upstream {u.decision_id} blocked; "
                            "fail_if_any_upstream_blocked"
                        ],
                    )
        return None

    # ── Context merging ───────────────────────────────────────────────

    @staticmethod
    def _merge_upstream_into_context(
        context: dict[str, Any],
        upstream: list[UpstreamSummary],
    ) -> dict[str, Any]:
        """Expose upstream outcomes/confidence at predictable keys so
        boundary rules like ``income_verification.confidence < 0.85`` and
        ``fraud_screening.decision == block`` can reach them."""

        merged = dict(context)
        any_block = False
        all_auto = True

        for u in upstream:
            existing = merged.get(u.decision_id) or {}
            if not isinstance(existing, dict):
                existing = {"value": existing}
            existing.setdefault("decision", u.outcome.value)
            existing.setdefault("outcome", u.outcome.value)
            existing.setdefault("confidence", u.confidence)
            merged[u.decision_id] = existing
            if u.outcome == PolicyOutcome.BLOCK:
                any_block = True
            if u.outcome != PolicyOutcome.ALLOW:
                all_auto = False

        merged.setdefault("any_upstream_hard_block", any_block)
        merged.setdefault("all_upstream_auto_cleared", all_auto and bool(upstream))
        return merged
