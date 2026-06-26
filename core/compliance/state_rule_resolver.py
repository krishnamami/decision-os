"""CM-E — state-specific mortgage rule resolver (catalogue-driven).

Evaluates the state rules in `regulatory_rules` (the `state_code`-tagged rows) for a
loan's property state. Sync + DB-less (RULE 5/6): the caller passes the loan inputs
+ the injected state rules; the resolver evaluates in memory. RULE 11: every output
carries `data_source` + `missing_inputs`; a missing loan field -> not_applicable,
never a fabricated pass.

Typed dispatch on `rule_value.type`:
  - threshold (LTV / rate / points / rate-spread / months-owned caps) -> COMPUTED
    pass/violation + breach + docs_needed. A rule scoped to a loan_purpose (e.g. the
    TX cash-out 80% LTV cap) only applies when the loan's purpose matches.
  - requirement / disclosure / timeline / prohibition -> needs_review (flagged with
    citation for a human — the input often isn't extractable; never auto-passed).

ADVISORY ONLY — does not move proposed_outcome. STANDALONE — NOT wired into the
16/16-critical compliance_check persona. The persona's hardcoded TX cash-out 80%
LTV block stays in place (a RULE 1 gap); folding it into this resolver + wiring
`state_rules_passed` is deferred until a green 16/16 can verify (network-degraded
eval). The TX cash-out cap is now de-hardcoded IN THE CATALOGUE (the row carries
field=ltv + loan_purpose=cash_out), ready for that future wiring.
"""
from __future__ import annotations

import json
from typing import Optional

REQUIREMENT_TYPES = {"requirement", "disclosure", "timeline", "prohibition"}


def _parse_rule_value(rv) -> dict:
    if isinstance(rv, str):
        try:
            return json.loads(rv)
        except (ValueError, TypeError):
            return {"value": rv}
    return rv or {}


async def load_state_rules(conn) -> list:
    """Load every state-tagged regulatory rule (all states). The caller filters by
    property_state inside resolve()."""
    rows = await conn.fetch(
        "SELECT rule_name, state_code, rule_value, citation, category "
        "FROM regulatory_rules WHERE state_code IS NOT NULL AND is_active=true "
        "ORDER BY state_code, rule_name")
    return [dict(r) for r in rows]


