"""
Exam-ready PDF export — CN-EX.

POST /api/accord/loans/{application_id}/export/exam-ready
Returns a 5-page reportlab PDF (Loan Summary, Decision Table, Conditions
Lifecycle, Override Chain + Escalation, Regulatory Compliance Flags) with a
confidential footer on every page. Reuses loan_detail() for the bulk of the
data (and its tenant isolation) plus a few focused queries for the override
chain, conditions lifecycle, compliance signals, and decision date.
"""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, PageBreak,
)

from api.accord.auth import get_current_user
from api.accord.pipeline import _get_pool, _require_db, loan_detail, _J

router = APIRouter(prefix="/api/accord", tags=["accord-exam"])

# outcome -> (text colour, cell background)
_OUTCOME = {
    "block":     (colors.HexColor("#b91c1c"), colors.HexColor("#fee2e2")),
    "allow":     (colors.HexColor("#166534"), colors.HexColor("#dcfce7")),
    "escalate":  (colors.HexColor("#92400e"), colors.HexColor("#fef3c7")),
    "recommend": (colors.HexColor("#1e40af"), colors.HexColor("#dbeafe")),
}
_AGENCY = {"fannie": "Fannie Mae", "fha": "FHA / HUD", "va": "VA",
           "cfpb": "CFPB", "ffiec": "FFIEC", "state": "State Regulatory"}
_GREEN = colors.HexColor("#166534")
_RED = colors.HexColor("#b91c1c")
_AMBER = colors.HexColor("#92400e")
_INK = colors.HexColor("#0f4d37")


def _money(v: Any) -> str:
    try:
        return f"${float(v):,.0f}"
    except (TypeError, ValueError):
        return "—"


def _date(dt: Any) -> str:
    if dt is None:
        return "—"
    try:
        return dt.strftime("%Y-%m-%d")
    except AttributeError:
        return str(dt)[:10] or "—"


def _short(s: Any, n: int = 60) -> str:
    s = str(s or "")
    return s if len(s) <= n else s[: n - 1] + "…"


def _citation(d: dict) -> str:
    for g in (d.get("governed_by") or []):
        if g.get("citation"):
            ag = _AGENCY.get((g.get("agency") or "").lower(), g.get("agency") or "")
            return f"{ag + ' ' if ag else ''}{g['citation']}"
    return "—"


def _footer(canvas, doc, app_id: str, tenant_id: str, who: str, when: str) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.grey)
    w = letter[0]
    canvas.drawCentredString(w / 2, 26, f"Accord Decision OS  |  Confidential  |  Exported by {who} on {when}")
    canvas.drawCentredString(w / 2, 15, f"Loan ID: {app_id}   |   Tenant: {tenant_id}")
    canvas.restoreState()


