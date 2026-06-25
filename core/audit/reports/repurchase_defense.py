"""Repurchase Defense Report generator (TR-D).

A READ-ONLY assembler: pulls the 8-section repurchase-defense package from the 8
EXISTING data sources (no new tables, no catalogue, no decision logic). It is an
audit artifact (like the overrides report / exception register), so it MAY read
the DB directly — it is NOT a persona/resolver. Returns a structured dict + an
HTML render. RULE 11: every section carries data_source + missing_inputs.

ACCESS NUANCES (verified vs live schema):
  • decision_outputs uses decision_id / outcome (NOT persona_id / proposed_outcome),
    and is versioned with superseded_by NEVER set — "current" = MAX(version) per
    (application_id, decision_id) → DISTINCT ON (decision_id) ... ORDER BY version DESC.
  • the persona payload lives in context_snapshot.output_payload (no output_payload col).
  • policy_trace.rule_disclosures keys: federal_value / agency_value / overlay_value /
    applied_value / {federal,agency}_citation / governed_by / delta_applied_vs_agency.
"""
from __future__ import annotations

import json
from datetime import datetime


def _j(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return {}
    return v or {}


async def _latest_payload(conn, application_id: str, tenant_id: str,
                          decision_id: str) -> dict:
    """Return the output_payload from the latest version of a decision that
    actually HAS one. decision_outputs is versioned and the advisory enrichment
    (ATR/QM, AUS reconciliation, exception analysis) is best-effort, so the very
    latest version can carry an empty payload while an earlier one is complete —
    walk newest-first and return the first non-empty payload."""
    rows = await conn.fetch(
        """SELECT context_snapshot FROM decision_outputs
           WHERE application_id=$1 AND tenant_id=$2 AND decision_id=$3
           ORDER BY version DESC NULLS LAST, created_at DESC""",
        application_id, tenant_id, decision_id,
    )
    for r in rows:
        snap = _j(r["context_snapshot"])
        # context_snapshot IS the flat payload for these personas (no nested
        # 'output_payload' key) — fall back to the snapshot itself, matching the
        # adverse_action _payload pattern.
        op = snap.get("output_payload", snap) if isinstance(snap, dict) else {}
        if isinstance(op, dict) and op:
            return op
    return {}


async def generate_repurchase_defense_report(
    conn, application_id: str, tenant_id: str,
) -> dict:
    """Assemble the 8-section repurchase-defense report for one application."""

    # ── SECTION 1: Loan Summary — entity_states ───────────────────────
    loan_row = await conn.fetchrow(
        """SELECT loan_amount, ltv, dti_back, dti_front, mid_credit_score,
                  qualifying_monthly, piti_monthly, total_liquid_assets,
                  borrower, property, loan_terms
           FROM entity_states WHERE application_id=$1 AND tenant_id=$2""",
        application_id, tenant_id,
    )
    borrower = _j(loan_row["borrower"]) if loan_row else {}
    prop = _j(loan_row["property"]) if loan_row else {}
    lt = _j(loan_row["loan_terms"]) if loan_row else {}
    section_1 = {
        "section": "Loan Summary", "data_source": "entity_states",
        "missing_inputs": [] if loan_row else ["entity_states row not found"],
        "loan_amount": float(loan_row["loan_amount"]) if loan_row and loan_row["loan_amount"] is not None else None,
        "ltv": float(loan_row["ltv"]) if loan_row and loan_row["ltv"] is not None else None,
        "dti_back": float(loan_row["dti_back"]) if loan_row and loan_row["dti_back"] is not None else None,
        "mid_credit_score": loan_row["mid_credit_score"] if loan_row else None,
        "qualifying_monthly": float(loan_row["qualifying_monthly"]) if loan_row and loan_row["qualifying_monthly"] is not None else None,
        "piti_monthly": float(loan_row["piti_monthly"]) if loan_row and loan_row["piti_monthly"] is not None else None,
        "loan_type": lt.get("loan_type"),
        "loan_purpose": lt.get("loan_purpose"),
        "property_type": prop.get("property_type") or (lt.get("property_type")),
    }

    # ── SECTION 2: Decision Summary — decision_outputs (MAX version) ───
    decisions = await conn.fetch(
        """SELECT DISTINCT ON (decision_id)
                  decision_id, outcome, created_at, context_snapshot, version,
                  human_override_reason
           FROM decision_outputs
           WHERE application_id=$1 AND tenant_id=$2
           ORDER BY decision_id, version DESC""",
        application_id, tenant_id,
    )
    by_decision = {d["decision_id"]: d for d in decisions}
    uw = by_decision.get("underwriting_decision")
    blocking = [d for d in decisions
                if d["outcome"] in ("block", "deny", "escalate")]
    section_2 = {
        "section": "Decision Summary",
        "data_source": "decision_outputs (MAX version per decision_id)",
        "missing_inputs": [] if uw else ["underwriting_decision not found"],
        "final_outcome": uw["outcome"] if uw else None,
        "decision_date": uw["created_at"].isoformat() if uw and uw["created_at"] else None,
        "total_personas": len(decisions),
        "blocking_personas": [d["decision_id"] for d in blocking],
        "persona_outcomes": {d["decision_id"]: d["outcome"] for d in decisions},
        "human_override_reason": uw["human_override_reason"] if uw else None,
    }

    # ── SECTION 3: 40-Rule Policy Trace — decision_trace.policy_trace ──
    trace_row = await conn.fetchrow(
        """SELECT policy_trace, created_at FROM decision_trace
           WHERE application_id=$1 AND tenant_id=$2
           ORDER BY created_at DESC LIMIT 1""",
        application_id, tenant_id,
    )
    policy_trace = _j(trace_row["policy_trace"]) if trace_row else {}
    rule_disclosures = policy_trace.get("rule_disclosures", []) if isinstance(policy_trace, dict) else []
    section_3 = {
        "section": "Policy Trace", "data_source": "decision_trace.policy_trace",
        "missing_inputs": [] if rule_disclosures else ["policy_trace empty or missing"],
        "rule_count": len(rule_disclosures),
        "rule_disclosures": rule_disclosures,
        "trace_date": trace_row["created_at"].isoformat() if trace_row and trace_row["created_at"] else None,
        "note": ("Each rule shows federal baseline / agency guideline / lender "
                 "overlay / applied value / citation; applied = what governed this decision."),
    }

    # ── SECTION 4: Evidence Quality per Document — document_index ──────
    docs = await conn.fetch(
        """SELECT document_type, confidence_score, extraction_method, s3_key,
                  extracted_fields
           FROM document_index
           WHERE application_id=$1 AND tenant_id=$2 AND is_current=true
           ORDER BY document_type""",
        application_id, tenant_id,
    )
    doc_evidence = []
    for d in docs:
        fields = _j(d["extracted_fields"])
        doc_evidence.append({
            "document_type": d["document_type"],
            "confidence_score": float(d["confidence_score"] or 0),
            "extraction_method": d["extraction_method"],
            "fields_extracted": len(fields) if isinstance(fields, dict) else 0,
            "field_names": list(fields.keys()) if isinstance(fields, dict) else [],
            "s3_key": d["s3_key"],
        })
    section_4 = {
        "section": "Evidence Quality per Document", "data_source": "document_index",
        "missing_inputs": [] if docs else ["no documents in document_index"],
        "document_count": len(docs), "documents": doc_evidence,
        "avg_confidence": round(sum(d["confidence_score"] for d in doc_evidence)
                                / len(doc_evidence), 3) if doc_evidence else 0,
    }

    # ── SECTION 5: AUS Reconciliation — aus_responses + approval_routing ─
    aus_row = await conn.fetchrow(
        """SELECT aus_system, recommendation, approve, eligible, risk_class
           FROM aus_responses WHERE application_id=$1 AND tenant_id=$2
           ORDER BY created_at DESC LIMIT 1""",
        application_id, tenant_id,
    )
    ar_payload = await _latest_payload(conn, application_id, tenant_id, "approval_routing")
    aus_recon = ar_payload.get("aus_reconciliation") or {}
    applicable = bool(aus_row) or bool(aus_recon.get("reconciliation_required"))
    section_5 = {
        "section": "AUS Reconciliation",
        "data_source": "aus_responses + approval_routing context_snapshot",
        "missing_inputs": [] if applicable else ["No DU/LP response on file"],
        "not_applicable": not applicable,
        "aus_system": aus_row["aus_system"] if aus_row else None,
        "aus_recommendation": aus_row["recommendation"] if aus_row else None,
        "reconciliation": aus_recon,
        "conflict": aus_recon.get("conflict"),
        "conflict_risk": aus_recon.get("risk"),
        "uw_action": aus_recon.get("uw_action"),
    }

    # ── SECTION 6: Exception Status — loan_exceptions + comp factors ───
    exceptions = await conn.fetch(
        """SELECT id, exception_type, blocked_signal, status, breach_pct,
                  below_agency_floor, granted, denial_reason, threshold_source,
                  requested_by, reviewed_by
           FROM loan_exceptions WHERE application_id=$1 AND tenant_id=$2
           ORDER BY created_at""",
        application_id, tenant_id,
    )
    exc_list = []
    for exc in exceptions:
        factors = await conn.fetch(
            """SELECT factor_type, factor_value, factor_numeric, threshold_met,
                      citation FROM compensating_factors WHERE exception_id=$1""",
            exc["id"],
        )
        exc_list.append({
            "exception_type": exc["exception_type"],
            "blocked_signal": exc["blocked_signal"],
            "status": exc["status"],
            "required_level": exc["threshold_source"],
            "breach_pct": float(exc["breach_pct"]) if exc["breach_pct"] is not None else None,
            "below_agency_floor": exc["below_agency_floor"],
            "granted": exc["granted"], "denial_reason": exc["denial_reason"],
            "requested_by": exc["requested_by"], "reviewed_by": exc["reviewed_by"],
            "compensating_factors": [dict(f) for f in factors],
        })
    section_6 = {
        "section": "Exception Status",
        "data_source": "loan_exceptions + compensating_factors",
        "missing_inputs": [], "not_applicable": len(exc_list) == 0,
        "exceptions_count": len(exc_list), "exceptions": exc_list,
    }

    # ── SECTION 7: Adverse Action Notice — adverse_action_notices ─────
    aan = await conn.fetchrow(
        """SELECT hmda_codes, denial_reasons, notice_deadline, status, sent_at,
                  notice_date FROM adverse_action_notices
           WHERE application_id=$1 AND tenant_id=$2
           ORDER BY created_at DESC LIMIT 1""",
        application_id, tenant_id,
    )
    section_7 = {
        "section": "Adverse Action Notice", "data_source": "adverse_action_notices",
        "missing_inputs": [] if aan else ["No adverse action — loan was not denied"],
        "not_applicable": aan is None,
        "hmda_denial_codes": aan["hmda_codes"] if aan else None,
        "denial_reasons": _j(aan["denial_reasons"]) if aan else None,
        "notice_deadline": aan["notice_deadline"].isoformat() if aan and aan["notice_deadline"] else None,
        "notice_status": aan["status"] if aan else None,
        "ecoa_rights_statement": (
            "The federal Equal Credit Opportunity Act prohibits creditors from "
            "discriminating against credit applicants on the basis of race, color, "
            "religion, national origin, sex, marital status, or age."
        ) if aan else None,
    }

    # ── SECTION 8: Compliance Attestation — compliance_check payload ──
    cc_payload = await _latest_payload(conn, application_id, tenant_id, "compliance_check")
    section_8 = {
        "section": "Compliance Attestation",
        "data_source": "compliance_check context_snapshot.output_payload",
        "missing_inputs": [] if cc_payload else ["compliance_check output not found"],
        "atr_satisfied": cc_payload.get("atr_satisfied"),
        "atr_factors_passed": cc_payload.get("atr_factors_passed"),
        "atr_factors_checked": cc_payload.get("atr_factors_checked"),
        "atr_factors_failed": cc_payload.get("atr_factors_failed"),
        "qm_classification": cc_payload.get("qm_classification"),
        "safe_harbor_protected": cc_payload.get("safe_harbor_protected"),
        "atr_citation": cc_payload.get("atr_citation", "12 CFR 1026.43(c)"),
        "qm_citation": cc_payload.get("qm_citation", "12 CFR 1026.43(e)"),
    }

    sections = [section_1, section_2, section_3, section_4,
                section_5, section_6, section_7, section_8]
    report = {
        "report_type": "REPURCHASE_DEFENSE",
        "application_id": application_id, "tenant_id": tenant_id,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "sections": sections,
        "data_completeness": sum(
            1 for s in sections
            if not s.get("missing_inputs") and not s.get("not_applicable")),
        "total_sections": 8,
        "attestation": (
            f"This repurchase defense report was generated from the Accord Decision "
            f"OS audit trail for application {application_id}. All rule disclosures "
            f"reflect the catalogue version in effect at decision time. Generated: "
            f"{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}"
        ),
    }
    report["html"] = _render_html(report)
    return report


def _fmt_money(v):
    return f"${v:,.0f}" if isinstance(v, (int, float)) else "N/A"


def _fmt_pct(v):
    return f"{v}%" if isinstance(v, (int, float)) else "N/A"


def _render_html(report: dict) -> str:
    s = {sec["section"]: sec for sec in report["sections"]}
    s1, s2, s3 = s["Loan Summary"], s["Decision Summary"], s["Policy Trace"]
    s4, s5, s6 = s["Evidence Quality per Document"], s["AUS Reconciliation"], s["Exception Status"]
    s7, s8 = s["Adverse Action Notice"], s["Compliance Attestation"]

    rules_html = "".join(
        f"<tr><td>{r.get('rule_name','')}</td><td>{r.get('decision_id','')}</td>"
        f"<td>{'' if r.get('federal_value') is None else r.get('federal_value')}</td>"
        f"<td>{'' if r.get('agency_value') is None else r.get('agency_value')}</td>"
        f"<td>{'' if r.get('overlay_value') is None else r.get('overlay_value')}</td>"
        f"<td><strong>{'' if r.get('applied_value') is None else r.get('applied_value')}</strong></td>"
        f"<td><small>{r.get('agency_citation') or r.get('federal_citation') or ''}</small></td></tr>"
        for r in s3.get("rule_disclosures", [])
    )

    docs_html = "".join(
        f"<tr><td>{d['document_type']}</td><td>{d['confidence_score']:.2f}</td>"
        f"<td>{d['extraction_method'] or ''}</td><td>{d['fields_extracted']}</td></tr>"
        for d in s4.get("documents", [])
    )

    if s6.get("not_applicable"):
        exc_html = '<p class="na">No exceptions requested for this application.</p>'
    else:
        exc_html = "<table><tr><th>Type</th><th>Status</th><th>Required Level</th>" \
                   "<th>Below Agency Floor</th><th>Granted</th><th>Factors</th></tr>" + "".join(
            f"<tr><td>{e['exception_type']}</td><td>{e['status']}</td>"
            f"<td>{e.get('required_level') or ''}</td>"
            f"<td>{'Yes' if e['below_agency_floor'] else 'No'}</td>"
            f"<td>{'—' if e['granted'] is None else ('Yes' if e['granted'] else 'No')}</td>"
            f"<td>{len(e['compensating_factors'])}</td></tr>"
            for e in s6.get("exceptions", [])) + "</table>"

    if s5.get("not_applicable"):
        aus_html = '<p class="na">No DU/LP response on file — AUS reconciliation not applicable.</p>'
    else:
        aus_html = (f"<p>AUS: {s5.get('aus_system') or 'n/a'} "
                    f"({s5.get('aus_recommendation') or 'n/a'}) · "
                    f"conflict: {s5.get('conflict') or 'none'} "
                    f"(risk {s5.get('conflict_risk') or 'n/a'})</p>")

    if s7.get("not_applicable"):
        aa_html = '<p class="na">Loan was not denied — no adverse action notice.</p>'
    else:
        aa_html = (f"<p>HMDA denial codes: <strong>{s7.get('hmda_denial_codes')}</strong> · "
                   f"deadline: {s7.get('notice_deadline')} · status: {s7.get('notice_status')}</p>"
                   f'<p class="meta">{s7.get("ecoa_rights_statement","")}</p>')

    outcome = (s2.get("final_outcome") or "unknown")
    outcome_color = {"block": "#c53030", "deny": "#c53030", "recommend": "#276749",
                     "approve": "#276749", "escalate": "#d97706"}.get(outcome, "#2d3748")

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<title>Repurchase Defense Report — {report['application_id']}</title>
<style>
 body {{ font-family: Georgia, serif; max-width: 900px; margin: 40px auto; padding: 20px; color:#1a202c; }}
 h1 {{ color:#0f4d37; border-bottom:3px solid #0f4d37; padding-bottom:10px; }}
 h2 {{ color:#2d3748; margin-top:30px; border-left:4px solid #0f4d37; padding-left:12px; }}
 .outcome {{ font-size:1.4em; font-weight:bold; color:{outcome_color}; padding:10px; background:#f7fafc; border-radius:4px; }}
 table {{ width:100%; border-collapse:collapse; margin:16px 0; font-size:0.85em; }}
 th {{ background:#0f4d37; color:white; padding:8px; text-align:left; }}
 td {{ padding:7px 8px; border-bottom:1px solid #e2e8f0; }}
 tr:nth-child(even) td {{ background:#f7fafc; }}
 .attestation {{ background:#e8f5f0; border:1px solid #0f4d37; padding:16px; margin-top:30px; font-size:0.85em; }}
 .na {{ color:#718096; font-style:italic; }} .meta {{ color:#718096; font-size:0.8em; }}
</style></head><body>
<h1>Repurchase Defense Report</h1>
<p class="meta">Application: {report['application_id']} | Generated: {report['generated_at']} |
Sections complete: {report['data_completeness']}/{report['total_sections']}</p>

<h2>1. Loan Summary</h2>
<table>
 <tr><th>Field</th><th>Value</th></tr>
 <tr><td>Loan Amount</td><td>{_fmt_money(s1.get('loan_amount'))}</td></tr>
 <tr><td>LTV</td><td>{_fmt_pct(s1.get('ltv'))}</td></tr>
 <tr><td>Back-End DTI</td><td>{_fmt_pct(s1.get('dti_back'))}</td></tr>
 <tr><td>Mid Credit Score</td><td>{s1.get('mid_credit_score') if s1.get('mid_credit_score') is not None else 'N/A'}</td></tr>
 <tr><td>Loan Type</td><td>{s1.get('loan_type') or 'N/A'}</td></tr>
 <tr><td>Property Type</td><td>{s1.get('property_type') or 'N/A'}</td></tr>
</table>

<h2>2. Decision Summary</h2>
<div class="outcome">Final Outcome: {outcome.upper()}</div>
<p>Decision Date: {s2.get('decision_date') or 'N/A'}</p>
<p>Blocking Personas: {', '.join(s2.get('blocking_personas') or ['None'])}</p>

<h2>3. Policy Trace — {s3.get('rule_count',0)} Rules Applied</h2>
<table>
 <tr><th>Rule</th><th>Decision</th><th>Federal</th><th>Agency</th><th>Overlay</th><th>Applied</th><th>Citation</th></tr>
 {rules_html}
</table>

<h2>4. Evidence Quality — {s4.get('document_count',0)} Documents (avg conf {s4.get('avg_confidence',0)})</h2>
<table>
 <tr><th>Document</th><th>Confidence</th><th>Method</th><th>Fields</th></tr>
 {docs_html}
</table>

<h2>5. AUS Reconciliation</h2>
{aus_html}

<h2>6. Exception Status — {s6.get('exceptions_count',0)}</h2>
{exc_html}

<h2>7. Adverse Action Notice</h2>
{aa_html}

<h2>8. Compliance Attestation</h2>
<table>
 <tr><th>Check</th><th>Result</th><th>Citation</th></tr>
 <tr><td>ATR Satisfied</td>
     <td>{'Yes' if s8.get('atr_satisfied') else 'No'} ({s8.get('atr_factors_passed','?')}/{s8.get('atr_factors_checked','?')} factors)</td>
     <td>{s8.get('atr_citation','')}</td></tr>
 <tr><td>QM Classification</td><td>{s8.get('qm_classification') or 'N/A'}</td><td>{s8.get('qm_citation','')}</td></tr>
 <tr><td>Safe Harbor Protected</td><td>{'Yes' if s8.get('safe_harbor_protected') else 'No'}</td><td></td></tr>
</table>

<div class="attestation">{report['attestation']}</div>
</body></html>"""


__all__ = ["generate_repurchase_defense_report"]
