"""IN-A — SQS consumer tests (injectable fake client, no AWS, no DB).

The consumer is exercised entirely through a FakeSQSClient + an injected dispatch
function, so no AWS and no real PersonaRunner run. Verifies poll/dispatch/delete/DLQ,
the malformed-message skip, the empty queue, and the graceful no-op when unconfigured.
"""
import asyncio
import json
import unittest

from core.infra.sqs_consumer import SQSConsumer, SQSMessage

QUEUE = "https://sqs.us-east-1.amazonaws.com/123/loans"
DLQ = "https://sqs.us-east-1.amazonaws.com/123/loans-dlq"


class FakeSQSClient:
    def __init__(self, messages=None):
        self._messages = list(messages or [])
        self.deleted = []
        self.dlq_sent = []

    def receive_message(self, **kwargs):
        n = kwargs.get("MaxNumberOfMessages", 10)
        msgs, self._messages = self._messages[:n], self._messages[n:]
        return {"Messages": msgs}

    def delete_message(self, **kwargs):
        self.deleted.append(kwargs.get("ReceiptHandle", ""))

    def send_message(self, **kwargs):
        self.dlq_sent.append(kwargs.get("MessageBody", ""))


def _msg(mid, rh, body):
    return {"MessageId": mid, "ReceiptHandle": rh, "Body": json.dumps(body)}


FAKE = [
    _msg("m1", "rh1", {"tenant_id": "meridian", "application_id": "APP-001", "event_type": "loan_submitted"}),
    _msg("m2", "rh2", {"tenant_id": "atlas", "application_id": "APP-002", "event_type": "document_arrived"}),
]


def _run(coro):
    return asyncio.run(coro)


class ConfigTests(unittest.TestCase):
    def test_not_configured_without_queue(self):
        c = SQSConsumer(queue_url="", client=FakeSQSClient())
        self.assertFalse(c.is_configured())
        r = _run(c.poll_once())
        self.assertEqual(r["status"], "not_configured")
        self.assertEqual(r["processed"], 0)

    def test_configured_with_queue_and_client(self):
        c = SQSConsumer(queue_url=QUEUE, client=FakeSQSClient())
        self.assertTrue(c.is_configured())

    def test_status_masks_queue(self):
        st = SQSConsumer(queue_url=QUEUE, client=FakeSQSClient(), dlq_url=DLQ).status()
        self.assertTrue(st["configured"])
        self.assertTrue(st["dlq_configured"])
        self.assertEqual(st["queue_env_var"], "SQS_QUEUE_URL")


class PollDispatchTests(unittest.TestCase):
    def _consumer(self, messages, dispatch, dlq=DLQ):
        self.client = FakeSQSClient(messages)
        return SQSConsumer(queue_url=QUEUE, client=self.client, dispatch_fn=dispatch, dlq_url=dlq)

    def test_successful_dispatch_deletes(self):
        async def ok(_msg):
            return True
        c = self._consumer(list(FAKE), ok)
        r = _run(c.poll_once())
        self.assertEqual(r["processed"], 2)
        self.assertEqual(r["failed"], 0)
        self.assertEqual(set(self.client.deleted), {"rh1", "rh2"})
        self.assertEqual(self.client.dlq_sent, [])

    def test_failed_dispatch_to_dlq(self):
        async def fail(_msg):
            return False
        c = self._consumer(list(FAKE), fail)
        r = _run(c.poll_once())
        self.assertEqual(r["failed"], 2)
        self.assertEqual(r["processed"], 0)
        self.assertEqual(len(self.client.dlq_sent), 2)
        self.assertEqual(self.client.deleted, [])  # not deleted on failure

    def test_dispatch_exception_to_dlq(self):
        async def boom(_msg):
            raise RuntimeError("kaboom")
        c = self._consumer(list(FAKE), boom)
        r = _run(c.poll_once())
        self.assertEqual(r["failed"], 2)
        self.assertEqual(len(self.client.dlq_sent), 2)

    def test_malformed_body_skipped(self):
        bad = [{"MessageId": "mX", "ReceiptHandle": "rhX", "Body": "{not json"}]
        async def ok(_msg):
            return True
        c = self._consumer(bad, ok)
        r = _run(c.poll_once())
        self.assertEqual(r["skipped"], 1)
        self.assertEqual(r["processed"], 0)

    def test_empty_queue(self):
        async def ok(_msg):
            return True
        c = self._consumer([], ok)
        r = _run(c.poll_once())
        self.assertEqual(r, {"status": "ok", "processed": 0, "failed": 0, "skipped": 0,
                             "messages_received": 0})

    def test_dispatch_receives_parsed_body(self):
        seen = {}
        async def capture(msg: SQSMessage):
            seen["body"] = msg.body
            return True
        c = self._consumer([FAKE[0]], capture)
        _run(c.poll_once())
        self.assertEqual(seen["body"]["application_id"], "APP-001")
        self.assertEqual(seen["body"]["event_type"], "loan_submitted")

    def test_no_dlq_failure_does_not_crash(self):
        async def fail(_msg):
            return False
        c = self._consumer(list(FAKE), fail, dlq="")  # no DLQ
        r = _run(c.poll_once())
        self.assertEqual(r["failed"], 2)
        self.assertEqual(self.client.dlq_sent, [])  # dropped + logged, no crash


class RunLoopTests(unittest.TestCase):
    def test_run_max_polls_stops(self):
        async def ok(_msg):
            return True
        client = FakeSQSClient(list(FAKE))
        c = SQSConsumer(queue_url=QUEUE, client=client, dispatch_fn=ok, dlq_url=DLQ)
        _run(c.run(max_polls=1))
        self.assertFalse(c._running)
        self.assertEqual(len(client.deleted), 2)  # processed the batch in one poll

    def test_run_noop_when_unconfigured(self):
        c = SQSConsumer(queue_url="", client=FakeSQSClient())
        _run(c.run(max_polls=3))  # returns immediately, no exception
        self.assertFalse(c._running)


if __name__ == "__main__":
    unittest.main()
