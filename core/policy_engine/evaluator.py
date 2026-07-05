from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import yaml
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .store import PolicyStore, PolicyVersionRecord


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
    # Type-2 policy versioning — set when the evaluator consulted a
    # PolicyStore. Carries the policy_version_id that produced the
    # outcome and the full agency chain that was walked (overlay-first).
    # Both default to None / [] so legacy YAML-only paths keep working.
    policy_version_id: Optional[str] = None
    policy_chain: list[str] = Field(default_factory=list)
    # Regulation citations for the boundary expressions that fired, from their
    # decisions.yaml ``governed_by`` (enriched with the resolved threshold when a
    # ThresholdResolver is supplied). Empty for legacy / string-only clauses.
    governed_by: list[dict] = Field(default_factory=list)


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

# A boundary clause item is either a plain expression string (legacy) or a
# dict {expression, governed_by} (new, PROMPT D). Both forms evaluate identically.
_RHS_RE = re.compile(r"([><=!]+\s*)([\d.]+)")


def _parse_clause_item(item: Any) -> tuple[str, Optional[dict]]:
    """(expression_str, governed_by_dict | None) for a clause item."""
    if isinstance(item, str):
        return item, None
    if isinstance(item, dict):
        return (item.get("expression") or item.get("expr") or ""), item.get("governed_by")
    return str(item), None


def _extract_rhs(expr: str) -> Optional[float]:
    m = _RHS_RE.search(expr)
    return float(m.group(2)) if m else None


