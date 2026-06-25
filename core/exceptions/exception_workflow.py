"""Exception workflow service (EX-C) — status transitions + approver authority.

Drives loan_exceptions through requested → under_review → granted/denied with an
approver-authority (RBAC) check, and writes each transition to loan_actions for
the audit trail (building on the existing override capture). The agency floor is
ABSOLUTE — no role can grant an exception below it (catalogue
exception_cannot_breach_agency_floor, EX-A).

can_approve() is pure (sync, no DB). transition_status() touches the DB (the only
place EX-C mutates loan_exceptions/loan_actions — engines/persona stay DB-less,
RULE 5/6). RULE 11: data_source + missing_inputs on every return.

APPROVER_AUTHORITY is a structural RBAC map (role -> levels it may grant), like
the signal maps elsewhere; the role NAMES are seeded in the catalogue (EX-C:
approver_uw_role / approver_manager_role / approver_senior_role) for the workbench.
"""
from __future__ import annotations

from typing import Optional

_CITE = "Fannie B3-2-02"

# role -> approval levels that role may grant (cumulative).
APPROVER_AUTHORITY = {
    "uw": ["uw_approval"],
    "uw_manager": ["uw_approval", "uw_manager_approval"],
    "senior_credit_officer": ["uw_approval", "uw_manager_approval", "senior_uw_approval"],
    "credit_committee": ["uw_approval", "uw_manager_approval", "senior_uw_approval"],
}

_REQUIRED_ROLE = {
    "uw_approval": "uw",
    "uw_manager_approval": "uw_manager",
    "senior_uw_approval": "senior_credit_officer",
    "insufficient_factors": "cannot_approve",
}

_VALID_TRANSITIONS = {
    "requested": ["under_review", "denied"],
    "under_review": ["granted", "denied"],
}


class ExceptionWorkflowService:
    def __init__(self, rules: Optional[dict] = None):
        from core.catalogue.rule_loader import SAFE_DEFAULTS
        r = dict(SAFE_DEFAULTS)
        if rules:
            r.update({k: v for k, v in rules.items() if v is not None})
        self._cannot_breach_agency = bool(
            r.get("exception_cannot_breach_agency_floor", True))

    def _required_role_for(self, level: str) -> str:
        return _REQUIRED_ROLE.get(level, "unknown")

    def can_approve(self, approver_role: str, required_level: str,
                    below_agency_floor: bool) -> dict:
        """Pure authority check: role × required level × the absolute agency-floor
        guardrail. No DB."""
        if below_agency_floor and self._cannot_breach_agency:
            return {"can_approve": False, "reason": "below_agency_floor_absolute",
                    "note": "No role can approve an exception below the agency floor.",
                    "citation": _CITE,
                    "data_source": "loan_exceptions.below_agency_floor + catalogue",
                    "missing_inputs": []}
        if required_level == "insufficient_factors":
            return {"can_approve": False, "reason": "insufficient_factors",
                    "note": "No compensating factors — exception cannot be approved.",
                    "citation": _CITE, "data_source": "loan_exceptions (approval_level)",
                    "missing_inputs": []}
        authority = APPROVER_AUTHORITY.get(approver_role, [])
        if required_level not in authority:
            return {"can_approve": False, "reason": "insufficient_authority",
                    "note": f"{approver_role} cannot approve {required_level} exceptions",
                    "required_role": self._required_role_for(required_level),
                    "data_source": "APPROVER_AUTHORITY map", "missing_inputs": []}
        return {"can_approve": True, "approver_role": approver_role,
                "required_level": required_level, "citation": _CITE,
                "data_source": "APPROVER_AUTHORITY map + catalogue", "missing_inputs": []}

    async def transition_status(
        self, conn, exception_id: str, tenant_id: str, new_status: str,
        reviewer_id: str, approver_role: str, granted: bool,
        denial_reason: Optional[str] = None,
    ) -> dict:
        exc = await conn.fetchrow(
            """SELECT status, below_agency_floor, application_id, decision_output_id,
                      threshold_source
               FROM loan_exceptions WHERE id=$1 AND tenant_id=$2""",
            exception_id, tenant_id,
        )
        if not exc:
            return {"success": False, "reason": "exception_not_found",
                    "data_source": "loan_exceptions table", "missing_inputs": []}

        # required_level was persisted by the writer in threshold_source.
        required_level = exc["threshold_source"] or "uw_approval"
        auth = self.can_approve(approver_role, required_level, exc["below_agency_floor"])
        if not auth["can_approve"]:
            return {"success": False, **auth}

        current = exc["status"]
        if new_status not in _VALID_TRANSITIONS.get(current, []):
            return {"success": False,
                    "reason": f"invalid_transition_{current}_to_{new_status}",
                    "data_source": "loan_exceptions.status", "missing_inputs": []}

        await conn.execute(
            """UPDATE loan_exceptions
               SET status=$1, reviewed_by=$2, reviewed_at=NOW(), granted=$3,
                   denial_reason=$4, updated_at=NOW()
               WHERE id=$5 AND tenant_id=$6""",
            new_status, reviewer_id, granted, denial_reason, exception_id, tenant_id,
        )
        import json as _json
        await conn.execute(
            """INSERT INTO loan_actions (
                   application_id, tenant_id, action_type, reason_category,
                   reason_text, performed_by, related_decision_id, metadata)
               VALUES ($1,$2,$3,'exception_workflow',$4,$5,$6,$7::jsonb)""",
            exc["application_id"], tenant_id,
            "grant_exception" if granted else "deny_exception",
            denial_reason or f"Exception {new_status} by {reviewer_id}",
            reviewer_id,
            str(exc["decision_output_id"]) if exc["decision_output_id"] else None,
            _json.dumps({"exception_id": exception_id, "approver_role": approver_role,
                         "required_level": required_level}),
        )
        return {"success": True, "exception_id": exception_id, "new_status": new_status,
                "granted": granted, "reviewer_id": reviewer_id,
                "data_source": "loan_exceptions + loan_actions tables", "missing_inputs": []}


__all__ = ["ExceptionWorkflowService", "APPROVER_AUTHORITY"]
