"""Store-level PII access logging — PRD §23.9 pii_access_always_logged.

  python -m unittest tests.core.audit.test_pii_log
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.audit.pii_log import (  # noqa: E402
    InMemoryPIIAccessLog,
    PIIAccessEntry,
    detect_pii_fields,
)
from core.context_store import (  # noqa: E402
    InMemoryDurableStore,
    InMemoryHotCache,
    LendingContextStore,
    Lineage,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class DetectPIIFieldsTests(unittest.TestCase):

    def test_detects_canonical_pii_fields(self):
        value = {"ssn": "123-45-6789", "first_name": "Alex", "income": 100_000}
        fields = detect_pii_fields(value)
        self.assertIn("ssn", fields)
        self.assertIn("first_name", fields)
        self.assertNotIn("income", fields)

    def test_returns_sorted_unique_fields(self):
        value = {"last_name": "Patel", "first_name": "Sam", "ssn": "x"}
        fields = detect_pii_fields(value)
        self.assertEqual(fields, sorted(fields))
        self.assertEqual(len(fields), len(set(fields)))

    def test_none_or_empty_value_returns_empty(self):
        self.assertEqual(detect_pii_fields(None), [])
        self.assertEqual(detect_pii_fields({}), [])

    def test_non_dict_value_returns_empty(self):
        self.assertEqual(detect_pii_fields([1, 2, 3]), [])
        self.assertEqual(detect_pii_fields("string"), [])


class StoreLevelLoggingTests(unittest.TestCase):

    def setUp(self):
        self.hot = InMemoryHotCache()
        self.durable = InMemoryDurableStore()
        self.log = InMemoryPIIAccessLog()
        self.store = LendingContextStore(
            self.hot, self.durable, pii_access_log=self.log
        )

    def test_pii_read_writes_log_entry(self):
        # Seed an Applicant with first_name (PII).
        lineage = Lineage(decision_id=None, agent="test", written_by="test")
        _run(self.store.set("Applicant", "cust_1", {
            "applicant_id": "cust_1",
            "first_name": "Alex",
            "last_name": "Patel",
        }, lineage))
        # Read it.
        record = _run(self.store.get("Applicant", "cust_1"))
        self.assertIsNotNone(record)
        # Log captured the PII fields.
        self.assertEqual(len(self.log), 1)
        entry = self.log._entries[0]
        self.assertEqual(entry.entity_type, "Applicant")
        self.assertEqual(entry.entity_id, "cust_1")
        self.assertIn("first_name", entry.pii_fields)
        self.assertIn("last_name", entry.pii_fields)

    def test_non_pii_read_does_not_log(self):
        lineage = Lineage(decision_id=None, agent="test", written_by="test")
        _run(self.store.set("Loan", "loan_1", {
            "loan_id": "loan_1",
            "principal_amount": 400_000,
        }, lineage))
        _run(self.store.get("Loan", "loan_1"))
        self.assertEqual(len(self.log), 0)

    def test_log_failure_does_not_break_read(self):
        # Sink raising on every record() must not propagate.
        class _Bad:
            async def record(self, entry):
                raise RuntimeError("log down")
            async def list_for_application(self, app_id): return []
            async def list_recent(self, limit=100): return []
        store = LendingContextStore(
            self.hot, self.durable, pii_access_log=_Bad()
        )
        lineage = Lineage(decision_id=None, agent="test", written_by="test")
        _run(store.set("Applicant", "cust_2", {
            "applicant_id": "cust_2", "first_name": "Z",
        }, lineage))
        # Read still succeeds.
        record = _run(store.get("Applicant", "cust_2"))
        self.assertIsNotNone(record)

    def test_log_unattached_means_no_logging(self):
        store = LendingContextStore(self.hot, self.durable)  # no log
        lineage = Lineage(decision_id=None, agent="test", written_by="test")
        _run(store.set("Applicant", "cust_3", {
            "applicant_id": "cust_3", "ssn": "x",
        }, lineage))
        record = _run(store.get("Applicant", "cust_3"))
        self.assertIsNotNone(record)  # read still works without log

    def test_list_for_application_filters_correctly(self):
        lineage = Lineage(decision_id=None, agent="test", written_by="test")
        _run(self.store.set("Applicant", "cust_a", {
            "applicant_id": "cust_a",
            "application_id": "app_a",
            "first_name": "A",
        }, lineage))
        _run(self.store.set("Applicant", "cust_b", {
            "applicant_id": "cust_b",
            "application_id": "app_b",
            "first_name": "B",
        }, lineage))
        _run(self.store.get("Applicant", "cust_a"))
        _run(self.store.get("Applicant", "cust_b"))
        rows_a = _run(self.log.list_for_application("app_a"))
        self.assertEqual(len(rows_a), 1)
        self.assertEqual(rows_a[0].entity_id, "cust_a")


if __name__ == "__main__":
    unittest.main()