def _base_style(extra: Optional[list] = None) -> TableStyle:
    s = [
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("BACKGROUND", (0, 0), (-1, 0), _INK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
    ]
    return TableStyle(s + (extra or []))


def _build_pdf(data: dict, overrides: list, comp: Any, es: Any, conds: list,
               uw_date: Any, user: dict, app_id: str, tenant_id: str) -> bytes:
    ss = getSampleStyleSheet()
    H1 = ParagraphStyle("H1", parent=ss["Title"], fontSize=18, spaceAfter=2, textColor=_INK)
    H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontSize=13, spaceBefore=10, spaceAfter=6, textColor=_INK)
    SUB = ParagraphStyle("SUB", parent=ss["Normal"], fontSize=9, textColor=colors.grey, spaceAfter=10)
    NORM = ParagraphStyle("NORM", parent=ss["Normal"], fontSize=9, spaceAfter=4)
    CELL = ParagraphStyle("CELL", parent=ss["Normal"], fontSize=8, leading=10)
    SMALL = ParagraphStyle("SMALL", parent=ss["Normal"], fontSize=7, leading=9)
    KEY = ParagraphStyle("KEY", parent=ss["Normal"], fontSize=9, textColor=colors.HexColor("#374151"), fontName="Helvetica-Bold")
    VAL = ParagraphStyle("VAL", parent=ss["Normal"], fontSize=9)

    story: list = []
    borrower = data.get("borrower") or {}
    metrics = data.get("metrics") or {}
    aus = data.get("aus_result") or {}
    loan_terms = _J(es["loan_terms"]) if (es and es["loan_terms"]) else {}
    prop = _J(es["property"]) if (es and es["property"]) else {}
    address = prop.get("address") or ", ".join(
        [str(x) for x in (prop.get("street"), prop.get("city"), prop.get("state"), prop.get("zip")) if x]) or "—"
    senior_uw = (overrides[0]["human_reviewer"] if overrides else data.get("escalated_by_name")) or "—"

    # ── PAGE 1 — Loan Summary ────────────────────────────────────────────
    story.append(Paragraph("Exam-Ready Loan File", H1))
    story.append(Paragraph(f"Application {app_id}", SUB))
    story.append(Paragraph("Loan Summary", H2))
    summary = [
        ("Borrower", borrower.get("name") or "—"),
        ("Loan Amount", _money(metrics.get("loan_amount"))),
        ("Property Address", address),
        ("Loan Type", loan_terms.get("loan_type") or "—"),
        ("Loan Program", data.get("loan_program") or "—"),
        ("AUS Result", aus.get("display") or "—"),
        ("UW Status", str(data.get("status") or "—").replace("_", " ").title()),
        ("Decision Date", _date(uw_date)),
        ("Assigned Underwriter", data.get("assigned_to_name") or "—"),
        ("Senior UW", senior_uw),
    ]
    t1 = Table([[Paragraph(k, KEY), Paragraph(str(v), VAL)] for k, v in summary], colWidths=[150, 340])
    t1.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e5e7eb")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f3f4f6")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t1)

    # ── PAGE 2 — Decision Table ──────────────────────────────────────────
    story.append(PageBreak())
    decisions = sorted(data.get("decisions") or [],
                       key=lambda x: (x.get("wave") if x.get("wave") is not None else 9, x.get("decision_id") or ""))
    story.append(Paragraph(f"Decision Table ({len(decisions)} decisions)", H2))
    rows = [["Decision", "Wave", "Outcome", "Governing Rule", "Citation"]]
    extra = []
    for i, d in enumerate(decisions, start=1):
        oc = (d.get("outcome") or "").lower()
        rows.append([
            Paragraph(d.get("persona_name") or d.get("decision_id") or "—", CELL),
            str(d.get("wave") if d.get("wave") is not None else "—"),
            Paragraph((oc or "—").upper(), SMALL),
            Paragraph(_short(d.get("rule") or "—", 60), SMALL),
            Paragraph(_short(_citation(d), 46), SMALL),
        ])
        if oc in _OUTCOME:
            fg, bg = _OUTCOME[oc]
            extra += [("BACKGROUND", (2, i), (2, i), bg), ("TEXTCOLOR", (2, i), (2, i), fg),
                      ("FONTNAME", (2, i), (2, i), "Helvetica-Bold")]
    t2 = Table(rows, colWidths=[108, 32, 68, 160, 122], repeatRows=1)
    t2.setStyle(_base_style(extra))
    story.append(t2)

    # ── PAGE 3 — Conditions Lifecycle ────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph(f"Conditions Lifecycle ({len(conds)} conditions)", H2))
    if conds:
        rows = [["Code", "Description", "Status", "Opened", "Cleared", "Cleared By"]]
        extra = []
        for i, c in enumerate(conds, start=1):
            rows.append([
                Paragraph(c["condition_code"], SMALL),
                Paragraph(_short(c["condition_text"], 46), SMALL),
                Paragraph(str(c["status"]), SMALL),
                _date(c["opened_at"]), _date(c["cleared_at"]), "—",
            ])
            if c["blocks_closing"] and c["status"] not in ("approved", "waived"):
                extra.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#fef2f2")))
                extra.append(("TEXTCOLOR", (0, i), (0, i), _RED))
        t3 = Table(rows, colWidths=[120, 158, 58, 56, 56, 42], repeatRows=1)
        t3.setStyle(_base_style(extra))
        story.append(t3)
        story.append(Spacer(1, 6))
        story.append(Paragraph("Rows shaded red are blocking conditions not yet cleared. "
                               "(“Cleared By” is not individually attributed in the current schema.)", SMALL))
    else:
        story.append(Paragraph("No conditions generated for this loan.", NORM))

    # ── PAGE 4 — Override Chain + Escalation ─────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("Override Chain", H2))
    if overrides:
        rows = [["Decision", "Reviewer", "Reason", "When"]]
        for o in overrides:
            rows.append([
                Paragraph(str(o["decision_id"]).replace("_", " ").title(), SMALL),
                Paragraph(str(o["human_reviewer"] or "—"), SMALL),
                Paragraph(_short(o["human_override_reason"], 66), SMALL),
                _date(o["acted_at"]),
            ])
        t4 = Table(rows, colWidths=[110, 96, 210, 74], repeatRows=1)
        t4.setStyle(_base_style())
        story.append(t4)
    else:
        story.append(Paragraph("No human overrides recorded for this loan.", NORM))

    story.append(Paragraph("Escalation Thread", H2))
    thread = data.get("escalation_thread") or []
    if thread:
        rows = [["When", "Actor", "Action", "Message"]]
        for e in thread:
            rows.append([
                Paragraph(str(e.get("time_ago") or _date(e.get("timestamp"))), SMALL),
                Paragraph(str(e.get("actor_name") or "—"), SMALL),
                Paragraph(str(e.get("action") or "").replace("_", " ").title(), SMALL),
                Paragraph(_short(e.get("message"), 60), SMALL),
            ])
        t4b = Table(rows, colWidths=[70, 110, 96, 214], repeatRows=1)
        t4b.setStyle(_base_style())
        story.append(t4b)
    else:
        story.append(Paragraph("No escalation activity recorded for this loan.", NORM))

    # ── PAGE 5 — Regulatory Compliance Flags ─────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("Regulatory Compliance Flags", H2))
    brl = ((comp["boundary_rule"] if comp else "") or "").lower()
    qm = data.get("qm") or {}
    cd_ok = loan_terms.get("cd_timing_compliant")
    denied = bool(es and es["loan_status"] == "denied")
    hmda = ("Incomplete", _RED) if "hmda_complete=false" in brl else ("Complete", _GREEN)
    fair = ("Flagged", _RED) if "fair_lending_violation=true" in brl else ("Clear", _GREEN)
    trid = ("Compliant", _GREEN) if cd_ok is True else (("Violation", _RED) if cd_ok is False else ("—", colors.grey))
    atr_map = {"safe_harbor": ("QM — Safe Harbor", _GREEN),
               "rebuttable_presumption": ("QM — Rebuttable Presumption", _AMBER),
               "non_qm": ("Non-QM", _RED), "pending": ("Pending", colors.grey)}
    atr = atr_map.get(qm.get("status") or "pending", (str(qm.get("status")), colors.grey))
    adverse = ("Sent / queued", _AMBER) if denied else ("Not sent", colors.grey)
    checks = [("HMDA Completeness", hmda), ("Fair Lending", fair), ("TRID — CD Timing", trid),
              ("ATR / QM", atr), ("Adverse Action Notice", adverse)]
    rows = [["Regulatory Check", "Status"]]
    extra = []
    for i, (label, (val, col)) in enumerate(checks, start=1):
        rows.append([Paragraph(label, CELL), Paragraph(val, CELL)])
        extra.append(("TEXTCOLOR", (1, i), (1, i), col))
        extra.append(("FONTNAME", (1, i), (1, i), "Helvetica-Bold"))
    t5 = Table(rows, colWidths=[220, 270], repeatRows=1)
    t5.setStyle(_base_style(extra))
    story.append(t5)

    who = user.get("name") or user.get("email") or "unknown"
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=54, bottomMargin=52,
                            leftMargin=54, rightMargin=54, title=f"Exam-Ready {app_id}")
    foot = lambda c, d: _footer(c, d, app_id, tenant_id, who, when)  # noqa: E731
    doc.build(story, onFirstPage=foot, onLaterPages=foot)
    return buf.getvalue()


