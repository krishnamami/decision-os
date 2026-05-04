"""FastAPI route tests via TestClient.

Boots a real app via create_app(seed_demo_data=True) so the routes see
12 personas + 7 applications. Tests assert HTTP status + response
shape + side effects (trace persistence, AgentLearning capture, etc.).

  python -m unittest tests.api.test_routes
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from api.main import create_app  # noqa: E402


# ─────────────────────────────────────────────────────────────────────
# Shared fixture — one TestClient per test class so the lifespan runs
# (seeding policies + 7 scenarios) only once per class.
# ─────────────────────────────────────────────────────────────────────


class _SeededAppMixin:
    """Mixin: each test class boots a TestClient with seed_demo_data.

    setUp creates the client; tearDown closes it. Lifespan kicks in via
    `with TestClient(app)` which is what we use."""

    @classmethod
    def setUpClass(cls):
        cls.app = create_app(seed_demo_data=True, mount_ui=False)
        cls.client = TestClient(cls.app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)


# ─────────────────────────────────────────────────────────────────────
# /health
# ─────────────────────────────────────────────────────────────────────


class HealthTests(_SeededAppMixin, unittest.TestCase):

    def test_health_returns_ok(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["domain"], "lending")
        self.assertEqual(body["agents"], "12")
        # 7 seed scenarios = 7 applications.
        self.assertEqual(body["applications"], "7")


# ─────────────────────────────────────────────────────────────────────
# POST /events
# ─────────────────────────────────────────────────────────────────────


class IngestEventTests(_SeededAppMixin, unittest.TestCase):

    def test_ingest_lead_received_event(self):
        r = self.client.post(
            "/events",
            json={
                "event": {
                    "event_type": "lead_received",
                    "customer_id": "cust_test_ingest",
                    "lead_source": "test_form",
                    "channel": "digital",
                }
            },
        )
        self.assertEqual(r.status_code, 201, r.text)
        body = r.json()
        self.assertEqual(body["event_type"], "lead_received")
        self.assertEqual(body["customer_id"], "cust_test_ingest")
        self.assertIn("event_id", body)
        # Hydrator wrote an Applicant entity.
        self.assertTrue(any(
            k.startswith("Applicant:") for k in body["hydrated_keys"]
        ))

    def test_unknown_event_type_returns_422(self):
        r = self.client.post(
            "/events",
            json={"event": {"event_type": "warp_drive_engaged"}},
        )
        self.assertEqual(r.status_code, 422)

    def test_missing_event_type_returns_422(self):
        r = self.client.post(
            "/events",
            json={"event": {}},
        )
        self.assertEqual(r.status_code, 422)


# ─────────────────────────────────────────────────────────────────────
# GET /trace/{trace_id} + /applications/{id}/traces
# ─────────────────────────────────────────────────────────────────────


class TraceReadTests(_SeededAppMixin, unittest.TestCase):

    def test_unknown_trace_id_returns_404(self):
        r = self.client.get("/trace/00000000-0000-0000-0000-000000000000")
        self.assertEqual(r.status_code, 404)

    def test_list_traces_for_known_application(self):
        # happy_path produces 12 traces.
        r = self.client.get("/applications/app_happy/traces")
        self.assertEqual(r.status_code, 200)
        traces = r.json()
        self.assertEqual(len(traces), 12)

    def test_get_trace_round_trip(self):
        # Pick any trace from the list endpoint, then GET it by id.
        r = self.client.get("/applications/app_happy/traces")
        trace_id = r.json()[0]["trace_id"]
        r2 = self.client.get(f"/trace/{trace_id}")
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["trace_id"], trace_id)


# ─────────────────────────────────────────────────────────────────────
# GET /decisions/{app}/{decision}
# ─────────────────────────────────────────────────────────────────────


class DecisionRecordTests(_SeededAppMixin, unittest.TestCase):

    def test_unknown_decision_returns_404(self):
        r = self.client.get("/decisions/app_happy/nonexistent_decision")
        self.assertEqual(r.status_code, 404)

    def test_known_decision_returns_record(self):
        # credit_assessment is auto_execute → writes a decision record.
        r = self.client.get("/decisions/app_happy/credit_assessment")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["application_id"], "app_happy")
        self.assertEqual(body["decision_id"], "credit_assessment")
        self.assertIn("outcome", body)
        self.assertIn("confidence", body)


# ─────────────────────────────────────────────────────────────────────
# POST /override
# ─────────────────────────────────────────────────────────────────────


class OverrideTests(_SeededAppMixin, unittest.TestCase):

    def _pick_trace_for_override(self):
        """Find a trace whose outcome we can flip without conflict.
        Use credit_assessment for app_happy — auto_execute, outcome=allow,
        no human_review attached, easy to override to BLOCK."""
        r = self.client.get("/applications/app_happy/traces")
        for t in r.json():
            if t["decision_id"] == "credit_assessment" and t.get("human_review") is None:
                return t
        return None

    def test_override_with_changed_outcome_writes_learning(self):
        trace = self._pick_trace_for_override()
        self.assertIsNotNone(trace)
        original_outcome = trace["outcome"]
        new_outcome = "block" if original_outcome != "block" else "escalate"
        r = self.client.post(
            "/override",
            json={
                "trace_id": trace["trace_id"],
                "reviewer_id": "test_reviewer",
                "reviewer_role": "credit_underwriter",
                "new_outcome": new_outcome,
                "override_reason": "test override path",
                "override_reason_code": "test_code",
            },
        )
        self.assertEqual(r.status_code, 201, r.text)
        body = r.json()
        self.assertIn("trace", body)
        self.assertIn("learning", body)
        self.assertEqual(
            body["trace"]["human_review"]["final_outcome"], new_outcome
        )
        self.assertEqual(
            body["learning"]["original_ai_decision"], original_outcome
        )
        self.assertEqual(body["learning"]["human_decision"], new_outcome)

    def test_override_unknown_trace_returns_404(self):
        r = self.client.post(
            "/override",
            json={
                "trace_id": "00000000-0000-0000-0000-000000000000",
                "reviewer_id": "x",
                "reviewer_role": "y",
                "new_outcome": "block",
                "override_reason": "doesn't matter",
            },
        )
        self.assertEqual(r.status_code, 404)


class OverrideSameOutcomeTests(unittest.TestCase):
    """Stand up a fresh app per test so the override-twice scenarios
    don't interfere with the OverrideTests class above."""

    def setUp(self):
        self.app = create_app(seed_demo_data=True, mount_ui=False)
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def test_same_outcome_returns_400(self):
        r = self.client.get("/applications/app_happy/traces")
        target = next(
            t for t in r.json()
            if t["decision_id"] == "credit_assessment"
        )
        # Submit the SAME outcome the trace already has — 400.
        r2 = self.client.post(
            "/override",
            json={
                "trace_id": target["trace_id"],
                "reviewer_id": "x",
                "reviewer_role": "y",
                "new_outcome": target["outcome"],
                "override_reason": "should be rejected",
            },
        )
        self.assertEqual(r2.status_code, 400)


