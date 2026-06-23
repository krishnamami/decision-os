from __future__ import annotations

import json
from typing import Optional

from core.context_store import ContextBundle
from core.normalizer.models import DecisionOutcome
from core.policy_engine import PolicyDecision
from core.trace import SignalDirection

from .base import LendingPersona, OfflineReasoning, latest_object, make_signal


def _as_list(val):
    """Asset context arrays (asset_accounts / unsourced_deposits) arrive as a
    JSON list or — depending on the view codec — a JSON string. Normalise to a
    Python list."""
    if val is None:
        return []
    if isinstance(val, str):
        try:
            val = json.loads(val)
        except (ValueError, TypeError):
            return []
    return list(val) if isinstance(val, (list, tuple)) else []


class AssetVerificationAgent(LendingPersona):
    """asset_verification — asset documentation quality.

    Reads the AssetProfile projected from ``vw_asset_verification_context``
    (borrower.assets) and decides whether the asset picture is clear,
    needs sourcing (escalate), or is a hard stop (block).

    Outcome model (deliberately NOT a percent-of-assets auto-block):
      BLOCK     reserves below the agency floor (default 2 months PITI) —
                a clear, defensible hard stop.
      ESCALATE  a large deposit (> $5K) or gift funds that aren't yet
                documented — UW must source the funds before closing.
                A large *unsourced* deposit is an escalate, not a denial,
                even when it is most of the borrower's liquid assets
                (Fannie Mae B3-4.3-04 wants it sourced, not refused).
      ALLOW     assets verified and nothing needs sourcing.

    SC15 (Maria Santos): $47K undocumented deposit, 3.2 months reserves →
    needs_sourcing=true, reserves_insufficient=false → ESCALATE.
    """

    DEFAULT_AGENT_ID = "asset_verification_agent_v1"

    LARGE_DEPOSIT_THRESHOLD = 5000.0
    MIN_RESERVES_MONTHS = 2.0

    def __init__(
        self,
        *,
        agent_id: str = DEFAULT_AGENT_ID,
        use_anthropic: bool = False,
        **kw,
    ):
        super().__init__(
            agent_id=agent_id,
            persona="asset_verification_agent",
            decision_id="asset_verification",
            use_anthropic=use_anthropic,
            **kw,
        )

    def _compute_offline(
        self, bundle: ContextBundle, policy: Optional[PolicyDecision]
    ) -> OfflineReasoning:
        assets = latest_object(bundle, "AssetProfile") or {}

        large_deposit = float(assets.get("large_deposit_amount") or 0.0)
        deposit_documented = bool(assets.get("large_deposit_documented"))
        liquid = float(
            assets.get("liquid_assets_total")
            or assets.get("total_liquid_assets")
            or 0.0
        )
        reserves = assets.get("reserves_months")
        reserves = float(reserves) if reserves is not None else None
        gift_funds = float(assets.get("gift_funds") or 0.0)
        gift_documented = bool(assets.get("gift_funds_documented"))
        assets_verified = bool(assets.get("assets_verified"))

        # ── Boundary-facing flags (the policy engine reads these) ────────
        large_deposit_unsourced = large_deposit > self.LARGE_DEPOSIT_THRESHOLD and not deposit_documented
        gift_funds_unsourced = gift_funds > 0 and not gift_documented
        needs_sourcing = large_deposit_unsourced or gift_funds_unsourced
        reserves_insufficient = (
            reserves is not None and 0.0 < reserves < self.MIN_RESERVES_MONTHS
        )
        # A large undocumented deposit relative to liquid assets is a *signal*
        # for the reviewer, not an auto-block.
        deposit_pct_of_liquid = (large_deposit / liquid) if liquid > 0 else 0.0
        assets_clear = assets_verified and not needs_sourcing and not reserves_insufficient

        signals = [
            make_signal("large_deposit_amount", round(large_deposit, 2)),
            make_signal(
                "large_deposit_unsourced",
                large_deposit_unsourced,
                direction=(
                    SignalDirection.CONTRADICTS
                    if large_deposit_unsourced
                    else SignalDirection.NEUTRAL
                ),
                weight=2.0,
            ),
            make_signal("reserves_months", reserves if reserves is not None else "n/a"),
            make_signal(
                "deposit_pct_of_liquid_assets",
                round(deposit_pct_of_liquid, 3),
                notes="informational — large unsourced deposits are sourced, not denied",
            ),
        ]
        if gift_funds_unsourced:
            signals.append(
                make_signal("gift_funds_unsourced", True, direction=SignalDirection.CONTRADICTS)
            )

        if reserves_insufficient:
            outcome = DecisionOutcome.BLOCK
            confidence = 0.9
            conclusion = (
                f"reserves {reserves:.1f}mo < {self.MIN_RESERVES_MONTHS:.0f}mo floor → block"
            )
            summary = f"Reserves {reserves:.1f} months below minimum — additional assets required."
        elif needs_sourcing:
            outcome = DecisionOutcome.ESCALATE
            confidence = 0.8
            parts = []
            if large_deposit_unsourced:
                parts.append(f"deposit ${large_deposit:,.0f} unsourced")
            if gift_funds_unsourced:
                parts.append(f"gift ${gift_funds:,.0f} without letter")
            conclusion = " + ".join(parts) + " → escalate for sourcing"
            summary = (
                "Large/undocumented funds require sourcing before closing "
                "(Fannie Mae B3-4.3-04 / B3-4.3-09)."
            )
        elif assets_verified:
            outcome = DecisionOutcome.ALLOW
            confidence = 0.92
            conclusion = "assets verified, nothing to source → allow"
            summary = "Assets verified. No documentation issues found."
        else:
            outcome = DecisionOutcome.ALLOW
            confidence = 0.6
            conclusion = "no asset flags → allow"
            summary = "No asset issues identified."

        # ── AV-D: AssetResolver + DepositAnalyzer over the entity tables ──
        # Engages only when the AV-A tables hold accounts for this loan;
        # otherwise the view returns empty arrays and the outcome is
        # unchanged. These branches can only escalate to BLOCK / ESCALATE,
        # never relax an existing outcome.
        asset_accounts = _as_list(assets.get("asset_accounts"))
        unsourced_deposits = _as_list(assets.get("unsourced_deposits"))
        asset_resolver_status = None
        total_qualifying_assets = None
        funds_sufficient = None
        asset_conditions: list[dict] = []
        # RA-4A: catalogue-resolved asset rules injected via the bundle (the
        # runner loaded them through rule_loader; resolvers stay sync/DB-less).
        asset_rules_obj = latest_object(bundle, "asset_rules") or {}
        asset_rule_values = asset_rules_obj.get("values")
        asset_rule_trace = asset_rules_obj.get("trace")

        if asset_accounts:
            from core.assets.asset_resolver import AssetResolver
            from core.assets.deposit_analyzer import DepositAnalyzer

            # Funds-to-close inputs from the view (AV-E). down_payment uses
            # purchase_price - loan_amount; while purchase_price is unseeded
            # it resolves to 0, so funds_needed reflects closing + prepaids +
            # reserves until the purchase price lands.
            loan_amount = float(assets.get("loan_amount") or 0)
            piti_monthly = float(assets.get("piti_monthly") or 0)
            down_payment = float(assets.get("down_payment_computed") or 0)
            qualifying_monthly = float(assets.get("qualifying_monthly") or 0)

            asset_result = AssetResolver(asset_rule_values).resolve_all(
                asset_accounts,
                qualifying_monthly=qualifying_monthly,
                piti_monthly=piti_monthly,
                loan_amount=loan_amount,
                down_payment=down_payment,
            )
            dep_result = DepositAnalyzer(asset_rule_values).analyze_deposits(
                unsourced_deposits,
                qualifying_monthly=qualifying_monthly,
            )

            asset_resolver_status = asset_result["overall_status"]
            total_qualifying_assets = asset_result["total_qualifying"]
            funds_sufficient = asset_result["funds_sufficient"]
            asset_conditions = (
                asset_result["all_conditions"] + dep_result["conditions"]
            )

            if asset_result["overall_status"] == "block":
                outcome = DecisionOutcome.BLOCK
                summary += " Insufficient assets for closing."
            elif (
                asset_result["overall_status"] == "escalate"
                or dep_result["requires_action"]
            ) and outcome is DecisionOutcome.ALLOW:
                outcome = DecisionOutcome.ESCALATE
                summary += (
                    f" Asset conditions: {len(dep_result['conditions'])} "
                    "deposit(s) need sourcing."
                )

        # ── RA-PERSONA-A: evidence quality (advisory, OUTCOME-NEUTRAL) ────
        # Read the evidence facts the enricher placed on the bundle. Raises
        # QUALITY signals + provenance but does NOT move the reserves/sourcing-
        # driven outcome above — so 16/16 holds. Threshold is the catalogue
        # documentation-confidence floor (Fannie B3-3.1-01, governed_by=agency)
        # attached to every bundle; the constant is a catalogue-unreachable
        # safety net only. Graceful: no evidence object → no signals.
        ev = latest_object(bundle, "evidence") or {}
        evidence_populated = bool(ev.get("evidence_populated"))
        ev_asset_value = ev.get("ev_asset_value")
        ev_asset_conf = ev.get("ev_asset_confidence")
        ev_asset_conflicts = bool(ev.get("ev_asset_conflicts"))
        conf_min = ev.get("income_confidence_min")
        if conf_min is None:
            conf_min = 0.75
        evidence_threshold_trace = ev.get("income_confidence_threshold_trace")
        if evidence_populated and ev_asset_conflicts:
            signals.append(make_signal(
                "ASSET_EVIDENCE_CONFLICT", True,
                direction=SignalDirection.CONTRADICTS, source="evidence",
                notes=("Verified-assets evidence conflicts across statements. "
                       "UW review of the asset documentation required."),
            ))
        if (evidence_populated and ev_asset_conf is not None
                and ev_asset_conf < conf_min):
            signals.append(make_signal(
                "ASSET_LOW_CONFIDENCE", round(float(ev_asset_conf), 3),
                direction=SignalDirection.CONTRADICTS, source="evidence",
                notes=(f"Asset evidence confidence {ev_asset_conf:.0%} below "
                       f"{conf_min:.0%} (Fannie B3-3.1-01). Re-source assets."),
            ))

        return OfflineReasoning(
            output_payload={
                "large_deposit_amount": round(large_deposit, 2),
                "large_deposit_documented": deposit_documented,
                # RA-PERSONA-A: evidence-quality provenance (advisory).
                "evidence_populated": evidence_populated,
                "asset_evidence_value": ev_asset_value,
                "asset_evidence_confidence": (
                    round(float(ev_asset_conf), 3)
                    if ev_asset_conf is not None else None
                ),
                "asset_evidence_conflicts": ev_asset_conflicts,
                "asset_evidence_governed_by": (
                    (evidence_threshold_trace or {}).get("governed_by")
                ),
                "evidence_threshold_trace": evidence_threshold_trace,
                "large_deposit_unsourced": large_deposit_unsourced,
                "gift_funds": round(gift_funds, 2),
                "gift_funds_unsourced": gift_funds_unsourced,
                "needs_sourcing": needs_sourcing,
                "reserves_months": reserves,
                "reserves_insufficient": reserves_insufficient,
                "deposit_pct_of_liquid_assets": round(deposit_pct_of_liquid, 3),
                "assets_verified": assets_verified,
                "assets_clear": assets_clear,
                # AV-D additions
                "asset_resolver_status": asset_resolver_status,
                "total_qualifying_assets": total_qualifying_assets,
                "funds_sufficient": funds_sufficient,
                "asset_conditions": asset_conditions,
                # RA-4A: catalogue provenance for every asset rule applied
                # (federal/agency/overlay layers per rule) for the workbench.
                "asset_rule_trace": asset_rule_trace,
            },
            proposed_outcome=outcome,
            confidence=confidence,
            signals=signals,
            contradictions=[],
            hypothesis=(
                "Assets are clear when verified with adequate reserves and no "
                "large unsourced deposits or undocumented gift funds."
            ),
            conclusion=conclusion,
            confidence_basis=(
                "High confidence on the reserves floor (deterministic). Sourcing "
                "escalations are confident routing decisions, not denials — the "
                "deposit-to-liquid ratio is informational only."
            ),
            summary=summary,
        )


__all__ = ["AssetVerificationAgent"]
