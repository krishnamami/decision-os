from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path
from typing import Any, AsyncIterator, Iterable, Optional, Union

from .base import ConnectorError, EventSink, PushConnector


# ─────────────────────────────────────────────────────────────────────
# MockCSVConnector — push reference.
#
# Stands in for inbound file drops (borrower portal exports, partner
# CSVs, S3 / SFTP batches). Reads a CSV where each row maps to one
# canonical event payload. Column names map 1:1 to BaseEvent fields,
# with two conveniences:
#   - cells starting with '{' or '[' are JSON-decoded
#   - "true" / "false" cells coerce to bool
#   - empty cells become None (not "")
#
# event_type is required per row.
# ─────────────────────────────────────────────────────────────────────


class MockCSVConnector(PushConnector):
    """File-drop / CSV push adapter.

    Either point at a CSV file via ``from_path()`` or hand it an iterable
    of dict rows for tests. Designed so the same adapter exercises both
    seed_events fixtures and real partner drops."""

    def __init__(
        self,
        source_system: str,
        sink: EventSink,
        rows: Iterable[dict[str, Any]],
        **kw: Any,
    ):
        super().__init__(source_system, sink, **kw)
        self._rows = list(rows)

    @classmethod
    def from_path(
        cls,
        source_system: str,
        sink: EventSink,
        path: Union[str, Path],
        **kw: Any,
    ) -> "MockCSVConnector":
        p = Path(path)
        if not p.exists():
            raise ConnectorError(f"csv file not found: {p}")
        with p.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            rows = [cls._coerce_row(r) for r in reader]
        return cls(source_system, sink, rows, **kw)

    @classmethod
    def from_text(
        cls,
        source_system: str,
        sink: EventSink,
        text: str,
        **kw: Any,
    ) -> "MockCSVConnector":
        reader = csv.DictReader(StringIO(text))
        rows = [cls._coerce_row(r) for r in reader]
        return cls(source_system, sink, rows, **kw)

    # ── PushConnector contract ───────────────────────────────────────

    async def stream(self) -> AsyncIterator[dict[str, Any]]:
        for row in self._rows:
            yield row

    def parse_raw(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise ConnectorError(
                f"csv row must be a dict, got {type(raw).__name__}"
            )
        if "event_type" not in raw:
            raise ConnectorError("csv row is missing event_type")
        return dict(raw)

    # ── Coercion ─────────────────────────────────────────────────────

    @staticmethod
    def _coerce_row(row: dict[str, Optional[str]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, val in row.items():
            if key is None:
                continue
            out[key] = MockCSVConnector._coerce_cell(val)
        return out

    @staticmethod
    def _coerce_cell(val: Any) -> Any:
        if val is None:
            return None
        if not isinstance(val, str):
            return val
        s = val.strip()
        if s == "":
            return None
        if s == "true":
            return True
        if s == "false":
            return False
        if (s.startswith("{") and s.endswith("}")) or (
            s.startswith("[") and s.endswith("]")
        ):
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                return s
        return s
