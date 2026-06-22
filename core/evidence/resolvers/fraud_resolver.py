"""
Fraud Fact Resolver — RA-3E

Gives fraud escalations evidence backing in the fact graph. Wraps the outputs
of IncomeMismatchDetector / UndisclosedDebtDetector (persisted in the
fraud_signals table) and resolves them to a single fact_type='fraud_indicator'
FactNode per application — with a confidence, conflicts_found, and a
resolution_method that cites the agency rule that triggered the flag.

Severity cutoffs (income variance %) come from agency_guidelines via
rule_loader (Fannie B3-3.1-01 / QC) — not hardcoded. The confidence SCALE
(0.95 / 0.75 / 0.50 / 0.80) is the evidence system's internal quality score,
consistent with the other fact resolvers' in-code confidence scales.

No fraud signals → no fact_node emitted (clean loans stay clean).

Follows the same shape as income_resolver.py: read inputs, build the fact,
persist via EvidenceStore.save_fact_node (supersede-then-insert).
"""
from __future__ import annotations

from typing import Optional

from ..models import FactNode
from ..store import EvidenceStore

# Detector signal_types this resolver recognises.
_INCOME_SIGNALS = ("income_mismatch", "income_inflation")
_DEBT_SIGNALS = ("undisclosed_debt",)


class FraudFactResolver:
    def __init__(self, conn):
        self.conn = conn
        self.store = EvidenceStore(conn)

    async def resolve(self, application_id: str, tenant_id: str) -> dict:
        """Read this application's fraud_signals and, if any, resolve a
        fraud_indicator FactNode. Idempotent via save_fact_node's
        supersede-then-insert. Returns {"fraud_indicator": FactNode} or {}."""
        signals = await self.conn.fetch(
            """
            SELECT signal_type, severity, variance_pct, description,
                   auto_block, condition_code
            FROM fraud_signals
            WHERE application_id = $1 AND tenant_id = $2
              AND resolved = false
              AND signal_type = ANY($3)
            ORDER BY variance_pct DESC NULLS LAST
            """,
            application_id, tenant_id,
            list(_INCOME_SIGNALS + _DEBT_SIGNALS),
        )
        if not signals:
            return {}

        # Severity cutoffs from the catalogue (Fannie B3-3.1-01 / QC).
        med, high, crit, trace = await self._thresholds(tenant_id)

        max_variance = 0.0
        confidence = 0.0
        notes: list[str] = []
        triggered: list[str] = []
        for s in signals:
            stype = s["signal_type"]
            var = float(s["variance_pct"] or 0.0)
            if stype in _INCOME_SIGNALS:
                if var >= crit:
                    conf, band = 0.95, f"critical {crit:.0f}%"
                elif var >= high:
                    conf, band = 0.75, f"high {high:.0f}%"
                elif var >= med:
                    conf, band = 0.50, f"medium {med:.0f}%"
                else:
                    continue  # below medium — not material
                max_variance = max(max_variance, var)
                confidence = max(confidence, conf)
                triggered.append(
                    f"{stype} {var:.0f}% >= {band} "
                    f"(Fannie B3-3.1-01 QC)"
                )
                notes.append(s["description"] or stype)
            elif stype in _DEBT_SIGNALS:
                confidence = max(confidence, 0.80)
                triggered.append(
                    f"{stype} (Fannie B3-6 / QC)"
                )
                notes.append(s["description"] or stype)

        if not triggered:
            return {}

        fact = FactNode(
            application_id=application_id,
            tenant_id=tenant_id,
            fact_type="fraud_indicator",
            fact_value=round(max_variance, 1) if max_variance else None,
            fact_text="; ".join(t.split(" (")[0] for t in triggered),
            confidence=confidence,
            resolution_method=" | ".join(triggered),
            evidence_ids=[],
            conflicts_found=True,
            conflict_ids=[],
            resolution_notes="\n".join(notes),
            agency_treatment={
                "thresholds": {
                    "income_mismatch_medium_pct": med,
                    "income_mismatch_high_pct": high,
                    "income_mismatch_critical_pct": crit,
                },
                "threshold_trace": trace,
                "signals": [
                    {
                        "signal_type": s["signal_type"],
                        "severity": s["severity"],
                        "variance_pct": float(s["variance_pct"] or 0.0),
                        "auto_block": bool(s["auto_block"]),
                    }
                    for s in signals
                ],
            },
        )
        await self.store.save_fact_node(fact)
        return {"fraud_indicator": fact}

    async def _thresholds(self, tenant_id: str):
        """Resolve the 3 income-mismatch severity cutoffs from the catalogue
        via rule_loader. Returns (medium, high, critical, trace)."""
        from core.catalogue.rule_loader import get_rule

        async def val(name: str, default: float) -> tuple[float, dict]:
            r = await get_rule(
                self.conn, name, tenant_id, agency="fannie", is_ceiling=True
            )
            applied = r.get("applied")
            return (
                float(applied) if applied is not None else default,
                {
                    "rule": name,
                    "applied": applied,
                    "governed_by": r.get("governed_by"),
                    "citation": (r.get("layers", {}).get("agency") or {}).get(
                        "citation"
                    ),
                },
            )

        med, t_med = await val("income_mismatch_medium_pct", 10.0)
        high, t_high = await val("income_mismatch_high_pct", 25.0)
        crit, t_crit = await val("income_mismatch_critical_pct", 50.0)
        return med, high, crit, [t_med, t_high, t_crit]


__all__ = ["FraudFactResolver"]
