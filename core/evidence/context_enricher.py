"""Context Enricher — EV-E.

Enriches the persona context bundle with the evidence trace (fact_nodes via
EvidenceTraceBuilder). This is a PARALLEL enrichment layer: every existing
field from the vw_*_context views is preserved untouched, and the evidence
facts are added alongside, so nothing breaks. Personas can begin reading
context['evidence'] (or the promoted top-level evidence_* fields) and migrate
off raw entity_states fields incrementally.

  context['qualifying_income']            -> entity_states (current behavior)
  context['evidence']['income']           -> fact_nodes (evidence graph)
  context['evidence_qualifying_monthly']  -> promoted fact value
"""
from __future__ import annotations

from typing import Optional

from .trace_builder import EvidenceTraceBuilder


class ContextEnricher:
    def __init__(self, conn):
        self.conn = conn
        self.builder = EvidenceTraceBuilder(conn)

    async def enrich_context(self, application_id: str, tenant_id: str,
                             existing_context: dict) -> dict:
        """Return existing_context plus an evidence layer (non-destructive)."""
        trace = await self.builder.build_trace(application_id, tenant_id)

        enriched = dict(existing_context)
        enriched["evidence"] = trace
        enriched["evidence_available"] = True
        enriched["requires_uw_review"] = trace.get("requires_uw_review", False)
        enriched["fraud_signals"] = trace.get("fraud_signals", [])
        enriched["overall_evidence_confidence"] = trace.get("overall_confidence", 0.0)

        # Promote key fact values to top level so personas can read them
        # directly without changing their existing access patterns.
        income = trace.get("income", {}).get("qualifying_monthly")
        if income:
            enriched["evidence_qualifying_monthly"] = income["value"]
            enriched["evidence_income_confidence"] = income["confidence"]
            enriched["evidence_income_conflicts"] = income["conflicts"]

        credit = trace.get("credit", {}).get("governing_score")
        if credit:
            enriched["evidence_governing_score"] = credit["value"]
            enriched["evidence_credit_conflicts"] = credit["conflicts"]

        assets = trace.get("assets", {}).get("verified_total")
        if assets:
            enriched["evidence_verified_assets"] = assets["value"]
            enriched["evidence_asset_conflicts"] = assets["conflicts"]

        employment = trace.get("employment", {}).get("continuity")
        if employment:
            enriched["evidence_employment_status"] = employment["text"]
            enriched["evidence_employment_conflicts"] = employment["conflicts"]

        return enriched

    # Live fact_type -> the context key personas will read (RA-3B / EV-F).
    # employment is textual (fact_text); the others are numeric (fact_value).
    EVIDENCE_KEYS = {
        "qualifying_income":      "evidence_qualifying_monthly",
        "governing_credit_score": "evidence_governing_score",
        "verified_assets":        "evidence_verified_assets",
        "employment_continuity":  "evidence_employment_status",
    }

    @staticmethod
    def _trace(result: dict, rule: str) -> dict:
        """Flatten a rule_loader.get_rule result into a workbench-friendly
        threshold trace: federal / agency / overlay / applied / citations."""
        layers = result.get("layers", {}) if result else {}
        citations = [
            layers[k].get("citation")
            for k in ("regulatory", "agency", "overlay")
            if layers.get(k) and layers[k].get("citation")
        ]
        return {
            "rule":     rule,
            "federal":  (layers.get("regulatory") or {}).get("value"),
            "agency":   (layers.get("agency") or {}).get("value"),
            "overlay":  (layers.get("overlay") or {}).get("value"),
            "applied":  result.get("applied") if result else None,
            "governed_by": result.get("governed_by") if result else None,
            "citations": citations,
        }

    async def _attach_income_thresholds(self, base: dict, tenant_id: str) -> None:
        """Resolve income documentation confidence thresholds from the
        catalogue (Fannie B3-3.1-01) via rule_loader and attach to base.
        Best-effort: on any failure the persona falls back to safe constants."""
        try:
            from core.catalogue.rule_loader import get_rule
            rmin = await get_rule(
                self.conn, "income_documentation_confidence_min",
                tenant_id, agency="fannie", is_ceiling=False,
            )
            rflr = await get_rule(
                self.conn, "income_documentation_confidence_floor",
                tenant_id, agency="fannie", is_ceiling=False,
            )
            if rmin.get("applied") is not None:
                base["income_confidence_min"] = float(rmin["applied"])
            if rflr.get("applied") is not None:
                base["income_confidence_floor"] = float(rflr["applied"])
            base["income_confidence_threshold_trace"] = self._trace(
                rmin, "income_documentation_confidence_min"
            )
        except Exception:
            pass

    async def _attach_fraud(
        self, base: dict, application_id: str, tenant_id: str
    ) -> None:
        """Attach the current fraud_indicator fact (RA-3E) if one exists.
        Best-effort: clean loans leave fraud_populated=False."""
        try:
            r = await self.conn.fetchrow(
                """SELECT confidence, conflicts_found, resolution_method
                   FROM fact_nodes
                   WHERE application_id=$1 AND tenant_id=$2
                   AND fact_type='fraud_indicator' AND superseded_by IS NULL
                   ORDER BY computed_at DESC LIMIT 1""",
                application_id, tenant_id,
            )
            if r:
                base["fraud_populated"] = True
                base["fraud_indicator_confidence"] = (
                    float(r["confidence"])
                    if r["confidence"] is not None else None
                )
                base["fraud_indicator_conflicts"] = bool(r["conflicts_found"])
                base["fraud_indicator_method"] = r["resolution_method"]
        except Exception:
            pass

    # ATR/QM catalogue rules -> base key (RA-7A). is_ceiling drives risk only.
    _ATR_QM_RULES = [
        ("atr_required_factors", "atr_required_factors", False),
        ("qm_dti_max", "QM Safe Harbor DTI Maximum", True),
        ("qm_points_fees_max", "qm_points_fees_max_pct", True),
        ("hpml_threshold_bps", "hpml_rate_threshold_1st_lien", True),
    ]

    async def _attach_atr_qm(self, base: dict, tenant_id: str) -> None:
        """Resolve the 4 ATR/QM thresholds from the catalogue (12 CFR 1026.43 /
        .35) via rule_loader and attach them + a workbench trace. Best-effort:
        on failure ATRVerifier falls back to its SAFE_DEFAULTS (RULE 9)."""
        try:
            from core.catalogue.rule_loader import get_rule
            traces = {}
            for key, rule_name, ceiling in self._ATR_QM_RULES:
                r = await get_rule(self.conn, rule_name, tenant_id, is_ceiling=ceiling)
                if r.get("applied") is not None:
                    base[key] = float(r["applied"])
                traces[rule_name] = self._trace(r, rule_name)
            base["atr_qm_rule_traces"] = traces
        except Exception:
            pass

    async def _attach_income_entity(
        self, base: dict, application_id: str, tenant_id: str
    ) -> None:
        """INC-E: surface entity_states.total_liquid_assets to income_verification
        so the asset-depletion resolver can run on real data. Best-effort + read-
        only; advisory output only (proposed_outcome untouched)."""
        try:
            es = await self.conn.fetchrow(
                """SELECT total_liquid_assets FROM entity_states
                   WHERE application_id=$1 AND tenant_id=$2""",
                application_id, tenant_id,
            )
            if es and es["total_liquid_assets"] is not None:
                base["total_liquid_assets"] = float(es["total_liquid_assets"])
        except Exception:
            pass

    async def _attach_compensating_factor_inputs(
        self, base: dict, application_id: str, tenant_id: str
    ) -> None:
        """EX-B: surface the compensating-factor input scalars to approval_routing
        so CompensatingFactorsEngine can detect factors on real data. Reads the
        entity_states scalars + borrower.employment.period_start, and the agency
        Minimum Credit Score floor via rule_loader (RULE 4 gateway). Best-effort,
        read-only, advisory (proposed_outcome untouched)."""
        try:
            import json as _json
            es = await self.conn.fetchrow(
                """SELECT mid_credit_score, ltv, piti_monthly, total_liquid_assets,
                          monthly_obligations, qualifying_monthly, borrower
                   FROM entity_states WHERE application_id=$1 AND tenant_id=$2""",
                application_id, tenant_id,
            )
            if not es:
                return
            borrower = es["borrower"]
            if isinstance(borrower, str):
                borrower = _json.loads(borrower) if borrower else {}
            emp = (borrower or {}).get("employment", {}) if isinstance(borrower, dict) else {}
            cf = {
                "mid_credit_score":        es["mid_credit_score"],
                "ltv":                     es["ltv"],
                "piti_monthly":            es["piti_monthly"],
                "total_liquid_assets":     es["total_liquid_assets"],
                "monthly_obligations":     es["monthly_obligations"],
                "qualifying_monthly":      es["qualifying_monthly"],
                "employment_period_start": (emp or {}).get("period_start"),
            }
            try:
                from core.catalogue.rule_loader import get_rule
                r = await get_rule(self.conn, "Minimum Credit Score", tenant_id,
                                   is_ceiling=False)
                if r.get("applied") is not None:
                    cf["min_credit_score_applied"] = float(r["applied"])
            except Exception:
                pass
            base["cf_inputs"] = cf
        except Exception:
            pass

    async def _attach_aus_result(
        self, base: dict, application_id: str, tenant_id: str
    ) -> None:
        """Surface the parsed DU result (RA-AUS-A) AND the parsed LP result
        (RA-AUS-C) for approval_routing, if either was ingested. Each is None when
        no response exists for that system (not all lenders run DU and/or LP) — the
        persona reconciles whichever exist. Best-effort."""
        try:
            from core.aus.store import load_aus_result
            base["aus_result"] = await load_aus_result(
                self.conn, application_id, tenant_id, "DU")
            base["aus_result_lp"] = await load_aus_result(
                self.conn, application_id, tenant_id, "LP")
        except Exception:
            pass

    async def _attach_hmda_fields(
        self, base: dict, application_id: str, tenant_id: str
    ) -> None:
        """Surface HMDA LAR source fields for underwriting_decision: demographic
        + loan data from vw_hmda_reporting (which reads borrower JSONB + the
        loan/subject_property tables) plus a few entity_states scalars. Demographic
        data is for the LAR record ONLY — never used in any decision. Best-effort."""
        try:
            v = await self.conn.fetchrow(
                """SELECT race, ethnicity, sex, age, loan_amount, loan_purpose,
                          loan_type
                   FROM vw_hmda_reporting WHERE application_id=$1""",
                application_id,
            )
            es = await self.conn.fetchrow(
                """SELECT interest_rate, qualifying_monthly,
                          property->>'lien_status' AS lien_status,
                          loan_terms->>'loan_type' AS lt_loan_type
                   FROM entity_states WHERE application_id=$1 AND tenant_id=$2""",
                application_id, tenant_id,
            )
            fields = dict(v) if v else {}
            if es:
                fields["interest_rate"] = es["interest_rate"]
                fields["qualifying_monthly"] = es["qualifying_monthly"]
                fields["lien_status"] = (
                    1 if (es["lien_status"] or "").lower() in ("first", "first_lien", "1")
                    else fields.get("lien_status")
                )
                if not fields.get("loan_type"):
                    fields["loan_type"] = es["lt_loan_type"]
            fields["tenant_id"] = tenant_id
            base["hmda_fields"] = fields
        except Exception:
            pass

    async def _attach_adverse_action(self, base: dict, tenant_id: str) -> None:
        """Resolve the ECOA adverse-action notice deadline (Reg B §1002.9 = 30
        days) from the catalogue for underwriting_decision. Best-effort: the
        AdverseActionEngine falls back to its 30-day default (RULE 9)."""
        try:
            from core.catalogue.rule_loader import get_rule
            r = await get_rule(self.conn, "Adverse Action Notice Deadline",
                               tenant_id, is_ceiling=True)
            if r.get("applied") is not None:
                base["adverse_action_days_max"] = int(float(r["applied"]))
            base["adverse_action_rule_trace"] = self._trace(
                r, "Adverse Action Notice Deadline")
        except Exception:
            pass

    async def _attach_atr_factors(
        self, base: dict, application_id: str, tenant_id: str
    ) -> None:
        """Surface the entity_states scalars the ATR 8-factor checklist needs
        (the compliance view exposes only ltv). Best-effort."""
        try:
            row = await self.conn.fetchrow(
                """SELECT qualifying_monthly, piti_monthly, monthly_obligations,
                          dti_back, mid_credit_score, ltv, loan_amount,
                          interest_rate
                   FROM entity_states
                   WHERE application_id=$1 AND tenant_id=$2""",
                application_id, tenant_id,
            )
            if row:
                base["atr_entity"] = {
                    k: (float(v) if isinstance(v, (int, float)) else v)
                    for k, v in dict(row).items()
                }
        except Exception:
            pass

    # P0-D — rate_pricing catalogue inputs. guideline_name -> base key.
    _PRICING_GUIDELINES = [
        ("rate_normal_band_max",                  "pricing_rate_normal_band_max"),
        ("llpa_manual_review_threshold",          "pricing_llpa_manual_review_threshold"),
        ("llpa_credit_score_below_700_per_point", "pricing_llpa_credit_per_point"),
        ("llpa_ltv_above_80_per_point",           "pricing_llpa_ltv_per_point"),
        ("llpa_dti_above_36_per_point",           "pricing_llpa_dti_per_point"),
        ("llpa_non_qm_add_on",                    "pricing_llpa_non_qm_add_on"),
    ]
    _RATE_PRODUCT_PREFIX = {
        "conventional": "PRD-FNMA", "conforming": "PRD-FNMA",
        "fha": "PRD-FHA", "va": "PRD-VA",
    }

    async def _attach_pricing(
        self, base: dict, application_id: str, tenant_id: str
    ) -> None:
        """P0-D: resolve rate_pricing inputs from the catalogue so the persona
        reads them off the bundle instead of hardcoding.
          base_rate  <- rate_sheet_entry (tenant product par; percent -> fraction)
          LLPA coeffs + band/review thresholds <- agency_guidelines (pricing)
          usury cap  <- regulatory_rules state cap keyed on property_state
        Best-effort; the persona keeps SAFE_DEFAULTS-matching constants as the
        crash guard, so a missing/deactivated row can never break pricing."""
        try:
            from core.catalogue.rule_loader import get_rule
            traces = {}
            for gname, bkey in self._PRICING_GUIDELINES:
                r = await get_rule(self.conn, gname, tenant_id, agency="fannie")
                if r.get("applied") is not None:
                    base[bkey] = float(r["applied"])
                traces[gname] = self._trace(r, gname)
            base["pricing_rule_traces"] = traces
        except Exception:
            pass
        try:
            from core.catalogue.rule_loader import _parse
            es = await self.conn.fetchrow(
                """SELECT loan_terms->>'loan_type' AS loan_type,
                          property->>'state' AS property_state
                   FROM entity_states WHERE application_id=$1 AND tenant_id=$2""",
                application_id, tenant_id,
            )
            loan_type = (es and es["loan_type"]) or "conforming"
            prefix = self._RATE_PRODUCT_PREFIX.get(str(loan_type).lower(), "PRD-FNMA")
            par = await self.conn.fetchval(
                """SELECT MIN(base_rate) FROM rate_sheet_entry
                   WHERE tenant_id=$1 AND product_id LIKE $2
                     AND effective_date <= CURRENT_DATE""",
                tenant_id, f"{prefix}%",
            )
            if par is not None:
                # rate_sheet_entry is in percent; the persona works in fractions.
                base["pricing_base_rate"] = round(float(par) / 100.0, 5)
                base["pricing_base_rate_governed_by"] = "rate_sheet_entry"
            # State usury cap. Dormant when property_state is absent (e.g. summit
            # loans) -> the persona falls back to the generous federal constant.
            prop_state = es["property_state"] if es else None
            base["pricing_property_state"] = prop_state
            if prop_state:
                row = await self.conn.fetchrow(
                    """SELECT rule_value FROM regulatory_rules
                       WHERE authority='state' AND is_active=true
                         AND rule_name ILIKE '%usury%' AND state_code=$1 LIMIT 1""",
                    prop_state,
                )
                if row:
                    v = _parse(row["rule_value"])
                    if isinstance(v, (int, float)):
                        base["pricing_usury_limit"] = round(float(v) / 100.0, 5)
                        base["pricing_usury_governed_by"] = "regulatory_rules"
        except Exception:
            pass

    # LTV per-band caps (advisory) — credit_band -> guideline_name.
    _LTV_CAP_BANDS = ["super_prime", "prime", "near_prime", "subprime",
                      "deep_subprime", "thin_file"]

    async def _attach_ltv_caps(self, base: dict, tenant_id: str) -> None:
        """Resolve the per-band max-LTV caps from the catalogue (agency_guidelines
        'max_ltv_{band}', percent -> fraction) so ltv_assessment reads them off the
        bundle instead of hardcoding _MAX_LTV_BY_BAND. Overlays tighten a band via
        overlay_rules(rule_type='max_ltv_{band}'). Best-effort; the persona keeps
        the dict as the crash-guard fallback."""
        try:
            from core.catalogue.rule_loader import get_rule
            caps = {}
            traces = {}
            for band in self._LTV_CAP_BANDS:
                gname = f"max_ltv_{band}"
                r = await get_rule(self.conn, gname, tenant_id, agency="fannie", is_ceiling=True)
                if r.get("applied") is not None:
                    caps[band] = float(r["applied"]) / 100.0  # catalogue percent -> fraction
                traces[gname] = self._trace(r, gname)
            base["ltv_caps_by_band"] = caps or None
            base["ltv_caps_trace"] = traces
        except Exception:
            pass

    async def _attach_product_eligibility(
        self, base: dict, application_id: str, tenant_id: str
    ) -> None:
        """Inject the tenant's active products + the conforming loan limit so
        product_eligibility reads the catalogue instead of hardcoding _PRODUCTS.
        max_dti/max_ltv are percent in the table -> fractions here. Best-effort;
        the persona keeps _PRODUCTS as the crash-guard fallback."""
        try:
            rows = await self.conn.fetch(
                """SELECT product_name, loan_type, max_loan_amount, min_credit_score,
                          max_dti, max_ltv
                   FROM products WHERE tenant_id=$1 AND is_active=true
                   ORDER BY product_name""",
                tenant_id,
            )
            products = [{
                "product_name": r["product_name"],
                "loan_type": r["loan_type"],
                "max_loan_amount": float(r["max_loan_amount"]) if r["max_loan_amount"] is not None else None,
                "min_credit_score": int(r["min_credit_score"]) if r["min_credit_score"] is not None else None,
                "max_dti": float(r["max_dti"]) / 100.0 if r["max_dti"] is not None else None,
                "max_ltv": float(r["max_ltv"]) / 100.0 if r["max_ltv"] is not None else None,
            } for r in rows]
            base["product_matrix"] = products or None
        except Exception:
            pass
        try:
            from core.catalogue.rule_loader import get_rule
            r = await get_rule(self.conn, "conforming_loan_limit", tenant_id,
                               agency="fannie", is_ceiling=True)
            if r.get("applied") is not None:
                base["conforming_loan_limit"] = float(r["applied"])
            base["conforming_loan_limit_trace"] = self._trace(r, "conforming_loan_limit")
        except Exception:
            pass

    # Credit band thresholds (min score per band) — guideline_name -> band label.
    _CREDIT_BAND_GUIDELINES = [
        ("credit_band_threshold_super_prime", "super_prime"),
        ("credit_band_threshold_prime", "prime"),
        ("credit_band_threshold_near_prime", "near_prime"),
        ("credit_band_threshold_subprime", "subprime"),
    ]

    async def _attach_credit_bands(self, base: dict, tenant_id: str) -> None:
        """Resolve the per-band minimum credit scores + the high-utilization
        threshold from the catalogue so credit_assessment reads them off the
        bundle instead of hardcoding _BAND_THRESHOLDS / 0.6. credit_bands is a
        [threshold, label] list sorted DESC (deep_subprime=0 floor appended).
        Best-effort; the persona keeps its constants as the crash-guard fallback."""
        try:
            from core.catalogue.rule_loader import get_rule
            bands = []
            traces = {}
            for gname, label in self._CREDIT_BAND_GUIDELINES:
                r = await get_rule(self.conn, gname, tenant_id, agency="fannie", is_ceiling=False)
                if r.get("applied") is not None:
                    bands.append([float(r["applied"]), label])
                traces[gname] = self._trace(r, gname)
            if bands:
                bands.append([0.0, "deep_subprime"])  # implicit floor
                bands.sort(key=lambda x: x[0], reverse=True)
                base["credit_bands"] = bands
            base["credit_band_traces"] = traces
            r = await get_rule(self.conn, "credit_utilization_high_threshold",
                               tenant_id, agency="fannie", is_ceiling=True)
            if r.get("applied") is not None:
                base["credit_utilization_high_threshold"] = float(r["applied"])
        except Exception:
            pass

    # employment_reconciliation boundary thresholds (guideline_name = base key).
    _EMPLOYMENT_THRESHOLDS = [
        "employment_continuity_coverage_min",
        "employment_max_gap_days_allowed",
        "employer_match_confidence_min",
        "employment_stated_drift_max_pct",
        "employment_comp_drift_max_pct",
        "employment_comp_drift_conflict_pct",
        "employment_partial_coverage_min",
    ]

    async def _attach_employment_thresholds(self, base: dict, tenant_id: str) -> None:
        """Resolve the 7 employment_reconciliation boundary thresholds from the
        catalogue and inject them on the bundle so the persona reads them instead
        of hardcoding. Best-effort; the persona keeps the literals as fallbacks."""
        try:
            from core.catalogue.rule_loader import get_rule
            traces = {}
            for gname in self._EMPLOYMENT_THRESHOLDS:
                r = await get_rule(self.conn, gname, tenant_id, agency="fannie")
                if r.get("applied") is not None:
                    base[gname] = float(r["applied"])
                traces[gname] = self._trace(r, gname)
            base["employment_threshold_traces"] = traces
        except Exception:
            pass

    # income_verification confidence scores + block threshold (name = base key).
    _INCOME_CONFIDENCE_KEYS = [
        "income_confidence_auto_verified",
        "income_confidence_partial",
        "income_confidence_conflict",
        "income_confidence_missing",
        "income_discrepancy_block_pct",
    ]

    async def _attach_income_confidence(self, base: dict, tenant_id: str) -> None:
        """Resolve the income_verification confidence scores + discrepancy-block
        threshold from the catalogue and inject them so the persona reads them
        instead of hardcoding. Best-effort; the persona keeps the literals as
        crash-guard fallbacks."""
        try:
            from core.catalogue.rule_loader import get_rule
            traces = {}
            for gname in self._INCOME_CONFIDENCE_KEYS:
                r = await get_rule(self.conn, gname, tenant_id, agency="fannie")
                if r.get("applied") is not None:
                    base[gname] = float(r["applied"])
                traces[gname] = self._trace(r, gname)
            base["income_confidence_traces"] = traces
        except Exception:
            pass

    async def evidence_facts(
        self, application_id: str, tenant_id: str,
        decision_id: Optional[str] = None,
    ) -> dict:
        """Return the RA-3B evidence_* keys from CURRENT (non-superseded)
        fact_nodes for one application.

        Adds, exactly:
          evidence_qualifying_monthly  <- qualifying_income.fact_value
          evidence_governing_score     <- governing_credit_score.fact_value
          evidence_verified_assets     <- verified_assets.fact_value
          evidence_employment_status   <- employment_continuity.fact_text
          evidence_overall_confidence  <- min() of the present confidences
          evidence_any_conflicts       <- any conflicts_found = true
          evidence_populated           <- bool, any current facts exist

        Graceful: never raises; returns evidence_populated=False with all
        values None when no facts exist. Non-destructive — the caller merges
        these alongside existing context keys.
        """
        base = {
            "evidence_qualifying_monthly": None,
            "evidence_governing_score":    None,
            "evidence_verified_assets":    None,
            "evidence_employment_status":  None,
            "evidence_overall_confidence": None,
            "evidence_any_conflicts":      False,
            "evidence_populated":          False,
            # Per-fact detail for persona consumption (RA-3D onward).
            "ev_income_value":             None,
            "ev_income_confidence":        None,
            "ev_income_method":            None,
            "ev_income_conflicts":         False,
            "ev_income_conflict_ids":      None,
            "ev_employment_confidence":    None,
            "ev_employment_conflicts":     False,
            # Per-fact credit + asset detail (RA-PERSONA-A) — symmetric with
            # income/employment, so credit_assessment / asset_verification can
            # read domain-specific evidence quality, not just the aggregate.
            "ev_credit_value":             None,
            "ev_credit_confidence":        None,
            "ev_credit_conflicts":         False,
            "ev_asset_value":              None,
            "ev_asset_confidence":         None,
            "ev_asset_conflicts":          False,
            # Catalogue-sourced thresholds (RA-3D correction) — read via
            # rule_loader so the governing values come from agency_guidelines,
            # not Python constants. Attached on every path (app-independent).
            "income_confidence_min":       None,
            "income_confidence_floor":     None,
            "income_confidence_threshold_trace": None,
            # Fraud evidence (RA-3E) — present only when a fraud_indicator
            # fact exists; clean loans carry fraud_populated=False.
            "fraud_indicator_confidence":  None,
            "fraud_indicator_conflicts":   False,
            "fraud_indicator_method":      None,
            "fraud_populated":             False,
            # ATR/QM (RA-7A) — populated only for the compliance_check decision
            # (12 CFR 1026.43). Thresholds from the catalogue; factors from
            # entity_states (the compliance view carries only ltv).
            "atr_required_factors":        None,
            "qm_dti_max":                  None,
            "qm_points_fees_max":          None,
            "hpml_threshold_bps":          None,
            "atr_qm_rule_traces":          None,
            "atr_entity":                  None,
            # Adverse-action deadline (RA-7B) — only for underwriting_decision.
            "adverse_action_days_max":     None,
            "adverse_action_rule_trace":   None,
            # HMDA LAR source fields (RA-7C) — only for underwriting_decision.
            "hmda_fields":                 None,
            # Parsed AUS results — only for approval_routing.
            "aus_result":                  None,   # DU (RA-AUS-A)
            "aus_result_lp":               None,   # LP (RA-AUS-C)
            # INC-E — only for income_verification (asset depletion input).
            "total_liquid_assets":         None,
            # EX-B — compensating-factor inputs, only for approval_routing.
            "cf_inputs":                   None,
            # P0-D — rate_pricing catalogue inputs (only for the rate_pricing
            # decision; None elsewhere so the persona uses its crash-guard
            # constants). base_rate <- rate_sheet_entry; LLPA coeffs + band/review
            # thresholds <- agency_guidelines; usury <- regulatory_rules.
            "pricing_base_rate":                    None,
            "pricing_llpa_credit_per_point":        None,
            "pricing_llpa_ltv_per_point":           None,
            "pricing_llpa_dti_per_point":           None,
            "pricing_llpa_non_qm_add_on":           None,
            "pricing_rate_normal_band_max":         None,
            "pricing_llpa_manual_review_threshold": None,
            "pricing_usury_limit":                  None,
            "pricing_property_state":               None,
            "pricing_rule_traces":                  None,
            # LTV per-band caps (only for ltv_assessment; None elsewhere so the
            # persona uses its _MAX_LTV_BY_BAND crash-guard fallback).
            "ltv_caps_by_band":                     None,
            "ltv_caps_trace":                       None,
            # Product catalogue (only for product_eligibility; None elsewhere so
            # the persona uses its _PRODUCTS crash-guard fallback).
            "product_matrix":                       None,
            "conforming_loan_limit":                None,
            "conforming_loan_limit_trace":          None,
            # Credit band thresholds (only for credit_assessment; None elsewhere
            # so the persona uses its _BAND_THRESHOLDS / 0.6 crash-guard fallback).
            "credit_bands":                         None,
            "credit_band_traces":                   None,
            "credit_utilization_high_threshold":    None,
            # employment_reconciliation thresholds (only for that decision; None
            # elsewhere so the persona uses its hardcoded constants).
            "employment_threshold_traces":          None,
            # income_verification confidence scores (only for that decision).
            "income_confidence_traces":             None,
        }

        # Thresholds + fraud first, so they ride on every return path.
        await self._attach_income_thresholds(base, tenant_id)
        await self._attach_fraud(base, application_id, tenant_id)
        # ATR/QM is only consumed by compliance_check — load it just for that
        # decision to avoid 13 personas paying for rules they never read.
        if decision_id == "compliance_check":
            await self._attach_atr_qm(base, tenant_id)
            await self._attach_atr_factors(base, application_id, tenant_id)
        elif decision_id == "underwriting_decision":
            await self._attach_adverse_action(base, tenant_id)
            await self._attach_hmda_fields(base, application_id, tenant_id)
        elif decision_id == "approval_routing":
            await self._attach_aus_result(base, application_id, tenant_id)
            await self._attach_compensating_factor_inputs(base, application_id, tenant_id)
        elif decision_id == "income_verification":
            await self._attach_income_entity(base, application_id, tenant_id)
            await self._attach_income_confidence(base, tenant_id)
        elif decision_id == "rate_pricing":
            await self._attach_pricing(base, application_id, tenant_id)
        elif decision_id == "ltv_assessment":
            await self._attach_ltv_caps(base, tenant_id)
        elif decision_id == "product_eligibility":
            await self._attach_product_eligibility(base, application_id, tenant_id)
        elif decision_id == "credit_assessment":
            await self._attach_credit_bands(base, tenant_id)
        elif decision_id == "employment_reconciliation":
            await self._attach_employment_thresholds(base, tenant_id)

        try:
            rows = await self.conn.fetch(
                """
                SELECT fact_type, fact_value, fact_text,
                       confidence, conflicts_found,
                       resolution_method, conflict_ids
                FROM fact_nodes
                WHERE application_id = $1
                  AND tenant_id = $2
                  AND superseded_by IS NULL
                  AND fact_type = ANY($3::text[])
                """,
                application_id, tenant_id,
                list(self.EVIDENCE_KEYS),
            )
        except Exception:
            return base

        if not rows:
            return base

        # Defensive: if more than one current row per type slips through,
        # keep the highest-confidence one.
        best: dict = {}
        for r in rows:
            ft = r["fact_type"]
            cur = best.get(ft)
            if cur is None or float(r["confidence"] or 0) > float(
                cur["confidence"] or 0
            ):
                best[ft] = r

        confidences = []
        any_conflict = False
        for ft, key in self.EVIDENCE_KEYS.items():
            r = best.get(ft)
            if r is None:
                continue
            if ft == "employment_continuity":
                base[key] = r["fact_text"]
            else:
                base[key] = (
                    float(r["fact_value"])
                    if r["fact_value"] is not None else None
                )
            if r["confidence"] is not None:
                confidences.append(float(r["confidence"]))
            if r["conflicts_found"]:
                any_conflict = True

            # Per-fact detail the personas read (income + employment first).
            if ft == "qualifying_income":
                base["ev_income_value"] = (
                    float(r["fact_value"])
                    if r["fact_value"] is not None else None
                )
                base["ev_income_confidence"] = (
                    float(r["confidence"])
                    if r["confidence"] is not None else None
                )
                base["ev_income_method"] = r["resolution_method"]
                base["ev_income_conflicts"] = bool(r["conflicts_found"])
                base["ev_income_conflict_ids"] = (
                    list(r["conflict_ids"]) if r["conflict_ids"] else None
                )
            elif ft == "employment_continuity":
                base["ev_employment_confidence"] = (
                    float(r["confidence"])
                    if r["confidence"] is not None else None
                )
                base["ev_employment_conflicts"] = bool(r["conflicts_found"])
            elif ft == "governing_credit_score":
                base["ev_credit_value"] = (
                    float(r["fact_value"])
                    if r["fact_value"] is not None else None
                )
                base["ev_credit_confidence"] = (
                    float(r["confidence"])
                    if r["confidence"] is not None else None
                )
                base["ev_credit_conflicts"] = bool(r["conflicts_found"])
            elif ft == "verified_assets":
                base["ev_asset_value"] = (
                    float(r["fact_value"])
                    if r["fact_value"] is not None else None
                )
                base["ev_asset_confidence"] = (
                    float(r["confidence"])
                    if r["confidence"] is not None else None
                )
                base["ev_asset_conflicts"] = bool(r["conflicts_found"])

        base["evidence_populated"] = True
        base["evidence_any_conflicts"] = any_conflict
        base["evidence_overall_confidence"] = (
            round(min(confidences), 3) if confidences else None
        )
        return base

    async def get_fact_summary(self, application_id: str, tenant_id: str) -> str:
        """One-line evidence summary for logging / monitoring."""
        trace = await self.builder.build_trace(application_id, tenant_id)
        income = trace.get("income", {}).get("qualifying_monthly", {}) or {}
        credit = trace.get("credit", {}).get("governing_score", {}) or {}
        assets = trace.get("assets", {}).get("verified_total", {}) or {}
        return (
            f"income=${float(income.get('value') or 0):,.0f}/mo "
            f"score={float(credit.get('value') or 0):.0f} "
            f"assets=${float(assets.get('value') or 0):,.0f} "
            f"conf={trace['overall_confidence']:.2f} "
            f"review={trace['requires_uw_review']}"
        )


__all__ = ["ContextEnricher"]
