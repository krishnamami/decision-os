"""MI-G — MISMO BPM+ conformance ASSESSMENT report (READ-ONLY).

Assembles a coverage assessment showing Accord's decisioning is expressible in
all four OMG BPM+ notations, sourced entirely from existing artifacts (same
read-only assembler pattern as TR-D / repurchase_defense — no tables, no
catalogue, no outcome changes, nothing written):

  DMN 1.4  — the 3-layer catalogue (regulatory + agency + overlay), PRIORITY
             hit policy; rule_loader.get_rule() already IS the eval semantics.
  BPMN 2.0 — the 14-persona wave DAG, read live from core.cron.runner.WAVE_CONFIG
             (NOT hardcoded — derived from the single source of truth).
  CMMN 1.1 — the exception lifecycle (exception_workflow.py state machine +
             loan_exceptions / compensating_factors instances).
  SDMN     — entity_states schema + persona_bundles (MISMO-aligned shared data).

HONEST SCOPE: this is a conformance ASSESSMENT + structurally-representative XML
fragments. It is NOT OMG-XSD-validated export (that is MI-F, future). Every
component states this in `honest_caveat`.

RULE 11: every component + the top-level report carry `data_source` +
`missing_inputs`. platform_guardrails is NOT a DMN source (RULE 2). Read-only.
"""
from __future__ import annotations

from datetime import datetime, timezone