@router.post("/loans/{application_id}/export/exam-ready")
async def export_exam_ready(application_id: str, user: dict = Depends(get_current_user)) -> Response:
    """5-page exam-ready PDF. Tenant isolation is inherited from loan_detail()
    (403/404 for a cross-tenant or unknown loan)."""
    _require_db()
    tenant_id = user["tenant_id"]
    data = await loan_detail(application_id, user)
    pool = await _get_pool()
    async with pool.acquire() as conn:
        overrides = await conn.fetch(
            "SELECT decision_id, human_reviewer, human_override_reason, acted_at "
            "FROM decision_outputs WHERE application_id=$1 AND tenant_id=$2 "
            "AND human_action='overridden' ORDER BY acted_at ASC",
            application_id, tenant_id)
        comp = await conn.fetchrow(
            "SELECT reasoning, boundary_rule FROM decision_outputs "
            "WHERE application_id=$1 AND tenant_id=$2 AND decision_id='compliance_check' "
            "ORDER BY version DESC LIMIT 1", application_id, tenant_id)
        es = await conn.fetchrow(
            "SELECT loan_terms, property, loan_status FROM entity_states "
            "WHERE application_id=$1 AND tenant_id=$2", application_id, tenant_id)
        conds = await conn.fetch(
            "SELECT condition_code, condition_text, status, blocks_closing, opened_at, cleared_at "
            "FROM loan_condition_instances WHERE application_id=$1 AND tenant_id=$2 "
            "ORDER BY blocks_closing DESC, opened_at ASC", application_id, tenant_id)
        uw_date = await conn.fetchval(
            "SELECT decided_at FROM decision_outputs WHERE application_id=$1 AND tenant_id=$2 "
            "AND decision_id='underwriting_decision' ORDER BY version DESC LIMIT 1",
            application_id, tenant_id)
    pdf = _build_pdf(data, list(overrides), comp, es, list(conds), uw_date, user, application_id, tenant_id)
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="exam-ready-{application_id}.pdf"'})


__all__ = ["router"]