def _replace_rhs(expr: str, new_value: Any) -> str:
    """Replace the numeric RHS of a comparison with ``new_value``. If the YAML
    threshold is a fraction (≤1.5, e.g. dti 0.43) but the resolved value is a
    percent (>1.5, e.g. 43), scale it down to keep the comparison in the same
    units as the evaluation context."""
    orig = _extract_rhs(expr)
    try:
        v: Any = float(new_value)
    except (TypeError, ValueError):
        return expr
    if orig is not None and orig <= 1.5 and v > 1.5:
        v = v / 100.0
    # render ints without a trailing .0
    out = int(v) if float(v).is_integer() else v
    return _RHS_RE.sub(lambda m: f"{m.group(1)}{out}", expr, count=1)


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
    # A credit_score of 0 or negative is a "no score on file" sentinel (thin
    # file), NOT a real sub-580 FICO — treat it as missing so a range check like
    # `credit_score < 580` can't wrongly block it (while `credit_score is null`
    # still escalates it).
    if (path.rsplit(".", 1)[-1].strip() == "credit_score"
            and isinstance(cur, (int, float)) and not isinstance(cur, bool)
            and cur <= 0):
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

    async def evaluate(
        self,
        decision_id: str,
        context: dict[str, Any],
        upstream: Optional[list[UpstreamSummary]] = None,
        *,
        policy_store: Optional["PolicyStore"] = None,
        at: Optional[datetime] = None,
        agency_chain: Optional[list[str]] = None,
        product: Optional[str] = None,
        state: Optional[str] = None,
        resolver: Optional[Any] = None,
    ) -> PolicyDecision:
        """Evaluate a decision's boundary against context.

        When ``policy_store`` is provided, the boundary clauses come from
        the active PolicyVersion at ``at`` for the first matching agency
        in ``agency_chain``. The PolicyDecision returned carries
        ``policy_version_id`` and ``policy_chain`` stamping which exact
        rule version fired — required for replay and regulator audit.

        When ``policy_store`` is None (legacy / tests), the YAML-loaded
        boundary is used and policy_version_id is left None. Outcomes
        are identical between the two paths as long as the seeded
        PolicyVersion matches the YAML — which is the v1 invariant.
        """

        if decision_id not in self._decisions:
            raise KeyError(f"unknown decision: {decision_id!r}")

        spec = self._decisions[decision_id]
        upstream = upstream or []
        upstream_by_id = {u.decision_id: u for u in upstream}

        # Resolve the active PolicyVersion FIRST so every return path —
        # including the hard-rule short-circuits below — can carry the
        # policy_version_id stamp. Without this, traces for blocked
        # dependents (fraud_block_stops_pipeline, contamination_guard,
        # upstream_block_propagates) would have policy_version_id=None.
        version_used, agency_used, version_chain = await self._resolve_active_version(
            decision_id=decision_id,
            policy_store=policy_store,
            at=at,
            agency_chain=agency_chain,
            product=product,
            state=state,
        )
        if version_used is not None:
            boundary = version_used.boundary or {}
            contamination_guard = version_used.contamination_guard or {}
        else:
            boundary = spec.get("boundary", {}) or {}
            contamination_guard = spec.get("contamination_guard") or {}

        version_stamp = self._version_stamp(version_used, version_chain)

        # ── 1. Pipeline-level hard rules ──────────────────────────────
        hard_block = self._check_hard_rules(decision_id, upstream_by_id)
        if hard_block is not None:
            return hard_block.model_copy(update=version_stamp)

        # ── 2. contamination_guard ────────────────────────────────────
        contamination = self._check_contamination(
            decision_id, contamination_guard, upstream_by_id
        )
        if contamination is not None:
            return contamination.model_copy(update=version_stamp)

        # ── 3. Boundary clauses, in priority order ────────────────────
        merged_context = self._merge_upstream_into_context(context, upstream)

        for clause_name, outcome in _CLAUSE_PRIORITY:
            raw_items = boundary.get(clause_name) or []
            if not raw_items:
                continue
            # Parse each item (string or {expression, governed_by}); when an item
            # is governed by a resolvable threshold and a resolver is supplied,
            # swap the hardcoded RHS for the tenant/agency-resolved value.
            eff_exprs: list[str] = []
            gov_records: list[dict] = []
            for item in raw_items:
                expr, gov = _parse_clause_item(item)
                eff = expr
                if gov:
                    rec = dict(gov)
                    tf = gov.get("threshold_field")
                    if tf and resolver is not None:
                        try:
                            resolution = await resolver.resolve(tf, _extract_rhs(expr))
                            eff = _replace_rhs(expr, resolution.value)
                            rec.update({
                                "effective_value": resolution.value,
                                "source": resolution.source,
                                "citation": resolution.citation or gov.get("citation"),
                                "floor_enforced": getattr(resolution, "floor_enforced", False),
                            })
                        except Exception:
                            pass
                    rec.setdefault("expression", expr)
                    gov_records.append(rec)
                eff_exprs.append(eff)
            matched, unmatched, all_ok = self._evaluate_clause(eff_exprs, merged_context)
            # block_if AND escalate_if are OR — ANY single condition fires (block:
            # bankruptcy OR foreclosure OR low-score / fair_lending OR ...; escalate:
            # high-risk OR senior-review-required / any single closing or compliance
            # concern). automate_if / recommend_if stay AND — recommend_if encodes
            # ranges (e.g. dti > 0.36 AND dti <= 0.43) that OR would make always-true.
            fired = bool(matched) if clause_name in ("block_if", "escalate_if") else all_ok
            if fired:
                # For an OR block, cite only the item(s) that actually fired
                # (fall back to all if expression matching can't correlate them).
                gov_fired = gov_records
                if clause_name in ("block_if", "escalate_if") and gov_records:
                    matched_raws = {m.raw for m in matched}
                    _f = [g for g in gov_records if g.get("expression") in matched_raws]
                    gov_fired = _f or gov_records
                return PolicyDecision(
                    decision_id=decision_id,
                    outcome=outcome,
                    matched_clause=clause_name,
                    matched_rules=matched,
                    unmatched_rules=unmatched,
                    reasons=[f"clause {clause_name} matched"],
                    governed_by=gov_fired,
                    **version_stamp,
                )

        # ── 4. No clause matched → escalate (safe default) ────────────
        return PolicyDecision(
            decision_id=decision_id,
            outcome=PolicyOutcome.ESCALATE,
            matched_clause=None,
            reasons=[
                "no boundary clause matched; escalating per safe default"
            ],
            **version_stamp,
        )

    # ── PolicyStore lookup helpers ────────────────────────────────────

    @staticmethod
    async def _resolve_active_version(
        *,
        decision_id: str,
        policy_store: Optional["PolicyStore"],
        at: Optional[datetime],
        agency_chain: Optional[list[str]],
        product: Optional[str],
        state: Optional[str],
    ) -> tuple[Optional["PolicyVersionRecord"], Optional[str], list[str]]:
        """Walk the agency_chain (overlay-first) and return:
          (selected_version, agency, version_chain).
        version_chain lists every agency consulted whether or not it
        had an active version — useful for the trace stamp."""

        if policy_store is None:
            return None, None, []

        chain = list(agency_chain or ["lender_overlay"])
        eval_at = at or datetime.utcnow()

        version_chain: list[str] = []
        chosen: Optional["PolicyVersionRecord"] = None
        chosen_agency: Optional[str] = None

        for agency in chain:
            v = await policy_store.active_version(
                decision_id, agency, at=eval_at, product=product, state=state
            )
            if v is not None:
                version_chain.append(v.policy_version_id)
                if chosen is None:
                    chosen = v
                    chosen_agency = agency
        return chosen, chosen_agency, version_chain

    @staticmethod
    def _version_stamp(
        version_used: Optional["PolicyVersionRecord"],
        version_chain: list[str],
    ) -> dict[str, Any]:
        return {
            "policy_version_id": version_used.policy_version_id if version_used else None,
            "policy_chain": list(version_chain),
        }

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
        # Order matters: SPECIFIC rules first so the trace's
        # policy_reasons names the most precise hard rule that fired.
        # Falls through to the generic upstream_block_propagates check
        # for any other BLOCK upstream.

        # closing_readiness specifically must not run if compliance is blocked.
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

        # Generic upstream_block_propagates_to_dependents — any other
        # BLOCK upstream we didn't catch above.
        for u in upstream_by_id.values():
            if u.outcome == PolicyOutcome.BLOCK:
                return PolicyDecision(
                    decision_id=decision_id,
                    outcome=PolicyOutcome.BLOCK,
                    reasons=[
                        f"upstream {u.decision_id} blocked "
                        "(upstream_block_propagates_to_dependents)"
                    ],
                )

        return None

    @staticmethod
    def _check_contamination(
        decision_id: str,
        guard: dict[str, Any],
        upstream_by_id: dict[str, UpstreamSummary],
    ) -> Optional[PolicyDecision]:
        threshold = guard.get("reject_if_upstream_confidence_below")
        if threshold is not None:
            for u in upstream_by_id.values():
                if u.confidence < threshold:
                    return PolicyDecision(
                        decision_id=decision_id,
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
                        decision_id=decision_id,
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
