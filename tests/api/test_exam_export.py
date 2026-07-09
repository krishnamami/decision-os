"""Exam-ready PDF export (CN-EX) — offline unit test of the PDF builder.

The full DB-backed endpoint is verified against prod post-deploy; here we
exercise _build_pdf() with mock loan_detail-shaped data and assert it emits a
valid PDF (%PDF header, non-trivial size). Missing fields must not crash it.
"""

from api.accord.exam_export import _build_pdf


def _mock_data() -> dict:
    return {
        "borrower": {"name": "Test Borrower"},
        "metrics": {"loan_amount": 400000, "credit_score": 720, "ltv": 95.0},
        "loan_program": "Conforming 30yr",
        "aus_result": {"display": "DU: Approve/Eligible"},
        "status": "in_review",
        "assigned_to_name": "Jane Underwriter",
        "escalated_by_name": "Karen Senior",
        "qm": {"status": "safe_harbor"},
        "escalation_thread": [
            {"time_ago": "2d ago", "actor_name": "Jane", "action": "escalated",
             "message": "Needs senior review on LTV."},
        ],
        "decisions": [
            {"decision_id": "ltv_assessment", "persona_name": "LTV Analyst", "wave": 2,
             "outcome": "block", "rule": "ltv > 0.97",
             "governed_by": [{"agency": "fannie", "citation": "Selling Guide B2-1.2-01"}]},
            {"decision_id": "credit_check", "persona_name": "Credit Analyst", "wave": 1,
             "outcome": "allow", "rule": "fico >= 620", "governed_by": []},
        ],
    }


def test_exam_pdf_has_valid_header():
    pdf = _build_pdf(
        data=_mock_data(),
        overrides=[{"decision_id": "underwriting_decision", "human_reviewer": "Karen Senior",
                    "human_override_reason": "Compensating factors accepted.", "acted_at": None}],
        comp={"boundary_rule": "hmda_complete=True, fair_lending_violation=False", "reasoning": ""},
        es=None,
        conds=[{"condition_code": "INC-01", "condition_text": "Provide 2 years W-2",
                "status": "open", "blocks_closing": True, "opened_at": None, "cleared_at": None}],
        uw_date=None,
        user={"name": "Compliance Officer"},
        app_id="APP-SC10-004",
        tenant_id="summit",
    )
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 1000


def test_exam_pdf_tolerates_empty_data():
    # No decisions / conditions / thread / overrides — must still produce a PDF.
    pdf = _build_pdf(
        data={"decisions": [], "conditions": []},
        overrides=[], comp=None, es=None, conds=[], uw_date=None,
        user={"email": "x@y.com"}, app_id="APP-EMPTY", tenant_id="summit",
    )
    assert pdf[:4] == b"%PDF"