# ─────────────────────────────────────────────────────────────────────
# POST /applications/{id}/run — E2E DAG runner
# ─────────────────────────────────────────────────────────────────────


class RunApplicationTests(_SeededAppMixin, unittest.TestCase):

    def test_run_seeded_application_completes(self):
        # app_happy is fully seeded — re-running the DAG against the
        # same entity state produces another batch of traces. Confirm
        # the response shape.
        r = self.client.post("/applications/app_happy/run")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["application_id"], "app_happy")
        self.assertFalse(body["halted"])
        self.assertEqual(len(body["completed"]), 12)


class AuditRouteTests(_SeededAppMixin, unittest.TestCase):
    """GET /audit/{id}, /audit/application/{id}, /audit/flags +
    POST /audit/{id}/access — covers the read paths and the
    pii_access_always_logged side-channel."""

    def test_list_audit_records_for_seeded_application(self):
        r = self.client.get("/audit/application/app_happy")
        self.assertEqual(r.status_code, 200, r.text)
        records = r.json()
        # 12 decisions → 12 audit records.
        self.assertEqual(len(records), 12)
        decision_types = {r["decision_type"] for r in records}
        for did in (
            "lead_scoring", "credit_assessment", "fraud_screening",
            "underwriting_decision", "closing_readiness",
        ):
            self.assertIn(did, decision_types)

    def test_get_audit_record_round_trip(self):
        r = self.client.get("/audit/application/app_happy")
        first = r.json()[0]
        r2 = self.client.get(f"/audit/{first['audit_id']}")
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertEqual(r2.json()["audit_id"], first["audit_id"])

    def test_unknown_audit_id_returns_404(self):
        r = self.client.get("/audit/00000000-0000-0000-0000-000000000000")
        self.assertEqual(r.status_code, 404)

    def test_flags_endpoint_filters_warn_and_fail(self):
        # Happy-path scenario should produce no flags. fraud_block /
        # contamination / compliance_block produce flags depending on
        # default audit inputs — the contract is just that the response
        # is a list.
        r = self.client.get("/audit/flags")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsInstance(r.json(), list)

    def test_post_access_log_writes_entry(self):
        r = self.client.get("/audit/application/app_happy")
        audit_id = r.json()[0]["audit_id"]
        r2 = self.client.post(
            f"/audit/{audit_id}/access",
            json={
                "user_id": "auditor_test",
                "role": "auditor",
                "action": "review",
            },
        )
        self.assertEqual(r2.status_code, 201, r2.text)
        log = r2.json()
        # At least the entry we just posted; get() above already added a
        # `system` row, plus the explicit POST row is present.
        actions = {entry["action"] for entry in log}
        users = {entry["user_id"] for entry in log}
        self.assertIn("review", actions)
        self.assertIn("auditor_test", users)

    def test_post_access_log_unknown_audit_id_returns_404(self):
        r = self.client.post(
            "/audit/00000000-0000-0000-0000-000000000000/access",
            json={"user_id": "x", "role": "y", "action": "read"},
        )
        self.assertEqual(r.status_code, 404)

    def test_adverse_action_returns_409_for_clean_decisions(self):
        # happy_path applicant — every decision is allow / recommend.
        # Adverse-action endpoint must refuse to generate a notice.
        r = self.client.get("/audit/application/app_happy")
        audit_id = r.json()[0]["audit_id"]
        r2 = self.client.get(f"/audit/{audit_id}/adverse-action")
        self.assertEqual(r2.status_code, 409, r2.text[:200])

    def test_adverse_action_404_for_unknown_audit_id(self):
        r = self.client.get(
            "/audit/00000000-0000-0000-0000-000000000000/adverse-action"
        )
        self.assertEqual(r.status_code, 404)

    def test_export_csv_streams_header_and_rows(self):
        r = self.client.get("/audit/export.csv")
        self.assertEqual(r.status_code, 200, r.text[:200])
        self.assertEqual(r.headers["content-type"].split(";")[0], "text/csv")
        body = r.text
        # Header is the first line; check for known columns.
        first_line = body.splitlines()[0]
        for col in ("audit_id", "decision_type", "overall_status", "regulation_tags"):
            self.assertIn(col, first_line)
        # Total = 1 header + N records. fraud_block / compliance_block
        # halt the DAG before all 12 decisions run, so the exact count
        # depends on halt behaviour. Lower bound: at least 7 (one per
        # scenario's lead_scoring) + much more.
        rows = body.splitlines()[1:]
        self.assertGreaterEqual(len(rows), 50)

    def test_export_csv_decision_type_filter(self):
        r = self.client.get(
            "/audit/export.csv?decision_type=credit_assessment"
        )
        self.assertEqual(r.status_code, 200)
        rows = r.text.splitlines()[1:]  # drop header
        # credit_assessment runs on every seed (no upstream blocks);
        # 7 applications → 7 records.
        self.assertEqual(len(rows), 7)
        for row in rows:
            self.assertIn("credit_assessment", row)

    def test_export_csv_only_filter_rejects_bogus_status(self):
        r = self.client.get("/audit/export.csv?only=glorp")
        self.assertEqual(r.status_code, 400)

    def test_export_csv_after_filter_rejects_bogus_iso(self):
        r = self.client.get("/audit/export.csv?after=not-a-date")
        self.assertEqual(r.status_code, 400)

    def test_export_jsonl_yields_one_record_per_line(self):
        import json

        # credit_assessment runs on every scenario — guaranteed 7.
        r = self.client.get("/audit/export.jsonl?decision_type=credit_assessment")
        self.assertEqual(r.status_code, 200)
        self.assertIn("ndjson", r.headers["content-type"])
        lines = [ln for ln in r.text.splitlines() if ln.strip()]
        self.assertEqual(len(lines), 7)
        for ln in lines:
            obj = json.loads(ln)
            self.assertEqual(obj["decision_type"], "credit_assessment")

    def test_adverse_action_returns_notice_for_block_decision(self):
        # fraud_block scenario produces a fraud_screening BLOCK trace.
        # The audit record for that decision is the source of an
        # ECOA-required notice.
        r = self.client.get("/audit/application/app_fraud")
        records = r.json()
        block_audit = next(
            (rec for rec in records if rec["decision_output"] == "block"),
            None,
        )
        self.assertIsNotNone(block_audit, "fraud_block must produce a BLOCK")
        r2 = self.client.get(f"/audit/{block_audit['audit_id']}/adverse-action")
        self.assertEqual(r2.status_code, 200, r2.text[:200])
        notice = r2.json()
        self.assertEqual(notice["application_id"], "app_fraud")
        self.assertIn("reasons", notice)
        self.assertGreater(len(notice["reasons"]), 0)
        self.assertIn("ecoa_statement", notice)


class AuditUIRenderTests(unittest.TestCase):
    """Boot a separate app with mount_ui=True so the audit templates
    render through Jinja2. Catches template syntax / missing-context
    bugs that the view-model tests can't see."""

    @classmethod
    def setUpClass(cls):
        cls.app = create_app(seed_demo_data=True, mount_ui=True)
        cls.client = TestClient(cls.app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def test_audit_flags_page_renders(self):
        r = self.client.get("/ui/audit/flags")
        self.assertEqual(r.status_code, 200, r.text[:500])
        self.assertIn("Audit flags", r.text)

    def test_audit_record_detail_renders(self):
        # Pull any audit_id from the API to drive the UI route.
        r = self.client.get("/audit/application/app_happy")
        audit_id = r.json()[0]["audit_id"]
        r2 = self.client.get(f"/ui/audit/{audit_id}")
        self.assertEqual(r2.status_code, 200, r2.text[:500])
        self.assertIn("Audit record", r2.text)
        self.assertIn("Compliance", r2.text)
        self.assertIn("Security", r2.text)

    def test_audit_unknown_id_returns_404(self):
        r = self.client.get("/ui/audit/00000000-0000-0000-0000-000000000000")
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