class StateRuleResolver:
    def __init__(self, rules: Optional[list] = None):
        self._rules = rules or []

    def evaluate_rule(self, rule: dict, loan: dict, loan_purpose: str = "") -> dict:
        rule_name = rule.get("rule_name", "")
        citation = rule.get("citation", "")
        state = rule.get("state_code", "")
        rv = _parse_rule_value(rule.get("rule_value") or {})
        rule_type = str(rv.get("type") or "requirement").lower()
        operator = str(rv.get("operator") or "").lower()
        field = rv.get("field")
        value = rv.get("value")
        ds = f"regulatory_rules[state_code={state}]"

        def _na(reason, missing):
            return {"rule_name": rule_name, "state": state, "status": "not_applicable",
                    "reason": reason, "citation": citation, "data_source": ds,
                    "missing_inputs": missing}

        # Requirement-style rules — human review (input not auto-evaluable).
        if rule_type in REQUIREMENT_TYPES:
            return {"rule_name": rule_name, "state": state, "status": "needs_review",
                    "reason": f"Manual verification required: {rule_name}",
                    "rule_type": rule_type, "citation": citation, "data_source": ds,
                    "missing_inputs": [f"{rule_name}: human review required — not "
                                       f"auto-evaluable ({rule_type})"]}

        # Threshold rules — computed.
        if rule_type == "threshold" and field and operator and value is not None:
            # purpose-scoped rule (e.g. TX cash-out cap) only applies to that purpose
            scope = rv.get("loan_purpose")
            if scope and scope not in (loan_purpose or ""):
                return _na(f"rule applies to loan_purpose '{scope}', not "
                           f"'{loan_purpose or 'unknown'}'", [])

            loan_val = loan.get(field)
            if loan_val is None:
                return _na(f"{field} not available in loan profile",
                           [f"{field} required for {rule_name}"])
            try:
                loan_num = float(loan_val)
                threshold = float(value)
            except (TypeError, ValueError):
                return _na("non-numeric threshold or loan value",
                           [f"{field} could not be parsed as a number"])

            if operator in ("max", "lte"):
                violation = loan_num > threshold
                breach = round(loan_num - threshold, 4) if violation else 0.0
            elif operator in ("min", "gte"):
                violation = loan_num < threshold
                breach = round(threshold - loan_num, 4) if violation else 0.0
            else:
                return _na(f"unsupported operator '{operator}'", [])

            return {
                "rule_name": rule_name, "state": state,
                "status": "violation" if violation else "pass",
                "loan_value": loan_num, "threshold": threshold, "operator": operator,
                "field": field, "breach": breach, "citation": citation,
                "data_source": f"entity_states.{field}", "missing_inputs": [],
                "docs_needed": ([f"{state} {rule_name}: {field} {loan_num} violates "
                                 f"{operator} {threshold} per {citation}"]
                                if violation else []),
            }

        return _na(f"rule not auto-evaluable (type={rule_type}, field={field!r})",
                   [f"cannot evaluate {rule_name} (type={rule_type})"])

    def resolve(self, property_state: str, loan: dict, loan_purpose: str = "") -> dict:
        loan = loan or {}
        if not property_state:
            return {"property_state": None, "status": "not_applicable",
                    "applicable_rules": 0, "violations": [], "needs_review": [],
                    "passed": [], "state_rules_passed": None, "method": "no_property_state",
                    "citation": "State mortgage law",
                    "data_source": "entity_states.loan_terms.urla.property_state",
                    "missing_inputs": ["property_state not available in loan profile"]}

        ps = property_state.upper()
        state_rules = [r for r in self._rules if (r.get("state_code") or "").upper() == ps]
        if not state_rules:
            return {"property_state": ps, "status": "not_applicable",
                    "applicable_rules": 0, "violations": [], "needs_review": [],
                    "passed": [], "state_rules_passed": True,
                    "method": "no_state_rules_seeded",
                    "note": f"No state rules seeded for {ps}",
                    "citation": "State mortgage law",
                    "data_source": f"regulatory_rules[state_code={ps}]", "missing_inputs": []}

        results = [self.evaluate_rule(r, loan, loan_purpose) for r in state_rules]
        violations = [r for r in results if r["status"] == "violation"]
        needs_review = [r for r in results if r["status"] == "needs_review"]
        passed = [r for r in results if r["status"] == "pass"]
        all_missing = [m for r in results for m in r.get("missing_inputs", [])]
        all_docs = [d for r in results for d in r.get("docs_needed", [])]

        return {
            "property_state": ps,
            "status": "violations_found" if violations else "clean",
            "applicable_rules": len(state_rules), "evaluated": len(results),
            "violations": violations, "needs_review": needs_review, "passed": passed,
            "state_rules_passed": len(violations) == 0,
            "docs_needed": all_docs,
            "note": ("Advisory only. The compliance_check persona's hardcoded TX "
                     "cash-out 80% LTV block is unchanged (RULE 1 gap, tracked for a "
                     "future de-hardcode once a green 16/16 confirms)."
                     if ps == "TX" else None),
            "method": f"state_rule_resolver: {len(state_rules)} rules for {ps}",
            "citation": "State mortgage law + regulatory_rules.state_code",
            "data_source": (f"regulatory_rules[state_code={ps}] + entity_states "
                            "(ltv/note_rate_pct/points_fees_pct/rate_spread_pct/months_owned)"),
            "missing_inputs": sorted(set(all_missing)),
        }


__all__ = ["StateRuleResolver", "load_state_rules", "REQUIREMENT_TYPES"]