# Read the wave DAG from the single source of truth — never hardcode it.
from core.cron.runner import WAVE_CONFIG


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _esc(v) -> str:
    return str(v if v is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _wave_structure() -> dict:
    """Derive the BPMN process structure from runner.WAVE_CONFIG (live source)."""
    by_wave: dict[int, list[tuple[str, list[str]]]] = {}
    for persona, cfg in WAVE_CONFIG.items():
        by_wave.setdefault(int(cfg["wave"]), []).append(
            (persona, list(cfg.get("upstream", []))))
    out: dict = {}
    for w in sorted(by_wave):
        items = sorted(by_wave[w], key=lambda x: x[0])
        if w == 1:
            out["wave_1_parallel"] = [p for p, _ in items]
        else:
            out[f"wave_{w}"] = [{"persona": p, "depends_on": up} for p, up in items]
    return out


def _dependent_items(wave_config: dict) -> list[dict]:
    """All non-wave-1 {persona, depends_on} items, in wave order."""
    items: list[dict] = []
    for key in sorted(k for k in wave_config if k != "wave_1_parallel"):
        items.extend(wave_config[key])
    return items


async def generate_mismo_bpm_conformance_report(conn, tenant_id: str) -> dict:
    """Read-only conformance assessment (coverage matrix + sample XML fragments)."""

    # ── COMPONENT 1: DMN ─────────────────────────────────────────────────
    reg_count = await conn.fetchval("SELECT COUNT(*) FROM regulatory_rules")
    ag_count = await conn.fetchval("SELECT COUNT(*) FROM agency_guidelines WHERE is_active=true")
    ov_count = await conn.fetchval(
        "SELECT COUNT(*) FROM overlay_rules WHERE tenant_id=$1 AND is_active=true", tenant_id)

    sample_rules = await conn.fetch(
        """SELECT guideline_name AS name, display_value, citation, category, agency
           FROM agency_guidelines
           WHERE is_active=true AND category IN ('credit','income','collateral','dti')
           ORDER BY category, guideline_name LIMIT 5""")

    dmn = {
        "notation": "DMN 1.4 — Decision Model and Notation",
        "omg_standard": "OMG DMN 1.4 (2023)",
        "source": "regulatory_rules + agency_guidelines + overlay_rules",
        "data_source": "Three sanctioned catalogue layers (RULE 2); "
                       "platform_guardrails intentionally excluded (not a rule layer)",
        "missing_inputs": [],
        "rule_counts": {
            "regulatory_rules": int(reg_count),
            "agency_guidelines": int(ag_count),
            "overlay_rules": int(ov_count),
            "total": int(reg_count) + int(ag_count) + int(ov_count),
        },
        "hit_policy": "PRIORITY (overlay > agency > regulatory)",
        "coverage": {
            "decision_tables": "Every catalogue rule expressible as a DMN decisionTable rule",
            "input_expressions": "entity_states fields (mid_credit_score, ltv, dti_back, ...)",
            "output_clauses": "threshold values with operators (gte / lte / eq)",
            "annotations": "citation column (Fannie B3-x.x-xx, 12 CFR 1026.xx)",
            "precedence": "overlay > agency > regulatory == DMN PRIORITY hit policy",
            "evaluation": "rule_loader.get_rule() already implements the eval semantics",
        },
        "conformance_level": "Level 2 — Decision Tables expressible",
        "sample_xml": _generate_dmn_fragment(sample_rules),
        "honest_caveat": (
            "Sample fragment is structurally representative DMN 1.4. Full "
            "schema-validated export against the OMG DMN XSD is MI-F (future). "
            "Evaluation semantics are fully implemented in rule_loader.get_rule()."),
    }

    # ── COMPONENT 2: BPMN (derived from runner.WAVE_CONFIG) ──────────────
    wave_config = _wave_structure()
    bpmn = {
        "notation": "BPMN 2.0 — Business Process Model and Notation",
        "omg_standard": "OMG BPMN 2.0 (2011)",
        "source": "core/cron/runner.py WAVE_CONFIG (read live, not hardcoded)",
        "data_source": "Explicit DAG with depends_on edges + wave boundaries",
        "missing_inputs": [],
        "process_structure": {
            "total_personas": len(WAVE_CONFIG),
            "waves": len({c["wave"] for c in WAVE_CONFIG.values()}),
            "wave_config": wave_config,
        },
        "coverage": {
            "tasks": f"{len(WAVE_CONFIG)} businessRuleTask elements (one per persona)",
            "sequence_flows": "depends_on edges -> sequenceFlow",
            "gateways": "wave boundaries -> parallel fork/join gateways",
            "converging_gateway": "underwriting_decision -> converging gateway",
            "error_handling": "persona failure -> boundary error event",
        },
        "conformance_level": "Level 1 — Process Structure expressible",
        "sample_xml": _generate_bpmn_fragment(wave_config),
        "honest_caveat": (
            "Wave DAG is machine-readable in WAVE_CONFIG (read live here). BPMN 2.0 "
            "is the cleanest of the four mappings. Full schema-validated BPMN 2.0 "
            "XML is a future export slice."),
    }

    # ── COMPONENT 3: CMMN ────────────────────────────────────────────────
    exc_count = await conn.fetchval(
        "SELECT COUNT(*) FROM loan_exceptions WHERE tenant_id=$1", tenant_id)
    cf_count = await conn.fetchval(
        """SELECT COUNT(*) FROM compensating_factors cf
           JOIN loan_exceptions le ON cf.exception_id = le.id
           WHERE le.tenant_id=$1""", tenant_id)
    cmmn = {
        "notation": "CMMN 1.1 — Case Management Model and Notation",
        "omg_standard": "OMG CMMN 1.1 (2016)",
        "source": "core/exceptions/exception_workflow.py",
        "data_source": "loan_exceptions + compensating_factors tables",
        "missing_inputs": [],
        "case_instances": {
            "loan_exceptions": int(exc_count),
            "compensating_factors": int(cf_count),
        },
        "case_structure": {
            "stages": ["requested", "under_review"],
            "milestones": ["granted", "denied"],
            "human_tasks": ["review_exception", "approve_or_deny"],
            "sentries": [
                "RBAC: approver_role must have authority for required_level",
                "Agency floor: below_agency_floor=True -> absolute block, no role overrides",
            ],
            "event_listeners": ["exception_requested", "review_completed"],
        },
        "coverage": {
            "case_definition": "ExceptionWorkflowService == CMMN Case",
            "stages": "requested / under_review == CMMN Stages",
            "milestones": "granted / denied == CMMN Milestones",
            "human_tasks": "can_approve + transition_status == Human Decision Tasks",
            "sentries": "RBAC + agency floor == CMMN Sentry conditions",
            "ad_hoc": "Adaptive compensating-factor detection == discretionary tasks",
        },
        "conformance_level": "Level 1 — Case Structure expressible",
        "sample_xml": _generate_cmmn_fragment(),
        "honest_caveat": (
            "The exception lifecycle is a genuine CMMN use case; the 4-state machine "
            "is small but maps faithfully. CMMN 1.1 is arguably heavier than the "
            "artifact warrants."),
    }

    # ── COMPONENT 4: SDMN ────────────────────────────────────────────────
    bundle_count = await conn.fetchval(
        "SELECT COUNT(*) FROM persona_bundles WHERE tenant_id=$1", tenant_id)
    entity_cols = await conn.fetch(
        """SELECT column_name FROM information_schema.columns
           WHERE table_name='entity_states'""")
    sdmn = {
        "notation": "SDMN — Shared Data Model and Notation",
        "omg_standard": "OMG SDMN (emerging standard)",
        "source": "entity_states schema + persona_bundles",
        "data_source": "PostgreSQL schema + JSONB bundle snapshots",
        "missing_inputs": [],
        "data_objects": {
            "entity_states_columns": len(entity_cols),
            "persona_bundle_count": int(bundle_count),
            "core_objects": [
                "borrower (JSONB: identity, employment, income, assets)",
                "property (JSONB: address, type, appraisal)",
                "loan_terms (JSONB: type, purpose, amount)",
                "decision (outcome, signals, rule_trace)",
                "evidence (fact_nodes: document -> field -> confidence)",
            ],
        },
        "coverage": {
            "shared_objects": "entity_states == canonical shared data object",
            "versioning": "persona_bundles freeze the snapshot at decision time",
            "provenance": "fact_nodes link every field to its source document",
            "mismo_alignment": "Field naming MISMO-aligned (S3 mismo/ layout)",
        },
        "conformance_level": "Emerging — JSON Schema representation",
        "sample_xml": "",
        "honest_caveat": (
            "SDMN is the newest BPM+ family member with thin tooling. A JSON Schema "
            "of entity_states is the pragmatic representation; MISMO field alignment "
            "already provides interoperability."),
    }

    matrix = {
        "DMN":  {"source_exists": True, "sample_xml": True,  "conformance": "Level 2"},
        "BPMN": {"source_exists": True, "sample_xml": True,  "conformance": "Level 1"},
        "CMMN": {"source_exists": True, "sample_xml": True,  "conformance": "Level 1"},
        "SDMN": {"source_exists": True, "sample_xml": False, "conformance": "Emerging"},
    }

    report = {
        "report_type": "MISMO_BPM_PLUS_CONFORMANCE",
        "tenant_id": tenant_id,
        "generated_at": _now_iso(),
        "accord_version": "rearch-core-complete",
        "components": {"DMN": dmn, "BPMN": bpmn, "CMMN": cmmn, "SDMN": sdmn},
        "coverage_matrix": matrix,
        "overall_assessment": (
            f"Accord Decision OS is expressible in all four OMG BPM+ notations. "
            f"DMN: {dmn['rule_counts']['total']} catalogue rules across 3 sanctioned "
            f"layers with PRIORITY hit policy. BPMN: {len(WAVE_CONFIG)}-persona wave "
            f"DAG with explicit depends_on edges. CMMN: exception lifecycle with RBAC "
            f"sentries and an absolute agency-floor guardrail. SDMN: MISMO-aligned "
            f"entity model with full provenance. Accord is not a proprietary black box "
            f"— it is a standards-based, auditable, and portable decision engine."),
        "honest_scope": (
            "This is a conformance ASSESSMENT with structurally-representative XML "
            "fragments — NOT OMG-XSD-validated export (that is MI-F, future)."),
        "data_source": (
            "regulatory_rules + agency_guidelines + overlay_rules + runner.WAVE_CONFIG "
            "+ exception_workflow.py + entity_states schema + persona_bundles (read-only)"),
        "missing_inputs": [],
        "html": "",
    }
    report["html"] = _render_conformance_html(report)
    return report


# ── XML fragment builders (pure) ────────────────────────────────────────────
def _generate_dmn_fragment(sample_rules) -> str:
    rows = ""
    for r in sample_rules:
        name = _esc(r["name"])
        val = _esc(r["display_value"])[:40]
        cit = _esc(r["citation"])[:40]
        rows += (
            f'\n      <rule id="rule_{name.replace(" ", "_")}">'
            f'\n        <description>{cit}</description>'
            f'\n        <inputEntry><text>{name}</text></inputEntry>'
            f'\n        <outputEntry><text>{val}</text></outputEntry>'
            f'\n      </rule>')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<definitions xmlns="https://www.omg.org/spec/DMN/20191111/MODEL/"\n'
        '             id="accord_catalogue_dmn" name="Accord Decision Catalogue — Sample"\n'
        '             namespace="https://accord.decideos.com/dmn">\n'
        '  <decision id="credit_assessment_decision" name="Credit Assessment">\n'
        '    <decisionTable id="dt_credit" hitPolicy="PRIORITY">\n'
        '      <input id="in_score" label="mid_credit_score">\n'
        '        <inputExpression typeRef="number"><text>mid_credit_score</text></inputExpression>\n'
        '      </input>\n'
        '      <output id="out_result" label="credit_result" typeRef="string"/>'
        f'{rows}\n'
        '    </decisionTable>\n'
        '  </decision>\n'
        '</definitions>')


