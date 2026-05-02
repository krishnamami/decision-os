from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Optional, Union

from pydantic import BaseModel, Field

from .base import ConnectorError, EventSink, PullConnector, PullRequest


# ─────────────────────────────────────────────────────────────────────
# RecordedResponse — one fixture row.
#
# Deterministic stand-in for an HTTP response body. The connector picks
# the response by matching ``key_fn(query)`` against ``key`` so each
# query produces a stable, replay-safe event. Closer to vcrpy / respx
# than a real network call, but with zero infrastructure.
# ─────────────────────────────────────────────────────────────────────


class RecordedResponse(BaseModel):
    """One recorded source response keyed by an arbitrary query key."""

    key: str
    payload: dict[str, Any] = Field(default_factory=dict)


KeyFn = Callable[[dict[str, Any]], str]


def _default_key(query: dict[str, Any]) -> str:
    if not query:
        return "*"
    if "key" in query:
        return str(query["key"])
    return json.dumps(query, sort_keys=True, default=str)


# ─────────────────────────────────────────────────────────────────────
# MockHTTPConnector — pull reference.
#
# Stands in for bureau / Plaid / AVM / TWN style request-response APIs.
# request_id + correlation_id are stamped onto the canonical event by
# the base PullConnector; this adapter's only job is to "look up" the
# right pre-recorded payload and return it.
# ─────────────────────────────────────────────────────────────────────


class MockHTTPConnector(PullConnector):
    """Recorded-fixture pull adapter.

    Construct with a list of RecordedResponse rows and an optional
    ``key_fn`` that extracts the lookup key from a query. The adapter
    returns the matching payload — use this in tests when you need
    'Experian returned this XML for X' to be deterministic across
    runs."""

    def __init__(
        self,
        source_system: str,
        sink: EventSink,
        responses: list[RecordedResponse],
        *,
        key_fn: KeyFn = _default_key,
        default_event_type: Optional[str] = None,
        **kw: Any,
    ):
        super().__init__(source_system, sink, **kw)
        self._responses: dict[str, RecordedResponse] = {
            r.key: r for r in responses
        }
        self._key_fn = key_fn
        self._default_event_type = default_event_type

    @classmethod
    def from_path(
        cls,
        source_system: str,
        sink: EventSink,
        path: Union[str, Path],
        **kw: Any,
    ) -> "MockHTTPConnector":
        p = Path(path)
        if not p.exists():
            raise ConnectorError(f"fixture file not found: {p}")
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ConnectorError(
                f"fixture file must be a list of {{key, payload}} entries, "
                f"got {type(data).__name__}"
            )
        responses = [RecordedResponse(**row) for row in data]
        return cls(source_system, sink, responses, **kw)

    # ── PullConnector contract ───────────────────────────────────────

    async def _perform(self, request: PullRequest) -> dict[str, Any]:
        key = self._key_fn(request.query)
        if key not in self._responses:
            raise ConnectorError(
                f"{self.source_system}: no recorded response for key={key!r} "
                f"(have {sorted(self._responses)})"
            )
        return dict(self._responses[key].payload)

    def parse_raw(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise ConnectorError(
                f"http response must be a dict, got {type(raw).__name__}"
            )
        canonical = dict(raw)
        if "event_type" not in canonical:
            if self._default_event_type is None:
                raise ConnectorError(
                    "recorded response missing event_type and no "
                    "default_event_type configured"
                )
            canonical["event_type"] = self._default_event_type
        return canonical
