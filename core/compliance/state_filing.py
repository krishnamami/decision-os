"""CF-D — state regulatory filing data aggregator (reporting counterpart to CM-E).

Aggregates decision/HMDA data into the COMMON state-filing data structure (loan
counts by action, $ volume + counts by product, denial rate, geographic
distribution) for each state the tenant is LICENSED in (tenants.settings.licenses).

State filings have no universal file format (NY DFS / CA DFPI / TX SML / FL OFR are
portal forms; the NMLS Mortgage Call Report is the common multistate channel), so
CF-D produces the DATA that populates any of them — it does NOT emit a state-specific
file, and submission stays a manual external step (like CF-A's CFPB upload).

Sync + pure + RULE 11. Post-decision read-only -> 16/16 by construction. Honest
gaps: no licenses -> no_licensed_states; NULL state_code/county -> geocoding
required; per-loan originator NMLS not collected -> always flagged.
"""
from __future__ import annotations

from typing import Optional

# action_taken (HMDA int codes + defensive outcome strings) -> filing label.
ACTION_LABELS = {
    "1": "originated", "2": "approved_not_accepted", "3": "denied", "4": "withdrawn",
    "5": "incomplete", "6": "purchased", "7": "preapproval_denied",
    "8": "preapproval_approved",
    "originated": "originated", "recommend": "originated", "approve": "originated",
    "allow": "originated", "block": "denied", "deny": "denied", "denied": "denied",
    "escalate": "approved_not_accepted", "withdraw": "withdrawn",
}


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


class StateFilingReport:
    NOT_SUBMITTED_NOTE = (
        "CF-D generates filing DATA only. Submission is a manual external step via the "
        "NMLS Mortgage Call Report (MCR) or the state portal (NY DFS, CA DFPI, TX SML, "
        "FL OFR). Verify with compliance counsel before submitting.")

    def generate(self, loans: list, licenses: list, period: str = "",
                 tenant_id: str = "", institution_name: str = "", nmls_id: str = "") -> dict:
        loans = loans or []
        if not licenses:
            return {"status": "no_licensed_states", "tenant_id": tenant_id, "period": period,
                    "state_packets": [],
                    "note": ("No state licenses configured. Run POST /api/accord/onboarding/"
                             "licenses to register state licenses; filing data is then "
                             "generated per licensed state."),
                    "submission_note": self.NOT_SUBMITTED_NOTE,
                    "data_source": "tenants.settings.licenses",
                    "missing_inputs": ["no state licenses in tenants.settings.licenses"]}

        packets = []
        for lic in licenses:
            state = str(lic.get("state") or "").upper()
            if not state:
                continue
            packets.append(self._state_packet(state, lic, loans, period,
                                               institution_name, nmls_id))
        all_missing = sorted({m for p in packets for m in p.get("missing_inputs", [])})
        return {"status": "generated", "tenant_id": tenant_id, "period": period,
                "institution_name": institution_name, "nmls_id": nmls_id,
                "states_licensed": len(packets), "state_packets": packets,
                "submission_note": self.NOT_SUBMITTED_NOTE,
                "data_source": "hmda_lar + tenants.settings.licenses",
                "missing_inputs": all_missing}

    def _state_packet(self, state: str, lic: dict, all_loans: list, period: str,
                      institution_name: str, nmls_id: str) -> dict:
        state_loans = [l for l in all_loans if str(l.get("state_code") or "").upper() == state]
        missing = []
        if not state_loans:
            null_count = sum(1 for l in all_loans if not l.get("state_code"))
            if all_loans and null_count == len(all_loans):
                missing.append("state_code is NULL for all loans — geocode property addresses "
                               "to populate hmda_lar.state_code before state filing")
            else:
                missing.append(f"no loans found for state {state} (loans may be in other states)")

        action_counts: dict = {}
        by_product: dict = {}
        by_county: dict = {}
        geo_missing = 0
        for l in state_loans:
            label = ACTION_LABELS.get(str(l.get("action_taken") or ""), "unknown")
            action_counts[label] = action_counts.get(label, 0) + 1
            lt = str(l.get("loan_type") or "unknown").lower()
            p = by_product.setdefault(lt, {"count": 0, "volume": 0.0})
            p["count"] += 1
            p["volume"] = round(p["volume"] + _f(l.get("loan_amount")), 2)
            county = l.get("county_code")
            if county:
                by_county[county] = by_county.get(county, 0) + 1
            else:
                geo_missing += 1

        total = len(state_loans)
        denied = action_counts.get("denied", 0)
        originated = action_counts.get("originated", 0)
        denial_rate = round(denied / total * 100, 1) if total else None
        total_volume = round(sum(_f(l.get("loan_amount")) for l in state_loans), 2)

        geo_status = "complete" if (total and geo_missing == 0) else (
            "partial" if by_county else "insufficient_data")
        if geo_missing:
            missing.append(f"{geo_missing} loan(s) missing county_code — geocode to enable "
                           "the geographic breakdown")
        # Per-loan originator NMLS is not collected anywhere today.
        missing.append("per-loan originator NMLS not collected — add it to application intake "
                       "for loan-officer-level reporting")

        return {
            "state": state, "license_number": lic.get("license_number", ""),
            "license_type": lic.get("license_type", ""), "expiry_date": lic.get("expiry_date", ""),
            "institution_name": institution_name, "nmls_id": nmls_id, "period": period,
            "summary": {"total_applications": total, "total_originated": originated,
                        "total_denied": denied, "total_volume_usd": total_volume,
                        "denial_rate_pct": denial_rate, "action_breakdown": action_counts},
            "by_product_type": by_product,
            "geographic": {"status": geo_status, "by_county": by_county, "missing_geo": geo_missing},
            "filing_references": {
                "nmls_mcr": "https://mortgage.nationwidelicensingsystem.org/REGSYS/MCR",
                "ny_dfs": "https://myportal.dfs.ny.gov" if state == "NY" else None,
                "ca_dfpi": "https://dfpi.ca.gov" if state == "CA" else None,
                "tx_sml": "https://www.sml.texas.gov" if state == "TX" else None,
                "fl_ofr": "https://flofr.gov" if state == "FL" else None,
            },
            "data_source": "hmda_lar + tenants.settings.licenses",
            "missing_inputs": missing,
        }


async def fetch_filing_data(conn, tenant_id: str, year: Optional[int] = None) -> tuple:
    """Fetch hmda_lar loans + the tenant's licenses/name/NMLS.
    Returns (loans, licenses, institution_name, nmls_id)."""
    import json
    params = [tenant_id]
    year_clause = ""
    if year:
        params.append(year)
        year_clause = " AND EXTRACT(YEAR FROM h.action_taken_date) = $2"
    loans = await conn.fetch(
        "SELECT state_code, county_code, census_tract, loan_type, action_taken, loan_amount "
        f"FROM hmda_lar h WHERE h.tenant_id=$1{year_clause} ORDER BY h.application_id", *params)
    tenant = await conn.fetchrow("SELECT settings, name FROM tenants WHERE tenant_id=$1", tenant_id)
    settings = {}
    if tenant and tenant["settings"]:
        raw = tenant["settings"]
        settings = json.loads(raw) if isinstance(raw, str) else (raw or {})
    name = (tenant["name"] if tenant else "") or tenant_id
    return ([dict(r) for r in loans], settings.get("licenses", []) or [],
            name, settings.get("nmls_id", ""))


__all__ = ["StateFilingReport", "fetch_filing_data", "ACTION_LABELS"]