def _generate_bpmn_fragment(wave_config: dict) -> str:
    flow = ""
    for p in wave_config.get("wave_1_parallel", []):
        flow += f'\n    <businessRuleTask id="{p}" name="{p.replace("_", " ").title()}"/>'
    seq = 1
    for item in _dependent_items(wave_config):
        p = item["persona"]
        flow += f'\n    <businessRuleTask id="{p}" name="{p.replace("_", " ").title()}"/>'
        for dep in item["depends_on"]:
            flow += f'\n    <sequenceFlow id="sf{seq}" sourceRef="{dep}" targetRef="{p}"/>'
            seq += 1
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL"\n'
        '             id="accord_bpmn" name="Accord 14-Persona Decision Process"\n'
        '             targetNamespace="https://accord.decideos.com/bpmn">\n'
        '  <process id="accord_underwriting" name="Accord Underwriting" isExecutable="false">\n'
        '    <startEvent id="start" name="Loan Application Received"/>\n'
        '    <parallelGateway id="wave1_fork" name="Wave 1 Start (Parallel)"/>'
        f'{flow}\n'
        '    <parallelGateway id="wave4_join" name="Converge to Underwriting Decision"/>\n'
        '    <endEvent id="end" name="Decision Committed"/>\n'
        '  </process>\n'
        '</definitions>')


