from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

from fastapi.templating import Jinja2Templates

from api.deps import Platform
from core.normalizer.models import DecisionMode, DecisionOutcome
from core.trace import DecisionTrace


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

    return {
        "application_id": app_id,
        "decision_id":    decision_id,
        "spec":           decision_spec,
        "trace":          trace,
        "trace_dict":     trace.model_dump(mode="json") if trace else None,
        "queued_item":    queued_item,
        "boundary":       decision_spec.get("boundary") or {},
        "bundle_objects": bundle_objects,
        "upstream_outputs": upstream_outputs,
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


__all__ = [
    "application_detail",
    "decision_detail",
    "list_applications",
    "queue_view",
    "templates",
    "OUTCOME_STYLES",
]
