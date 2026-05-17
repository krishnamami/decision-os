from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

from fastapi.templating import Jinja2Templates

from api.deps import Platform
from core.normalizer.models import DecisionMode, DecisionOutcome
from core.policy_engine.evaluator import _evaluate_rule  # internal but stable
from core.trace import DecisionTrace

# Persona panels — mapping is here, not on the persona class, so the UI
# layer owns its own rendering decisions and personas stay headless.
PERSONA_PANELS: dict[str, str] = {
    "lead_scoring":          "personas/_lead_scoring.html",
    "income_verification":   "personas/_income_verification.html",
    "credit_assessment":     "personas/_credit_assessment.html",
    "fraud_screening":       "personas/_fraud_screening.html",
    "compliance_check":      "personas/_compliance_check.html",
    "dti_calculation":       "personas/_dti_calculation.html",
    "ltv_assessment":        "personas/_ltv_assessment.html",
    "product_eligibility":   "personas/_product_eligibility.html",
    "rate_pricing":          "personas/_rate_pricing.html",
    "underwriting_decision": "personas/_underwriting_decision.html",
    "approval_routing":      "personas/_approval_routing.html",
    "closing_readiness":     "personas/_closing_readiness.html",
}


# ─────────────────────────────────────────────────────────────────────
# Templates + view-model helpers.
#
# Routes stay thin: pull data from the Platform, hand it through the
# helpers below into a typed view-model dict, render. All templating
# logic that's >1 line lives here, not in Jinja, so the templates stay
# legible and the logic stays unit-testable.
# ─────────────────────────────────────────────────────────────────────


TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# Color palette per outcome — keeps the CSS classes in one place so
# every view tints consistently.
OUTCOME_STYLES: dict[str, dict[str, str]] = {
    "allow":     {"bg": "bg-emerald-100", "text": "text-emerald-800", "border": "border-emerald-300", "dot": "bg-emerald-500"},
    "recommend": {"bg": "bg-amber-100",   "text": "text-amber-800",   "border": "border-amber-300",   "dot": "bg-amber-500"},
    "escalate":  {"bg": "bg-orange-100",  "text": "text-orange-800",  "border": "border-orange-300",  "dot": "bg-orange-500"},
    "block":     {"bg": "bg-rose-100",    "text": "text-rose-800",    "border": "border-rose-300",    "dot": "bg-rose-500"},
    "skipped":   {"bg": "bg-slate-100",   "text": "text-slate-600",   "border": "border-slate-300",   "dot": "bg-slate-400"},
    "pending":   {"bg": "bg-slate-50",    "text": "text-slate-500",   "border": "border-slate-200",   "dot": "bg-slate-300"},
}

MODE_LABELS: dict[str, str] = {
    "auto_execute":   "auto",
    "human_approval": "human",
    "recommend":      "rec",
    "shadow":         "shadow",
}


# ─────────────────────────────────────────────────────────────────────
# Application list — top-level summary across every known app.
# ─────────────────────────────────────────────────────────────────────


def list_applications(platform: Platform) -> list[dict[str, Any]]:
    """Walk the durable store + trace writer, return one row per app."""

    durable = platform.store._durable  # type: ignore[attr-defined]
    records = getattr(durable, "_records", None) or []

    # Distinct application ids from Application entity rows.
    app_ids: set[str] = {
        r.entity_id for r in records
        if r.entity_type == "Application"
        and r.decision_id is None
        and r.superseded_at is None
    }

    rows: list[dict[str, Any]] = []
    for app_id in sorted(app_ids):
        traces = _all_traces_sync(platform, app_id)
        outcomes = _outcomes_by_decision(traces)
        completed = [t for t in traces]
        halted = any(
            t.outcome == DecisionOutcome.BLOCK and t.decision_id == "fraud_screening"
            for t in traces
        )
        halt_reason = "fraud_block_stops_pipeline" if halted else None

        # Application object for richer display.
        app_record = next(
            (r for r in records
             if r.entity_type == "Application" and r.entity_id == app_id
             and r.superseded_at is None),
            None,
        )
        app_value = app_record.value if app_record else {}

        rows.append({
            "application_id": app_id,
            "loan_purpose":   app_value.get("loan_purpose"),
            "requested_amount": app_value.get("requested_amount"),
            "property_state": app_value.get("property_state"),
            "submitted_at":   app_value.get("submitted_at"),
            "completed":      len(completed),
            "halted":         halted,
            "halt_reason":    halt_reason,
            "outcome_counts": _count_outcomes(outcomes),
            "queued_count":   _count_queued(platform, app_id),
        })
    return rows


def _all_traces_sync(platform: Platform, app_id: str) -> list[DecisionTrace]:
    # InMemoryTraceWriter exposes its dict directly; same shape as the
    # async list_for_application but doesn't need an event loop. The
    # routes call this synchronously at render time.
    writer = platform.trace_writer
    by_app = getattr(writer, "_traces", None)
    if by_app is None:
        return []
    return [t for t in by_app.values() if t.application_id == app_id]


def _outcomes_by_decision(traces: list[DecisionTrace]) -> dict[str, DecisionOutcome]:
    return {t.decision_id: t.outcome for t in traces}


