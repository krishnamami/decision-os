"""MI-F — DMN 1.3 rule export from the catalogue (MISMO BPM+ native).

MI-G proved the catalogue is DMN-expressible with a 5-rule illustrative fragment.
MI-F is the real thing: a complete, well-formed DMN 1.3 document over ALL three
sanctioned catalogue layers (regulatory + agency + overlay) for one tenant, grouped
into one <decision>/<decisionTable> per category, hitPolicy="PRIORITY" (overlay >
agency > regulatory — the same precedence rule_loader.get_rule applies).

  - Numeric threshold rows  -> real FEEL conditions (>= 620, <= 43) from the
    rule_value JSONB {operator, value}.
  - Non-numeric / no-operator rows (waiting periods, lien-treatment strings,
    disclosure timelines) -> text/annotation rules (still valid DMN, complete
    export). RULE 11: nothing is dropped; what isn't a single-field gate is
    represented honestly as an annotation rule rather than a fabricated condition.

generate_dmn_export() is a PURE builder (DB-free, unit-testable); fetch_dmn_rules()
is the thin async catalogue read; validate_dmn_xml() is stdlib ElementTree
(well-formed + structural — no lxml/xmlschema dependency). Read-only: no catalogue
writes, no persona wiring, no S3 in this slice. 16/16 by construction.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Any, Optional

DMN_NS = "https://www.omg.org/spec/DMN/20191111/MODEL/"  # OMG DMN 1.3

# Category -> the entity_states field the DMN input column tests.
CATEGORY_FIELD_MAP = {
    "credit": "mid_credit_score", "dti": "dti_back", "ltv": "ltv",
    "income": "qualifying_monthly", "asset": "total_liquid_assets",
    "reserves": "total_liquid_assets", "product": "loan_type", "fee": "loan_amount",
    "disclosure": "note_date", "property": "property_type", "mi": "ltv",
    "exception": "exception_level", "document": "document_type", "title": "title_status",
    "atr": "dti_back", "qm": "dti_back", "hpml": "note_rate",
    "fair_lending": "demographic_category", "fraud": "fraud_score", "rate": "note_rate",
    "residual_income": "residual_income", "timeline": "days_to_close",
    "reporting": "application_id", "trid": "days_to_close",
}

FEEL_OPERATOR_MAP = {
    "min": ">=", "gte": ">=", "max": "<=", "lte": "<=",
    "eq": "=", "neq": "!=", "lt": "<", "gt": ">",
}

# Lender overlays key on rule_type (lender-era names); map to the base category so
# they co-locate with the agency/regulatory rows for the same field, and synthesize
# the comparison operator the bare overlay_value implies.
OVERLAY_CATEGORY_MAP = {
    "credit_floor": "credit", "dti_back_max": "dti",
    "ltv_max_purchase": "ltv", "ltv_max_cashout": "ltv", "ltv_max_refi": "ltv",
}
OVERLAY_OPERATOR_MAP = {
    "credit_floor": "min", "dti_back_max": "max",
    "ltv_max_purchase": "max", "ltv_max_cashout": "max", "ltv_max_refi": "max",
}

_VALID_HIT_POLICIES = {"UNIQUE", "FIRST", "PRIORITY", "ANY", "COLLECT",
                       "RULE ORDER", "OUTPUT ORDER"}


def _esc(s: Any) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _feel_condition(rule_value: Any, field: str) -> tuple:
    """rule_value (a {operator,value,...} dict) -> (feel_expr|None, is_numeric, raw_value).

    A clean numeric threshold becomes a FEEL comparison; anything without a known
    operator (waiting-period values, string treatments, requirements) returns
    feel=None so the caller emits an annotation rule (no fabricated direction)."""
    if not isinstance(rule_value, dict):
        return None, False, rule_value

    op = FEEL_OPERATOR_MAP.get(str(rule_value.get("operator", "")).lower())
    val = rule_value.get("value")
    r_type = str(rule_value.get("type", "")).lower()

    if op is not None and val is not None:
        try:
            num = float(str(val).replace("%", "").replace(",", ""))
            return f"{op} {num}", True, num
        except ValueError:
            pass
    if r_type == "boolean" or str(val).lower() in ("true", "false"):
        return f"= {str(val).lower()}", False, val
    if val is not None:
        return None, False, val   # value present but no comparison direction -> annotation
    return None, False, rule_value


def _build_decision_table(category: str, rules: list, hit_policy: str = "PRIORITY") -> str:
    field = CATEGORY_FIELD_MAP.get(category, category)
    has_numeric = any(r.get("is_numeric") for r in rules)
    input_type = "number" if has_numeric else "string"

    rule_rows = ""
    for i, r in enumerate(rules):
        feel = r.get("feel")
        cond = _esc(feel) if feel else "-"   # "-" = FEEL "any" (no condition)
        val = _esc(r.get("value", ""))
        cit = _esc(r.get("citation", ""))
        name = _esc(r.get("name", ""))
        layer = _esc(r.get("layer", ""))
        rule_rows += (
            f'\n      <rule id="rule_{_esc(category)}_{i}">'
            f'\n        <description>{layer}: {name}{" (" + _esc(r["loan_type"]) + ")" if r.get("loan_type") else ""}</description>'
            f'\n        <inputEntry id="ie_{_esc(category)}_{i}"><text>{cond}</text></inputEntry>'
            f'\n        <outputEntry id="oe_{_esc(category)}_{i}"><text>"{val}"</text></outputEntry>'
            f'\n        <annotationEntry><text>{cit}</text></annotationEntry>'
            f'\n      </rule>')

    return (
        f'\n  <decision id="decision_{_esc(category)}" name="{_esc(category.replace("_", " ").title())} Rules">'
        f'\n    <decisionTable id="dt_{_esc(category)}" hitPolicy="{hit_policy}">'
        f'\n      <input id="in_{_esc(category)}" label="{_esc(field)}">'
        f'\n        <inputExpression id="iexpr_{_esc(category)}" typeRef="{input_type}"><text>{_esc(field)}</text></inputExpression>'
        f'\n      </input>'
        f'\n      <output id="out_{_esc(category)}" label="applied_value" typeRef="string"/>'
        f'\n      <annotation name="citation"/>'
        f'{rule_rows}'
        f'\n    </decisionTable>'
        f'\n  </decision>')


def generate_dmn_export(agency_rows: list, regulatory_rows: list, overlay_rows: list,
                        tenant_id: str, version: str = "v1",
                        category_filter: Optional[str] = None) -> str:
    """Build a complete DMN 1.3 document from the three catalogue layers. Pure.
    Rules are grouped by category; within each, layered overlay -> agency ->
    regulatory so the PRIORITY hit policy reflects overlay > agency > regulatory."""
    by_category: dict[str, list] = {}

    def _add(rows, layer):
        for r in rows:
            if layer == "overlay":
                rt = r.get("rule_type") or r.get("guideline_name") or "other"
                cat = OVERLAY_CATEGORY_MAP.get(rt, rt)
                raw = r.get("overlay_value", r.get("guideline_value"))
                try:
                    rv: Any = {"type": "threshold",
                               "operator": OVERLAY_OPERATOR_MAP.get(rt, "eq"),
                               "value": float(raw)}
                except (TypeError, ValueError):
                    rv = {"value": raw}
                name = rt
                citation = f"Lender overlay ({r.get('direction', 'stricter')})"
                loan_type = r.get("loan_type")
            else:
                cat = str(r.get("category") or "other").lower()
                rv = r.get("guideline_value") if r.get("guideline_value") is not None else r.get("rule_value")
                if isinstance(rv, str):
                    try:
                        rv = json.loads(rv)
                    except (ValueError, TypeError):
                        rv = {"value": rv}
                name = r.get("guideline_name") or r.get("rule_name") or ""
                citation = r.get("citation", "")
                loan_type = None
            feel, is_numeric, val = _feel_condition(rv, CATEGORY_FIELD_MAP.get(cat, cat))
            by_category.setdefault(cat, []).append({
                "name": name, "feel": feel, "value": val, "is_numeric": is_numeric,
                "citation": citation, "layer": layer, "loan_type": loan_type})

    _add(overlay_rows, "overlay")      # highest priority first
    _add(agency_rows, "agency")
    _add(regulatory_rows, "regulatory")

    if category_filter:
        by_category = {k: v for k, v in by_category.items() if k == category_filter.lower()}

    decisions = "".join(_build_decision_table(cat, rules)
                        for cat, rules in sorted(by_category.items()))
    total = sum(len(v) for v in by_category.values())

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<definitions\n'
        f'  xmlns="{DMN_NS}"\n'
        '  xmlns:dmndi="https://www.omg.org/spec/DMN/20191111/DMNDI/"\n'
        '  xmlns:dc="http://www.omg.org/spec/DMN/20180521/DC/"\n'
        f'  id="accord_{_esc(tenant_id)}_dmn"\n'
        f'  name="Accord Decision Catalogue — {_esc(tenant_id)} — {_esc(version)}"\n'
        f'  namespace="https://accord.decideos.com/dmn/{_esc(tenant_id)}">\n'
        '  <!--\n'
        f'    Accord Decision OS MI-F DMN exporter | tenant={_esc(tenant_id)} version={_esc(version)}\n'
        '    Layers: overlay (highest) > agency > regulatory (lowest) | hitPolicy=PRIORITY\n'
        f'    Categories: {len(by_category)} | Rules: {total} | OMG DMN 1.3 (MISMO BPM+)\n'
        '  -->'
        f'{decisions}\n'
        '</definitions>')


async def fetch_dmn_rules(conn, tenant_id: str) -> tuple:
    """Read the three catalogue layers for a tenant. RULE 11: returns exactly what
    the catalogue holds (active rows only); nothing synthesized here."""
    agency = await conn.fetch(
        "SELECT guideline_name, guideline_value, citation, category, agency "
        "FROM agency_guidelines WHERE is_active=true ORDER BY category, guideline_name")
    regulatory = await conn.fetch(
        "SELECT rule_name, rule_value, citation, category "
        "FROM regulatory_rules WHERE is_active=true ORDER BY category, rule_name")
    overlay = await conn.fetch(
        "SELECT rule_type, overlay_value, direction, loan_type "
        "FROM overlay_rules WHERE tenant_id=$1 AND is_active=true "
        "ORDER BY rule_type, loan_type NULLS FIRST", tenant_id)
    return ([dict(r) for r in agency], [dict(r) for r in regulatory],
            [dict(r) for r in overlay])


def validate_dmn_xml(xml_str: str) -> tuple:
    """Stdlib well-formedness + structural validation. Returns (is_valid, errors).
    Full OMG-XSD validation needs the schema file + lxml/xmlschema (a follow-up)."""
    errors: list = []
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError as e:
        return False, [f"XML parse error: {e}"]

    if not root.tag.endswith("definitions"):
        errors.append(f"root must be <definitions>, got {root.tag}")
    if "omg.org/spec/DMN" not in root.tag:
        errors.append("root not in an OMG DMN namespace")

    decisions = root.findall(f"{{{DMN_NS}}}decision")
    if not decisions:
        errors.append("no <decision> elements found")
    for dec in decisions:
        tables = dec.findall(f"{{{DMN_NS}}}decisionTable")
        if not tables:
            errors.append(f"decision {dec.get('id', '?')} has no <decisionTable>")
        for t in tables:
            hp = t.get("hitPolicy", "")
            if hp not in _VALID_HIT_POLICIES:
                errors.append(f"invalid hitPolicy {hp!r} in {dec.get('id', '?')}")
            if t.find(f"{{{DMN_NS}}}input") is None:
                errors.append(f"decisionTable in {dec.get('id', '?')} has no <input>")
            if t.find(f"{{{DMN_NS}}}output") is None:
                errors.append(f"decisionTable in {dec.get('id', '?')} has no <output>")
    return len(errors) == 0, errors


def count_rules(xml_str: str) -> int:
    """Number of <rule> elements (for tests / introspection)."""
    root = ET.fromstring(xml_str)
    return len(root.findall(f".//{{{DMN_NS}}}rule"))


__all__ = ["generate_dmn_export", "fetch_dmn_rules", "validate_dmn_xml", "count_rules",
           "CATEGORY_FIELD_MAP", "FEEL_OPERATOR_MAP", "OVERLAY_CATEGORY_MAP"]
