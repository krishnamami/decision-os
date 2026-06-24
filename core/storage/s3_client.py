"""Async S3 client wrapper (RA-P0-A) with graceful no-credentials fallback.

When AWS credentials are NOT configured (local dev, CI, the meridian demo), every
operation is a safe no-op: put -> False, get -> None, exists -> False. The upload
flow and extraction pipeline therefore never depend on S3 — exactly the pattern
pdfplumber uses to stand in for Textract until AWS creds land.

NOTE on detection: ``boto3.client('s3')`` does NOT raise on missing credentials —
the failure only surfaces on the first API call (as NoCredentialsError, which is
a BotoCoreError, NOT a ClientError). So we detect availability up front via
``Session.get_credentials()`` and additionally swallow the credential/boto errors
on every call, so a misconfigured environment can never break the request.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class S3Client:
    def __init__(self) -> None:
        self._bucket = os.environ.get("S3_BUCKET", "accord-docs")
        self._client = None
        self._resolved = False  # have we tried to build a client yet?

    def _get_client(self):
        """Lazily build a boto3 S3 client, but only if credentials are actually
        available. Returns None when AWS is not configured — the local-dev path."""
        if self._resolved:
            return self._client
        self._resolved = True
        try:
            import boto3  # imported lazily so the module loads without boto3
            session = boto3.Session()
            if session.get_credentials() is None:
                logger.info("S3 not configured (no AWS credentials) — "
                            "storage operations are no-ops.")
                self._client = None
            else:
                self._client = session.client("s3")
        except Exception as exc:  # boto3 missing / config error -> degrade
            logger.info("S3 client unavailable (%s) — storage no-ops.", exc)
            self._client = None
        return self._client

    async def put(self, key: str, data: bytes,
                  content_type: str = "application/octet-stream") -> bool:
        """Store an object (server-side AES256). Returns True on success, False if
        S3 is not configured or the put fails. Never raises."""
        client = self._get_client()
        if not client:
            return False
        try:
            client.put_object(
                Bucket=self._bucket, Key=key, Body=data,
                ContentType=content_type, ServerSideEncryption="AES256",
            )
            return True
        except Exception as exc:
            logger.warning("S3 put failed for %s: %s", key, exc)
            return False

    async def get(self, key: str) -> Optional[bytes]:
        """Fetch an object's bytes, or None if absent / S3 not configured."""
        client = self._get_client()
        if not client:
            return None
        try:
            response = client.get_object(Bucket=self._bucket, Key=key)
            return response["Body"].read()
        except Exception as exc:
            logger.warning("S3 get failed for %s: %s", key, exc)
            return None

    async def exists(self, key: str) -> bool:
        """True if the object exists; False if absent / S3 not configured."""
        client = self._get_client()
        if not client:
            return False
        try:
            client.head_object(Bucket=self._bucket, Key=key)
            return True
        except Exception:
            return False


# Module-level singleton — import this, not the class.
s3 = S3Client()

__all__ = ["S3Client", "s3"]