def _count_outcomes(outcomes: dict[str, DecisionOutcome]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for o in outcomes.values():
        counts[o.value] += 1
    return dict(counts)


def _count_queued(platform: Platform, app_id: str) -> int:
    items = getattr(platform.human_queue, "_items", {})
    return sum(1 for v in items.values() if v.application_id == app_id)


# ─────────────────────────────────────────────────────────────────────
# Application detail — DAG-shape grid by execution wave.
# ─────────────────────────────────────────────────────────────────────


def application_detail(platform: Platform, app_id: str) -> dict[str, Any]:
    spec = platform.spec
    traces = _all_traces_sync(platform, app_id)
    trace_by_id: dict[str, DecisionTrace] = {t.decision_id: t for t in traces}
    queued_ids = {
        v.decision_id for v in getattr(platform.human_queue, "_items", {}).values()
        if v.application_id == app_id
    }

    waves: list[list[dict[str, Any]]] = []
    for wave_ids in spec.execution_waves:
        wave_cards: list[dict[str, Any]] = []
        for did in wave_ids:
            decision_spec = spec.decision_index.get(did, {})
            trace = trace_by_id.get(did)
            wave_cards.append(_decision_card(decision_spec, trace, did in queued_ids))
        waves.append(wave_cards)

    durable = platform.store._durable  # type: ignore[attr-defined]
    records = getattr(durable, "_records", None) or []
    app_record = next(
        (r for r in records
         if r.entity_type == "Application" and r.entity_id == app_id
         and r.superseded_at is None),
        None,
    )

    return {
        "application_id": app_id,
        "application":    app_record.value if app_record else {},
        "waves":          waves,
        "wave_labels":    _wave_labels(spec.execution_waves),
        "queued_count":   len(queued_ids),
    }


def _decision_card(
    spec: dict[str, Any],
    trace: Optional[DecisionTrace],
    queued: bool,
) -> dict[str, Any]:
    if trace is not None:
        outcome = trace.outcome.value
        confidence = trace.confidence
        matched_clause = trace.matched_clause
        ran = True
    else:
        outcome = "pending"
        confidence = None
        matched_clause = None
        ran = False

    return {
        "decision_id":     spec.get("id"),
        "name":            spec.get("name"),
        "persona":         spec.get("persona"),
        "mode":            spec.get("mode"),
        "mode_label":      MODE_LABELS.get(spec.get("mode", ""), spec.get("mode")),
        "risk_level":      spec.get("risk_level"),
        "owner_team":      spec.get("owner_team"),
        "depends_on":      [d["decision"] for d in spec.get("depends_on") or []],
        "outcome":         outcome,
        "outcome_style":   OUTCOME_STYLES.get(outcome, OUTCOME_STYLES["pending"]),
        "confidence":      confidence,
        "matched_clause":  matched_clause,
        "ran":             ran,
        "queued":          queued,
        "trace_id":        str(trace.trace_id) if trace else None,
    }


def _wave_labels(waves: list[list[str]]) -> list[str]:
    if not waves:
        return []
    labels = ["Independent (parallel)"]
    for i in range(1, len(waves)):
        labels.append(f"Dependent wave {i}")
    return labels


# ─────────────────────────────────────────────────────────────────────
# Decision detail — bundle, journal, policy, critic, output, override.
# ─────────────────────────────────────────────────────────────────────


def decision_detail(
    platform: Platform, app_id: str, decision_id: str
) -> Optional[dict[str, Any]]:
    spec = platform.spec
    if decision_id not in spec.decision_index:
        return None

    traces = _all_traces_sync(platform, app_id)
    trace = next((t for t in traces if t.decision_id == decision_id), None)
    decision_spec = spec.decision_index.get(decision_id, {})
    queued_item = next(
        (v for v in getattr(platform.human_queue, "_items", {}).values()
         if v.application_id == app_id and v.decision_id == decision_id),
        None,
    )

    learnings = []
    if trace is not None:
        try:
            learnings = _sync_recall(platform, trace.agent_id, decision_id)
        except Exception:
            learnings = []

    bundle_objects = _bundle_for_decision(platform, app_id, decision_id)
    upstream_outputs = _upstream_outputs(platform, app_id, decision_spec)

    boundary = decision_spec.get("boundary") or {}
    output_payload = trace.output_payload if trace else {}
    boundary_eval = _evaluate_boundary(boundary, output_payload, bundle_objects)

    routing_target = (
        _routing_target(trace.mode.value, trace.outcome.value) if trace else None
    )
    upstream_status = _upstream_status_rows(
        traces, decision_spec, platform.spec.decision_index
    )
    read_permissions = _read_permissions(decision_id)
    atomic_steps = _atomic_pipeline(trace, routing_target)
    persona_panel = PERSONA_PANELS.get(decision_id)
    persona_view = _persona_view(decision_id, trace, decision_spec)
    contamination_guard = decision_spec.get("contamination_guard") or {}

    policy_panel = _policy_panel(platform, trace)
    evidence_panel = _evidence_panel(platform, app_id, decision_id, trace=trace)
    audit_panel = _audit_panel_for_trace(platform, trace)

    return {
        "application_id": app_id,
        "decision_id":    decision_id,
        "spec":           decision_spec,
        "trace":          trace,
        "trace_dict":     trace.model_dump(mode="json") if trace else None,
        "queued_item":    queued_item,
        "boundary":       boundary,
        "boundary_eval":  boundary_eval,
        "bundle_objects": bundle_objects,
        "upstream_outputs": upstream_outputs,
        "upstream_status": upstream_status,
        "read_permissions": read_permissions,
        "routing_target": routing_target,
        "atomic_steps":   atomic_steps,
        "persona_panel":  persona_panel,
        "persona_view":   persona_view,
        "policy_panel":   policy_panel,
        "evidence_panel": evidence_panel,
        "audit_panel":    audit_panel,
        "contamination_guard": contamination_guard,
        "learnings":      learnings,
        "outcome_style":  OUTCOME_STYLES.get(
            trace.outcome.value if trace else "pending",
            OUTCOME_STYLES["pending"],
        ),
        "outcome_palette": OUTCOME_STYLES,
        "decision_modes": [m.value for m in DecisionMode],
        "decision_outcomes": [o.value for o in DecisionOutcome],
    }


def _bundle_for_decision(
    platform: Platform, app_id: str, decision_id: str
) -> dict[str, dict[str, dict[str, Any]]]:
    """Re-derive what the agent would currently see for this decision.

    Not the original snapshot the trace was built from — that's pinned
    by inputs_snapshot_id and would require a snapshot read by id. For
    v0 we show the *current* world the way the personas read it; if
    they diverge from the trace that itself is interesting."""

    from core.ontology import LENDING_OBJECT_TYPES

    durable = platform.store._durable  # type: ignore[attr-defined]
    records = getattr(durable, "_records", None) or []

    out: dict[str, dict[str, dict[str, Any]]] = {}
    for ot_id, ot in LENDING_OBJECT_TYPES.items():
        if decision_id not in ot.decisions_that_read_it:
            continue
        entities: dict[str, dict[str, Any]] = {}
        for r in records:
            if r.entity_type != ot_id or r.decision_id is not None or r.superseded_at is not None:
                continue
            value = r.value if isinstance(r.value, dict) else {}
            # Filter to this application — same logic as the resolver.
            if ot_id == "Application" and r.entity_id != app_id:
                continue
            if (ot_id not in ("Application", "Applicant")
                and value.get("application_id") not in (app_id, None)):
                continue
            try:
                entities[r.entity_id] = ot.to_context_bundle(value, decision_id)
            except (PermissionError, KeyError):
                continue
        if entities:
            out[ot_id] = entities
    return out


def _upstream_outputs(
    platform: Platform, app_id: str, decision_spec: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    durable = platform.store._durable  # type: ignore[attr-defined]
    records = getattr(durable, "_records", None) or []
    upstream_ids = [d["decision"] for d in decision_spec.get("depends_on") or []]

    out: dict[str, dict[str, Any]] = {}
    for upstream in upstream_ids:
        target_eid = f"{app_id}:{upstream}"
        rec = next(
            (r for r in records
             if r.entity_type == "decision" and r.entity_id == target_eid
             and r.decision_id == upstream and r.superseded_at is None),
            None,
        )
        out[upstream] = rec.value if rec else {}
    return out


# ─────────────────────────────────────────────────────────────────────
# Cross-cutting view helpers — one place per concept so all personas
# light the same way.
# ─────────────────────────────────────────────────────────────────────


def _routing_target(mode: str, outcome: str) -> dict[str, str]:
    """Mirrors ModeRouter.route. Trace doesn't persist routed.action, so
    we derive it for the UI from (mode, outcome). Source of truth is
    core/decision_agents/mode_router.py."""

    if outcome == "block":
        action, label, tone = "block_writeback", "block · writeback", "rose"
    elif mode == "shadow":
        action, label, tone = "shadow_record", "shadow · trace only", "slate"
    elif mode in ("human_approval", "recommend") or outcome in ("recommend", "escalate"):
        action, label, tone = "queue_human", "queued · human review", "amber"
    else:
        action, label, tone = "auto_writeback", "auto · written back", "emerald"
    return {"action": action, "label": label, "tone": tone}


def _evaluate_boundary(
    boundary: dict[str, list[str]],
    output_payload: dict[str, Any],
    bundle_objects: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    """Evaluate every boundary rule against current values so the UI
    can light each rule ✓/✗.

    Mirrors AtomicTool._policy_context flattening: bundle objects first
    (lowest precedence), then output_payload (highest). decision lookups
    aren't supported here — they're only relevant for upstream and
    we surface those separately."""

    ctx: dict[str, Any] = {}
    for ot_id, entities in (bundle_objects or {}).items():
        for _eid, fields in entities.items():
            if not isinstance(fields, dict):
                continue
            for k, v in fields.items():
                if k.startswith("_"):
                    continue
                ctx.setdefault(k, v)
            ctx.setdefault(ot_id, fields)
    for k, v in (output_payload or {}).items():
        ctx[k] = v

    out: dict[str, dict[str, Any]] = {}
    for clause_name, rules in (boundary or {}).items():
        rules = rules or []
        rule_results: list[dict[str, Any]] = []
        all_matched = True if rules else False
        for rule in rules:
            try:
                matched = _evaluate_rule(rule, ctx)
                error = None
            except Exception as err:
                matched = False
                error = str(err)
            rule_results.append({"rule": rule, "matched": matched, "error": error})
            if not matched:
                all_matched = False
        out[clause_name] = {
            "all_matched": all_matched,
            "rules": rule_results,
            "rule_count": len(rules),
        }
    return out


def _upstream_status_rows(
    traces: list[DecisionTrace],
    decision_spec: dict[str, Any],
    decision_index: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """For dependents: one row per declared upstream with its outcome +
    confidence so the user can see at a glance whether contamination /
    block propagation will fire."""

    upstream_ids = [d["decision"] for d in decision_spec.get("depends_on") or []]
    if not upstream_ids:
        return []
    by_decision = {t.decision_id: t for t in traces}
    rows: list[dict[str, Any]] = []
    for did in upstream_ids:
        upstream_trace = by_decision.get(did)
        upstream_spec = decision_index.get(did, {})
        if upstream_trace is not None:
            outcome = upstream_trace.outcome.value
            confidence = upstream_trace.confidence
        else:
            outcome = "pending"
            confidence = None
        rows.append({
            "decision_id": did,
            "name":        upstream_spec.get("name", did),
            "outcome":     outcome,
            "outcome_style": OUTCOME_STYLES.get(outcome, OUTCOME_STYLES["pending"]),
            "confidence":  confidence,
            "trace_id":    str(upstream_trace.trace_id) if upstream_trace else None,
        })
    return rows


def _read_permissions(decision_id: str) -> list[str]:
    """ObjectType ids this decision is allowed to read — the
    no_agent_without_permissions hard rule made visible.

    Reads the ontology directly so the chip row never drifts from the
    actual projection."""

    from core.ontology import LENDING_OBJECT_TYPES
    return sorted(
        ot_id for ot_id, ot in LENDING_OBJECT_TYPES.items()
        if decision_id in ot.decisions_that_read_it
    )


def _atomic_pipeline(
    trace: Optional[DecisionTrace], routing_target: Optional[dict[str, str]]
) -> list[dict[str, Any]]:
    """7 steps from PRD §7. Visible as a strip so the user reads the
    decision through the contract, not just the headline outcome."""

    if trace is None:
        return [
            {"label": "context_build",     "status": "pending"},
            {"label": "policy_pre_check",  "status": "pending"},
            {"label": "agent reason",      "status": "pending"},
            {"label": "policy_check",      "status": "pending"},
            {"label": "critic",            "status": "pending"},
            {"label": "trace_write",       "status": "pending"},
            {"label": "mode_route",        "status": "pending"},
        ]

    critic_label = (
        trace.critic_review.verdict.value if trace.critic_review else "skipped (low risk)"
    )
    critic_status = "matched" if trace.critic_review else "skipped"
    return [
        {"label": "context_build",
         "status": "matched",
         "value":  f"snapshot {str(trace.inputs_snapshot_id)[:8]}"},
        {"label": "policy_pre_check",
         "status": "matched",
         "value":  "hard rules + contamination"},
        {"label": "agent reason",
         "status": "matched",
         "value":  trace.agent_id},
        {"label": "policy_check",
         "status": "matched",
         "value":  trace.matched_clause or "no match → escalate"},
        {"label": "critic",
         "status": critic_status,
         "value":  critic_label},
        {"label": "trace_write",
         "status": "matched",
         "value":  str(trace.trace_id)[:8]},
        {"label": "mode_route",
         "status": "matched",
         "value":  routing_target["label"] if routing_target else "—"},
    ]


def _persona_view(
    decision_id: str,
    trace: Optional[DecisionTrace],
    decision_spec: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """Per-persona view-model. None when no panel exists."""

    if decision_id not in PERSONA_PANELS or trace is None:
        return None
    builder = _PERSONA_VIEW_BUILDERS.get(decision_id)
    if builder is None:
        return None
    return builder(trace, decision_spec)


# ─────────────────────────────────────────────────────────────────────
# Tiny shared helpers used by per-persona view-models.
# ─────────────────────────────────────────────────────────────────────


def _pct_of(value: Any, lo: float, hi: float) -> Optional[float]:
    if value is None or hi == lo:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(100.0, ((v - lo) / (hi - lo)) * 100.0))


def _traffic_tone(value: Any, green_below: float, amber_below: float) -> str:
    """Tone for a 0..1 risk-style score where lower is better."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "slate"
    if v < green_below:
        return "emerald"
    if v < amber_below:
        return "amber"
    return "rose"


def _flag(label: str, value: Any, trigger: str, *, fired: Optional[bool] = None) -> dict[str, Any]:
    is_fired = bool(value) if fired is None else bool(fired)
    return {
        "label": label,
        "value": value,
        "trigger": trigger,
        "fired": is_fired,
    }


def _credit_assessment_view(
    trace: DecisionTrace, decision_spec: dict[str, Any]
) -> dict[str, Any]:
    """Gauge + band data for the credit_assessment panel."""

    payload = trace.output_payload or {}
    score = payload.get("credit_score")
    score_int = int(score) if isinstance(score, (int, float)) else None

    # Band thresholds (must match domains/lending/personas/credit_assessment.py
    # _BAND_THRESHOLDS — kept here so the UI can render the gauge without
    # importing the persona).
    bands = [
        {"label": "deep_subprime", "low": 300, "high": 600, "tone": "rose"},
        {"label": "subprime",      "low": 600, "high": 660, "tone": "orange"},
        {"label": "near_prime",    "low": 660, "high": 700, "tone": "amber"},
        {"label": "prime",         "low": 700, "high": 760, "tone": "emerald"},
        {"label": "super_prime",   "low": 760, "high": 850, "tone": "indigo"},
    ]

    score_pct = None
    if score_int is not None:
        score_pct = max(0.0, min(100.0, ((score_int - 300) / (850 - 300)) * 100))

    flags = [
        {"label": "active_bankruptcy",
         "value": payload.get("active_bankruptcy"),
         "trigger": "block",
         "fired": bool(payload.get("active_bankruptcy"))},
        {"label": "foreclosure_last_36_months",
         "value": payload.get("foreclosure_last_36_months"),
         "trigger": "block",
         "fired": bool(payload.get("foreclosure_last_36_months"))},
        {"label": "thin_file",
         "value": payload.get("thin_file"),
         "trigger": "escalate",
         "fired": bool(payload.get("thin_file"))},
        {"label": "no_derogatory_last_24_months",
         "value": payload.get("no_derogatory_last_24_months"),
         "trigger": "auto",
         "fired": bool(payload.get("no_derogatory_last_24_months"))},
    ]

    return {
        "score":         score_int,
        "score_pct":     score_pct,
        "band":          payload.get("credit_band"),
        "bands":         bands,
        "flags":         flags,
        "thresholds": {
            "auto":      680,
            "recommend": 600,
        },
    }


# ─────────────────────────────────────────────────────────────────────
# 11 remaining persona view-models. Each produces a dict the
# corresponding partial renders. Output_payload keys mirror the
# matching persona class in domains/lending/personas/.
# ─────────────────────────────────────────────────────────────────────


def _lead_scoring_view(trace: DecisionTrace, spec: dict[str, Any]) -> dict[str, Any]:
    p = trace.output_payload or {}
    intent = p.get("intent_score")
    return {
        "intent_score":    intent,
        "intent_pct":      _pct_of(intent, 0.0, 1.0),
        "thresholds":      {"auto": 0.7, "recommend": 0.5},
        "channel":         p.get("channel"),
        "source":          p.get("source"),
        "channel_fit":     bool(p.get("channel_fit")),
        "lead_priority":   p.get("lead_priority"),
        "ambiguous_identity": bool(p.get("ambiguous_identity")),
        "flags": [
            _flag("ambiguous_identity",  p.get("ambiguous_identity"),  "escalate"),
            _flag("channel_fit",         p.get("channel_fit"),         "auto",
                  fired=bool(p.get("channel_fit"))),
        ],
    }


def _income_verification_view(trace: DecisionTrace, spec: dict[str, Any]) -> dict[str, Any]:
    p = trace.output_payload or {}
    stated = p.get("stated_income")  # not always written
    verified = p.get("verified_income")
    confidence = p.get("income_confidence_score")
    discrepancy = p.get("income_discrepancy_pct")
    # Use trace.reasoning signals to recover stated_income if missing.
    if stated is None and trace.reasoning and trace.reasoning.signals_evaluated:
        for sig in trace.reasoning.signals_evaluated:
            if sig.name == "stated_income":
                stated = sig.value
                break
    bar_max = max([v for v in (stated, verified) if isinstance(v, (int, float))] or [1.0])
    return {
        "stated_income":    stated,
        "verified_income":  verified,
        "stated_pct":       _pct_of(stated,   0, bar_max),
        "verified_pct":     _pct_of(verified, 0, bar_max),
        "confidence":       confidence,
        "confidence_pct":   _pct_of(confidence, 0.0, 1.0),
        "thresholds":       {"auto": 0.9, "recommend": 0.75},
        "employment_type":  p.get("employment_type"),
        "payroll_verified": bool(p.get("payroll_verified")),
        "discrepancy":      discrepancy,
        "flags": [
            _flag("income_discrepancy_pct > 0.25", discrepancy, "block",
                  fired=isinstance(discrepancy, (int, float)) and discrepancy > 0.25),
            _flag("multiple_income_sources",       p.get("multiple_income_sources"), "escalate"),
            _flag("foreign_income",                p.get("foreign_income"),          "escalate"),
            _flag("payroll_verified",              p.get("payroll_verified"),        "auto"),
        ],
    }


def _fraud_screening_view(trace: DecisionTrace, spec: dict[str, Any]) -> dict[str, Any]:
    p = trace.output_payload or {}
    fraud_score = p.get("fraud_score")
    return {
        "fraud_score":        fraud_score,
        "fraud_pct":          _pct_of(fraud_score, 0.0, 1.0),
        "fraud_tone":         _traffic_tone(fraud_score, 0.2, 0.5),
        "thresholds":         {"auto_below": 0.2, "block_at": 0.5},
        "identity_match":     p.get("identity_match_confidence"),
        "id_match_pct":       _pct_of(p.get("identity_match_confidence"), 0.0, 1.0),
        "doc_auth":           p.get("document_authenticity_score"),
        "doc_auth_pct":       _pct_of(p.get("document_authenticity_score"), 0.0, 1.0),
        "fraud_cleared":      bool(p.get("fraud_cleared")),
        "halts_pipeline":     trace.outcome.value == "block",
        "flags": [
            _flag("watchlist_match",          p.get("watchlist_match"),           "block"),
            _flag("synthetic_identity_flag",  p.get("synthetic_identity_flag"),   "block"),
            _flag("document_authenticity<0.8", p.get("document_authenticity_score"), "escalate",
                  fired=isinstance(p.get("document_authenticity_score"), (int, float))
                        and p.get("document_authenticity_score") < 0.8),
            _flag("identity_match≥0.95",      p.get("identity_match_confidence"), "auto",
                  fired=isinstance(p.get("identity_match_confidence"), (int, float))
                        and p.get("identity_match_confidence") >= 0.95),
        ],
    }


def _compliance_check_view(trace: DecisionTrace, spec: dict[str, Any]) -> dict[str, Any]:
    p = trace.output_payload or {}
    return {
        "halts_closing":  trace.outcome.value == "block",
        "checklist": [
            {"label": "all_hmda_fields_complete", "ok": bool(p.get("all_hmda_fields_complete"))},
            {"label": "no_fair_lending_flags",    "ok": bool(p.get("no_fair_lending_flags"))},
            {"label": "state_rules_passed",       "ok": bool(p.get("state_rules_passed"))},
            {"label": "compliance_cleared",       "ok": bool(p.get("compliance_cleared"))},
        ],
        "flags": [
            _flag("fair_lending_violation",       p.get("fair_lending_violation"),       "block"),
            _flag("missing_required_disclosures", p.get("missing_required_disclosures"), "block"),
            _flag("regulatory_ambiguity",         p.get("regulatory_ambiguity"),         "escalate"),
            _flag("mixed_jurisdiction",           p.get("mixed_jurisdiction"),           "escalate"),
            _flag("minor_data_gap",               p.get("minor_data_gap"),               "recommend"),
        ],
    }


def _dti_calculation_view(trace: DecisionTrace, spec: dict[str, Any]) -> dict[str, Any]:
    p = trace.output_payload or {}
    dti = p.get("dti_ratio") or p.get("dti")
    bar_max = 0.60  # gauge upper bound — clauses cap at 0.50 block
    monthly_obl = p.get("monthly_obligations")
    monthly_inc = p.get("monthly_income")
    pulled_from_upstream = trace.upstream_decision_ids and "income_verification" in trace.upstream_decision_ids
    upstream_conf = None
    for sig in (trace.reasoning.signals_evaluated if trace.reasoning else []):
        if sig.name == "income_verification.confidence":
            upstream_conf = sig.value
            break
    guard_threshold = (spec.get("contamination_guard") or {}).get("reject_if_upstream_confidence_below")
    return {
        "dti":              dti,
        "dti_pct":          _pct_of(dti, 0.0, bar_max),
        "thresholds":       {"auto": 0.36, "recommend": 0.43, "block": 0.50},
        "verified_income":  p.get("verified_income"),
        "monthly_income":   monthly_inc,
        "monthly_obligations": monthly_obl,
        "pulled_from_upstream": bool(pulled_from_upstream),
        "upstream_confidence": upstream_conf,
        "guard_threshold":     guard_threshold,
        "guard_fired":      isinstance(upstream_conf, (int, float))
                            and isinstance(guard_threshold, (int, float))
                            and upstream_conf < guard_threshold,
    }


def _ltv_assessment_view(trace: DecisionTrace, spec: dict[str, Any]) -> dict[str, Any]:
    p = trace.output_payload or {}
    ltv = p.get("ltv_ratio") or p.get("ltv")
    appraised = p.get("appraised_value")
    loan_amount = p.get("loan_amount")
    bar_max_dollars = max([v for v in (appraised, loan_amount) if isinstance(v, (int, float))] or [1.0])
    return {
        "ltv":                  ltv,
        "ltv_pct":              _pct_of(ltv, 0.0, 1.0),
        "thresholds":           {"auto": 0.80, "recommend": 0.95, "block": 0.97},
        "appraised_value":      appraised,
        "loan_amount":          loan_amount,
        "appraised_bar":        _pct_of(appraised,   0, bar_max_dollars),
        "loan_bar":             _pct_of(loan_amount, 0, bar_max_dollars),
        "max_allowable_ltv":    p.get("max_allowable_ltv"),
        "exceeds_max_allowed":  isinstance(ltv, (int, float)) and isinstance(p.get("max_allowable_ltv"), (int, float))
                                and ltv > p.get("max_allowable_ltv"),
        "flags": [
            _flag("appraisal_disputed", p.get("appraisal_disputed"), "escalate"),
        ],
    }


def _product_eligibility_view(trace: DecisionTrace, spec: dict[str, Any]) -> dict[str, Any]:
    p = trace.output_payload or {}
    return {
        "eligible_products":        list(p.get("eligible_products") or []),
        "exceptions_required":      list(p.get("guideline_exceptions_required") or []),
        "no_eligible_products":     bool(p.get("no_eligible_products")),
        "eligible_with_exceptions": bool(p.get("eligible_with_exceptions")),
    }


def _rate_pricing_view(trace: DecisionTrace, spec: dict[str, Any]) -> dict[str, Any]:
    p = trace.output_payload or {}
    base = 0.0625
    llpa = p.get("llpa") or 0.0
    rate = p.get("interest_rate")
    usury = 0.18
    return {
        "base_rate":             base,
        "llpa":                  llpa,
        "interest_rate":         rate,
        "usury_limit":           usury,
        "rate_pct_of_usury":     _pct_of(rate, 0.0, usury),
        "base_pct_of_usury":     _pct_of(base, 0.0, usury),
        "llpa_pct_of_usury":     _pct_of(llpa, 0.0, usury),
        "loan_type":             p.get("loan_type"),
        "rate_within_normal_band":     bool(p.get("rate_within_normal_band")),
        "no_manual_adjustments":       bool(p.get("no_manual_adjustments_required")),
        "pricing_exception_possible":  bool(p.get("pricing_exception_possible")),
        "rate_exceeds_usury":          bool(p.get("rate_exceeds_usury_limit")),
        "concurrent_lock_conflict":    bool(p.get("concurrent_rate_lock_conflict")),
    }


def _underwriting_decision_view(trace: DecisionTrace, spec: dict[str, Any]) -> dict[str, Any]:
    p = trace.output_payload or {}
    upstream_outcomes = p.get("upstream_outcomes") or {}
    pills = []
    for did, outcome in upstream_outcomes.items():
        outcome = outcome or "missing"
        pills.append({
            "decision_id": did,
            "outcome":     outcome,
            "outcome_style": OUTCOME_STYLES.get(outcome, OUTCOME_STYLES["pending"]),
        })
    risk = p.get("risk_score")
    return {
        "underwriting_outcome":    p.get("underwriting_outcome"),
        "risk_score":              risk,
        "risk_pct":                _pct_of(risk, 0.0, 1.0),
        "thresholds":              {"auto": 0.25, "escalate": 0.60},
        "all_upstream_auto":       bool(p.get("all_upstream_auto_cleared")),
        "any_upstream_block":      bool(p.get("any_upstream_hard_block")),
        "senior_review_required":  bool(p.get("senior_underwriter_review_required")),
        "exceptions":              list(p.get("exceptions_required") or []),
        "upstream_pills":          pills,
    }


def _approval_routing_view(trace: DecisionTrace, spec: dict[str, Any]) -> dict[str, Any]:
    p = trace.output_payload or {}
    return {
        "routing_target":  p.get("routing_target"),
        "channel":         p.get("communication_channel"),
        "timeline":        p.get("timeline"),
        "underwriting":    (p.get("underwriting_decision") or {}).get("outcome"),
        "applicant_dispute": bool(p.get("applicant_dispute_flag")),
    }


def _closing_readiness_view(trace: DecisionTrace, spec: dict[str, Any]) -> dict[str, Any]:
    p = trace.output_payload or {}
    return {
        "clear_to_close":          bool(p.get("clear_to_close")),
        "halts_block":             trace.outcome.value == "block",
        "checklist": [
            {"label": "title_clear",            "ok": bool(p.get("title_clear"))},
            {"label": "cd_timing_compliant",    "ok": bool(p.get("cd_timing_compliant"))},
            {"label": "all_conditions_cleared", "ok": bool(p.get("all_conditions_cleared"))},
            {"label": "underwriting=approve",   "ok": p.get("underwriting_outcome") == "approve"},
        ],
        "outstanding_conditions":  list(p.get("outstanding_conditions") or []),
        "underwriting_outcome":    p.get("underwriting_outcome"),
        "compliance_outcome":      (p.get("compliance_check") or {}).get("outcome"),
        "flags": [
            _flag("title_defect",           p.get("title_defect"),           "block"),
            _flag("cd_timing_violation",    not p.get("cd_timing_compliant"), "block",
                  fired=not bool(p.get("cd_timing_compliant"))),
            _flag("lien_dispute",           p.get("lien_dispute"),           "escalate"),
            _flag("insurance_gap",          p.get("insurance_gap"),          "escalate"),
            _flag("minor_conditions_outstanding", p.get("minor_conditions_outstanding"), "recommend"),
        ],
    }


_PERSONA_VIEW_BUILDERS: dict[str, Any] = {
    "lead_scoring":          _lead_scoring_view,
    "income_verification":   _income_verification_view,
    "credit_assessment":     _credit_assessment_view,
    "fraud_screening":       _fraud_screening_view,
    "compliance_check":      _compliance_check_view,
    "dti_calculation":       _dti_calculation_view,
    "ltv_assessment":        _ltv_assessment_view,
    "product_eligibility":   _product_eligibility_view,
    "rate_pricing":          _rate_pricing_view,
    "underwriting_decision": _underwriting_decision_view,
    "approval_routing":      _approval_routing_view,
    "closing_readiness":     _closing_readiness_view,
}


def _sync_recall(platform: Platform, agent_id: str, decision_id: str) -> list[Any]:
    """Cheap synchronous recall over the InMemoryLearningStore — same
    body as ReflectionService.recall but without the await."""

    store = platform.learning_store
    learnings = list(getattr(store, "_learnings", {}).values())
    return [
        lrn for lrn in learnings
        if lrn.agent_id == agent_id and lrn.decision_id == decision_id and lrn.is_active
    ]


# ─────────────────────────────────────────────────────────────────────
# Human queue
# ─────────────────────────────────────────────────────────────────────


def queue_view(platform: Platform) -> dict[str, Any]:
    """Cross-application queue view.

    Returns both open items (waiting for review) and recently-resolved
    receipts (already acted on this session). The persona workbench's
    Approve/Decline endpoints call HumanQueue.resolve() which moves
    items from open → resolved; this view shows both sides of that
    transition."""

    items = list(getattr(platform.human_queue, "_items", {}).values())
    items.sort(key=lambda i: i.enqueued_at, reverse=True)

    open_rows: list[dict[str, Any]] = []
    for item in items:
        # Find the trace so the queue can link straight into decision detail.
        traces = _all_traces_sync(platform, item.application_id)
        trace = next(
            (t for t in traces if t.decision_id == item.decision_id), None
        )
        open_rows.append({
            "queue_id":         str(item.id),
            "application_id":   item.application_id,
            "decision_id":      item.decision_id,
            "agent_id":         item.agent_id,
            "proposed_outcome": item.proposed_outcome.value,
            "outcome_style":    OUTCOME_STYLES.get(
                item.proposed_outcome.value, OUTCOME_STYLES["pending"]
            ),
            "confidence":       item.confidence,
            "reasons":          list(item.reasons),
            "enqueued_at":      item.enqueued_at,
            "trace_id":         str(trace.trace_id) if trace else None,
        })

    resolved = list(getattr(platform.human_queue, "_resolved", []))
    resolved.sort(key=lambda r: r.resolved_at, reverse=True)
    resolved_rows: list[dict[str, Any]] = []
    for r in resolved:
        resolution_tone = "emerald" if r.resolution == "approve" else (
            "rose" if r.resolution == "decline" else "slate"
        )
        resolved_rows.append({
            "item_id":        str(r.item_id),
            "application_id": r.application_id,
            "decision_id":    r.decision_id,
            "decision_label": PERSONA_LABELS.get(r.decision_id, r.decision_id),
            "resolution":     r.resolution,
            "resolution_tone": resolution_tone,
            "reviewer_id":    r.reviewer_id,
            "reviewer_role":  r.reviewer_role,
            "resolved_at":    r.resolved_at,
            "notes":          r.notes,
        })

    return {
        "items":         open_rows,
        "resolved":      resolved_rows,
        "open_count":    len(open_rows),
        "resolved_count": len(resolved_rows),
    }


# ─────────────────────────────────────────────────────────────────────
# Filters / template helpers
# ─────────────────────────────────────────────────────────────────────


def _format_currency(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"${float(value):,.0f}"
    except (TypeError, ValueError):
        return str(value)


def _format_pct(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return str(value)


def _format_confidence(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _format_dt(value: Any) -> str:
    if value is None:
        return "—"
    s = str(value)
    return s[:19].replace("T", " ")


# Register filters on the Jinja env once at import time.
templates.env.filters["currency"] = _format_currency
templates.env.filters["pct"] = _format_pct
templates.env.filters["confidence"] = _format_confidence
templates.env.filters["dt"] = _format_dt


# ─────────────────────────────────────────────────────────────────────
# Workbench — operator-centric rollup per owner_team.
#
# 9 owner_teams in decisions.yaml; each one's workbench shows the
# decisions that team owns across every application: KPI strip on top,
# queue of pending reviews, application picker, and a per-app focused
# view that splits work into finished / pending-for-me / waiting-on-
# upstream / downstream-waiting.
# ─────────────────────────────────────────────────────────────────────


OWNER_TEAM_LABELS: dict[str, str] = {
    "growth_ops":        "Growth Ops",
    "underwriting":      "Underwriting",
    "credit_risk":       "Credit Risk",
    "fraud_ops":         "Fraud Ops",
    "compliance":        "Compliance",
    "product_ops":       "Product Ops",
    "secondary_markets": "Secondary Markets",
    "loan_ops":          "Loan Ops",
    "closing_ops":       "Closing Ops",
}


def list_workbenches(platform: Platform) -> list[dict[str, Any]]:
    """One card per owner_team. KPI snapshot for the team rollup."""
    spec = platform.spec
    by_team: dict[str, list[dict[str, Any]]] = {}
    for d in spec.decisions:
        by_team.setdefault(d.get("owner_team", "—"), []).append(d)

    rows: list[dict[str, Any]] = []
    for team in sorted(by_team.keys()):
        decisions = by_team[team]
        kpis = _team_kpis(platform, decisions)
        rows.append({
            "owner_team":   team,
            "label":        OWNER_TEAM_LABELS.get(team, team),
            "decision_ids": [d["id"] for d in decisions],
            "decision_count": len(decisions),
            **kpis,
        })
    return rows


def workbench_view(
    platform: Platform,
    owner_team: str,
    application_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    spec = platform.spec
    owned = [d for d in spec.decisions if d.get("owner_team") == owner_team]
    if not owned:
        return None
    owned_ids = [d["id"] for d in owned]

    durable = platform.store._durable  # type: ignore[attr-defined]
    records = getattr(durable, "_records", None) or []
    all_app_ids = sorted({
        r.entity_id for r in records
        if r.entity_type == "Application"
        and r.decision_id is None
        and r.superseded_at is None
    })

    kpis = _team_kpis(platform, owned)
    queue_rows = _queue_for_team(platform, owned_ids)

    focused = None
    selected = application_id if application_id in all_app_ids else None
    if selected is not None:
        focused = _focused_app_for_team(platform, selected, owned, spec)

    # Application dropdown options: pre-build with status hints so the
    # picker shows which apps are halted / pending review at a glance.
    app_options: list[dict[str, Any]] = []
    for aid in all_app_ids:
        traces = _all_traces_sync(platform, aid)
        any_block = any(t.outcome.value == "block" for t in traces)
        team_traces = [t for t in traces if t.decision_id in owned_ids]
        in_queue = any(
            i.decision_id in owned_ids and i.application_id == aid
            for i in getattr(platform.human_queue, "_items", {}).values()
        )
        app_options.append({
            "application_id": aid,
            "team_decisions": len(team_traces),
            "in_queue":       in_queue,
            "any_block":      any_block,
        })

    return {
        "owner_team":             owner_team,
        "label":                  OWNER_TEAM_LABELS.get(owner_team, owner_team),
        "owned_decisions": [
            {
                "id":         d["id"],
                "name":       d["name"],
                "mode":       d["mode"],
                "risk_level": d["risk_level"],
                "depends_on": [dep["decision"] for dep in d.get("depends_on") or []],
            }
            for d in owned
        ],
        "all_application_ids":    all_app_ids,
        "application_options":    app_options,
        "selected_application_id": selected,
        "kpis":                   kpis,
        "queue":                  queue_rows,
        "focused":                focused,
    }


def _team_kpis(
    platform: Platform, owned_decisions: list[dict[str, Any]]
) -> dict[str, Any]:
    owned_ids = [d["id"] for d in owned_decisions]

    writer = platform.trace_writer
    all_traces = list(getattr(writer, "_traces", {}).values())
    team_traces = [t for t in all_traces if t.decision_id in owned_ids]

    queue_items = [
        i for i in getattr(platform.human_queue, "_items", {}).values()
        if i.decision_id in owned_ids
    ]

    completed   = len([t for t in team_traces if t.outcome.value != "block"])
    blocked     = len([t for t in team_traces if t.outcome.value == "block"])
    auto_cleared = len([
        t for t in team_traces
        if t.mode.value == "auto_execute" and t.outcome.value == "allow"
    ])

    durable = platform.store._durable  # type: ignore[attr-defined]
    records = getattr(durable, "_records", None) or []
    apps_touched = {t.application_id for t in team_traces}
    portfolio_value = 0.0
    for app_id in apps_touched:
        rec = next(
            (r for r in records
             if r.entity_type == "Application"
             and r.entity_id == app_id
             and r.superseded_at is None),
            None,
        )
        if rec is not None:
            try:
                portfolio_value += float((rec.value or {}).get("requested_amount") or 0)
            except (TypeError, ValueError):
                pass

    durs = [t.duration_ms for t in team_traces if t.duration_ms is not None]
    avg_dur = (sum(durs) / len(durs)) if durs else None

    sla_by_did = {d["id"]: d.get("sla_seconds") for d in owned_decisions}
    in_sla = 0
    measured = 0
    for t in team_traces:
        sla = sla_by_did.get(t.decision_id)
        if sla and t.duration_ms is not None:
            measured += 1
            if t.duration_ms <= float(sla) * 1000.0:
                in_sla += 1
    sla_pct = (in_sla / measured * 100.0) if measured else None

    # "Decisions per loan" the team is responsible for, averaged.
    decisions_per_loan_avg = (
        len(team_traces) / len(apps_touched) if apps_touched else 0
    )

    # Downstream-waiting count rolled up across all applications.
    spec = platform.spec
    downstream_pending = 0
    for app_id in apps_touched:
        traces = _all_traces_sync(platform, app_id)
        trace_by_did = {t.decision_id: t for t in traces}
        queue_decisions = {
            i.decision_id for i in getattr(platform.human_queue, "_items", {}).values()
            if i.application_id == app_id
        }
        for other in spec.decisions:
            if other["id"] in owned_ids:
                continue
            deps = [dep["decision"] for dep in other.get("depends_on") or []]
            if not any(d in owned_ids for d in deps):
                continue
            other_trace = trace_by_did.get(other["id"])
            if other_trace and other_trace.outcome.value in ("allow", "block"):
                continue
            if other["id"] in queue_decisions:
                downstream_pending += 1
            elif other_trace is None:
                downstream_pending += 1

    return {
        "open_queue":           len(queue_items),
        "completed":            completed,
        "blocked":              blocked,
        "auto_cleared":         auto_cleared,
        "applications_touched": len(apps_touched),
        "portfolio_value":      portfolio_value,
        "avg_duration_ms":      avg_dur,
        "sla_pct":              sla_pct,
        "decisions_per_loan_avg": decisions_per_loan_avg,
        "downstream_pending":   downstream_pending,
    }


def _queue_for_team(
    platform: Platform, owned_ids: list[str]
) -> list[dict[str, Any]]:
    items = [
        i for i in getattr(platform.human_queue, "_items", {}).values()
        if i.decision_id in owned_ids
    ]
    items.sort(key=lambda i: i.enqueued_at, reverse=True)
    rows: list[dict[str, Any]] = []
    for item in items:
        traces = _all_traces_sync(platform, item.application_id)
        trace = next(
            (t for t in traces if t.decision_id == item.decision_id), None
        )
        rows.append({
            "application_id":   item.application_id,
            "decision_id":      item.decision_id,
            "proposed_outcome": item.proposed_outcome.value,
            "outcome_style":    OUTCOME_STYLES.get(
                item.proposed_outcome.value, OUTCOME_STYLES["pending"]
            ),
            "confidence":       item.confidence,
            "enqueued_at":      item.enqueued_at,
            "trace_id":         str(trace.trace_id) if trace else None,
            "reasons":          list(item.reasons or []),
        })
    return rows


def _focused_app_for_team(
    platform: Platform,
    application_id: str,
    owned_decisions: list[dict[str, Any]],
    spec: Any,
) -> dict[str, Any]:
    owned_ids = [d["id"] for d in owned_decisions]
    durable = platform.store._durable  # type: ignore[attr-defined]
    records = getattr(durable, "_records", None) or []

    app_rec = next(
        (r for r in records
         if r.entity_type == "Application"
         and r.entity_id == application_id
         and r.superseded_at is None),
        None,
    )
    app_value = app_rec.value if app_rec else {}

    traces = _all_traces_sync(platform, application_id)
    trace_by_did = {t.decision_id: t for t in traces}

    queue_items_by_did = {
        i.decision_id: i
        for i in getattr(platform.human_queue, "_items", {}).values()
        if i.application_id == application_id and i.decision_id in owned_ids
    }
    all_queue_ids = {
        i.decision_id
        for i in getattr(platform.human_queue, "_items", {}).values()
        if i.application_id == application_id
    }

    finished:           list[dict[str, Any]] = []
    pending_for_me:     list[dict[str, Any]] = []
    waiting_upstream:   list[dict[str, Any]] = []

    for d in owned_decisions:
        did = d["id"]
        trace = trace_by_did.get(did)
        in_queue = did in queue_items_by_did

        if trace and trace.human_review:
            review = trace.human_review
            finished.append({
                "decision_id":     did,
                "name":            d["name"],
                "outcome":         review.final_outcome.value,
                "outcome_style":   OUTCOME_STYLES.get(
                    review.final_outcome.value, OUTCOME_STYLES["pending"]
                ),
                "mode":            d["mode"],
                "confidence":      trace.confidence,
                "trace_id":        str(trace.trace_id),
                "matched_clause":  trace.matched_clause,
                "human_reviewed":  True,
                "reviewer_role":   review.reviewer_role,
            })
        elif trace and not in_queue:
            finished.append({
                "decision_id":     did,
                "name":            d["name"],
                "outcome":         trace.outcome.value,
                "outcome_style":   OUTCOME_STYLES.get(
                    trace.outcome.value, OUTCOME_STYLES["pending"]
                ),
                "mode":            d["mode"],
                "confidence":      trace.confidence,
                "trace_id":        str(trace.trace_id),
                "matched_clause":  trace.matched_clause,
                "human_reviewed":  False,
            })
        elif in_queue:
            qi = queue_items_by_did[did]
            pending_for_me.append({
                "decision_id":      did,
                "name":             d["name"],
                "proposed_outcome": qi.proposed_outcome.value,
                "outcome_style":    OUTCOME_STYLES.get(
                    qi.proposed_outcome.value, OUTCOME_STYLES["pending"]
                ),
                "confidence":       qi.confidence,
                "enqueued_at":      qi.enqueued_at,
                "trace_id":         str(trace.trace_id) if trace else None,
                "reasons":          list(qi.reasons or []),
            })
        else:
            depends_on = [dep["decision"] for dep in d.get("depends_on") or []]
            missing = [
                u for u in depends_on
                if u not in trace_by_did
                or trace_by_did[u].outcome.value not in ("allow",)
            ]
            waiting_upstream.append({
                "decision_id":     did,
                "name":            d["name"],
                "depends_on":      depends_on,
                "missing_upstream": missing,
                "any_blocked": any(
                    trace_by_did.get(u) and trace_by_did[u].outcome.value == "block"
                    for u in depends_on
                ),
            })

    downstream_waiting: list[dict[str, Any]] = []
    for other in spec.decisions:
        oid = other["id"]
        if oid in owned_ids:
            continue
        deps = [dep["decision"] for dep in other.get("depends_on") or []]
        my_deps = [u for u in deps if u in owned_ids]
        if not my_deps:
            continue
        other_trace = trace_by_did.get(oid)
        if other_trace and other_trace.outcome.value == "allow":
            # Cleanly cleared — nothing waiting on me.
            continue
        # We deliberately keep "block" downstream visible: if my output
        # cascaded into a downstream block (e.g. compliance blocks →
        # closing_readiness blocks via compliance_block_stops_closing),
        # the operator must see that impact here, not have it disappear.
        if oid in all_queue_ids:
            status = "queued"
        elif other_trace is not None:
            status = other_trace.outcome.value
        else:
            status = "not_run"
        downstream_waiting.append({
            "decision_id":      oid,
            "name":             other["name"],
            "owner_team":       other.get("owner_team"),
            "owner_team_label": OWNER_TEAM_LABELS.get(other.get("owner_team", ""), other.get("owner_team", "")),
            "depends_on_mine":  my_deps,
            "status":           status,
            "outcome_style":    OUTCOME_STYLES.get(
                status if status != "not_run" else "pending",
                OUTCOME_STYLES["pending"],
            ),
        })

    return {
        "application_id":             application_id,
        "applicant_id":               app_value.get("applicant_id"),
        "loan_purpose":               app_value.get("loan_purpose"),
        "requested_amount":           app_value.get("requested_amount"),
        "property_state":             app_value.get("property_state"),
        "submitted_at":               app_value.get("submitted_at"),
        "decisions_completed":        len(traces),
        "total_decisions_in_pipeline": len(spec.decisions),
        "finished":                   finished,
        "pending_for_me":             pending_for_me,
        "waiting_upstream":           waiting_upstream,
        "downstream_waiting":         downstream_waiting,
    }


# ─────────────────────────────────────────────────────────────────────
# Per-persona workbench — the AI-agent's day.
#
# 12 personas; one workbench each. Different shape from the per-team
# workbench above:
#   - Team workbench is *operator-centric* — the team has work across
#     many decisions; the view rolls up.
#   - Persona workbench is *agent-centric* — one AI persona, one
#     decision_id. Operators handling that decision see the queue and
#     drill in; persona maintainers see KPIs / accuracy / latency for
#     their specific agent.
#
# Layout matches the user-supplied design (screenshot 2026-05-03):
#   header tabs (siblings within owner_team)
#     · agent identity (decision_id · persona)
#     · time-range selector
#   KPI strip (4): Decisions completed · Pending review ·
#                  Auto-decided % · Avg time to decide (human reviews)
#   View tabs: Workbench · History · Analytics
#   Two columns:
#     left  = queue or recently-completed (depending on persona mode)
#     right = focused application detail (Application Context, Signals,
#             AI Reasoning, Approve / Decline / Request evidence)
#
# Auto-execute personas (lead_scoring, dti_calculation, ltv_assessment,
# approval_routing) almost never queue. Their left column shows
# "Recently completed" instead — same row shape, just no Approve action
# (the AI already wrote back).
# ─────────────────────────────────────────────────────────────────────


PERSONA_LABELS: dict[str, str] = {
    "lead_scoring":          "Lead qualifier",
    "income_verification":   "Income underwriter",
    "credit_assessment":     "Credit underwriter",
    "fraud_screening":       "Fraud officer",
    "compliance_check":      "Compliance officer",
    "dti_calculation":       "DTI calculator",
    "ltv_assessment":        "LTV calculator",
    "product_eligibility":   "Product specialist",
    "rate_pricing":          "Pricing officer",
    "underwriting_decision": "Senior underwriter",
    "approval_routing":      "Workflow router",
    "closing_readiness":     "Closing officer",
}


# Visual-only "avatar" tones — deterministic from applicant_id so the
# same applicant always paints the same colour. List kept short to ease
# legibility; modulo over the list keeps it bounded.
_AVATAR_TONES: list[str] = [
    "indigo", "emerald", "amber", "rose", "sky", "violet", "teal", "orange",
]


TIME_RANGES: dict[str, dict[str, Any]] = {
    "quarter":  {"label": "This quarter",  "days": 91},
    "month":    {"label": "This month",    "days": 30},
    "week":     {"label": "This week",     "days": 7},
    "all_time": {"label": "All time",      "days": None},
}


def list_persona_workbenches(platform: Platform) -> list[dict[str, Any]]:
    """One card per persona — for the /ui/personas index."""

    spec = platform.spec
    rows: list[dict[str, Any]] = []
    for d in spec.decisions:
        decision_id = d["id"]
        kpis = _persona_kpis(platform, decision_id, range_key="quarter")
        rows.append({
            "decision_id":    decision_id,
            "persona":        d.get("persona"),
            "label":          PERSONA_LABELS.get(decision_id, decision_id),
            "owner_team":     d.get("owner_team"),
            "owner_team_label": OWNER_TEAM_LABELS.get(d.get("owner_team", ""), d.get("owner_team", "")),
            "mode":           d.get("mode"),
            "risk_level":     d.get("risk_level"),
            "is_auto":        d.get("mode") == "auto_execute",
            **kpis,
        })
    return rows


def persona_workbench_view(
    platform: Platform,
    decision_id: str,
    *,
    application_id: Optional[str] = None,
    time_range: str = "quarter",
    tab: str = "workbench",
) -> Optional[dict[str, Any]]:
    spec = platform.spec
    decision_spec = spec.decision_index.get(decision_id)
    if decision_spec is None:
        return None
    if time_range not in TIME_RANGES:
        time_range = "quarter"
    if tab not in ("workbench", "history", "analytics"):
        tab = "workbench"

    persona_label = PERSONA_LABELS.get(decision_id, decision_id)
    owner_team = decision_spec.get("owner_team", "")
    is_auto = decision_spec.get("mode") == "auto_execute"

    # Sibling personas in the same owner_team — top-tab navigation.
    siblings: list[dict[str, Any]] = []
    for d in spec.decisions:
        if d.get("owner_team") != owner_team:
            continue
        sib_id = d["id"]
        siblings.append({
            "decision_id": sib_id,
            "label":       PERSONA_LABELS.get(sib_id, sib_id),
            "active":      sib_id == decision_id,
        })

    kpis = _persona_kpis(platform, decision_id, range_key=time_range)

    # Left column rows — different shape per persona-mode.
    if is_auto:
        left_label = "Recently completed"
        left_rows = _persona_recent_traces(
            platform, decision_id, selected_app=application_id, limit=10
        )
    else:
        left_label = f"{persona_label.lower().replace(' ', '_')} queue"
        left_rows = _persona_queue_rows(
            platform, decision_id, selected_app=application_id
        )

    focused = None
    if application_id is not None:
        focused = _persona_focused_app(
            platform, decision_id, application_id
        )

    return {
        "decision_id":     decision_id,
        "persona":         decision_spec.get("persona"),
        "persona_label":   persona_label,
        "decision_name":   decision_spec.get("name"),
        "owner_team":      owner_team,
        "owner_team_label": OWNER_TEAM_LABELS.get(owner_team, owner_team),
        "mode":            decision_spec.get("mode"),
        "risk_level":      decision_spec.get("risk_level"),
        "is_auto":         is_auto,
        "siblings":        siblings,
        "selected_application_id": application_id,
        "time_range":      time_range,
        "time_range_label": TIME_RANGES[time_range]["label"],
        "time_ranges":     [
            {"key": k, "label": v["label"], "selected": k == time_range}
            for k, v in TIME_RANGES.items()
        ],
        "tab":             tab,
        "kpis":            kpis,
        "left_label":      left_label,
        "left_rows":       left_rows,
        "focused":         focused,
    }


# ─────────────────────────────────────────────────────────────────────
# Persona KPIs
# ─────────────────────────────────────────────────────────────────────


def _persona_kpis(
    platform: Platform, decision_id: str, *, range_key: str
) -> dict[str, Any]:
    """4 KPIs: Decisions completed · Pending review · Auto-decided % ·
    Avg time to decide (human reviews)."""

    writer = platform.trace_writer
    all_traces = list(getattr(writer, "_traces", {}).values())
    persona_traces = [t for t in all_traces if t.decision_id == decision_id]

    days = TIME_RANGES.get(range_key, TIME_RANGES["quarter"])["days"]
    if days is not None:
        cutoff = datetime.utcnow() - timedelta(days=days)
        persona_traces = [t for t in persona_traces if t.started_at >= cutoff]

    decisions_completed = len(persona_traces)
    pending_review = sum(
        1 for i in getattr(platform.human_queue, "_items", {}).values()
        if i.decision_id == decision_id
    )
    # Auto-decided = AI made the call AND no human had to act:
    # mode is auto_execute AND outcome is ALLOW (so it didn't queue
    # via recommend/escalate) AND no human review is attached.
    # Reconciles with Pending review — a queued recommend doesn't
    # count as auto-decided.
    auto_count = sum(
        1 for t in persona_traces
        if t.human_review is None
        and t.mode.value == "auto_execute"
        and t.outcome.value == "allow"
    )
    auto_decided_pct = (
        auto_count / decisions_completed if decisions_completed else None
    )

    # Human-review avg latency: time from trace.ended_at → review.reviewed_at
    review_latencies_ms: list[float] = []
    for t in persona_traces:
        if t.human_review is None or t.ended_at is None:
            continue
        delta = (t.human_review.reviewed_at - t.ended_at).total_seconds() * 1000.0
        if delta >= 0:
            review_latencies_ms.append(delta)
    avg_review_ms = (
        sum(review_latencies_ms) / len(review_latencies_ms)
        if review_latencies_ms else None
    )

    return {
        "decisions_completed": decisions_completed,
        "pending_review":      pending_review,
        "auto_decided_pct":    auto_decided_pct,
        "avg_review_ms":       avg_review_ms,
        "human_reviewed_count": len(review_latencies_ms),
    }


# ─────────────────────────────────────────────────────────────────────
# Left column — queue (human modes) or recently-completed (auto modes)
# ─────────────────────────────────────────────────────────────────────


def _persona_queue_rows(
    platform: Platform, decision_id: str, *, selected_app: Optional[str]
) -> list[dict[str, Any]]:
    items = [
        i for i in getattr(platform.human_queue, "_items", {}).values()
        if i.decision_id == decision_id
    ]
    # Oldest first — urgency rises with wait time, matches screenshot order.
    items.sort(key=lambda i: i.enqueued_at)
    out: list[dict[str, Any]] = []
    for item in items:
        out.append(
            _persona_row_from_queue(platform, item, selected_app)
        )
    return out


def _persona_recent_traces(
    platform: Platform,
    decision_id: str,
    *,
    selected_app: Optional[str],
    limit: int,
) -> list[dict[str, Any]]:
    writer = platform.trace_writer
    traces = [
        t for t in getattr(writer, "_traces", {}).values()
        if t.decision_id == decision_id
    ]
    traces.sort(key=lambda t: t.started_at, reverse=True)
    rows: list[dict[str, Any]] = [
        _persona_row_from_trace(platform, trace, selected_app)
        for trace in traces[:limit]
    ]
    # Operator priority: pending-review rows first (urgent action),
    # then everything else by recency. Stable sort preserves the
    # started_at ordering within each group.
    rows.sort(key=lambda r: (0 if r.get("is_queued") else 1))
    return rows


def _persona_row_from_queue(
    platform: Platform, item: Any, selected_app: Optional[str]
) -> dict[str, Any]:
    app_value = _application_value(platform, item.application_id)
    loan_value = _loan_value(platform, item.application_id)
    return {
        "application_id":   item.application_id,
        "is_selected":      item.application_id == selected_app,
        "is_queued":        True,    # by definition — these are queue items
        "applicant_id":     app_value.get("applicant_id"),
        "display_name":     _display_name(app_value, item.application_id),
        "initials":         _initials(app_value, item.application_id),
        "avatar_tone":      _avatar_tone(item.application_id),
        "loan_summary":     _loan_summary(app_value, loan_value),
        "amount":           app_value.get("requested_amount"),
        "ago_minutes":      _minutes_ago(item.enqueued_at),
        "risk_pill":        _risk_pill_for_persona(item.decision_id, item),
        "proposed_outcome": item.proposed_outcome.value,
        "outcome":          item.proposed_outcome.value,
        "outcome_style":    OUTCOME_STYLES.get(
            item.proposed_outcome.value, OUTCOME_STYLES["pending"]
        ),
        "confidence":       item.confidence,
        "kind":             "queued",
    }


def _persona_row_from_trace(
    platform: Platform, trace: Any, selected_app: Optional[str]
) -> dict[str, Any]:
    app_value = _application_value(platform, trace.application_id)
    loan_value = _loan_value(platform, trace.application_id)
    # A trace is "queued" when its outcome routed to QUEUE_HUMAN — i.e.
    # there's a corresponding queue item for the same (decision, app).
    is_queued = any(
        i.application_id == trace.application_id
        and i.decision_id == trace.decision_id
        for i in getattr(platform.human_queue, "_items", {}).values()
    )
    return {
        "application_id":   trace.application_id,
        "is_selected":      trace.application_id == selected_app,
        "is_queued":        is_queued,
        "applicant_id":     app_value.get("applicant_id"),
        "display_name":     _display_name(app_value, trace.application_id),
        "initials":         _initials(app_value, trace.application_id),
        "avatar_tone":      _avatar_tone(trace.application_id),
        "loan_summary":     _loan_summary(app_value, loan_value),
        "amount":           app_value.get("requested_amount"),
        "ago_minutes":      _minutes_ago(trace.started_at),
        "risk_pill":        _risk_pill_for_persona(trace.decision_id, trace),
        "proposed_outcome": trace.outcome.value,
        "outcome":          trace.outcome.value,
        "outcome_style":    OUTCOME_STYLES.get(
            trace.outcome.value, OUTCOME_STYLES["pending"]
        ),
        "confidence":       trace.confidence,
        "kind":             "completed",
    }


# ─────────────────────────────────────────────────────────────────────
# Right column — focused application detail
# ─────────────────────────────────────────────────────────────────────


def _persona_focused_app(
    platform: Platform, decision_id: str, application_id: str
) -> Optional[dict[str, Any]]:
    spec = platform.spec
    decision_spec = spec.decision_index.get(decision_id, {})

    app_value = _application_value(platform, application_id)
    loan_value = _loan_value(platform, application_id)

    traces = _all_traces_sync(platform, application_id)
    trace = next((t for t in traces if t.decision_id == decision_id), None)

    queue_item = next(
        (i for i in getattr(platform.human_queue, "_items", {}).values()
         if i.application_id == application_id and i.decision_id == decision_id),
        None,
    )

    application_context = _persona_application_context(
        decision_id, app_value, loan_value, traces
    )
    signals_evaluated = _persona_signals(trace)
    ai_reasoning = _persona_ai_reasoning(trace)
    policy_panel = _policy_panel(platform, trace)
    audit_panel = _audit_panel_for_trace(platform, trace)
    # Prefer the trace's frozen claim_provenance over live retrieval
    # — the trace is the audit-correct view of what evidence drove
    # this specific outcome. Live KnowledgeStore reads can drift if a
    # claim is re-verified or re-extracted later.
    evidence_panel = _evidence_panel(
        platform, application_id, decision_id, trace=trace
    )

    has_human_review = trace is not None and trace.human_review is not None
    can_act = queue_item is not None and not has_human_review
    can_send_back = (
        decision_spec.get("type") == "dependent" and queue_item is not None
    )

    return {
        "application_id":      application_id,
        "applicant_id":        app_value.get("applicant_id"),
        "display_name":        _display_name(app_value, application_id),
        "initials":            _initials(app_value, application_id),
        "avatar_tone":         _avatar_tone(application_id),
        "loan_summary":        _loan_summary(app_value, loan_value),
        "amount":              app_value.get("requested_amount"),
        "risk_pill":           (
            _risk_pill_for_persona(decision_id, trace)
            if trace is not None
            else _risk_pill_for_confidence(None)
        ),
        "trace":               trace,
        "trace_id":            str(trace.trace_id) if trace else None,
        "queue_item_id":       str(queue_item.id) if queue_item else None,
        "outcome":             trace.outcome.value if trace else None,
        "outcome_style":       OUTCOME_STYLES.get(
            trace.outcome.value if trace else "pending",
            OUTCOME_STYLES["pending"],
        ),
        "confidence":          trace.confidence if trace else None,
        "matched_clause":      trace.matched_clause if trace else None,
        "application_context": application_context,
        "signals_evaluated":   signals_evaluated,
        "ai_reasoning":        ai_reasoning,
        "policy_panel":        policy_panel,
        "audit_panel":         audit_panel,
        "evidence_panel":      evidence_panel,
        "has_human_review":    has_human_review,
        "human_review":        trace.human_review if has_human_review else None,
        "can_act":             can_act,
        "can_send_back":       can_send_back,
        "decision_outcomes":   [o.value for o in DecisionOutcome],
    }


# ─────────────────────────────────────────────────────────────────────
# Policy + Evidence panels — surface STREAM C / STREAM E in the UI.
# Used by both persona workbench detail and decision detail.
# ─────────────────────────────────────────────────────────────────────


def _audit_panel_for_trace(
    platform: Platform, trace: Optional[DecisionTrace]
) -> Optional[dict[str, Any]]:
    """Look up the AuditRecord whose decision_id matches this trace's
    trace_id and return a panel-shaped dict (4-check status pills +
    flags + an `audit_id` link target). Returns None when audit isn't
    wired or the record isn't present."""

    if trace is None:
        return None
    audit_store = getattr(platform, "audit_store", None)
    if audit_store is None:
        return None

    records = getattr(audit_store, "_records", None)
    if not isinstance(records, dict):
        return None

    record = next(
        (r for r in records.values() if r.decision_id == trace.trace_id),
        None,
    )
    if record is None:
        return None

    overall = record.overall_status.value
    return {
        "audit_id":           str(record.audit_id),
        "overall_status":     overall,
        "overall_tone":       AUDIT_STATUS_TONES.get(overall, "slate"),
        "compliance_status":  record.compliance_status.value,
        "security_status":    record.security_status.value,
        "ethics_status":      record.ethics_status.value,
        "fairness_status":    record.fairness_status.value,
        "regulation_tags":    list(record.regulation_tags or []),
        "consent_status":     record.consent_status.value,
        "fairness_flag_count": len(record.fairness_flags or []),
        "protected_attrs_used": list(record.protected_attrs_used or []),
        "applicant_segment":  record.applicant_segment,
        "human_reviewed":     record.human_reviewed,
    }


def _policy_panel(
    platform: Platform, trace: Optional[DecisionTrace]
) -> Optional[dict[str, Any]]:
    """Resolve the PolicyVersion that fired on this trace + extract
    display fields. Returns None when policy_version_id wasn't stamped
    (legacy traces from before STREAM C phase 2)."""

    if trace is None or not trace.policy_version_id:
        return None

    policy_store = getattr(platform, "policy_store", None)
    if policy_store is None:
        return None

    versions = getattr(policy_store, "_iter_active_values", lambda _t: [])(
        "PolicyVersion"
    )
    version = next(
        (v for v in versions if v.get("policy_version_id") == trace.policy_version_id),
        None,
    )
    policies = getattr(policy_store, "_iter_active_values", lambda _t: [])("Policy")
    policy = None
    if version is not None:
        policy = next(
            (p for p in policies if p.get("policy_id") == version.get("policy_id")),
            None,
        )

    chain_ids = list(trace.policy_chain or [])
    return {
        "policy_version_id": trace.policy_version_id,
        "policy_id":         version.get("policy_id") if version else None,
        "version_number":    version.get("version_number") if version else None,
        "valid_from":        version.get("valid_from") if version else None,
        "valid_to":          version.get("valid_to") if version else None,
        "source_revision":   version.get("source_revision") if version else None,
        "source_url":        version.get("source_url") if version else None,
        "agency":            policy.get("agency") if policy else None,
        "owner_team":        policy.get("owner_team") if policy else None,
        "policy_name":       policy.get("name") if policy else None,
        "policy_chain":      chain_ids,
        "chain_size":        len(chain_ids),
    }


def _evidence_panel(
    platform: Platform,
    application_id: str,
    decision_id: str,
    *,
    trace: Optional[DecisionTrace] = None,
) -> dict[str, Any]:
    """List the verified Claims that drove this decision + their source
    Documents. Reads via Retriever so the doc_type matrix gating is
    honoured — only claims this decision is allowed to see appear.

    When a ``trace`` is supplied AND it carries claim_provenance, that
    frozen list wins over live retrieval — the trace is the audit-
    correct view of what drove THIS specific outcome. Live retrieval
    stays as fallback (no trace yet, or trace pre-dates the
    claim_provenance feature)."""

    # Frozen-trace path: the audit-correct answer.
    if (
        trace is not None
        and getattr(trace, "claim_provenance", None)
    ):
        return _evidence_panel_from_provenance(
            platform, application_id, decision_id, trace
        )

    retriever = getattr(platform, "retriever", None)
    knowledge_store = getattr(platform, "knowledge_store", None)
    if retriever is None:
        return {
            "claims": [],
            "documents": [],
            "doc_types_consulted": 0,
        }

    # `retrieve` is async — render-time path is sync. Walk the
    # KnowledgeStore directly for v0; same in-memory walk Retriever
    # uses, but synchronous. Postgres swap will need to flip the views
    # to async, which is already on the TIER 1 list.
    docs_by_id: dict[str, Any] = {}
    if knowledge_store is not None:
        for d in _ks_list_sync(knowledge_store, "Document"):
            if d.get("application_id") != application_id:
                continue
            docs_by_id[d.get("document_id")] = d

    matrix = _doc_type_matrix(platform)
    relevant_doc_types = {
        dt for dt, entry in matrix.items()
        if isinstance(entry, dict)
        and decision_id in (entry.get("feeds_decisions") or [])
    }

    rows: list[dict[str, Any]] = []
    referenced_doc_ids: set[str] = set()
    if knowledge_store is not None:
        for c in _ks_list_sync(knowledge_store, "Claim"):
            if c.get("application_id") != application_id:
                continue
            if c.get("status") != "verified":
                continue
            doc_id = c.get("document_id")
            doc = docs_by_id.get(doc_id) or {}
            if doc.get("doc_type") not in relevant_doc_types:
                continue
            referenced_doc_ids.add(doc_id)
            rows.append({
                "field_name":    c.get("field_name"),
                "value":         c.get("field_value"),
                "source_doc_id": doc_id,
                "source_page":   c.get("source_page"),
                "verified_by":   c.get("verified_by"),
                "verified_at":   c.get("verified_at"),
                "extraction_method": c.get("extraction_method"),
                "extraction_confidence": c.get("extraction_confidence"),
                "doc_type":      doc.get("doc_type"),
            })

    referenced_docs = [
        {
            "document_id": did,
            "doc_type":    docs_by_id[did].get("doc_type"),
            "status":      docs_by_id[did].get("status"),
            "source_url":  docs_by_id[did].get("source_url"),
            "source_system": docs_by_id[did].get("source_system"),
            "page_count":  docs_by_id[did].get("page_count"),
            "verified_by": docs_by_id[did].get("verified_by"),
        }
        for did in referenced_doc_ids if did in docs_by_id
    ]

    return {
        "claims": rows,
        "documents": referenced_docs,
        "doc_types_consulted": len(relevant_doc_types),
        "doc_types_in_scope": sorted(relevant_doc_types),
    }


def _evidence_panel_from_provenance(
    platform: Platform,
    application_id: str,
    decision_id: str,
    trace: DecisionTrace,
) -> dict[str, Any]:
    """Build the evidence panel from the trace's frozen claim_provenance.

    Each entry is the audit-correct view of what evidence the decision
    consumed. We still cross-reference live Documents for `doc_type` /
    `source_url` (which aren't on the frozen ClaimProvenance — those
    are stable Document metadata, not claim-time-frozen)."""

    knowledge_store = getattr(platform, "knowledge_store", None)
    docs_by_id: dict[str, dict[str, Any]] = {}
    if knowledge_store is not None:
        for d in _ks_list_sync(knowledge_store, "Document"):
            doc_id = d.get("document_id")
            if doc_id:
                docs_by_id[doc_id] = d

    rows: list[dict[str, Any]] = []
    referenced_doc_ids: set[str] = set()
    for c in trace.claim_provenance:
        doc = docs_by_id.get(c.document_id) or {}
        referenced_doc_ids.add(c.document_id)
        rows.append({
            "field_name":    c.field_name,
            "value":         c.field_value,
            "source_doc_id": c.document_id,
            "source_page":   c.source_page,
            "verified_by":   c.verified_by,
            "verified_at":   c.verified_at,
            "extraction_method": None,  # not frozen on ClaimProvenance
            "extraction_confidence": c.extraction_confidence,
            "doc_type":      doc.get("doc_type"),
            "frozen":        True,
        })

    referenced_docs = [
        {
            "document_id": did,
            "doc_type":    docs_by_id[did].get("doc_type") if did in docs_by_id else None,
            "status":      docs_by_id[did].get("status") if did in docs_by_id else None,
            "source_url":  docs_by_id[did].get("source_url") if did in docs_by_id else None,
            "source_system": docs_by_id[did].get("source_system") if did in docs_by_id else None,
            "page_count":  docs_by_id[did].get("page_count") if did in docs_by_id else None,
            "verified_by": docs_by_id[did].get("verified_by") if did in docs_by_id else None,
        }
        for did in referenced_doc_ids
    ]

    return {
        "claims": rows,
        "documents": referenced_docs,
        "doc_types_consulted": len(set(r.get("doc_type") for r in rows if r.get("doc_type"))),
        "doc_types_in_scope": sorted(
            set(r.get("doc_type") for r in rows if r.get("doc_type"))
        ),
        "frozen": True,
    }


def _ks_list_sync(knowledge_store: Any, entity_type: str) -> list[dict[str, Any]]:
    """Sync list-active over the in-memory knowledge store. Wraps the
    private `_iter_active_values` so the view layer doesn't need an
    event loop. Postgres swap uses a SELECT instead."""
    try:
        return knowledge_store._iter_active_values(entity_type)  # type: ignore[attr-defined]
    except Exception:
        return []


def _doc_type_matrix(platform: Platform) -> dict[str, Any]:
    """Cached doc_type matrix from knowledge_base.json. Cheap walk; not
    worth memoizing across requests for v0."""
    try:
        from core.knowledge.retriever import _load_doc_type_matrix
        return _load_doc_type_matrix()
    except Exception:
        return {}


def _persona_application_context(
    decision_id: str,
    app_value: dict[str, Any],
    loan_value: dict[str, Any],
    traces: list[DecisionTrace],
) -> list[dict[str, Any]]:
    """Right-aligned label/value rows. Source priority:
       1. fields the decision is supposed to read (per knowledge_base)
       2. always include core loan fields if present"""

    pairs: list[tuple[str, Any, Optional[str]]] = []
    upstream_payloads = {t.decision_id: (t.output_payload or {}) for t in traces}

    # Pull commonly relevant fields from upstream output_payload.
    credit = upstream_payloads.get("credit_assessment", {})
    income = upstream_payloads.get("income_verification", {})
    dti = upstream_payloads.get("dti_calculation", {})
    ltv = upstream_payloads.get("ltv_assessment", {})

    # Loan / application headline fields.
    if loan_value.get("loan_type"):
        pairs.append(("Loan type", loan_value.get("loan_type"), None))
    if loan_value.get("term_months"):
        pairs.append(("Term", f"{loan_value['term_months']} mo", None))
    if app_value.get("loan_purpose"):
        pairs.append(("Loan purpose", app_value.get("loan_purpose"), None))
    if app_value.get("property_state"):
        pairs.append(("Property state", app_value.get("property_state"), None))

    # Per-decision interesting context — same key fields the screenshot shows.
    if decision_id in (
        "credit_assessment", "rate_pricing", "ltv_assessment",
        "product_eligibility", "underwriting_decision",
    ):
        if credit.get("credit_band"):
            pairs.append(("Credit band", credit["credit_band"], None))
        if credit.get("credit_score") is not None:
            pairs.append(("Credit score", credit["credit_score"], None))
    if decision_id in (
        "credit_assessment", "rate_pricing", "underwriting_decision",
        "product_eligibility",
    ):
        if dti.get("dti_ratio") is not None:
            pairs.append(("DTI ratio", dti["dti_ratio"], "pct"))
    if decision_id in (
        "credit_assessment", "ltv_assessment", "rate_pricing",
        "underwriting_decision", "product_eligibility",
    ):
        if ltv.get("ltv_ratio") is not None:
            pairs.append(("LTV ratio", ltv["ltv_ratio"], "pct"))
    if decision_id in (
        "income_verification", "dti_calculation", "underwriting_decision",
    ):
        if income.get("verified_income") is not None:
            pairs.append(("Verified income", income["verified_income"], "currency"))
        if income.get("employment_type"):
            pairs.append(("Employment", income["employment_type"], None))

    return [
        {"label": lbl, "value": val, "fmt": fmt}
        for (lbl, val, fmt) in pairs
    ]


def _persona_signals(trace: Optional[DecisionTrace]) -> list[dict[str, Any]]:
    if trace is None or trace.reasoning is None:
        return []
    rows: list[dict[str, Any]] = []
    for sig in trace.reasoning.signals_evaluated:
        rows.append({
            "name":      sig.name,
            "value":     sig.value,
            "direction": sig.direction.value if sig.direction else "neutral",
            "notes":     sig.notes,
        })
    return rows


def _persona_ai_reasoning(trace: Optional[DecisionTrace]) -> Optional[dict[str, Any]]:
    if trace is None or trace.reasoning is None:
        return None
    r = trace.reasoning
    return {
        "hypothesis":     r.hypothesis_tested,
        "summary":        r.human_readable_summary,
        "conclusion":     r.conclusion,
        "confidence_basis": r.confidence_basis,
        "contradiction_count": len(r.contradictions_found or []),
    }


# ─────────────────────────────────────────────────────────────────────
# Persona helpers (cosmetic / display)
# ─────────────────────────────────────────────────────────────────────


def _application_value(platform: Platform, app_id: str) -> dict[str, Any]:
    durable = platform.store._durable  # type: ignore[attr-defined]
    records = getattr(durable, "_records", None) or []
    rec = next(
        (r for r in records
         if r.entity_type == "Application" and r.entity_id == app_id
         and r.superseded_at is None),
        None,
    )
    return rec.value if rec else {}


def _loan_value(platform: Platform, app_id: str) -> dict[str, Any]:
    durable = platform.store._durable  # type: ignore[attr-defined]
    records = getattr(durable, "_records", None) or []
    rec = next(
        (r for r in records
         if r.entity_type == "Loan"
         and isinstance(r.value, dict)
         and r.value.get("application_id") == app_id
         and r.superseded_at is None),
        None,
    )
    return rec.value if rec else {}


# Demo-only deterministic name generation. Real applicant names flow
# in via real connectors (LeadReceived event payload) — for now we
# derive a stable "First Last" from applicant_id so screenshots and
# demos read like a real loan file. The same applicant_id always
# produces the same name across runs.
#
# Two small lists (12 first names × 12 last names = 144 combos). For
# 7 seed applicants the collision probability is low enough that the
# demo reads naturally. Real PII never flows through here — the seed
# applicant_ids are fake to begin with.
_DEMO_FIRST_NAMES: tuple[str, ...] = (
    "Priya", "James", "Marcus", "Elena", "Hailey", "Jordan",
    "Aisha", "Raj", "Sofia", "Kenji", "Amara", "Diego",
)
_DEMO_LAST_NAMES: tuple[str, ...] = (
    "Patel", "Okafor", "Chen", "Rodriguez", "Mendez", "Kim",
    "Nguyen", "Williams", "Garcia", "Singh", "Johnson", "Park",
)


def _friendly_name_from_id(applicant_id: Optional[str]) -> Optional[str]:
    """Deterministic First Last from applicant_id. Returns None if id
    is empty/None — caller falls back to the raw id."""
    if not isinstance(applicant_id, str) or not applicant_id:
        return None
    h = sum(ord(c) * (i + 1) for i, c in enumerate(applicant_id))
    first = _DEMO_FIRST_NAMES[h % len(_DEMO_FIRST_NAMES)]
    last = _DEMO_LAST_NAMES[(h // 7) % len(_DEMO_LAST_NAMES)]
    return f"{first} {last}"


def _display_name(app_value: dict[str, Any], application_id: str) -> str:
    """Applicant display name. Real path: full_name on the Application
    (flows from real connectors). Demo path: deterministic name from
    applicant_id so demos read like a real loan file. Last-resort
    fallback: applicant_id verbatim, then application_id."""

    return (
        app_value.get("full_name")
        or _friendly_name_from_id(app_value.get("applicant_id"))
        or app_value.get("applicant_id")
        or application_id
    )


def _initials(app_value: dict[str, Any], application_id: str) -> str:
    name = _display_name(app_value, application_id)
    if not isinstance(name, str) or not name:
        return "—"
    parts = [p for p in name.replace("_", " ").split(" ") if p]
    if not parts:
        return name[:2].upper()
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return parts[0][:2].upper()


def _avatar_tone(seed: str) -> str:
    if not seed:
        return "slate"
    idx = sum(ord(c) for c in seed) % len(_AVATAR_TONES)
    return _AVATAR_TONES[idx]


# Loan-type display labels. Domain abbreviations (FHA, VA, USDA) need
# uppercase; non_qm is conventionally written "Non-QM". Falls back to
# .title() for unknown types so a future loan_type still renders.
LOAN_TYPE_LABELS: dict[str, str] = {
    "conforming": "Conforming",
    "jumbo":      "Jumbo",
    "fha":        "FHA",
    "va":         "VA",
    "usda":       "USDA",
    "non_qm":     "Non-QM",
}


def _loan_type_label(loan_type: Optional[str]) -> str:
    if not loan_type:
        return ""
    raw = loan_type.strip().lower()
    return LOAN_TYPE_LABELS.get(raw, raw.replace("_", " ").title())


def _loan_summary(
    app_value: dict[str, Any], loan_value: dict[str, Any]
) -> str:
    type_label = _loan_type_label(loan_value.get("loan_type"))
    term_months = loan_value.get("term_months")
    term_years = (
        f"{int(term_months / 12)}yr"
        if isinstance(term_months, (int, float)) and term_months
        else ""
    )
    application_id = app_value.get("application_id") or ""
    parts: list[str] = []
    if application_id:
        parts.append(application_id)
    if type_label and term_years:
        parts.append(f"{type_label} {term_years}")
    elif type_label:
        parts.append(type_label)
    elif term_years:
        parts.append(term_years)
    return " · ".join(parts) if parts else "—"


def _minutes_ago(when: Optional[datetime]) -> Optional[int]:
    if when is None:
        return None
    delta = datetime.utcnow() - when
    minutes = int(delta.total_seconds() / 60)
    return max(0, minutes)


def _risk_pill_for_confidence(confidence: Optional[float]) -> str:
    """Per-app risk pill for the queue rows. Mirrors the screenshot:
    high confidence → low risk; lower confidence → higher risk. Drives
    UI tone, not policy."""

    if confidence is None:
        return "medium"
    try:
        c = float(confidence)
    except (TypeError, ValueError):
        return "medium"
    if c >= 0.85:
        return "low"
    if c >= 0.65:
        return "medium"
    return "high"


# Per-persona risk-pill mappings. These pills drive UI tone, not
# policy — they're a quick visual signal in the queue/recently-completed
# rows so the operator can spot high-touch loans without opening each.
# Confidence-only ("how sure was the AI") rolled into one bucket because
# offline reasoners produce ≥0.85 on most happy-path scenarios.
_CREDIT_BAND_RISK: dict[str, str] = {
    "super_prime":   "low",
    "prime":         "low",
    "near_prime":    "medium",
    "subprime":      "high",
    "deep_subprime": "high",
    "thin_file":     "medium",
}


def _risk_pill_for_persona(decision_id: str, payload_or_item: Any) -> str:
    """Decision-aware risk pill. Falls back to confidence when the
    decision-specific signal isn't present.

    Argument is either a trace (uses .output_payload) or a HumanQueueItem
    (uses .payload). Both expose the relevant signal under the same
    field names."""

    payload = getattr(payload_or_item, "output_payload", None)
    if payload is None:
        payload = getattr(payload_or_item, "payload", None)
    if not isinstance(payload, dict):
        payload = {}

    if decision_id == "credit_assessment":
        band = payload.get("credit_band")
        if isinstance(band, str) and band in _CREDIT_BAND_RISK:
            return _CREDIT_BAND_RISK[band]

    if decision_id == "fraud_screening":
        score = payload.get("fraud_score")
        if isinstance(score, (int, float)):
            if score < 0.2:
                return "low"
            if score < 0.5:
                return "medium"
            return "high"

    if decision_id == "ltv_assessment":
        ltv = payload.get("ltv_ratio") or payload.get("ltv")
        if isinstance(ltv, (int, float)):
            if ltv <= 0.80:
                return "low"
            if ltv <= 0.95:
                return "medium"
            return "high"

    if decision_id == "dti_calculation":
        dti = payload.get("dti_ratio") or payload.get("dti")
        if isinstance(dti, (int, float)):
            if dti <= 0.36:
                return "low"
            if dti <= 0.43:
                return "medium"
            return "high"

    if decision_id == "income_verification":
        emp = payload.get("employment_type")
        verified = payload.get("payroll_verified")
        if emp == "salaried" and verified:
            return "low"
        if emp in ("self_employed", "contractor"):
            return "medium"
        # Falls through to confidence below.

    if decision_id == "underwriting_decision":
        risk = payload.get("risk_score")
        if isinstance(risk, (int, float)):
            if risk <= 0.25:
                return "low"
            if risk <= 0.60:
                return "medium"
            return "high"

    # Last resort — confidence on the trace / queue item.
    confidence = getattr(payload_or_item, "confidence", None)
    return _risk_pill_for_confidence(confidence)


# ─────────────────────────────────────────────────────────────────────
# Policy inspection — list + detail
# ─────────────────────────────────────────────────────────────────────


# Display-friendly agency labels.
AGENCY_LABELS: dict[str, str] = {
    "lender_overlay": "Lender Overlay",
    "freddie":        "Freddie Mac",
    "fannie":         "Fannie Mae",
    "fha":            "FHA",
    "va":             "VA",
    "usda":           "USDA",
    "cfpb":           "CFPB",
    "state":          "State",
}


def list_policies(platform: Platform) -> dict[str, Any]:
    """Index of all active Policy + their PolicyVersions, grouped by
    agency for navigation."""

    policy_store = getattr(platform, "policy_store", None)
    if policy_store is None:
        return {"agencies": [], "total_policies": 0, "total_versions": 0}

    policies = policy_store._iter_active_values("Policy")  # type: ignore[attr-defined]
    versions = policy_store._iter_active_values("PolicyVersion")  # type: ignore[attr-defined]

    # Group versions by policy_id.
    versions_by_policy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for v in versions:
        versions_by_policy[v.get("policy_id", "")].append(v)
    for pid in versions_by_policy:
        versions_by_policy[pid].sort(
            key=lambda v: v.get("version_number", 0), reverse=True
        )

    # Group policies by agency.
    by_agency: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in policies:
        agency = p.get("agency", "unknown")
        decision_id = p.get("decision_id")
        policy_versions = versions_by_policy.get(p.get("policy_id", ""), [])
        latest = policy_versions[0] if policy_versions else None
        by_agency[agency].append({
            "policy_id": p.get("policy_id"),
            "name":      p.get("name"),
            "decision_id": decision_id,
            "decision_label": PERSONA_LABELS.get(
                decision_id, decision_id or "—"
            ) if decision_id else "—",
            "owner_team": p.get("owner_team"),
            "product_scope": p.get("product_scope") or [],
            "state_scope":   p.get("state_scope") or [],
            "version_count": len(policy_versions),
            "latest_version_id":     latest.get("policy_version_id") if latest else None,
            "latest_version_number": latest.get("version_number") if latest else None,
            "latest_valid_from":     latest.get("valid_from") if latest else None,
            "latest_source_revision": latest.get("source_revision") if latest else None,
        })

    agencies = []
    for agency in sorted(by_agency.keys()):
        items = by_agency[agency]
        items.sort(key=lambda i: (i.get("decision_id") or "", i.get("policy_id") or ""))
        agencies.append({
            "agency":       agency,
            "label":        AGENCY_LABELS.get(agency, agency),
            "policy_count": len(items),
            "policies":     items,
        })

    return {
        "agencies": agencies,
        "total_policies": len(policies),
        "total_versions": len(versions),
    }


def policy_version_detail(
    platform: Platform, policy_version_id: str
) -> Optional[dict[str, Any]]:
    """Detail view for a single PolicyVersion."""

    policy_store = getattr(platform, "policy_store", None)
    if policy_store is None:
        return None

    versions = policy_store._iter_active_values("PolicyVersion")  # type: ignore[attr-defined]
    version = next(
        (v for v in versions if v.get("policy_version_id") == policy_version_id),
        None,
    )
    if version is None:
        return None

    policies = policy_store._iter_active_values("Policy")  # type: ignore[attr-defined]
    policy = next(
        (p for p in policies if p.get("policy_id") == version.get("policy_id")),
        None,
    )

    # All versions for this policy — supersession chain view.
    siblings = sorted(
        [v for v in versions if v.get("policy_id") == version.get("policy_id")],
        key=lambda v: v.get("version_number", 0),
        reverse=True,
    )

    boundary = version.get("boundary") or {}
    boundary_clauses = []
    for clause in ("block_if", "escalate_if", "recommend_if", "automate_if"):
        rules = boundary.get(clause) or []
        boundary_clauses.append({
            "clause":     clause,
            "rule_count": len(rules),
            "rules":      list(rules),
            "tone":       _clause_tone(clause),
        })

    return {
        "policy_version_id": policy_version_id,
        "version":           version,
        "policy":            policy,
        "agency":            policy.get("agency") if policy else None,
        "agency_label":      AGENCY_LABELS.get(
            policy.get("agency", "") if policy else "", "—"
        ),
        "decision_id":       policy.get("decision_id") if policy else None,
        "decision_label":    PERSONA_LABELS.get(
            policy.get("decision_id", "") if policy else "",
            policy.get("decision_id", "") if policy else "—",
        ),
        "boundary_clauses":  boundary_clauses,
        "siblings":          siblings,
    }


def _clause_tone(clause: str) -> str:
    return {
        "block_if":     "rose",
        "escalate_if":  "orange",
        "recommend_if": "amber",
        "automate_if":  "emerald",
    }.get(clause, "slate")


# ─────────────────────────────────────────────────────────────────────
# Document inspection — list per application + single doc detail
# ─────────────────────────────────────────────────────────────────────


# Display-friendly status pill tones for Document.status.
DOC_STATUS_TONES: dict[str, str] = {
    "verified":         "emerald",
    "human_corrected":  "amber",
    "ocr_extracted":    "amber",
    "unverified":       "slate",
    "rejected":         "rose",
}


def list_documents_for_application(
    platform: Platform, application_id: str
) -> dict[str, Any]:
    """All Documents uploaded for an application + claim counts."""

    knowledge_store = getattr(platform, "knowledge_store", None)
    if knowledge_store is None:
        return {
            "application_id": application_id,
            "documents": [],
            "total_documents": 0,
            "total_claims": 0,
        }

    docs_raw = _ks_list_sync(knowledge_store, "Document")
    claims_raw = _ks_list_sync(knowledge_store, "Claim")

    docs_for_app = [d for d in docs_raw if d.get("application_id") == application_id]
    claims_for_app = [
        c for c in claims_raw if c.get("application_id") == application_id
    ]

    claims_by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in claims_for_app:
        doc_id = c.get("document_id")
        if doc_id:
            claims_by_doc[doc_id].append(c)

    rows: list[dict[str, Any]] = []
    for d in docs_for_app:
        doc_id = d.get("document_id", "")
        doc_claims = claims_by_doc.get(doc_id, [])
        verified_claim_count = sum(1 for c in doc_claims if c.get("status") == "verified")
        rows.append({
            "document_id":  doc_id,
            "doc_type":     d.get("doc_type"),
            "status":       d.get("status"),
            "status_tone":  DOC_STATUS_TONES.get(d.get("status", ""), "slate"),
            "source_system": d.get("source_system"),
            "source_url":   d.get("source_url"),
            "uploaded_at":  d.get("uploaded_at"),
            "uploaded_by":  d.get("uploaded_by"),
            "verified_at":  d.get("verified_at"),
            "verified_by":  d.get("verified_by"),
            "ocr_confidence": d.get("ocr_confidence"),
            "page_count":   d.get("page_count"),
            "claim_count":  len(doc_claims),
            "verified_claim_count": verified_claim_count,
        })

    rows.sort(key=lambda r: (r.get("doc_type") or "", r.get("uploaded_at") or ""))

    return {
        "application_id":   application_id,
        "documents":        rows,
        "total_documents":  len(rows),
        "total_claims":     sum(r["claim_count"] for r in rows),
    }


def list_pending_claims(platform: Platform) -> dict[str, Any]:
    """Cross-application pending-claim queue. Fed by KnowledgeStore;
    each row links to the source document + has verify/reject actions."""

    knowledge_store = getattr(platform, "knowledge_store", None)
    if knowledge_store is None:
        return {"claims": [], "total": 0}

    claims_raw = _ks_list_sync(knowledge_store, "Claim")
    docs_raw = _ks_list_sync(knowledge_store, "Document")
    docs_by_id = {d.get("document_id"): d for d in docs_raw}

    pending = [c for c in claims_raw if c.get("status") == "pending"]
    pending.sort(key=lambda c: c.get("extracted_at") or "", reverse=True)

    rows: list[dict[str, Any]] = []
    for c in pending:
        doc = docs_by_id.get(c.get("document_id"), {})
        rows.append({
            "claim_id":         c.get("claim_id"),
            "document_id":      c.get("document_id"),
            "doc_type":         doc.get("doc_type"),
            "application_id":   c.get("application_id"),
            "applicant_id":     c.get("applicant_id"),
            "field_name":       c.get("field_name"),
            "field_value":      c.get("field_value"),
            "source_page":      c.get("source_page"),
            "extraction_method": c.get("extraction_method"),
            "extraction_confidence": c.get("extraction_confidence"),
            "extracted_at":     c.get("extracted_at"),
            "extracted_by":     c.get("extracted_by"),
            "doc_status":       doc.get("status"),
            "doc_ocr_confidence": doc.get("ocr_confidence"),
        })

    return {"claims": rows, "total": len(rows)}


def document_detail_view(
    platform: Platform, document_id: str
) -> Optional[dict[str, Any]]:
    """Single Document detail + all its Claims."""

    knowledge_store = getattr(platform, "knowledge_store", None)
    if knowledge_store is None:
        return None

    docs_raw = _ks_list_sync(knowledge_store, "Document")
    doc = next(
        (d for d in docs_raw if d.get("document_id") == document_id), None
    )
    if doc is None:
        return None

    claims_raw = _ks_list_sync(knowledge_store, "Claim")
    claims_for_doc = [
        c for c in claims_raw if c.get("document_id") == document_id
    ]
    claims_for_doc.sort(key=lambda c: c.get("field_name") or "")

    return {
        "document":   doc,
        "doc_type":   doc.get("doc_type"),
        "status":     doc.get("status"),
        "status_tone": DOC_STATUS_TONES.get(doc.get("status", ""), "slate"),
        "claims":     claims_for_doc,
        "claim_count": len(claims_for_doc),
        "verified_count": sum(1 for c in claims_for_doc if c.get("status") == "verified"),
        "pending_count":  sum(1 for c in claims_for_doc if c.get("status") == "pending"),
    }


# ─────────────────────────────────────────────────────────────────────
# Audit views — list flags + drill into a single AuditRecord
# ─────────────────────────────────────────────────────────────────────


# Tone palette for the four overall_status values.
AUDIT_STATUS_TONES = {
    "pass": "emerald",
    "warn": "amber",
    "fail": "rose",
}


def _audit_records_sync(audit_store: Any) -> list[Any]:
    """Best-effort sync read of every AuditRecord. The InMemory store
    exposes _records as a {audit_id: AuditRecord} dict; production
    Postgres is async, so this view reads via the public coroutine
    when available and falls back to the dict otherwise."""

    records_attr = getattr(audit_store, "_records", None)
    if isinstance(records_attr, dict):
        return list(records_attr.values())
    return []


def _audit_record_to_row(record: Any) -> dict[str, Any]:
    overall = getattr(record.overall_status, "value", record.overall_status)
    return {
        "audit_id":           str(record.audit_id),
        "decision_id":        str(record.decision_id),
        "application_id":     record.application_id,
        "decision_type":      record.decision_type,
        "decision_label":     PERSONA_LABELS.get(record.decision_type, record.decision_type),
        "owner":              record.owner,
        "mode":               getattr(record.mode, "value", record.mode),
        "outcome":            getattr(record.decision_output, "value", record.decision_output),
        "overall_status":     overall,
        "overall_tone":       AUDIT_STATUS_TONES.get(overall, "slate"),
        "compliance_status":  getattr(record.compliance_status, "value", record.compliance_status),
        "security_status":    getattr(record.security_status, "value", record.security_status),
        "ethics_status":      getattr(record.ethics_status, "value", record.ethics_status),
        "fairness_status":    getattr(record.fairness_status, "value", record.fairness_status),
        "regulation_tags":    list(record.regulation_tags or []),
        "consent_status":     getattr(record.consent_status, "value", record.consent_status),
        "fairness_flag_count": len(record.fairness_flags or []),
        "bias_score":         record.bias_score,
        "human_reviewed":     record.human_reviewed,
        "timestamp":          record.timestamp,
    }


def list_audit_flags(platform: Platform) -> dict[str, Any]:
    """Cross-application audit flags index. Surfaces every record
    whose overall_status is warn or fail so the compliance team can
    work the queue."""

    audit_store = getattr(platform, "audit_store", None)
    if audit_store is None:
        return {"flags": [], "total": 0, "warn_count": 0, "fail_count": 0}

    records = _audit_records_sync(audit_store)
    flagged = [
        r for r in records
        if getattr(r.overall_status, "value", r.overall_status) in ("warn", "fail")
    ]
    flagged.sort(key=lambda r: (r.timestamp or datetime.min), reverse=True)

    rows = [_audit_record_to_row(r) for r in flagged]
    return {
        "flags":       rows,
        "total":       len(rows),
        "warn_count":  sum(1 for r in rows if r["overall_status"] == "warn"),
        "fail_count":  sum(1 for r in rows if r["overall_status"] == "fail"),
    }


def list_audit_for_application(
    platform: Platform, application_id: str
) -> dict[str, Any]:
    """Per-application audit roster. Used by the application detail
    page to render the "all decisions audited" summary strip."""

    audit_store = getattr(platform, "audit_store", None)
    if audit_store is None:
        return {"records": [], "application_id": application_id}

    records = [
        r for r in _audit_records_sync(audit_store)
        if r.application_id == application_id
    ]
    records.sort(key=lambda r: (r.timestamp or datetime.min))
    return {
        "records":        [_audit_record_to_row(r) for r in records],
        "application_id": application_id,
        "decision_count": len(records),
    }


def audit_record_detail(
    platform: Platform, audit_id: str
) -> Optional[dict[str, Any]]:
    """Drilldown for a single AuditRecord. Renders all four blocks +
    associated check findings (re-runs the checkers in dry-run mode
    so the UI shows the same findings strings the engine produced)."""

    from core.audit.compliance_checker import ComplianceChecker
    from core.audit.ethics_checker import EthicsChecker
    from core.audit.fairness_checker import FairnessChecker
    from core.audit.security_checker import SecurityChecker

    audit_store = getattr(platform, "audit_store", None)
    if audit_store is None:
        return None

    matching = [
        r for r in _audit_records_sync(audit_store)
        if str(r.audit_id) == audit_id
    ]
    if not matching:
        return None
    record = matching[0]

    # Re-run checkers — pure functions on the record, so this is cheap
    # and gives the UI the actual `findings` strings without persisting
    # them on the record itself.
    findings = {
        "compliance": ComplianceChecker().check(record).findings,
        "security":   SecurityChecker().check(record).findings,
        "ethics":     EthicsChecker().check(record).findings,
        "fairness":   FairnessChecker().check(record).findings,
    }

    # Adverse-action signal — drives the "ECOA notice" link in the UI.
    from core.audit.adverse_action import is_adverse_action

    overall = getattr(record.overall_status, "value", record.overall_status)
    return {
        "record":          record,
        "row":             _audit_record_to_row(record),
        "findings":        findings,
        "overall_tone":    AUDIT_STATUS_TONES.get(overall, "slate"),
        "policy_applied":  [p.model_dump() for p in record.policy_applied],
        "fairness_flags":  [f.model_dump() for f in record.fairness_flags],
        "accessed_by":     [a.model_dump() for a in record.accessed_by],
        "is_adverse_action": is_adverse_action(record),
    }


# ═════════════════════════════════════════════════════════════════════
# EDMS DATA LAYER — added late, optional, off by default.
#
# When DATABASE_URL is set the async dispatchers below return view-model
# dicts shaped IDENTICALLY to the existing sync helpers, but populated
# from EDMS PostgreSQL instead of the in-memory Platform. ui/routes.py
# always calls the async dispatcher; when DATABASE_URL is empty the
# dispatcher just delegates back to the sync helper, so nothing about
# the in-memory path changes and the test suite is unaffected.
# ═════════════════════════════════════════════════════════════════════


import os as _edms_os
import json as _edms_json

# Pick up DATABASE_URL from .env if present (mirrors core/cron/runner.py).
try:
    from dotenv import load_dotenv as _edms_load_dotenv  # type: ignore

    _edms_load_dotenv()
except ImportError:  # pragma: no cover — listed in requirements.txt
    pass


DATABASE_URL: Optional[str] = (
    _edms_os.environ.get("DATABASE_URL", "").strip() or None
)


_edms_store_singleton: Any = None
_decision_store_singleton: Any = None
_edms_pool: Any = None


def _get_edms_stores() -> tuple[Any, Any]:
    """Return (EdmsContextStore, DecisionStore) — or (None, None) when
    DATABASE_URL is not configured. Lazy so module import stays cheap."""
    global _edms_store_singleton, _decision_store_singleton
    if not DATABASE_URL:
        return (None, None)
    if _edms_store_singleton is None:
        from core.edms_store import EdmsContextStore
        from core.decision_store import DecisionStore

        _edms_store_singleton = EdmsContextStore(DATABASE_URL)
        _decision_store_singleton = DecisionStore(DATABASE_URL)
    return (_edms_store_singleton, _decision_store_singleton)


async def _get_edms_pool() -> Any:
    """A separate asyncpg pool for ad-hoc reads the store classes don't
    expose. Reusing the pool inside the store classes would require
    poking at private state; cheaper to keep one more pool."""
    global _edms_pool
    if _edms_pool is None:
        import asyncpg  # type: ignore

        _edms_pool = await asyncpg.create_pool(
            DATABASE_URL, min_size=1, max_size=5
        )
    return _edms_pool


# ─── helpers ─────────────────────────────────────────────────────────


def _edms_maybe_json(val: Any) -> Any:
    if val is None or isinstance(val, (dict, list)):
        return val
    if isinstance(val, (bytes, bytearray)):
        val = val.decode("utf-8", errors="replace")
    if isinstance(val, str):
        try:
            return _edms_json.loads(val)
        except (ValueError, _edms_json.JSONDecodeError):
            return val
    return val


def _edms_jsonify(val: Any) -> Any:
    """Recursively replace non-JSON-serializable values (datetime, UUID,
    Decimal) with strings. Templates call ``| tojson`` on these dicts;
    a stray datetime in a JSONB payload would otherwise raise."""
    from datetime import date as _date
    from decimal import Decimal as _Decimal
    from uuid import UUID as _UUID

    if val is None or isinstance(val, (str, int, float, bool)):
        return val
    if isinstance(val, dict):
        return {k: _edms_jsonify(v) for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        return [_edms_jsonify(v) for v in val]
    if isinstance(val, (datetime, _date)):
        return val.isoformat()
    if isinstance(val, _UUID):
        return str(val)
    if isinstance(val, _Decimal):
        return float(val)
    return str(val)


def _edms_outcome_style(outcome: Optional[str]) -> dict[str, str]:
    return OUTCOME_STYLES.get(outcome or "pending", OUTCOME_STYLES["pending"])


def _edms_halt_reason(outcomes_by_decision: dict[str, str]) -> Optional[str]:
    if outcomes_by_decision.get("fraud_screening") == "block":
        return "fraud_block_stops_pipeline"
    if outcomes_by_decision.get("compliance_check") == "block":
        return "compliance_block_stops_closing"
    return None


# ─── 1) list_applications ────────────────────────────────────────────


async def _list_applications_edms() -> list[dict[str, Any]]:
    pool = await _get_edms_pool()
    async with pool.acquire() as conn:
        apps = await conn.fetch(
            """
            SELECT application_id, decisions_complete, decisions_total,
                   has_block, pending_human_review, escalate_count,
                   pipeline_started, last_decision_at
            FROM vw_pipeline_status
            ORDER BY application_id
            LIMIT 250
            """
        )
        # Per-app outcome rollup in one round trip.
        outcome_rows = await conn.fetch(
            """
            SELECT application_id, decision_id, outcome
            FROM decision_outputs
            WHERE version = (
                SELECT MAX(version) FROM decision_outputs d2
                WHERE d2.application_id = decision_outputs.application_id
                  AND d2.decision_id = decision_outputs.decision_id
            )
            """
        )
        entity_rows = await conn.fetch(
            """
            SELECT application_id, status, loan_amount, loan_terms
            FROM entity_states
            """
        )
    outcomes_by_app: dict[str, dict[str, str]] = {}
    for r in outcome_rows:
        outcomes_by_app.setdefault(r["application_id"], {})[r["decision_id"]] = r["outcome"]
    entity_by_app: dict[str, dict[str, Any]] = {}
    for r in entity_rows:
        loan_terms = _edms_maybe_json(r["loan_terms"]) or {}
        entity_by_app[r["application_id"]] = {
            "loan_amount": r["loan_amount"],
            "status": r["status"],
            "loan_terms": loan_terms if isinstance(loan_terms, dict) else {},
        }

    rows: list[dict[str, Any]] = []
    for a in apps:
        app_id = a["application_id"]
        per_app = outcomes_by_app.get(app_id, {})
        counts: dict[str, int] = defaultdict(int)
        for o in per_app.values():
            counts[o] += 1
        es = entity_by_app.get(app_id, {})
        loan_terms = es.get("loan_terms", {})
        rows.append(
            {
                "application_id":   app_id,
                "loan_purpose":     loan_terms.get("loan_purpose"),
                "requested_amount": (
                    loan_terms.get("loan_amount") or es.get("loan_amount")
                ),
                "property_state":   loan_terms.get("property_state"),
                "submitted_at":     a["pipeline_started"],
                "completed":        int(a["decisions_complete"] or 0),
                "halted":           bool(a["has_block"]),
                "halt_reason":      _edms_halt_reason(per_app),
                "outcome_counts":   dict(counts),
                "queued_count":     int(a["pending_human_review"] or 0),
            }
        )
    return rows


async def list_applications_async(platform: Platform) -> list[dict[str, Any]]:
    if DATABASE_URL:
        return await _list_applications_edms()
    return list_applications(platform)


# ─── 2) application_detail ───────────────────────────────────────────


async def _application_detail_edms(
    platform: Platform, application_id: str
) -> dict[str, Any]:
    spec = platform.spec
    pool = await _get_edms_pool()
    async with pool.acquire() as conn:
        decisions = await conn.fetch(
            """
            SELECT decision_id, wave, outcome, mode, confidence,
                   boundary_matched, decided_at, human_action,
                   human_reviewer, id
            FROM decision_outputs
            WHERE application_id = $1
              AND version = (
                  SELECT MAX(version) FROM decision_outputs d2
                  WHERE d2.application_id = decision_outputs.application_id
                    AND d2.decision_id = decision_outputs.decision_id
              )
            """,
            application_id,
        )
        entity = await conn.fetchrow(
            "SELECT * FROM entity_states WHERE application_id = $1 LIMIT 1",
            application_id,
        )

    by_decision: dict[str, dict[str, Any]] = {
        d["decision_id"]: dict(d) for d in decisions
    }
    waves: list[list[dict[str, Any]]] = []
    for wave_ids in spec.execution_waves:
        wave_cards: list[dict[str, Any]] = []
        for did in wave_ids:
            decision_spec = spec.decision_index.get(did, {})
            row = by_decision.get(did)
            wave_cards.append(_decision_card_from_edms(decision_spec, row))
        waves.append(wave_cards)

    pending_human = sum(
        1 for d in decisions
        if d["mode"] in ("human_approval", "recommend")
        and d["human_action"] is None
    )

    # Synthesize an "application" dict from entity_states — templates
    # read .get(...) so missing fields render as "—".
    application: dict[str, Any] = {}
    if entity is not None:
        e = dict(entity)
        loan_terms = _edms_maybe_json(e.get("loan_terms")) or {}
        loan_terms = loan_terms if isinstance(loan_terms, dict) else {}
        application = {
            "applicant_id":     _edms_maybe_json(e.get("borrower") or {}).get(
                "applicant_id"
            ) if isinstance(e.get("borrower"), (dict, str, bytes)) else None,
            "loan_purpose":     loan_terms.get("loan_purpose"),
            "requested_amount": loan_terms.get("loan_amount") or e.get("loan_amount"),
            "property_state":   loan_terms.get("property_state"),
            "submitted_at":     e.get("created_at"),
            "loan_type":        loan_terms.get("loan_type"),
        }

    return {
        "application_id": application_id,
        "application":    application,
        "waves":          waves,
        "wave_labels":    _wave_labels(spec.execution_waves),
        "queued_count":   pending_human,
    }


def _decision_card_from_edms(
    spec: dict[str, Any], row: Optional[dict[str, Any]]
) -> dict[str, Any]:
    if row is None:
        outcome = "pending"
        confidence = None
        matched_clause = None
        ran = False
        trace_id = None
        queued = False
    else:
        outcome = row["outcome"]
        confidence = row["confidence"]
        matched_clause = row.get("boundary_matched")
        ran = True
        trace_id = str(row["id"]) if row.get("id") else None
        queued = (
            row.get("mode") in ("human_approval", "recommend")
            and row.get("human_action") is None
        )
    return {
        "decision_id":    spec.get("id"),
        "name":           spec.get("name"),
        "persona":        spec.get("persona"),
        "mode":           spec.get("mode"),
        "mode_label":     MODE_LABELS.get(spec.get("mode", ""), spec.get("mode")),
        "risk_level":     spec.get("risk_level"),
        "owner_team":     spec.get("owner_team"),
        "depends_on":     [d["decision"] for d in spec.get("depends_on") or []],
        "outcome":        outcome,
        "outcome_style":  _edms_outcome_style(outcome),
        "confidence":     confidence,
        "matched_clause": matched_clause,
        "ran":            ran,
        "queued":         queued,
        "trace_id":       trace_id,
    }


async def application_detail_async(
    platform: Platform, application_id: str
) -> dict[str, Any]:
    if DATABASE_URL:
        return await _application_detail_edms(platform, application_id)
    return application_detail(platform, application_id)


# ─── 3) decision_detail ──────────────────────────────────────────────


async def _decision_detail_edms(
    platform: Platform, application_id: str, decision_id: str
) -> Optional[dict[str, Any]]:
    spec = platform.spec
    if decision_id not in spec.decision_index:
        return None
    decision_spec = spec.decision_index.get(decision_id, {})

    edms, _ = _get_edms_stores()
    pool = await _get_edms_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM decision_outputs
            WHERE application_id = $1 AND decision_id = $2
              AND version = (
                  SELECT MAX(version) FROM decision_outputs d2
                  WHERE d2.application_id = decision_outputs.application_id
                    AND d2.decision_id = decision_outputs.decision_id
              )
            LIMIT 1
            """,
            application_id,
            decision_id,
        )
        upstream_rows = await conn.fetch(
            """
            SELECT decision_id, outcome, confidence, decided_at
            FROM decision_outputs
            WHERE application_id = $1
              AND decision_id != $2
              AND version = (
                  SELECT MAX(version) FROM decision_outputs d2
                  WHERE d2.application_id = decision_outputs.application_id
                    AND d2.decision_id = decision_outputs.decision_id
              )
            """,
            application_id,
            decision_id,
        )

    # Persona view context — best effort; some decisions (lead_scoring)
    # don't have an EDMS view.
    try:
        snap = await edms.snapshot(
            application_id=application_id,
            decision_id=decision_id,
            upstream_decision_ids=None,
        )
        bundle_objects = snap.context if isinstance(snap.context, dict) else {}
    except Exception:  # noqa: BLE001 — degrade gracefully on missing view
        bundle_objects = {}

    # Synthesize a Trace-like dict the template can read. The actual
    # DecisionTrace object isn't available in EDMS mode (the cron runner
    # doesn't persist a Pydantic trace); the template guards with
    # {% if trace %} for the rich panels.
    trace_dict: Optional[dict[str, Any]] = None
    queued_item = None
    boundary = decision_spec.get("boundary") or {}
    output_payload: dict[str, Any] = {}

    if row is not None:
        d = dict(row)
        reasoning = _edms_maybe_json(d.get("reasoning")) or {}
        if not isinstance(reasoning, dict):
            reasoning = {}
        ctx_snap = _edms_maybe_json(d.get("context_snapshot")) or {}
        if isinstance(ctx_snap, dict):
            output_payload = ctx_snap
        trace_dict = {
            "trace_id":       str(d["id"]),
            "agent_id":       decision_spec.get("persona") or decision_id,
            "decision_id":    decision_id,
            "application_id": application_id,
            "outcome":        d["outcome"],
            "mode":           d["mode"],
            "risk_level":     d.get("risk_level"),
            "confidence":     d.get("confidence"),
            "matched_clause": d.get("boundary_matched"),
            "policy_reasons": [d["boundary_rule"]] if d.get("boundary_rule") else [],
            "output_payload": output_payload,
            "work_journal": {
                "hypothesis_tested": reasoning.get("hypothesis"),
                "conclusion":        reasoning.get("conclusion"),
                "confidence_basis":  reasoning.get("confidence_basis"),
                "human_readable_summary": reasoning.get("summary"),
                "signals_evaluated": [
                    {
                        "name":       s.get("name"),
                        "direction":  "neutral",
                        "summary":    str(s.get("value")) if s.get("value") is not None else "",
                        "value":      s.get("value"),
                    }
                    for s in (reasoning.get("signals") or [])
                    if isinstance(s, dict)
                ],
                "contradictions_found": [],
            },
            "started_at": d.get("decided_at"),
            "ended_at":   d.get("decided_at"),
            "human_review": (
                {
                    "reviewer_id":   d.get("human_reviewer"),
                    "reviewer_role": "reviewer",
                    "original_ai_decision": d["outcome"],
                    "final_outcome": d["outcome"],
                    "overridden":    d.get("human_action") == "overridden",
                    "override_reason": d.get("human_override_reason"),
                    "reviewed_at":   d.get("acted_at"),
                }
                if d.get("human_action") else None
            ),
        }
        if d.get("mode") in ("human_approval", "recommend") and d.get("human_action") is None:
            queued_item = {
                "id":               d["id"],
                "application_id":   application_id,
                "decision_id":      decision_id,
                "agent_id":         decision_spec.get("persona") or decision_id,
                "proposed_outcome": d["outcome"],
                "confidence":       d.get("confidence"),
                "reasons":          [d["boundary_rule"]] if d.get("boundary_rule") else [],
                "enqueued_at":      d.get("decided_at"),
            }

    upstream_outputs: dict[str, dict[str, Any]] = {}
    for u in upstream_rows:
        upstream_outputs[u["decision_id"]] = _edms_jsonify({
            "outcome":    u["outcome"],
            "confidence": u["confidence"],
            "decided_at": u["decided_at"],
        })

    # Re-derive a basic boundary_eval against the EDMS output_payload
    # so the boundary section in decision.html stays populated. Falls
    # back to {} when the eval helper isn't available or raises.
    try:
        boundary_eval = _evaluate_boundary(boundary, output_payload, bundle_objects)
    except Exception:  # noqa: BLE001 — degrade gracefully
        boundary_eval = {}

    # Stubbed panels — the in-memory path has rich data here from the
    # trace_writer / knowledge_store / audit_store. EDMS has none of
    # that today; templates guard each panel with {% if %}, and the
    # dict-shaped ones default to {} so .get() calls in Jinja are safe.
    return {
        "application_id":   application_id,
        "decision_id":      decision_id,
        "spec":             decision_spec,
        "trace":            None,
        "trace_dict":       trace_dict,
        "queued_item":      queued_item,
        "boundary":         boundary,
        "boundary_eval":    boundary_eval or {},
        "bundle_objects":   bundle_objects,
        "upstream_outputs": upstream_outputs,
        "upstream_status":  [],
        "read_permissions": [],
        "routing_target":   None,
        "atomic_steps":     [],
        "persona_panel":    PERSONA_PANELS.get(decision_id),
        "persona_view":     None,
        "policy_panel":     None,
        "evidence_panel":   None,
        "audit_panel":      None,
        "contamination_guard": decision_spec.get("contamination_guard") or {},
        "learnings":        [],
        "outcome_style":    _edms_outcome_style(
            trace_dict["outcome"] if trace_dict else "pending"
        ),
        "outcome_palette":  OUTCOME_STYLES,
        "decision_modes":   [m.value for m in DecisionMode],
        "decision_outcomes": [o.value for o in DecisionOutcome],
        # EDMS-mode marker so the override POST handler knows to route
        # the write back to PG instead of the in-memory trace_writer.
        "_edms_source":     True,
    }


async def decision_detail_async(
    platform: Platform, application_id: str, decision_id: str
) -> Optional[dict[str, Any]]:
    if DATABASE_URL:
        return await _decision_detail_edms(platform, application_id, decision_id)
    return decision_detail(platform, application_id, decision_id)


# ─── 4) queue_view ───────────────────────────────────────────────────


async def _queue_view_edms() -> dict[str, Any]:
    pool = await _get_edms_pool()
    async with pool.acquire() as conn:
        open_rows_raw = await conn.fetch(
            """
            SELECT id, application_id, decision_id, mode, outcome,
                   confidence, boundary_rule, decided_at
            FROM decision_outputs
            WHERE mode IN ('human_approval', 'recommend')
              AND human_action IS NULL
              AND version = (
                  SELECT MAX(version) FROM decision_outputs d2
                  WHERE d2.application_id = decision_outputs.application_id
                    AND d2.decision_id = decision_outputs.decision_id
              )
            ORDER BY decided_at ASC
            LIMIT 200
            """
        )
        resolved_rows_raw = await conn.fetch(
            """
            SELECT id, application_id, decision_id, human_action,
                   human_reviewer, human_override_reason, acted_at
            FROM decision_outputs
            WHERE human_action IS NOT NULL
              AND version = (
                  SELECT MAX(version) FROM decision_outputs d2
                  WHERE d2.application_id = decision_outputs.application_id
                    AND d2.decision_id = decision_outputs.decision_id
              )
            ORDER BY acted_at DESC NULLS LAST
            LIMIT 100
            """
        )

    items: list[dict[str, Any]] = []
    for r in open_rows_raw:
        items.append(
            {
                "queue_id":         str(r["id"]),
                "application_id":   r["application_id"],
                "decision_id":      r["decision_id"],
                "agent_id":         r["decision_id"],
                "proposed_outcome": r["outcome"],
                "outcome_style":    _edms_outcome_style(r["outcome"]),
                "confidence":       r["confidence"],
                "reasons":          [r["boundary_rule"]] if r["boundary_rule"] else [],
                "enqueued_at":      r["decided_at"],
                "trace_id":         str(r["id"]),
            }
        )

    resolved: list[dict[str, Any]] = []
    for r in resolved_rows_raw:
        action = r["human_action"]
        resolution_tone = (
            "emerald" if action == "approved"
            else "rose" if action == "overridden"
            else "slate"
        )
        resolved.append(
            {
                "item_id":         str(r["id"]),
                "application_id":  r["application_id"],
                "decision_id":     r["decision_id"],
                "decision_label":  PERSONA_LABELS.get(r["decision_id"], r["decision_id"]),
                "resolution":      "approve" if action == "approved" else "decline",
                "resolution_tone": resolution_tone,
                "reviewer_id":     r["human_reviewer"],
                "reviewer_role":   "reviewer",
                "resolved_at":     r["acted_at"],
                "notes":           r["human_override_reason"],
            }
        )

    return {
        "items":          items,
        "resolved":       resolved,
        "open_count":     len(items),
        "resolved_count": len(resolved),
    }


async def queue_view_async(platform: Platform) -> dict[str, Any]:
    if DATABASE_URL:
        return await _queue_view_edms()
    return queue_view(platform)


# ─── 5) list_persona_workbenches ─────────────────────────────────────


async def _list_persona_workbenches_edms(
    platform: Platform,
) -> list[dict[str, Any]]:
    spec = platform.spec
    pool = await _get_edms_pool()
    async with pool.acquire() as conn:
        agg = await conn.fetch(
            """
            SELECT decision_id,
                   COUNT(*) AS total,
                   COUNT(*) FILTER (
                       WHERE mode IN ('human_approval', 'recommend')
                         AND human_action IS NULL
                   ) AS pending,
                   COUNT(*) FILTER (
                       WHERE mode = 'auto_execute' AND outcome = 'allow'
                         AND human_action IS NULL
                   ) AS auto_decided,
                   AVG(
                       CASE WHEN acted_at IS NOT NULL AND decided_at IS NOT NULL
                            THEN EXTRACT(EPOCH FROM (acted_at - decided_at)) * 1000.0
                       END
                   ) AS avg_review_ms,
                   COUNT(*) FILTER (
                       WHERE acted_at IS NOT NULL
                   ) AS human_reviewed
            FROM decision_outputs
            WHERE version = (
                SELECT MAX(version) FROM decision_outputs d2
                WHERE d2.application_id = decision_outputs.application_id
                  AND d2.decision_id = decision_outputs.decision_id
            )
            GROUP BY decision_id
            """
        )
    by_did = {r["decision_id"]: dict(r) for r in agg}

    rows: list[dict[str, Any]] = []
    for d in spec.decisions:
        decision_id = d["id"]
        m = by_did.get(decision_id, {})
        total = int(m.get("total") or 0)
        auto = int(m.get("auto_decided") or 0)
        rows.append(
            {
                "decision_id":      decision_id,
                "persona":          d.get("persona"),
                "label":            PERSONA_LABELS.get(decision_id, decision_id),
                "owner_team":       d.get("owner_team"),
                "owner_team_label": OWNER_TEAM_LABELS.get(
                    d.get("owner_team", ""), d.get("owner_team", "")
                ),
                "mode":             d.get("mode"),
                "risk_level":       d.get("risk_level"),
                "is_auto":          d.get("mode") == "auto_execute",
                "decisions_completed":  total,
                "pending_review":       int(m.get("pending") or 0),
                "auto_decided_pct":     (auto / total) if total else None,
                "avg_review_ms":        (
                    float(m["avg_review_ms"])
                    if m.get("avg_review_ms") is not None else None
                ),
                "human_reviewed_count": int(m.get("human_reviewed") or 0),
            }
        )
    return rows


async def list_persona_workbenches_async(
    platform: Platform,
) -> list[dict[str, Any]]:
    if DATABASE_URL:
        return await _list_persona_workbenches_edms(platform)
    return list_persona_workbenches(platform)


# ─── 6) persona_workbench_view ───────────────────────────────────────


async def _persona_kpis_edms(decision_id: str) -> dict[str, Any]:
    pool = await _get_edms_pool()
    async with pool.acquire() as conn:
        agg = await conn.fetchrow(
            """
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (
                       WHERE mode IN ('human_approval', 'recommend')
                         AND human_action IS NULL
                   ) AS pending,
                   COUNT(*) FILTER (
                       WHERE mode = 'auto_execute' AND outcome = 'allow'
                         AND human_action IS NULL
                   ) AS auto_decided,
                   AVG(
                       CASE WHEN acted_at IS NOT NULL AND decided_at IS NOT NULL
                            THEN EXTRACT(EPOCH FROM (acted_at - decided_at)) * 1000.0
                       END
                   ) AS avg_review_ms,
                   COUNT(*) FILTER (
                       WHERE acted_at IS NOT NULL
                   ) AS human_reviewed
            FROM decision_outputs
            WHERE decision_id = $1
              AND version = (
                  SELECT MAX(version) FROM decision_outputs d2
                  WHERE d2.application_id = decision_outputs.application_id
                    AND d2.decision_id = decision_outputs.decision_id
              )
            """,
            decision_id,
        )
    total = int(agg["total"] or 0) if agg else 0
    auto = int(agg["auto_decided"] or 0) if agg else 0
    return {
        "decisions_completed":  total,
        "pending_review":       int(agg["pending"] or 0) if agg else 0,
        "auto_decided_pct":     (auto / total) if total else None,
        "avg_review_ms":        (
            float(agg["avg_review_ms"]) if agg and agg["avg_review_ms"] is not None
            else None
        ),
        "human_reviewed_count": int(agg["human_reviewed"] or 0) if agg else 0,
    }


def _edms_minutes_ago(when: Any) -> Optional[int]:
    if when is None or not isinstance(when, datetime):
        return None
    now = datetime.now(when.tzinfo) if when.tzinfo else datetime.utcnow()
    return max(0, int((now - when).total_seconds() // 60))


async def _persona_queue_rows_edms(
    decision_id: str, selected_app: Optional[str]
) -> list[dict[str, Any]]:
    pool = await _get_edms_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT dout.application_id, dout.outcome, dout.confidence,
                   dout.decided_at, dout.mode,
                   es.mid_credit_score, es.ltv, es.dti_back,
                   es.loan_amount, es.status,
                   es.borrower, es.loan_terms
            FROM decision_outputs dout
            LEFT JOIN entity_states es
                   ON es.application_id = dout.application_id
                  AND es.tenant_id = dout.tenant_id
            WHERE dout.decision_id = $1
              AND dout.mode IN ('human_approval', 'recommend')
              AND dout.human_action IS NULL
              AND dout.version = (
                  SELECT MAX(version) FROM decision_outputs d2
                  WHERE d2.application_id = dout.application_id
                    AND d2.decision_id = dout.decision_id
              )
            ORDER BY dout.decided_at ASC
            LIMIT 100
            """,
            decision_id,
        )

    out: list[dict[str, Any]] = []
    for r in rows:
        app_id = r["application_id"]
        borrower = _edms_maybe_json(r["borrower"]) or {}
        if not isinstance(borrower, dict):
            borrower = {}
        loan_terms = _edms_maybe_json(r["loan_terms"]) or {}
        if not isinstance(loan_terms, dict):
            loan_terms = {}
        app_value = {
            "applicant_id":     borrower.get("applicant_id"),
            "loan_purpose":     loan_terms.get("loan_purpose"),
            "requested_amount": loan_terms.get("loan_amount") or r["loan_amount"],
            "property_state":   loan_terms.get("property_state"),
        }
        loan_value = {
            "loan_type":      loan_terms.get("loan_type"),
            "interest_rate":  loan_terms.get("interest_rate"),
            "term_months":    loan_terms.get("term_months"),
        }
        out.append(
            {
                "application_id":   app_id,
                "is_selected":      app_id == selected_app,
                "is_queued":        True,
                "applicant_id":     app_value["applicant_id"],
                "display_name":     _display_name(app_value, app_id),
                "initials":         _initials(app_value, app_id),
                "avatar_tone":      _avatar_tone(app_id),
                "loan_summary":     _loan_summary(app_value, loan_value),
                "amount":           app_value["requested_amount"],
                "ago_minutes":      _edms_minutes_ago(r["decided_at"]),
                "risk_pill":        _risk_pill_for_confidence(r["confidence"]),
                "proposed_outcome": r["outcome"],
                "outcome":          r["outcome"],
                "outcome_style":    _edms_outcome_style(r["outcome"]),
                "confidence":       r["confidence"],
                "kind":             "queued",
            }
        )
    return out


async def _persona_recent_traces_edms(
    decision_id: str, selected_app: Optional[str], limit: int
) -> list[dict[str, Any]]:
    pool = await _get_edms_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT dout.application_id, dout.outcome, dout.confidence,
                   dout.decided_at, dout.mode, dout.human_action,
                   es.borrower, es.loan_terms, es.loan_amount
            FROM decision_outputs dout
            LEFT JOIN entity_states es
                   ON es.application_id = dout.application_id
                  AND es.tenant_id = dout.tenant_id
            WHERE dout.decision_id = $1
              AND dout.version = (
                  SELECT MAX(version) FROM decision_outputs d2
                  WHERE d2.application_id = dout.application_id
                    AND d2.decision_id = dout.decision_id
              )
            ORDER BY dout.decided_at DESC
            LIMIT $2
            """,
            decision_id,
            limit,
        )

    out: list[dict[str, Any]] = []
    for r in rows:
        app_id = r["application_id"]
        borrower = _edms_maybe_json(r["borrower"]) or {}
        if not isinstance(borrower, dict):
            borrower = {}
        loan_terms = _edms_maybe_json(r["loan_terms"]) or {}
        if not isinstance(loan_terms, dict):
            loan_terms = {}
        app_value = {
            "applicant_id":     borrower.get("applicant_id"),
            "loan_purpose":     loan_terms.get("loan_purpose"),
            "requested_amount": loan_terms.get("loan_amount") or r["loan_amount"],
            "property_state":   loan_terms.get("property_state"),
        }
        loan_value = {
            "loan_type":      loan_terms.get("loan_type"),
            "interest_rate":  loan_terms.get("interest_rate"),
            "term_months":    loan_terms.get("term_months"),
        }
        is_queued = (
            r["mode"] in ("human_approval", "recommend")
            and r["human_action"] is None
        )
        out.append(
            {
                "application_id":   app_id,
                "is_selected":      app_id == selected_app,
                "is_queued":        is_queued,
                "applicant_id":     app_value["applicant_id"],
                "display_name":     _display_name(app_value, app_id),
                "initials":         _initials(app_value, app_id),
                "avatar_tone":      _avatar_tone(app_id),
                "loan_summary":     _loan_summary(app_value, loan_value),
                "amount":           app_value["requested_amount"],
                "ago_minutes":      _edms_minutes_ago(r["decided_at"]),
                "risk_pill":        _risk_pill_for_confidence(r["confidence"]),
                "proposed_outcome": r["outcome"],
                "outcome":          r["outcome"],
                "outcome_style":    _edms_outcome_style(r["outcome"]),
                "confidence":       r["confidence"],
                "kind":             "completed",
            }
        )
    out.sort(key=lambda r: (0 if r["is_queued"] else 1))
    return out


async def _persona_focused_app_edms(
    platform: Platform, decision_id: str, application_id: str
) -> dict[str, Any]:
    """Build the focused-app panel from EDMS. Stubs the policy /
    evidence / audit panels (None) — templates guard with {% if %}."""
    spec = platform.spec
    decision_spec = spec.decision_index.get(decision_id, {})
    pool = await _get_edms_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM decision_outputs
            WHERE application_id = $1 AND decision_id = $2
              AND version = (
                  SELECT MAX(version) FROM decision_outputs d2
                  WHERE d2.application_id = decision_outputs.application_id
                    AND d2.decision_id = decision_outputs.decision_id
              )
            LIMIT 1
            """,
            application_id,
            decision_id,
        )
        entity = await conn.fetchrow(
            "SELECT * FROM entity_states WHERE application_id = $1 LIMIT 1",
            application_id,
        )

    borrower = _edms_maybe_json(entity["borrower"] if entity else None) or {}
    if not isinstance(borrower, dict):
        borrower = {}
    loan_terms = _edms_maybe_json(entity["loan_terms"] if entity else None) or {}
    if not isinstance(loan_terms, dict):
        loan_terms = {}
    app_value = {
        "applicant_id":     borrower.get("applicant_id"),
        "loan_purpose":     loan_terms.get("loan_purpose"),
        "requested_amount": loan_terms.get("loan_amount") or (entity and entity["loan_amount"]),
        "property_state":   loan_terms.get("property_state"),
    }
    loan_value = {
        "loan_type":      loan_terms.get("loan_type"),
        "interest_rate":  loan_terms.get("interest_rate"),
        "term_months":    loan_terms.get("term_months"),
    }

    has_human_review = row is not None and row["human_action"] is not None
    can_act = (
        row is not None
        and row["mode"] in ("human_approval", "recommend")
        and row["human_action"] is None
    )

    outcome = row["outcome"] if row else None
    confidence = row["confidence"] if row else None

    # Skinny trace surrogate for the template.
    trace_surrogate = None
    if row is not None:
        reasoning = _edms_maybe_json(row["reasoning"]) or {}
        if not isinstance(reasoning, dict):
            reasoning = {}
        trace_surrogate = {
            "trace_id":    str(row["id"]),
            "agent_id":    decision_spec.get("persona") or decision_id,
            "decision_id": decision_id,
            "outcome":     outcome,
            "confidence":  confidence,
            "started_at":  row["decided_at"],
            "human_review": None if not has_human_review else {
                "reviewer_id":   row["human_reviewer"],
                "reviewer_role": "reviewer",
                "overridden":    row["human_action"] == "overridden",
                "override_reason": row["human_override_reason"],
                "final_outcome": outcome,
                "original_ai_decision": outcome,
                "reviewed_at":  row["acted_at"],
            },
            "output_payload": (
                _edms_maybe_json(row["context_snapshot"]) or {}
                if row["context_snapshot"] else {}
            ),
            "work_journal": {
                "hypothesis_tested": reasoning.get("hypothesis"),
                "conclusion":        reasoning.get("conclusion"),
                "confidence_basis":  reasoning.get("confidence_basis"),
                "human_readable_summary": reasoning.get("summary"),
                "signals_evaluated": [
                    {
                        "name":      s.get("name"),
                        "direction": "neutral",
                        "summary":   str(s.get("value")) if s.get("value") is not None else "",
                        "value":     s.get("value"),
                    }
                    for s in (reasoning.get("signals") or [])
                    if isinstance(s, dict)
                ],
                "contradictions_found": [],
            },
        }

    application_context = _persona_application_context(
        decision_id, app_value, loan_value, []
    )

    return {
        "application_id":      application_id,
        "applicant_id":        app_value["applicant_id"],
        "display_name":        _display_name(app_value, application_id),
        "initials":            _initials(app_value, application_id),
        "avatar_tone":         _avatar_tone(application_id),
        "loan_summary":        _loan_summary(app_value, loan_value),
        "amount":              app_value["requested_amount"],
        "risk_pill":           _risk_pill_for_confidence(confidence),
        "trace":               trace_surrogate,
        "trace_id":            str(row["id"]) if row else None,
        "queue_item_id":       str(row["id"]) if can_act else None,
        "outcome":             outcome,
        "outcome_style":       _edms_outcome_style(outcome),
        "confidence":          confidence,
        "matched_clause":      row["boundary_matched"] if row else None,
        "application_context": application_context,
        "signals_evaluated":   (
            trace_surrogate["work_journal"]["signals_evaluated"]
            if trace_surrogate else []
        ),
        "ai_reasoning":        (
            {
                "hypothesis": trace_surrogate["work_journal"]["hypothesis_tested"],
                "conclusion": trace_surrogate["work_journal"]["conclusion"],
                "confidence_basis": trace_surrogate["work_journal"]["confidence_basis"],
                "summary":    trace_surrogate["work_journal"]["human_readable_summary"],
            }
            if trace_surrogate else None
        ),
        "policy_panel":     None,
        "audit_panel":      None,
        "evidence_panel":   None,
        "has_human_review": has_human_review,
        "human_review":     (
            trace_surrogate["human_review"] if trace_surrogate and has_human_review
            else None
        ),
        "can_act":          can_act,
        "can_send_back":    can_act and decision_spec.get("type") == "dependent",
        "decision_outcomes": [o.value for o in DecisionOutcome],
    }


async def _persona_workbench_view_edms(
    platform: Platform,
    decision_id: str,
    *,
    application_id: Optional[str],
    time_range: str,
    tab: str,
) -> Optional[dict[str, Any]]:
    spec = platform.spec
    decision_spec = spec.decision_index.get(decision_id)
    if decision_spec is None:
        return None
    if time_range not in TIME_RANGES:
        time_range = "quarter"
    if tab not in ("workbench", "history", "analytics"):
        tab = "workbench"

    persona_label = PERSONA_LABELS.get(decision_id, decision_id)
    owner_team = decision_spec.get("owner_team", "")
    is_auto = decision_spec.get("mode") == "auto_execute"

    siblings: list[dict[str, Any]] = []
    for d in spec.decisions:
        if d.get("owner_team") != owner_team:
            continue
        sib_id = d["id"]
        siblings.append(
            {
                "decision_id": sib_id,
                "label":       PERSONA_LABELS.get(sib_id, sib_id),
                "active":      sib_id == decision_id,
            }
        )

    kpis = await _persona_kpis_edms(decision_id)

    if is_auto:
        left_label = "Recently completed"
        left_rows = await _persona_recent_traces_edms(
            decision_id, application_id, 10
        )
    else:
        left_label = f"{persona_label.lower().replace(' ', '_')} queue"
        left_rows = await _persona_queue_rows_edms(
            decision_id, application_id
        )

    focused = None
    if application_id is not None:
        focused = await _persona_focused_app_edms(
            platform, decision_id, application_id
        )

    return {
        "decision_id":     decision_id,
        "persona":         decision_spec.get("persona"),
        "persona_label":   persona_label,
        "decision_name":   decision_spec.get("name"),
        "owner_team":      owner_team,
        "owner_team_label": OWNER_TEAM_LABELS.get(owner_team, owner_team),
        "mode":            decision_spec.get("mode"),
        "risk_level":      decision_spec.get("risk_level"),
        "is_auto":         is_auto,
        "siblings":        siblings,
        "selected_application_id": application_id,
        "time_range":      time_range,
        "time_range_label": TIME_RANGES[time_range]["label"],
        "time_ranges":     [
            {"key": k, "label": v["label"], "selected": k == time_range}
            for k, v in TIME_RANGES.items()
        ],
        "tab":             tab,
        "kpis":            kpis,
        "left_label":      left_label,
        "left_rows":       left_rows,
        "focused":         focused,
    }


async def persona_workbench_view_async(
    platform: Platform,
    decision_id: str,
    *,
    application_id: Optional[str] = None,
    time_range: str = "quarter",
    tab: str = "workbench",
) -> Optional[dict[str, Any]]:
    if DATABASE_URL:
        return await _persona_workbench_view_edms(
            platform, decision_id,
            application_id=application_id,
            time_range=time_range,
            tab=tab,
        )
    return persona_workbench_view(
        platform, decision_id,
        application_id=application_id,
        time_range=time_range,
        tab=tab,
    )


# ─── Override write — EDMS branch used by ui/routes.py ───────────────


async def record_override_edms(
    *,
    application_id: str,
    decision_id: str,
    new_outcome: str,
    reviewer: str,
    reason: Optional[str],
    overridden: bool,
) -> Optional[str]:
    """Write human action + (optional) outcome flip + timeline row.

    Returns the application_id of the next pending review for this
    decision, or None when the queue is empty / row not found."""

    pool = await _get_edms_pool()
    now = datetime.now()
    action = "overridden" if overridden else "approved"
    async with pool.acquire() as conn:
        async with conn.transaction():
            current = await conn.fetchrow(
                """
                SELECT id, outcome, wave, tenant_id FROM decision_outputs
                WHERE application_id = $1 AND decision_id = $2
                  AND version = (
                      SELECT MAX(version) FROM decision_outputs d2
                      WHERE d2.application_id = decision_outputs.application_id
                        AND d2.decision_id = decision_outputs.decision_id
                  )
                LIMIT 1
                """,
                application_id, decision_id,
            )
            if current is None:
                return None
            final_outcome = new_outcome if overridden else current["outcome"]
            await conn.execute(
                """
                UPDATE decision_outputs
                   SET human_action = $1,
                       human_reviewer = $2,
                       human_override_reason = $3,
                       outcome = $4,
                       acted_at = $5
                 WHERE id = $6
                """,
                action, reviewer, reason, final_outcome, now, current["id"],
            )
            await conn.execute(
                """
                INSERT INTO decision_timeline (
                    application_id, decision_id, wave, from_state,
                    to_state, trigger, transition_at, tenant_id
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                application_id, decision_id, current["wave"],
                current["outcome"], final_outcome,
                "human_override" if overridden else "human_approve",
                now, current["tenant_id"],
            )
            next_app = await conn.fetchval(
                """
                SELECT application_id FROM decision_outputs
                WHERE decision_id = $1
                  AND application_id != $2
                  AND mode IN ('human_approval', 'recommend')
                  AND human_action IS NULL
                  AND version = (
                      SELECT MAX(version) FROM decision_outputs d2
                      WHERE d2.application_id = decision_outputs.application_id
                        AND d2.decision_id = decision_outputs.decision_id
                  )
                ORDER BY decided_at ASC
                LIMIT 1
                """,
                decision_id, application_id,
            )
    return next_app


__all__ = [
    "AGENCY_LABELS",
    "AUDIT_STATUS_TONES",
    "DATABASE_URL",
    "DOC_STATUS_TONES",
    "application_detail",
    "application_detail_async",
    "audit_record_detail",
    "decision_detail",
    "decision_detail_async",
    "document_detail_view",
    "list_applications",
    "list_applications_async",
    "list_audit_flags",
    "list_audit_for_application",
    "list_documents_for_application",
    "list_pending_claims",
    "list_persona_workbenches",
    "list_persona_workbenches_async",
    "list_policies",
    "list_workbenches",
    "persona_workbench_view",
    "persona_workbench_view_async",
    "policy_version_detail",
    "queue_view",
    "queue_view_async",
    "record_override_edms",
    "templates",
    "workbench_view",
    "OUTCOME_STYLES",
    "PERSONA_LABELS",
    "TIME_RANGES",
]
