"""Outcome tracker tests — PRD STEP 12.

  python -m unittest tests.core.trace.test_outcome_tracker
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.trace import (  # noqa: E402
    InMemoryOutcomeTracker,
    OutcomeRecord,
    OutcomeType,
    correlate,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _record(
    *,
    application_id: str = "app_test",
    outcome_type: OutcomeType = OutcomeType.FUNDED,
    recorded_at: datetime | None = None,
    occurred_at: datetime | None = None,
    amount: float | None = None,
) -> OutcomeRecord:
    return OutcomeRecord(
        application_id=application_id,
        outcome_type=outcome_type,
        recorded_at=recorded_at or datetime.utcnow(),
        occurred_at=occurred_at,
        amount=amount,
    )


class CaptureAndReadTests(unittest.TestCase):

    def setUp(self):
        self.tracker = InMemoryOutcomeTracker()

    def test_capture_then_get(self):
        record = _record()
        oid = _run(self.tracker.capture(record))
        self.assertEqual(oid, record.outcome_id)
        roundtrip = _run(self.tracker.get(oid))
        self.assertIsNotNone(roundtrip)
        self.assertEqual(roundtrip.outcome_type, OutcomeType.FUNDED)

    def test_duplicate_capture_raises(self):
        record = _record()
        _run(self.tracker.capture(record))
        with self.assertRaises(ValueError):
            _run(self.tracker.capture(record))

    def test_list_for_application_orders_by_recorded_at(self):
        base = datetime.utcnow()
        early = _record(recorded_at=base, outcome_type=OutcomeType.FUNDED)
        mid   = _record(recorded_at=base + timedelta(days=30),
                        outcome_type=OutcomeType.MODIFIED)
        late  = _record(recorded_at=base + timedelta(days=90),
                        outcome_type=OutcomeType.DEFAULT)
        # Insert out of order
        _run(self.tracker.capture(late))
        _run(self.tracker.capture(early))
        _run(self.tracker.capture(mid))
        rows = _run(self.tracker.list_for_application("app_test"))
        types = [r.outcome_type for r in rows]
        self.assertEqual(
            types, [OutcomeType.FUNDED, OutcomeType.MODIFIED, OutcomeType.DEFAULT]
        )

    def test_latest_for_application_returns_most_recent(self):
        base = datetime.utcnow()
        _run(self.tracker.capture(_record(
            recorded_at=base, outcome_type=OutcomeType.FUNDED,
        )))
        _run(self.tracker.capture(_record(
            recorded_at=base + timedelta(days=30),
            outcome_type=OutcomeType.MODIFIED,
        )))
        latest = _run(self.tracker.latest_for_application("app_test"))
        self.assertIsNotNone(latest)
        self.assertEqual(latest.outcome_type, OutcomeType.MODIFIED)

    def test_latest_returns_none_for_unknown_application(self):
        latest = _run(self.tracker.latest_for_application("nonexistent"))
        self.assertIsNone(latest)

    def test_list_by_type_filters_correctly(self):
        _run(self.tracker.capture(_record(application_id="a",
                                           outcome_type=OutcomeType.FUNDED)))
        _run(self.tracker.capture(_record(application_id="b",
                                           outcome_type=OutcomeType.FUNDED)))
        _run(self.tracker.capture(_record(application_id="c",
                                           outcome_type=OutcomeType.DEFAULT)))
        funded = _run(self.tracker.list_by_type(OutcomeType.FUNDED))
        defaults = _run(self.tracker.list_by_type(OutcomeType.DEFAULT))
        self.assertEqual(len(funded), 2)
        self.assertEqual(len(defaults), 1)


class CorrelationTests(unittest.TestCase):

    def test_correlate_picks_final_outcome_type(self):
        decision_at = datetime.utcnow()
        outcomes = [
            _record(
                outcome_type=OutcomeType.FUNDED,
                recorded_at=decision_at + timedelta(days=10),
            ),
            _record(
                outcome_type=OutcomeType.DEFAULT,
                recorded_at=decision_at + timedelta(days=120),
            ),
        ]
        c = correlate(
            "app_test",
            decision_id="underwriting_decision",
            decision_outcome="allow",
            decision_confidence=0.85,
            decision_at=decision_at,
            outcomes=outcomes,
        )
        self.assertEqual(c.final_outcome_type, OutcomeType.DEFAULT)
        self.assertEqual(c.decision_outcome, "allow")
        self.assertEqual(c.confidence, 0.85)
        self.assertEqual(c.days_to_first_outcome, 10)

    def test_correlate_with_no_outcomes(self):
        c = correlate(
            "app_test",
            decision_id="underwriting_decision",
            decision_outcome="block",
            decision_confidence=0.9,
            decision_at=datetime.utcnow(),
            outcomes=[],
        )
        self.assertIsNone(c.final_outcome_type)
        self.assertIsNone(c.days_to_first_outcome)
        self.assertEqual(c.outcomes, [])

    def test_correlate_uses_occurred_at_when_present(self):
        # occurred_at takes precedence over recorded_at — the event
        # may have happened before we knew about it.
        decision_at = datetime.utcnow()
        outcomes = [
            _record(
                outcome_type=OutcomeType.FUNDED,
                occurred_at=decision_at + timedelta(days=5),
                recorded_at=decision_at + timedelta(days=20),
            ),
        ]
        c = correlate(
            "app_test",
            decision_id="underwriting_decision",
            decision_outcome="allow",
            decision_confidence=None,
            decision_at=decision_at,
            outcomes=outcomes,
        )
        self.assertEqual(c.days_to_first_outcome, 5)


if __name__ == "__main__":
    unittest.main()
