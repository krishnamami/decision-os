"""ThresholdResolver — resolve the effective value for a governed boundary
threshold from three layers, highest priority first:

  1. tenant_rules (active lender overlay) — what the lender set in Policy Studio
  2. agency_guidelines — the agency standard (Fannie / FHA / …)
  3. decisions.yaml default — the value baked into the boundary expression

So when a lender changes their DTI cap from 43% to 40%, the next evaluation
uses 40% — decisions.yaml thresholds become dynamic.

Floor enforcement: a tenant value below the agency/regulatory floor is rejected
and the floor is used instead (e.g. credit floor can't drop below 620 Fannie /
580 FHA).

Values in tenant_rules and agency_guidelines are stored as PERCENTS (dti 43,
credit 620, ltv 97); the evaluator scales them to the boundary's units.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional

# Condition keys are interpolated into a jsonb path in get_waiver(); restrict
# them to safe identifiers so a caller-supplied key can't inject SQL.
_IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _jsonb_text(val: Any) -> str:
    """The text a jsonb ``->>`` extraction yields for a Python value
    (booleans render as 'true'/'false', everything else via str())."""
    if isinstance(val, bool):
        return "true" if val else "false"
    return str(val)


@dataclass
class ThresholdResolution:
    value: Any
    source: str  # tenant_rules | agency_guidelines | agency_floor_enforced | system_default
    citation: Optional[str] = None
    rule_version_id: Optional[str] = None
    governed_by: Optional[str] = None
    floor_enforced: bool = False
    floor_value: Any = None
    note: Optional[str] = None


# governed_by.threshold_field → (agency, category, guideline_name)
FIELD_TO_AGENCY_GUIDELINE = {
    "dti.back_max": ("fannie", "dti", "DU Maximum DTI"),
    "dti.front_max": ("fannie", "dti", "Manual UW Maximum DTI"),
    "credit.min_score": ("fannie", "credit", "Minimum Credit Score"),
    "ltv.max": ("fannie", "ltv", "Primary Residence 1-Unit Max LTV"),
    "ltv.no_mi_threshold": ("fannie", "ltv", "Primary Residence 1-Unit Max LTV"),
    "reserves.investment": ("fannie", "reserves", "Investment Property Reserves"),
}

# Hard floors a tenant overlay may not go below.
AGENCY_FLOORS = {
    "credit.min_score": 620,   # Fannie minimum
    "reserves.primary": 2,     # Fannie minimum reserves
    "reserves.investment": 6,
}
FHA_FLOORS = {"credit.min_score": 580}  # FHA minimum with 3.5% down


class ThresholdResolver:
    def __init__(
        self,
        conn,
        tenant_id: str,
        programs: Optional[list[str]] = None,
        rule_version_id: Optional[Any] = None,
    ):
        self._conn = conn
        self._tenant_id = tenant_id
        self._programs = [p.lower() for p in (programs or ["conventional"])]
        # When set, resolve() reads tenant overlay rules from THIS version
        # rather than the tenant's current active version. The cron path
        # passes the loan's applicable version (pinned at rate lock →
        # pipeline-cutoff protection → current) so a rate-locked loan is
        # always scored under the rules in force when it locked.
        self._rule_version_id = rule_version_id
        # Caches keyed so one instance can never serve another tenant's rules.
        self._tenant_rules_cache: dict = {}
        self._rules_cache: dict = {}
        self._agency_cache: Optional[dict] = None

    async def resolve(
        self,
        threshold_field: str,
        default_value: Any,
        rule_version_id: Optional[Any] = None,
    ) -> ThresholdResolution:
        parts = threshold_field.split(".")
        if len(parts) != 2:
            return ThresholdResolution(value=default_value, source="system_default",
                                       note=f"Unparseable field path: {threshold_field}")
        category, field = parts
        rid = rule_version_id if rule_version_id is not None else self._rule_version_id
        tenant_rules = await self._get_tenant_rules(rid)
        agency = await self._get_agency_guidelines()

        # Layer 1 — tenant overlay
        tenant_value = None
        if tenant_rules and isinstance(tenant_rules.get(category), dict):
            tenant_value = tenant_rules[category].get(field)
        if tenant_value is not None:
            floor = self._floor(threshold_field)
            if floor is not None and _num(tenant_value) is not None and _num(tenant_value) < floor:
                return ThresholdResolution(
                    value=floor, source="agency_floor_enforced", floor_enforced=True,
                    floor_value=floor,
                    note=f"Tenant value {tenant_value} below agency floor {floor} for {threshold_field}",
                )
            return ThresholdResolution(value=tenant_value, source="tenant_rules",
                                       rule_version_id=rid, governed_by="tenant_rules")

        # Layer 2 — agency guideline
        ag_key = FIELD_TO_AGENCY_GUIDELINE.get(threshold_field)
        if ag_key and agency:
            a, ck, name = ag_key
            key = f"{a}:{ck}:{name}"
            if key in agency:
                return ThresholdResolution(value=agency[key], source="agency_guidelines",
                                           citation=agency.get(f"{key}:meta", {}).get("citation"),
                                           governed_by="agency_guidelines")

        # Layer 3 — decisions.yaml default
        return ThresholdResolution(value=default_value, source="system_default",
                                   governed_by="decisions_yaml")

    async def _get_tenant_rules(self, rule_version_id: Optional[str] = None) -> dict:
        # Fix 2: cache keyed by (tenant_id, rule_version_id) — a single resolver
        # instance can never return another tenant's (or version's) rules.
        cache_key = (self._tenant_id, rule_version_id)
        if cache_key in self._tenant_rules_cache:
            return self._tenant_rules_cache[cache_key]
        try:
            if rule_version_id:
                # Fix 1: a pinned rule_version_id must belong to this tenant,
                # else a leaked/guessed version id would read cross-tenant policy.
                row = await self._conn.fetchrow(
                    "SELECT rules FROM tenant_rules WHERE rule_version_id = $1 "
                    "AND tenant_id = $2", rule_version_id, self._tenant_id)
            else:
                row = await self._conn.fetchrow(
                    "SELECT rules FROM tenant_rules WHERE tenant_id = $1 AND status = 'active' "
                    "ORDER BY version DESC LIMIT 1", self._tenant_id)
            rules = row["rules"] if row else None
            parsed = (json.loads(rules) if isinstance(rules, str) else rules) or {}
        except Exception:
            parsed = {}
        self._tenant_rules_cache[cache_key] = parsed
        return parsed

    async def _get_agency_guidelines(self) -> dict:
        if self._agency_cache is not None:
            return self._agency_cache
        try:
            rows = await self._conn.fetch(
                "SELECT agency, category, guideline_name, guideline_value, citation "
                "FROM agency_guidelines WHERE is_active = true")
            cache: dict = {}
            for r in rows:
                gv = r["guideline_value"]
                if isinstance(gv, str):
                    gv = json.loads(gv)
                value = gv.get("value") if isinstance(gv, dict) else None
                key = f"{r['agency']}:{r['category']}:{r['guideline_name']}"
                cache[key] = value
                cache[f"{key}:meta"] = {"citation": r["citation"]}
            self._agency_cache = cache
        except Exception:
            self._agency_cache = {}
        return self._agency_cache

    async def get_waiver(
        self,
        tenant_id: str,
        waiver_type: str,
        conditions: Optional[dict] = None,
    ) -> Optional[float]:
        """Active, unexpired waiver value from tenant_rule_waivers, or None.

        ``conditions`` is matched against the waiver's ``conditions`` JSONB by
        text equality, so booleans / strings / numbers all compare correctly
        (e.g. {"first_time_homebuyer": True} matches a JSON ``true``). Layer 1
        of resolve_credit_floor(). Tenant-scoped by the ``tenant_id`` argument.
        """
        query = (
            "SELECT waiver_value FROM tenant_rule_waivers "
            "WHERE tenant_id = $1 AND waiver_type = $2 AND is_active = true "
            "AND (expires_at IS NULL OR expires_at > NOW())"
        )
        params: list = [tenant_id, waiver_type]
        for key, val in (conditions or {}).items():
            if not _IDENT_RE.match(key):
                continue  # skip unsafe keys rather than risk SQL injection
            params.append(_jsonb_text(val))
            query += f" AND conditions->>'{key}' = ${len(params)}"
        row = await self._conn.fetchrow(query, *params)
        return (float(row["waiver_value"])
                if row and row["waiver_value"] is not None else None)

    async def resolve_credit_floor(
        self,
        tenant_id: str,
        loan_type: Optional[str] = None,
        first_time_buyer: bool = False,
    ) -> int:
        """Effective minimum credit score, highest-priority layer first:

          1. tenant_rule_waivers  — e.g. FTB credit-floor override
          2. overlay_rules        — lender overlay
          3. tenant_rules         — rules->'credit'->>'min_score'
          4. agency floor         — by program (FHA 580 / VA 580 / Fannie 620)
          5. system default       — 620

        Reads the catalogue tables directly, tenant-scoped by the ``tenant_id``
        argument (the catalogue tables carry their own tenant_id column).
        """
        # Layer 1 — FTB waiver (tenant_rule_waivers)
        if first_time_buyer:
            wv = await self.get_waiver(
                tenant_id, "credit_floor_override",
                {"first_time_homebuyer": True})
            if wv is not None:
                return int(wv)

        # Layer 2 — overlay (exact loan_type match wins over the NULL catch-all)
        overlay = await self._conn.fetchrow(
            "SELECT overlay_value FROM overlay_rules WHERE tenant_id = $1 "
            "AND rule_type = 'credit_floor' AND (loan_type = $2 OR loan_type IS NULL) "
            "AND is_active = true "
            "ORDER BY CASE WHEN loan_type = $2 THEN 0 ELSE 1 END LIMIT 1",
            tenant_id, loan_type)
        if overlay and overlay["overlay_value"] is not None:
            return int(overlay["overlay_value"])

        # Layer 3 — tenant_rules.rules JSONB -> credit.min_score
        rules = await self._get_cached_rules(tenant_id)
        credit = rules.get("credit") if isinstance(rules, dict) else None
        if isinstance(credit, dict) and credit.get("min_score") is not None:
            return int(credit["min_score"])

        # Layer 4 — agency floor by program. agency_guidelines stores values
        # generically (guideline_value JSONB), with no loan_type/min_credit_score
        # columns, so use the codified floors keyed by program.
        lt = (loan_type or "Conventional").upper()
        if lt == "FHA":
            return FHA_FLOORS["credit.min_score"]
        if lt == "VA":
            return 580
        return AGENCY_FLOORS["credit.min_score"]

    # Parameters where a tenant overlay may only move the value DOWN (the
    # platform_ceiling is the hard maximum). credit_floor is the mirror case —
    # a tenant may only move it UP, never below the agency_floor.
    _CEILING_PARAMS = frozenset({
        "dti_back_max", "ltv_max_purchase", "ltv_max_cashout", "ltv_max_refi",
    })

    async def validate_overlay_within_bounds(
        self,
        product_type: str,
        parameter: str,
        proposed_value: float,
    ) -> dict:
        """Validate that a proposed tenant overlay stays within the platform
        guardrails for ``(product_type, parameter)``. Called before a tenant
        overlay rule is saved.

        Returns a dict with:
          valid:            bool
          reason:           str (only when invalid, or when no guardrail exists)
          agency_floor:     float | None
          platform_ceiling: float | None

        Enforcement is one-sided per parameter:
          credit_floor      — tenant may only go HIGHER than agency_floor.
          dti/ltv ceilings  — tenant may only go LOWER than platform_ceiling.
        """
        row = await self._conn.fetchrow(
            "SELECT agency_floor, platform_ceiling, description "
            "FROM platform_guardrails WHERE product_type = $1 AND parameter = $2",
            product_type, parameter,
        )
        if not row:
            return {"valid": True, "reason": "no guardrail defined",
                    "agency_floor": None, "platform_ceiling": None}

        floor = _num(row["agency_floor"]) if row["agency_floor"] is not None else None
        ceiling = _num(row["platform_ceiling"]) if row["platform_ceiling"] is not None else None
        proposed = _num(proposed_value)

        # credit_floor: a tenant overlay may require a higher score but never
        # drop below the agency floor.
        if parameter == "credit_floor":
            if floor is not None and proposed is not None and proposed < floor:
                return {
                    "valid": False,
                    "reason": (
                        f"Below agency floor {floor}. Cannot set {parameter} "
                        f"below {floor} for {product_type}."
                    ),
                    "agency_floor": floor,
                    "platform_ceiling": ceiling,
                }

        # dti / ltv maxima: a tenant overlay may tighten (go lower) but never
        # exceed the platform ceiling.
        elif parameter in self._CEILING_PARAMS:
            if ceiling is not None and proposed is not None and proposed > ceiling:
                return {
                    "valid": False,
                    "reason": (
                        f"Exceeds platform ceiling {ceiling}. Cannot set "
                        f"{parameter} above {ceiling} for {product_type}."
                    ),
                    "agency_floor": floor,
                    "platform_ceiling": ceiling,
                }

        return {"valid": True, "agency_floor": floor, "platform_ceiling": ceiling}

    async def _get_cached_rules(self, tenant_id: str) -> dict:
        """tenant_rules.rules JSONB for ``tenant_id``, cached per-tenant."""
        if tenant_id in self._rules_cache:
            return self._rules_cache[tenant_id]
        try:
            row = await self._conn.fetchrow(
                "SELECT rules FROM tenant_rules WHERE tenant_id = $1 AND status = 'active' "
                "ORDER BY version DESC LIMIT 1", tenant_id)
            rules = row["rules"] if row else None
            parsed = (json.loads(rules) if isinstance(rules, str) else rules) or {}
        except Exception:
            parsed = {}
        self._rules_cache[tenant_id] = parsed
        return parsed

    def _floor(self, threshold_field: str) -> Any:
        if "fha" in self._programs and threshold_field in FHA_FLOORS:
            return FHA_FLOORS[threshold_field]
        return AGENCY_FLOORS.get(threshold_field)


def _num(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


__all__ = ["ThresholdResolver", "ThresholdResolution"]
