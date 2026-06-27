"""IN-A — SQS event-driven pipeline consumer.

Turns the on-demand-only pipeline into an event-driven one: an SQS message
("loan_submitted" / "document_arrived") triggers a pipeline run for the tenant.
Injectable boto3 client (the S3 / RA-P0-A pattern) so it is fully testable without
AWS and a graceful no-op when SQS_QUEUE_URL / AWS creds are unset.

DECISION-PATH-INERT: this is a TRIGGER only — it invokes the existing PersonaRunner;
the decision logic is unchanged. 16/16 by construction.

Message body shape:
  {"tenant_id": "...", "application_id": "...",
   "event_type": "loan_submitted" | "document_arrived"}
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class SQSMessage:
    message_id: str
    receipt_handle: str
    body: dict
    queue_url: str


class SQSConsumer:
    DEFAULT_QUEUE_ENV = "SQS_QUEUE_URL"
    DEFAULT_WAIT_SEC = 20      # SQS long-poll
    DEFAULT_MAX_MSG = 10
    DEFAULT_VISIBILITY = 30

    def __init__(self, queue_url: Optional[str] = None, client=None,
                 dispatch_fn: Optional[Callable] = None, dlq_url: Optional[str] = None):
        self._queue_url = queue_url or os.environ.get(self.DEFAULT_QUEUE_ENV, "")
        self._client = client  # injectable for tests
        self._dispatch = dispatch_fn or self._default_dispatch
        self._dlq_url = dlq_url or os.environ.get("SQS_DLQ_URL", "")
        self._running = False

    @property
    def _sqs(self):
        """Lazy boto3 client; None if boto3 unavailable. (boto3 builds a client even
        without creds — the queue_url gate in is_configured() is the real switch.)"""
        if self._client is not None:
            return self._client
        try:
            import boto3
            return boto3.client("sqs")
        except Exception:
            return None

    def is_configured(self) -> bool:
        return bool(self._queue_url) and self._sqs is not None

    async def _default_dispatch(self, msg: SQSMessage) -> bool:
        """Trigger the existing pipeline for the message's tenant. Returns True on
        success, False on failure (-> DLQ). NOTE: PersonaRunner.run_all_waves runs
        the tenant's wave batch (no per-application entry point today); the
        application_id is logged, per-app granularity is a future refinement."""
        tenant_id = msg.body.get("tenant_id", "")
        application_id = msg.body.get("application_id", "")
        event_type = msg.body.get("event_type", "loan_submitted")
        if not tenant_id or not application_id:
            logger.warning("[SQS] message missing tenant/application: %s", msg.body)
            return False
        logger.info("[SQS] %s -> %s/%s", event_type, tenant_id, application_id)
        try:
            from core.cron.runner import PersonaRunner
            runner = PersonaRunner(os.environ.get("DATABASE_URL", ""))
            await runner.run_all_waves(tenant_id=tenant_id)
            return True
        except Exception as e:  # noqa: BLE001
            logger.error("[SQS] dispatch failed %s/%s: %s", tenant_id, application_id, e)
            return False

    def _parse_message(self, raw: dict) -> Optional[SQSMessage]:
        try:
            body_str = raw.get("Body", "{}")
            body = json.loads(body_str) if isinstance(body_str, str) else (body_str or {})
            return SQSMessage(message_id=raw.get("MessageId", ""),
                              receipt_handle=raw.get("ReceiptHandle", ""),
                              body=body, queue_url=self._queue_url)
        except Exception as e:  # noqa: BLE001
            logger.warning("[SQS] failed to parse message: %s", e)
            return None

    def _delete_message(self, receipt_handle: str) -> None:
        sqs = self._sqs
        if not sqs or not self._queue_url:
            return
        try:
            sqs.delete_message(QueueUrl=self._queue_url, ReceiptHandle=receipt_handle)
        except Exception as e:  # noqa: BLE001
            logger.warning("[SQS] delete failed: %s", e)

    def _send_to_dlq(self, msg: SQSMessage, error: str = "") -> None:
        sqs = self._sqs
        if not sqs or not self._dlq_url:
            logger.warning("[SQS] no DLQ configured, dropping failed message: %s", msg.message_id)
            return
        try:
            sqs.send_message(QueueUrl=self._dlq_url, MessageBody=json.dumps(
                {"original": msg.body, "error": error, "message_id": msg.message_id}))
            logger.info("[SQS] sent to DLQ: %s", msg.message_id)
        except Exception as e:  # noqa: BLE001
            logger.error("[SQS] DLQ send failed: %s", e)

    async def poll_once(self) -> dict:
        """Poll the queue once. No-op (not_configured) when AWS/queue unset."""
        if not self.is_configured():
            return {"status": "not_configured", "processed": 0, "failed": 0, "skipped": 0,
                    "note": (f"SQS not configured — set {self.DEFAULT_QUEUE_ENV} + AWS "
                             "credentials to enable event-driven processing.")}
        sqs = self._sqs
        try:
            resp = sqs.receive_message(
                QueueUrl=self._queue_url, MaxNumberOfMessages=self.DEFAULT_MAX_MSG,
                WaitTimeSeconds=self.DEFAULT_WAIT_SEC, VisibilityTimeout=self.DEFAULT_VISIBILITY)
        except Exception as e:  # noqa: BLE001
            logger.error("[SQS] receive_message failed: %s", e)
            return {"status": "error", "error": str(e), "processed": 0, "failed": 0, "skipped": 0}

        messages = resp.get("Messages", []) or []
        processed = failed = skipped = 0
        for raw in messages:
            msg = self._parse_message(raw)
            if not msg:
                skipped += 1
                continue
            try:
                ok = await self._dispatch(msg)
            except Exception as e:  # noqa: BLE001
                logger.error("[SQS] unhandled error for %s: %s", msg.message_id, e)
                self._send_to_dlq(msg, str(e))
                failed += 1
                continue
            if ok:
                self._delete_message(msg.receipt_handle)
                processed += 1
            else:
                self._send_to_dlq(msg, "dispatch returned False")
                failed += 1
        return {"status": "ok", "processed": processed, "failed": failed,
                "skipped": skipped, "messages_received": len(messages)}

    async def run(self, max_polls: Optional[int] = None) -> None:
        """Continuous polling loop. max_polls=None runs forever; an int stops after N
        (for tests). No-op when unconfigured."""
        if not self.is_configured():
            logger.warning("[SQS] consumer not configured (%s unset) — no-op mode.",
                           self.DEFAULT_QUEUE_ENV)
            return
        self._running = True
        polls = 0
        logger.info("[SQS] consumer started, queue=%s", self._queue_url)
        while self._running:
            result = await self.poll_once()
            if result.get("processed") or result.get("failed"):
                logger.info("[SQS] poll result: %s", result)
            polls += 1
            if max_polls is not None and polls >= max_polls:
                break
        self._running = False
        logger.info("[SQS] consumer stopped.")

    def stop(self) -> None:
        self._running = False

    def status(self) -> dict:
        """Configuration status for the management endpoint (no secrets leaked)."""
        q = self._queue_url
        masked = (q[:24] + "…") if len(q) > 24 else q
        return {"configured": self.is_configured(), "queue_url": masked or None,
                "dlq_configured": bool(self._dlq_url), "running": self._running,
                "queue_env_var": self.DEFAULT_QUEUE_ENV}


__all__ = ["SQSConsumer", "SQSMessage"]