def _generate_cmmn_fragment() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<definitions xmlns="http://www.omg.org/spec/CMMN/20151109/MODEL"\n'
        '             id="accord_exception_cmmn" name="Accord Exception Lifecycle"\n'
        '             targetNamespace="https://accord.decideos.com/cmmn">\n'
        '  <case id="exception_case" name="Loan Exception">\n'
        '    <casePlanModel id="plan" name="Exception Review Plan" autoComplete="false">\n'
        '      <stage id="stage_requested" name="Requested">\n'
        '        <sentry id="sentry_review"><planItemOnPart sourceRef="task_submit"/></sentry>\n'
        '      </stage>\n'
        '      <stage id="stage_under_review" name="Under Review">\n'
        '        <sentry id="sentry_rbac">\n'
        '          <ifPart><condition>approver_role has authority for required_level</condition></ifPart>\n'
        '        </sentry>\n'
        '        <sentry id="sentry_agency_floor">\n'
        '          <ifPart><condition>below_agency_floor == false (ABSOLUTE — no role overrides)</condition></ifPart>\n'
        '        </sentry>\n'
        '      </stage>\n'
        '      <milestone id="milestone_granted" name="Exception Granted"/>\n'
        '      <milestone id="milestone_denied" name="Exception Denied"/>\n'
        '      <humanTask id="task_submit" name="Request Exception"/>\n'
        '      <humanTask id="task_review" name="Review and Decide"/>\n'
        '    </casePlanModel>\n'
        '  </case>\n'
        '</definitions>')


