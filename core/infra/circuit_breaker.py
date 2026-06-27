"""HA-C — circuit breaker for external calls (Claude API, S3, SQS).

A minimal, dependency-free circuit breaker that protects the platform from a failing
external dependency: after N failures in a rolling window the circuit OPENs and calls
short-circuit immediately (no waiting on a dead dependency); after a cooldown it goes
HALF_OPEN and lets ONE trial call through to test recovery.

States:
    CLOSED    — normal; calls pass through; failures are counted in a rolling window.
    OPEN      — tripped; calls are rejected immediately (raise CircuitOpenError) until
                the cooldown elapses.
    HALF_OPEN — one trial call is allowed; success -> CLOSED, failure -> OPEN again.

Defaults: 5 failures within 60s -> OPEN; 30s cooldown -> HALF_OPEN.

Pure Python, no external deps. The clock is INJECTABLE (``now_fn``) so tests are
deterministic — no sleeps, no wall-clock dependence. This module is decision-path-inert
(it wraps I/O at the edge); a persona never imports it -> 16/16 by construction.

RULE 11 posture: ``snapshot()`` returns the circuit state so every response that used a
guarded external call can carry ``circuit`` provenance (state + failure_count + the
degradation that was applied), exactly like ``data_source`` / ``missing_inputs``.
"""
from __future__ import annotations

import logging
import threading
import time as _time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

CLOSED = "CLOSED"
OPEN = "OPEN"
HALF_OPEN = "HALF_OPEN"

DEFAULT_FAILURE_THRESHOLD = 5      # failures within the window to trip OPEN
DEFAULT_WINDOW_SEC = 60.0          # rolling failure window
DEFAULT_COOLDOWN_SEC = 30.0       # OPEN -> HALF_OPEN cooldown


class CircuitOpenError(RuntimeError):
    """Raised when a call is attempted while the circuit is OPEN (caller should
    apply its graceful-degradation path rather than wait on a dead dependency)."""

    def __init__(self, name: str, retry_after_sec: float):
        self.name = name
        self.retry_after_sec = round(retry_after_sec, 1)
        super().__init__(
            f"circuit '{name}' is OPEN — retry in ~{self.retry_after_sec}s")


class CircuitBreaker:
    """One breaker per external dependency. Thread-safe (a simple lock — these calls
    are I/O-bound, not hot-path). Inject ``now_fn`` for deterministic tests."""

    def __init__(self, name: str,
                 failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
                 window_sec: float = DEFAULT_WINDOW_SEC,
                 cooldown_sec: float = DEFAULT_COOLDOWN_SEC,
                 now_fn: Optional[Callable[[], float]] = None):
        self.name = name
        self.failure_threshold = failure_threshold
        self.window_sec = window_sec
        self.cooldown_sec = cooldown_sec
        self._now = now_fn or _time.monotonic
        self._lock = threading.Lock()
        self._state = CLOSED
        self._failures: list[float] = []   # timestamps within the rolling window
        self._opened_at: Optional[float] = None

    # ── introspection ────────────────────────────────────────────────
    @property
    def state(self) -> str:
        """Current state, lazily transitioning OPEN -> HALF_OPEN once cooldown elapses."""
        with self._lock:
            self._maybe_half_open()
            return self._state

    def snapshot(self) -> dict:
        """RULE 11 provenance: the circuit state to embed in a guarded response."""
        with self._lock:
            self._maybe_half_open()
            return {
                "circuit": self.name,
                "state": self._state,
                "failure_count": len(self._failures),
                "failure_threshold": self.failure_threshold,
                "retry_after_sec": self._retry_after(),
            }

    # ── core ─────────────────────────────────────────────────────────
    def allow(self) -> bool:
        """True if a call may proceed (CLOSED or the single HALF_OPEN trial)."""
        with self._lock:
            self._maybe_half_open()
            return self._state in (CLOSED, HALF_OPEN)

    def record_success(self) -> None:
        with self._lock:
            self._failures.clear()
            if self._state != CLOSED:
                logger.info("[circuit:%s] recovered -> CLOSED", self.name)
            self._state = CLOSED
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            now = self._now()
            # A failure during the HALF_OPEN trial re-opens immediately.
            if self._state == HALF_OPEN:
                self._trip(now)
                return
            self._failures.append(now)
            self._prune(now)
            if len(self._failures) >= self.failure_threshold:
                self._trip(now)

    def call(self, fn: Callable, *args, **kwargs):
        """Run ``fn`` through the breaker. Raises CircuitOpenError without calling
        ``fn`` when OPEN. On exception: record failure + re-raise. On success: record."""
        if not self.allow():
            raise CircuitOpenError(self.name, self._retry_after())
        try:
            result = fn(*args, **kwargs)
        except Exception:
            self.record_failure()
            raise
        self.record_success()
        return result

    # ── internals (lock held by caller) ──────────────────────────────
    def _prune(self, now: float) -> None:
        cutoff = now - self.window_sec
        self._failures = [t for t in self._failures if t >= cutoff]

    def _trip(self, now: float) -> None:
        if self._state != OPEN:
            logger.warning("[circuit:%s] tripped OPEN after %d failures",
                           self.name, len(self._failures))
        self._state = OPEN
        self._opened_at = now

    def _maybe_half_open(self) -> None:
        if self._state == OPEN and self._opened_at is not None:
            if self._now() - self._opened_at >= self.cooldown_sec:
                self._state = HALF_OPEN
                logger.info("[circuit:%s] cooldown elapsed -> HALF_OPEN", self.name)

    def _retry_after(self) -> float:
        if self._state == OPEN and self._opened_at is not None:
            return max(0.0, round(self.cooldown_sec - (self._now() - self._opened_at), 1))
        return 0.0


# ── Shared breakers + documented degradation paths ───────────────────
# One breaker per external dependency. The degradation note is the contract the
# caller honors when the circuit is OPEN — every degraded path ALREADY works without
# the dependency (graceful no-AWS / rule-based extraction), so OPEN is safe.
_BREAKERS: dict[str, CircuitBreaker] = {}

DEGRADATION = {
    "claude_api": "fall back to the rule-based path (pdfplumber/regex extraction "
                  "already runs without Claude — RA-EX-F).",
    "s3_upload":  "queue locally / skip the put; extraction is unaffected "
                  "(s3_client already no-ops without AWS — RA-P0-A).",
    "sqs_send":   "process synchronously inline (the pipeline already runs without "
                  "SQS — IN-A).",
}


def get_breaker(name: str, **kwargs) -> CircuitBreaker:
    """Process-wide breaker for a named dependency (created on first use)."""
    bp = _BREAKERS.get(name)
    if bp is None:
        bp = CircuitBreaker(name, **kwargs)
        _BREAKERS[name] = bp
    return bp


def degradation_for(name: str) -> str:
    return DEGRADATION.get(name, "skip the optional external call; core path unaffected.")


__all__ = ["CircuitBreaker", "CircuitOpenError", "get_breaker", "degradation_for",
           "DEGRADATION", "CLOSED", "OPEN", "HALF_OPEN",
           "DEFAULT_FAILURE_THRESHOLD", "DEFAULT_WINDOW_SEC", "DEFAULT_COOLDOWN_SEC"]
