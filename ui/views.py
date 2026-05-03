from __future__ import annotations

from collections import defaultdict
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


def queue_view(platform: Platform) -> list[dict[str, Any]]:
    items = list(getattr(platform.human_queue, "_items", {}).values())
    items.sort(key=lambda i: i.enqueued_at, reverse=True)

    rows: list[dict[str, Any]] = []
    for item in items:
        # Find the trace so the queue can link straight into decision detail.
        traces = _all_traces_sync(platform, item.application_id)
        trace = next(
            (t for t in traces if t.decision_id == item.decision_id), None
        )
        rows.append({
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
    return rows


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


__all__ = [
    "application_detail",
    "decision_detail",
    "list_applications",
    "list_workbenches",
    "queue_view",
    "templates",
    "workbench_view",
    "OUTCOME_STYLES",
]