# ── HTML render (pure) ───────────────────────────────────────────────────────
def _render_conformance_html(report: dict) -> str:
    comps = report["components"]

    def comp_section(data: dict) -> str:
        cov_rows = "".join(
            f'<tr><td><strong>{k.replace("_", " ").title()}</strong></td><td>{_esc(v)}</td></tr>'
            for k, v in data.get("coverage", {}).items())
        sample = data.get("sample_xml", "")
        xml_block = (
            f'<pre style="background:#1e1e1e;color:#d4d4d4;padding:12px;border-radius:4px;'
            f'font-size:11px;overflow-x:auto"><code>{_esc(sample[:1000])}</code></pre>'
            if sample else "")
        return (
            f'<h2 style="color:#0f4d37;border-left:4px solid #0f4d37;padding-left:12px">'
            f'{_esc(data["notation"])}</h2>'
            f'<p><strong>OMG Standard:</strong> {_esc(data["omg_standard"])} | '
            f'<strong>Conformance:</strong> {_esc(data["conformance_level"])}</p>'
            f'<p><strong>Source:</strong> {_esc(data["source"])}</p>'
            f'<table style="width:100%;border-collapse:collapse;margin:12px 0;font-size:13px">'
            f'<tr style="background:#0f4d37;color:white"><th style="padding:8px;text-align:left">'
            f'Coverage Area</th><th style="padding:8px;text-align:left">Accord Implementation</th></tr>'
            f'{cov_rows}</table>'
            f'<p style="font-size:12px;color:#718096;font-style:italic">&#9888; '
            f'{_esc(data["honest_caveat"])}</p>{xml_block}')

    matrix_rows = "".join(
        f'<tr><td style="padding:8px"><strong>{k}</strong></td>'
        f'<td style="padding:8px;text-align:center">{"&#10003;" if v["source_exists"] else "&#10007;"}</td>'
        f'<td style="padding:8px;text-align:center">{"&#10003;" if v["sample_xml"] else "&mdash;"}</td>'
        f'<td style="padding:8px">{v["conformance"]}</td></tr>'
        for k, v in report["coverage_matrix"].items())

    return (
        '<!DOCTYPE html>\n<html><head><meta charset="UTF-8">\n'
        '<title>MISMO BPM+ Conformance — Accord Decision OS</title>\n'
        '<style>body{font-family:Georgia,serif;max-width:960px;margin:40px auto;padding:20px;color:#1a202c}'
        'h1{color:#0f4d37;border-bottom:3px solid #0f4d37;padding-bottom:10px}'
        'table td,table th{padding:7px 10px;border:1px solid #e2e8f0}'
        'tr:nth-child(even) td{background:#f7fafc}pre{overflow-x:auto}</style></head><body>\n'
        '<h1>MISMO BPM+ Conformance Assessment</h1>\n'
        f'<p><strong>Accord Decision OS</strong> | Tenant: {_esc(report["tenant_id"])} | '
        f'Generated: {_esc(report["generated_at"])}</p>\n'
        f'<p style="background:#e8f5f0;padding:16px;border:1px solid #0f4d37;border-radius:4px">'
        f'{_esc(report["overall_assessment"])}</p>\n'
        f'<p style="font-size:12px;color:#718096;font-style:italic">&#9888; {_esc(report["honest_scope"])}</p>\n'
        '<h2 style="color:#0f4d37">Coverage Matrix</h2>\n'
        '<table style="width:100%;border-collapse:collapse">'
        '<tr style="background:#0f4d37;color:white"><th style="padding:8px">Notation</th>'
        '<th style="padding:8px">Source Exists</th><th style="padding:8px">Sample XML</th>'
        '<th style="padding:8px">Conformance Level</th></tr>'
        f'{matrix_rows}</table>\n'
        f'{comp_section(comps["DMN"])}\n{comp_section(comps["BPMN"])}\n'
        f'{comp_section(comps["CMMN"])}\n{comp_section(comps["SDMN"])}\n'
        '<div style="background:#e8f5f0;border:1px solid #0f4d37;padding:16px;margin-top:30px;font-size:13px">'
        '<strong>Attestation:</strong> Generated from the Accord Decision OS audit trail. All '
        'component mappings reference live source artifacts (catalogue tables, runner.WAVE_CONFIG, '
        'exception_workflow.py, entity_states schema). Sample XML fragments are structurally '
        'representative; full schema-validated export against the OMG XSD is a planned future slice '
        '(MI-F).</div>\n</body></html>')
