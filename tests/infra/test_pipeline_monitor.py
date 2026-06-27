"""IN-C — pipeline observability tests (pure + mockable, no AWS, no DB).

Watermark staleness bands, health assessment (watermark + DLQ), and the CloudWatch
metric sink (injectable client + graceful no-op). RULE 11 throughout.
"""
import unittest
from datetime import datetime, timedelta, timezone

from core.infra.pipeline_monitor import (
    CloudWatchMetricSink,
    assess_pipeline_health,
    evaluate_watermark,
    fetch_dlq_depth,
)

NOW = "2026-06-27T12:00:00+00:00"


def _ago(seconds):
    return (datetime(2026, 6, 27, 12, 0, 0, tzinfo=timezone.utc) - timedelta(seconds=seconds)).isoformat()


class WatermarkTests(unittest.TestCase):
    def test_healthy(self):
        r = evaluate_watermark(_ago(60), now=NOW)
        self.assertEqual(r["status"], "healthy")
        self.assertEqual(r["age_seconds"], 60.0)

    def test_stale(self):
        r = evaluate_watermark(_ago(400), now=NOW)   # > 300, < 900
        self.assertEqual(r["status"], "stale")

    def test_stalled_15min(self):
        r = evaluate_watermark(_ago(1000), now=NOW)  # > 900
        self.assertEqual(r["status"], "stalled")
        self.assertIn("stalled", r["note"].lower())

    def test_boundary(self):
        self.assertEqual(evaluate_watermark(_ago(300), now=NOW)["status"], "stale")     # == stale_sec
        self.assertEqual(evaluate_watermark(_ago(900), now=NOW)["status"], "stalled")   # == stalled_sec

    def test_unknown_no_watermark(self):
        r = evaluate_watermark(None, now=NOW)
        self.assertEqual(r["status"], "unknown")
        self.assertTrue(r["missing_inputs"])

    def test_custom_thresholds(self):
        r = evaluate_watermark(_ago(60), now=NOW, stale_sec=30, stalled_sec=120)
        self.assertEqual(r["status"], "stale")

    def test_datetime_input(self):
        dt = datetime(2026, 6, 27, 11, 59, 0, tzinfo=timezone.utc)
        self.assertEqual(evaluate_watermark(dt, now=NOW)["status"], "healthy")


class HealthAssessmentTests(unittest.TestCase):
    def test_healthy(self):
        wm = evaluate_watermark(_ago(60), now=NOW)
        out = assess_pipeline_health(wm, dlq_depth=0)
        self.assertEqual(out["overall_status"], "healthy")
        self.assertEqual(out["findings"], [])

    def test_stalled_overrides(self):
        wm = evaluate_watermark(_ago(1000), now=NOW)
        out = assess_pipeline_health(wm, dlq_depth=0)
        self.assertEqual(out["overall_status"], "stalled")
        self.assertIn("Page on-call", out["recommended_action"])

    def test_dlq_degraded(self):
        wm = evaluate_watermark(_ago(60), now=NOW)
        out = assess_pipeline_health(wm, dlq_depth=5)
        self.assertEqual(out["overall_status"], "degraded")
        self.assertTrue(any("DLQ" in f for f in out["findings"]))

    def test_unknown(self):
        out = assess_pipeline_health(evaluate_watermark(None, now=NOW), dlq_depth=None)
        self.assertEqual(out["overall_status"], "unknown")
        self.assertTrue(out["missing_inputs"])

    def test_dlq_none_flagged_missing(self):
        wm = evaluate_watermark(_ago(60), now=NOW)
        out = assess_pipeline_health(wm, dlq_depth=None)
        self.assertTrue(any("DLQ depth unavailable" in m for m in out["missing_inputs"]))

    def test_rule11(self):
        out = assess_pipeline_health(evaluate_watermark(_ago(60), now=NOW), dlq_depth=0)
        self.assertIn("data_source", out)
        self.assertIn("missing_inputs", out)


class FakeCloudWatch:
    def __init__(self):
        self.calls = []

    def put_metric_data(self, **kwargs):
        self.calls.append(kwargs)


class MetricSinkTests(unittest.TestCase):
    def test_emit_with_client(self):
        cw = FakeCloudWatch()
        out = CloudWatchMetricSink(client=cw).emit({"WatermarkAgeSeconds": 60.0, "DLQDepth": 2},
                                                   dimensions={"tenant_id": "meridian"})
        self.assertTrue(out["emitted"])
        self.assertEqual(out["count"], 2)
        self.assertEqual(len(cw.calls), 1)
        self.assertEqual(cw.calls[0]["Namespace"], "Accord/Pipeline")

    def test_noop_without_client(self):
        # no injected client + boto3 cloudwatch with no creds builds a client, so force
        # the no-op path by simulating an unavailable client
        class NoCW(CloudWatchMetricSink):
            @property
            def _cw(self):
                return None
        out = NoCW().emit({"X": 1.0})
        self.assertFalse(out["emitted"])
        self.assertEqual(out["count"], 0)

    def test_none_values_skipped(self):
        cw = FakeCloudWatch()
        out = CloudWatchMetricSink(client=cw).emit({"A": 5.0, "B": None})
        self.assertEqual(out["count"], 1)  # None value dropped

    def test_empty_metrics_noop(self):
        out = CloudWatchMetricSink(client=FakeCloudWatch()).emit({})
        self.assertFalse(out["emitted"])


class DlqDepthTests(unittest.TestCase):
    def test_none_without_client(self):
        self.assertIsNone(fetch_dlq_depth(None, ""))

    def test_reads_attribute(self):
        class FakeSQS:
            def get_queue_attributes(self, **k):
                return {"Attributes": {"ApproximateNumberOfMessages": "7"}}
        self.assertEqual(fetch_dlq_depth(FakeSQS(), "https://dlq"), 7)


if __name__ == "__main__":
    unittest.main()
