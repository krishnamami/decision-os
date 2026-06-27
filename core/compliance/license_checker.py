"""P0-I — state licensing compliance checker (SAFE Act 12 U.S.C. §5101).

Verifies a loan's property_state is among the tenant's active state licenses
(tenants.settings.licenses). Originating where the lender is not licensed violates
the SAFE Act + state law, so an unlicensed state is a hard compliance block.

STANDALONE + pure + sync + DB-less (RULE 5/6). NOT wired into the 16/16-critical
compliance_check persona — persona wiring is deferred to a green 16/16. RULE 11:
data_source + missing_inputs on every output.

16/16-safe by construction via two not_applicable guards (never blocks meridian):
  - property_state unknown (meridian property_state is NULL)  -> not_applicable
  - no licenses configured (no tenant has any today)          -> not_applicable

Statuses: licensed | unlicensed (BLOCK) | not_applicable.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

_EXPIRING_WINDOW_DAYS = 30


class LicenseComplianceChecker:
    REGULATORY_NOTE = (
        "Originating a mortgage loan in a state where the lender is not licensed violates "
        "the SAFE Act (12 U.S.C. §5101) and applicable state lending law. This is a "
        "compliance gate — do not override without legal review.")

    def check(self, property_state: Optional[str], licenses: list,
              check_date: Optional[str] = None, tenant_id: str = "") -> dict:
        today_str = check_date or date.today().isoformat()
        ds = "entity_states.property_state + tenants.settings.licenses"

        # Guard 1 — no property_state (meridian) -> not_applicable
        if not property_state:
            return {"status": "not_applicable", "licensed": None, "property_state": None,
                    "tenant_id": tenant_id, "reason": "property_state not available in loan profile",
                    "citation": "SAFE Act 12 U.S.C. §5101", "data_source": ds,
                    "missing_inputs": ["property_state required for the license check — capture "
                                       "the property address at intake"]}

        # Guard 2 — no licenses configured -> not_applicable (never blocks)
        if not licenses:
            return {"status": "not_applicable", "licensed": None,
                    "property_state": property_state, "tenant_id": tenant_id,
                    "reason": "no state licenses configured for this tenant",
                    "citation": "SAFE Act 12 U.S.C. §5101",
                    "data_source": "tenants.settings.licenses",
                    "note": ("WARNING: until state licenses are configured (POST "
                             "/onboarding/licenses), lending compliance cannot be verified."),
                    "missing_inputs": ["no licenses in tenants.settings.licenses — run "
                                       "/onboarding/licenses before processing production loans"]}

        state = property_state.upper().strip()
        licensed_states = sorted({str(l.get("state", "")).upper().strip() for l in licenses})
        state_licenses = [l for l in licenses
                          if str(l.get("state", "")).upper().strip() == state]

        if not state_licenses:
            return {"status": "unlicensed", "licensed": False, "property_state": state,
                    "tenant_id": tenant_id, "licensed_states": licensed_states,
                    "reason": f"tenant is not licensed to originate in {state} — block at intake",
                    "regulatory_note": self.REGULATORY_NOTE,
                    "citation": "SAFE Act 12 U.S.C. §5101",
                    "data_source": "tenants.settings.licenses", "missing_inputs": []}

        # expiry: ISO dates sort lexicographically, so string compare is correct
        active = [l for l in state_licenses
                  if not (l.get("expiry_date") and str(l["expiry_date"]) < today_str)]
        expired = [l for l in state_licenses if l not in active]

        if not active:
            return {"status": "unlicensed", "licensed": False, "property_state": state,
                    "tenant_id": tenant_id, "expired_licenses": expired,
                    "reason": f"all {state} licenses expired as of {today_str} — renew before originating",
                    "regulatory_note": self.REGULATORY_NOTE,
                    "citation": "SAFE Act 12 U.S.C. §5101",
                    "data_source": "tenants.settings.licenses", "missing_inputs": []}

        soon_cutoff = (date.fromisoformat(today_str) + timedelta(days=_EXPIRING_WINDOW_DAYS)).isoformat()
        expiring_soon = [l for l in active
                         if l.get("expiry_date") and str(l["expiry_date"]) <= soon_cutoff]
        return {"status": "licensed", "licensed": True, "property_state": state,
                "tenant_id": tenant_id, "active_licenses": active,
                "license_count": len(active), "expiring_soon": expiring_soon,
                "citation": "SAFE Act 12 U.S.C. §5101",
                "data_source": "tenants.settings.licenses", "missing_inputs": []}

    def check_bulk(self, loans: list, licenses: list, tenant_id: str = "",
                   check_date: Optional[str] = None) -> dict:
        """Audit a pipeline: per-loan license status + a summary. Each loan dict may
        carry property_state or state_code (+ application_id)."""
        loans = loans or []
        results = []
        for loan in loans:
            r = self.check(loan.get("property_state") or loan.get("state_code"),
                           licenses, check_date=check_date, tenant_id=tenant_id)
            r["application_id"] = loan.get("application_id", "")
            results.append(r)
        blocked = [r for r in results if r["status"] == "unlicensed"]
        licensed = [r for r in results if r["status"] == "licensed"]
        na = [r for r in results if r["status"] == "not_applicable"]
        return {
            "total": len(results), "licensed": len(licensed), "unlicensed": len(blocked),
            "not_applicable": len(na),
            "blocked_loans": [r["application_id"] for r in blocked],
            "licensed_states": sorted({str(l.get("state", "")).upper().strip() for l in licenses}),
            "results": results,
            "note": ("Standalone advisory audit — NOT wired into the compliance_check persona "
                     "(deferred to a green 16/16). Unlicensed loans should be blocked at intake."),
            "citation": "SAFE Act 12 U.S.C. §5101",
            "data_source": "tenants.settings.licenses + loan property_state",
            "missing_inputs": sorted({m for r in results for m in r.get("missing_inputs", [])}),
        }


async def fetch_license_data(conn, tenant_id: str) -> list:
    """Read the tenant's configured state licenses from tenants.settings."""
    import json
    row = await conn.fetchrow("SELECT settings FROM tenants WHERE tenant_id=$1", tenant_id)
    if not row or not row["settings"]:
        return []
    s = row["settings"]
    s = json.loads(s) if isinstance(s, str) else (s or {})
    return s.get("licenses", []) or []


__all__ = ["LicenseComplianceChecker", "fetch_license_data"]
