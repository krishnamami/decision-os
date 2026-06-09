"""MiroFish PolicySimulator — re-evaluate a portfolio under a what-if.

Unlike a simple threshold sweep, this re-runs the *affected persona
agents* on every loan with the scenario applied, and records each flip
with the agent's REASONING (the numbers that moved, and what it would
take to qualify) — not just "DTI exceeded 36%".

Three override families (see ``core.mirofish.scenarios``):
  • policy      — move a boundary threshold; data unchanged, the agent
                  evaluates against the new cap/floor.
  • stress      — shock the DATA (rate ↑, price ↓); PITI / DTI / LTV
                  recompute, then the agent re-evaluates the new value.
  • regulatory  — change the conforming limit; loans reclassify and
                  product_eligibility re-evaluates.

Deterministic by default (local-first, no API key). ``anthropic_client``
is accepted for parity with the rest of MiroFish; the per-flip reasoning
here is fully derivable from the loan math, so the bulk loop stays fast
and offline.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional

from core.mirofish.models import (
    SimulationFlip,
    SimulationResult,
    SimulationScenario,
)


# Default boundaries the agents evaluate against today (the "before").
DEFAULT_BOUNDARIES: dict[str, dict[str, float]] = {
    "dti_calculation": {"back_dti_max": 43},
    "credit_assessment": {"min_score": 620},
    "ltv_assessment": {"max_ltv": 97},
    "product_eligibility": {"conforming_limit": 766550},
}

_SEVERITY = {"allow": 0, "recommend": 1, "escalate": 2, "block": 3}
_AMORT_MONTHS = 360
_ANTHROPIC_MODEL = "claude-sonnet-4-6"


def _f(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _amortized_pi(loan: float, annual_rate_pct: float, months: int = _AMORT_MONTHS) -> float:
    """Monthly principal + interest for a fixed loan."""
    mr = (annual_rate_pct / 100.0) / 12.0
    if mr <= 0:
        return loan / months
    factor = (1 + mr) ** months
    return loan * mr * factor / (factor - 1)


class PolicySimulator:
    """Apply a :class:`SimulationScenario` across the portfolio and return
    which decisions flip and why as a :class:`SimulationResult`."""

    def __init__(self, db_connection: Any, anthropic_client: Optional[Any] = None):
        self.db = db_connection
        self.client = anthropic_client

    @asynccontextmanager
    async def _acquire(self):
        db = self.db
        if hasattr(db, "acquire"):
            async with db.acquire() as conn:
                yield conn
        else:
            yield db

    # ── Public entrypoint ────────────────────────────────────────────

    async def simulate(self, scenario: SimulationScenario) -> SimulationResult:
        started = datetime.now(timezone.utc)
        tenant_id = scenario.tenant_id

        affected = self._affected_decisions(scenario)
        boundaries_after = self._scenario_boundaries(scenario)
        is_stress = "_stress" in scenario.overrides

        entities = await self._get_entity_states(tenant_id)
        before_map = await self._snapshot_before(tenant_id, affected)

        flips: list[SimulationFlip] = []
        per_decision: dict[str, list[dict]] = defaultdict(list)
        total = 0
        affected_apps = 0
        approved_before = approved_after = 0
        vol_before = vol_after = 0.0
        new_blocks = new_allows = 0

        for state in entities:
            total += 1
            app_id = state.get("application_id")
            loan_amt = _f(state.get("loan_amount")) or 0.0
            after_state = self._apply_overrides(state, scenario) if is_stress else state

            ok_before = ok_after = True
            app_flipped = False
            for decision_id in affected:
                base_bounds = DEFAULT_BOUNDARIES.get(decision_id, {})
                after_bounds = boundaries_after.get(decision_id, base_bounds)
                baseline, _ = self._evaluate_with_agent(decision_id, state, base_bounds)
                after, vals = self._evaluate_with_agent(decision_id, after_state, after_bounds)

                if baseline != "allow":
                    ok_before = False
                if after != "allow":
                    ok_after = False

                # A flip is purely scenario-attributable: baseline and
                # after both come from this evaluator, so they differ only
                # because the scenario moved a threshold or the data. Show
                # the live stored outcome as the "before" when it agrees.
                if baseline != after:
                    stored = before_map.get((app_id, decision_id))
                    from_outcome = stored if (stored and stored != after) else baseline
                    app_flipped = True
                    reason = self._generate_flip_reason(
                        state, decision_id, baseline, after, scenario, vals
                    )
                    flips.append(
                        SimulationFlip(
                            application_id=str(app_id),
                            borrower_name=self._borrower_name(state),
                            decision_id=decision_id,
                            from_outcome=from_outcome,
                            to_outcome=after,
                            reason=reason,
                            loan_amount=loan_amt,
                        )
                    )
                    per_decision[decision_id].append(
                        {**vals, "to": after, "loan": loan_amt, "tighter": _SEVERITY[after] > _SEVERITY[baseline]}
                    )

            if ok_before:
                approved_before += 1
                vol_before += loan_amt
            if ok_after:
                approved_after += 1
                vol_after += loan_amt
            if ok_before and not ok_after:
                new_blocks += 1
            if not ok_before and ok_after:
                new_allows += 1
            if app_flipped:
                affected_apps += 1

        impact = self._impact(
            total, approved_before, approved_after, vol_before, vol_after,
            new_blocks, new_allows, affected_apps,
        )
        agent_insights = self._agent_insights(per_decision, scenario, boundaries_after)

        return SimulationResult(
            simulation_id=scenario.scenario_id,  # tie the run to its scenario
            scenario=scenario,
            status="completed",
            total_apps=total,
            affected_apps=affected_apps,
            flipped=flips,
            impact=impact,
            agent_insights=agent_insights,
            started_at=started,
            completed_at=datetime.now(timezone.utc),
        )

    # ── DB reads ─────────────────────────────────────────────────────

    async def _get_entity_states(self, tenant_id: str) -> list[dict]:
        async with self._acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT application_id, loan_amount, appraised_value, purchase_price,
                       interest_rate, monthly_obligations, combined_monthly_income,
                       qualifying_monthly, piti_monthly, mi_monthly, mid_credit_score,
                       ltv, dti_back, borrower
                FROM entity_states
                WHERE tenant_id = $1
                """,
                tenant_id,
            )
        return [dict(r) for r in rows]

    async def _snapshot_before(
        self, tenant_id: str, affected: list[str]
    ) -> dict[tuple, str]:
        """The current stored outcome for each (app, affected decision) —
        the live 'before' the simulation is measured against."""
        if not affected:
            return {}
        async with self._acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT application_id, decision_id, outcome
                FROM decision_outputs dout
                WHERE tenant_id = $1 AND decision_id = ANY($2)
                  AND version = (
                      SELECT MAX(version) FROM decision_outputs d2
                      WHERE d2.application_id = dout.application_id
                        AND d2.decision_id = dout.decision_id
                  )
                """,
                tenant_id,
                affected,
            )
        return {(r["application_id"], r["decision_id"]): r["outcome"] for r in rows}

    # ── Scenario interpretation ──────────────────────────────────────

    @staticmethod
    def _affected_decisions(scenario: SimulationScenario) -> list[str]:
        ov = scenario.overrides or {}
        if "_stress" in ov:
            stress = ov["_stress"] or {}
            decs = []
            if "rate_delta" in stress:
                decs.append("dti_calculation")
            if "price_delta_pct" in stress:
                decs.append("ltv_assessment")
            return decs
        return [k for k in ov if k in DEFAULT_BOUNDARIES]

    @staticmethod
    def _scenario_boundaries(scenario: SimulationScenario) -> dict[str, dict]:
        """Per-decision boundaries AFTER the scenario (policy/regulatory
        move thresholds; stress leaves them at default and moves data)."""
        out: dict[str, dict] = {}
        for decision_id, params in (scenario.overrides or {}).items():
            if decision_id in DEFAULT_BOUNDARIES and isinstance(params, dict):
                out[decision_id] = {**DEFAULT_BOUNDARIES[decision_id], **params}
        return out

    # ── Apply data shocks (stress) ───────────────────────────────────

    def _apply_overrides(self, entity_state: dict, scenario: SimulationScenario) -> dict:
        """Return a modified copy of the loan for STRESS scenarios:
        recompute PITI/DTI from a rate shock and LTV from a price move.
        Policy/regulatory scenarios leave the data untouched."""
        stress = (scenario.overrides or {}).get("_stress")
        if not isinstance(stress, dict):
            return entity_state
        s = dict(entity_state)
        n = self._loan_numbers(entity_state)

        rate_delta = _f(stress.get("rate_delta"))
        if rate_delta is not None and n["loan_amount"] and n["interest_rate"] is not None:
            new_rate = n["interest_rate"] + rate_delta
            base_pi = _amortized_pi(n["loan_amount"], n["interest_rate"])
            new_pi = _amortized_pi(n["loan_amount"], new_rate)
            escrow = max(0.0, (n["piti"] or base_pi) - base_pi)  # hold taxes/ins constant
            new_piti = new_pi + escrow
            base_piti = n["piti"] if n["piti"] else base_pi
            s["interest_rate"] = new_rate
            s["_piti"] = new_piti
            obl = n["obligations"] or 0.0
            if n["income"]:
                s["_dti_pct"] = (new_piti + obl) / n["income"] * 100.0
            elif n["dti_pct"] and (base_piti + obl) > 0:
                # Scale the canonical baseline DTI by the housing-payment
                # change — robust when income isn't on file.
                s["_dti_pct"] = n["dti_pct"] * (new_piti + obl) / (base_piti + obl)

        price_delta = _f(stress.get("price_delta_pct"))
        if price_delta is not None:
            if n["appraised"] and n["loan_amount"]:
                new_appraised = n["appraised"] * (1 + price_delta / 100.0)
                s["appraised_value"] = new_appraised
                if new_appraised > 0:
                    s["_ltv_pct"] = n["loan_amount"] / new_appraised * 100.0
            elif n["ltv_pct"]:
                # LTV scales inversely with the price move.
                s["_ltv_pct"] = n["ltv_pct"] / (1 + price_delta / 100.0)
        return s

    # ── Re-run one agent's boundary logic ────────────────────────────

    def _evaluate_with_agent(
        self, agent_id: str, entity_state: dict, modified_boundaries: dict
    ) -> tuple[str, dict]:
        """Re-run one persona agent's deterministic boundary logic on one
        loan with the given boundaries. Returns (outcome, computed values
        used for the flip reasoning)."""
        n = self._loan_numbers(entity_state)
        b = modified_boundaries or {}

        if agent_id == "dti_calculation":
            dti = entity_state.get("_dti_pct")
            dti = dti if dti is not None else n["dti_pct"]
            cap = float(b.get("back_dti_max", 43))
            vals = {
                "metric": "dti", "dti": dti, "cap": cap,
                "income": n["income"], "obligations": n["obligations"],
                "piti": entity_state.get("_piti") or n["piti"], "loan": n["loan_amount"],
            }
            if dti is None:
                return "escalate", vals
            outcome = "allow" if dti <= cap else ("recommend" if dti <= 50 else "block")
            return outcome, vals

        if agent_id == "credit_assessment":
            score = n["score"]
            floor = float(b.get("min_score", 620))
            vals = {"metric": "score", "score": score, "floor": floor}
            if score is None:
                return "escalate", vals
            outcome = "block" if score < floor else ("allow" if score >= 680 else "recommend")
            return outcome, vals

        if agent_id == "ltv_assessment":
            ltv = entity_state.get("_ltv_pct")
            ltv = ltv if ltv is not None else n["ltv_pct"]
            cap = float(b.get("max_ltv", 97))
            vals = {
                "metric": "ltv", "ltv": ltv, "cap": cap,
                "appraised": _f(entity_state.get("appraised_value")) or n["appraised"],
                "loan": n["loan_amount"],
            }
            if ltv is None:
                return "escalate", vals
            outcome = "block" if ltv > cap else ("recommend" if ltv > 80 else "allow")
            return outcome, vals

        if agent_id == "product_eligibility":
            loan = n["loan_amount"]
            limit = float(b.get("conforming_limit", 766550))
            vals = {"metric": "product", "loan": loan, "limit": limit}
            if loan is None:
                return "escalate", vals
            within = loan <= limit
            vals["within"] = within
            return ("allow" if within else "escalate"), vals

        return "recommend", {"metric": agent_id}

    # ── Flip reasoning (numbers-driven, plain English) ───────────────

    def _generate_flip_reason(
        self, app: dict, decision_id: str, old_outcome: str,
        new_outcome: str, scenario: SimulationScenario, vals: dict,
    ) -> str:
        tighter = _SEVERITY[new_outcome] > _SEVERITY[old_outcome]

        if decision_id == "dti_calculation":
            dti = vals.get("dti") or 0
            cap = vals.get("cap")
            income = vals.get("income") or 0
            piti = vals.get("piti") or 0
            oblig = vals.get("obligations") or 0
            if tighter:
                msg = (
                    f"Back-end DTI of {dti:.1f}% now exceeds the tightened {cap:.0f}% threshold "
                    f"(it qualified under the prior limit). At monthly income ${income:,.0f}, "
                    f"PITI ${piti:,.0f} plus obligations ${oblig:,.0f} yields {dti:.1f}%."
                )
                if cap and dti:
                    need_income = (piti + oblig) / (cap / 100.0) if income else 0
                    need_loan = (vals.get("loan") or 0) * (cap / dti)  # DTI scales with payment ~ loan
                    extras = []
                    if need_income:
                        extras.append(f"income would need to reach ${need_income:,.0f}")
                    if need_loan > 0:
                        extras.append(("or " if extras else "") + f"the loan reduce toward ${need_loan:,.0f}")
                    if extras:
                        msg += " To qualify, " + " ".join(extras) + "."
                return msg
            return (
                f"Back-end DTI of {dti:.1f}% now qualifies under the relaxed {cap:.0f}% threshold "
                f"(it was over the prior limit). Monthly income ${income:,.0f}, PITI ${piti:,.0f}, "
                f"obligations ${oblig:,.0f}."
            )

        if decision_id == "credit_assessment":
            score = vals.get("score")
            floor = vals.get("floor")
            if tighter:
                return (
                    f"Mid credit score {int(score)} now falls below the raised {int(floor)} floor "
                    f"(it cleared the prior 620 floor). This loan needs a stronger credit profile "
                    f"or a different program to qualify."
                )
            return (
                f"Mid credit score {int(score)} now clears the {int(floor)} floor under the relaxed "
                f"policy (it was below the prior minimum)."
            )

        if decision_id == "ltv_assessment":
            ltv = vals.get("ltv") or 0
            cap = vals.get("cap")
            loan = vals.get("loan") or 0
            # Extra down payment to bring LTV to a target — derived from the
            # LTV itself (loan × (ltv−target)/ltv), not an inconsistent value.
            def down_to(target: float) -> float:
                return loan * max(0.0, ltv - target) / ltv if ltv else 0.0
            if new_outcome == "block":
                return (
                    f"LTV of {ltv:.1f}% now exceeds the {cap:.0f}% cap (it qualified before). "
                    f"The borrower needs about ${down_to(cap):,.0f} more down payment to reach "
                    f"{cap:.0f}%."
                )
            if new_outcome == "recommend":
                return (
                    f"LTV of {ltv:.1f}% now crosses the 80% line, so mortgage insurance is "
                    f"required (about ${down_to(80):,.0f} more down would avoid MI). It "
                    f"previously sat at or below 80%."
                )
            return (
                f"LTV of {ltv:.1f}% now sits within limits under the relaxed scenario."
            )

        if decision_id == "product_eligibility":
            loan = vals.get("loan") or 0
            limit = vals.get("limit") or 0
            within = vals.get("within")
            if within:
                return (
                    f"Loan ${loan:,.0f} now falls within the ${limit:,.0f} conforming limit and "
                    f"reclassifies jumbo → conforming, opening agency programs."
                )
            return (
                f"Loan ${loan:,.0f} now exceeds the ${limit:,.0f} conforming limit and reclassifies "
                f"conforming → jumbo, requiring a jumbo program / manual exception."
            )

        return f"{decision_id} flipped {old_outcome} → {new_outcome} under '{scenario.name}'."

    # ── Aggregation ──────────────────────────────────────────────────

    @staticmethod
    def _impact(
        total: int, approved_before: int, approved_after: int,
        vol_before: float, vol_after: float, new_blocks: int,
        new_allows: int, affected_apps: int,
    ) -> dict:
        rate_before = (approved_before / total) if total else 0.0
        rate_after = (approved_after / total) if total else 0.0
        return {
            "volume_before": round(vol_before, 2),
            "volume_after": round(vol_after, 2),
            "volume_change": round(vol_after - vol_before, 2),
            "approval_rate_before": round(rate_before, 4),
            "approval_rate_after": round(rate_after, 4),
            "approval_rate_change": round(rate_after - rate_before, 4),
            "affected_count": affected_apps,
            "new_blocks": new_blocks,
            "new_allows": new_allows,
        }

    def _agent_insights(
        self, per_decision: dict[str, list[dict]],
        scenario: SimulationScenario, boundaries_after: dict,
    ) -> list[str]:
        out: list[str] = []
        for decision_id, items in per_decision.items():
            n = len(items)
            if not n:
                continue
            if decision_id == "dti_calculation":
                cap = boundaries_after.get("dti_calculation", {}).get("back_dti_max", 43)
                incomes = [i["income"] for i in items if i.get("income")]
                obligs = [i["obligations"] for i in items if i.get("obligations")]
                med_inc = f"${statistics.median(incomes):,.0f}" if incomes else "—"
                med_obl = f"${statistics.median(obligs):,.0f}" if obligs else "—"
                n_tight = sum(1 for i in items if i.get("tighter"))
                n_loose = n - n_tight
                parts = []
                if n_tight:
                    parts.append(f"{n_tight} now fall short that previously qualified")
                if n_loose:
                    parts.append(f"{n_loose} now qualify that previously fell short")
                out.append(
                    f"DTI agent: at the {cap:.0f}% threshold, {n} loans change outcome — "
                    + "; ".join(parts) + ". "
                    f"Median affected borrower: income {med_inc}, obligations {med_obl}/mo."
                )
            elif decision_id == "credit_assessment":
                floor = boundaries_after.get("credit_assessment", {}).get("min_score", 620)
                scores = [i["score"] for i in items if i.get("score") is not None]
                lo = f"{min(scores):.0f}" if scores else "—"
                hi = f"{max(scores):.0f}" if scores else "—"
                out.append(
                    f"Credit agent: raising the floor to {int(floor)} drops {n} near-prime loans "
                    f"(affected score range {lo}–{hi}). These borrowers were qualifying on the "
                    f"prior 620 floor."
                )
            elif decision_id == "ltv_assessment":
                cap = boundaries_after.get("ltv_assessment", {}).get("max_ltv", 97)
                ltvs = [i["ltv"] for i in items if i.get("ltv") is not None]
                med = f"{statistics.median(ltvs):.1f}%" if ltvs else "—"
                out.append(
                    f"Collateral agent: {n} loans move at the {cap:.0f}% LTV line "
                    f"(median affected LTV {med}). High-LTV borrowers need more down payment."
                )
            elif decision_id == "product_eligibility":
                limit = boundaries_after.get("product_eligibility", {}).get("conforming_limit", 766550)
                to_conf = sum(1 for i in items if i.get("within"))
                to_jumbo = n - to_conf
                out.append(
                    f"Product agent: at a ${limit:,.0f} conforming limit, {n} loans reclassify — "
                    f"{to_conf} jumbo → conforming, {to_jumbo} conforming → jumbo."
                )
        if not out:
            out.append("No loans changed outcome under this scenario.")
        return out

    # ── Helpers ──────────────────────────────────────────────────────

    def _loan_numbers(self, state: dict) -> dict:
        loan = _f(state.get("loan_amount"))
        appraised = _f(state.get("appraised_value")) or _f(state.get("purchase_price"))
        rate = _f(state.get("interest_rate"))
        obligations = _f(state.get("monthly_obligations")) or 0.0
        income = _f(state.get("combined_monthly_income")) or _f(state.get("qualifying_monthly"))
        piti = _f(state.get("piti_monthly"))
        score = _f(state.get("mid_credit_score"))

        # Back-end DTI: prefer the stored canonical value (already a
        # percent, e.g. 36.07), fall back to computing it from PITI +
        # obligations / income only when the column is absent.
        dti_pct = None
        stored_dti = _f(state.get("dti_back"))
        if stored_dti and stored_dti > 0:
            dti_pct = stored_dti * 100 if stored_dti <= 1.5 else stored_dti
        elif income:
            base_piti = piti
            if base_piti is None and loan and rate is not None:
                base_piti = _amortized_pi(loan, rate)
            if base_piti is not None:
                dti_pct = (base_piti + obligations) / income * 100.0

        # Derive monthly income when the column is null but we know the
        # DTI and the housing + obligation total — keeps stress math
        # (rate shock → new DTI) and the flip reasoning grounded.
        if income is None and dti_pct and piti is not None:
            denom = dti_pct / 100.0
            if denom > 0:
                income = (piti + obligations) / denom

        ltv_pct = None
        stored_ltv = _f(state.get("ltv"))
        if stored_ltv and stored_ltv > 0:
            ltv_pct = stored_ltv * 100 if stored_ltv <= 1.5 else stored_ltv
        elif loan and appraised:
            ltv_pct = loan / appraised * 100.0

        return {
            "loan_amount": loan, "appraised": appraised, "interest_rate": rate,
            "obligations": obligations, "income": income, "piti": piti,
            "score": score, "dti_pct": dti_pct, "ltv_pct": ltv_pct,
        }

    @staticmethod
    def _borrower_name(state: dict) -> str:
        borrower = state.get("borrower")
        if isinstance(borrower, (bytes, bytearray)):
            borrower = borrower.decode("utf-8", "replace")
        if isinstance(borrower, str):
            import json
            try:
                borrower = json.loads(borrower)
            except (ValueError, json.JSONDecodeError):
                borrower = None
        if isinstance(borrower, dict):
            ident = borrower.get("identity")
            if isinstance(ident, dict):
                for k in ("full_name", "name", "legal_name"):
                    if ident.get(k):
                        return str(ident[k])
        return str(state.get("application_id") or "the borrower")
