from __future__ import annotations

from datetime import datetime
from typing import Any, Awaitable, Callable, Optional, Protocol
from uuid import UUID

from core.connectors import EventSink
from core.context_store import LendingContextStore
from core.context_store.base import Lineage
from core.normalizer.models import (
    ApplicationSubmittedEvent,
    BaseEvent,
    CreditPulledEvent,
    EventType,
    FraudSignalEvent,
    IncomeDeclaredEvent,
    KYCCompletedEvent,
    LeadReceivedEvent,
    PayrollReceivedEvent,
    PropertyAppraisedEvent,
)


# ─────────────────────────────────────────────────────────────────────
# EventLog — append-only buffer of canonical events.
#
# Production swap is Postgres / Kafka. The in-memory log is enough for
# the API surface to expose normalize → ingest → replay without standing
# up infrastructure, and it lets connectors hand events through the same
# sink as direct POST /events submissions.
# ─────────────────────────────────────────────────────────────────────


class EventLog:
    """In-memory append-only event log."""

    def __init__(self) -> None:
        self._events: list[BaseEvent] = []
        self._by_id: dict[UUID, BaseEvent] = {}

    async def append(self, event: BaseEvent) -> None:
        self._events.append(event)
        self._by_id[event.event_id] = event

    def all(self) -> list[BaseEvent]:
        return list(self._events)

    def by_id(self, event_id: UUID) -> Optional[BaseEvent]:
        return self._by_id.get(event_id)

    def __len__(self) -> int:
        return len(self._events)


# ─────────────────────────────────────────────────────────────────────
# EntityHydrator — translate canonical events into context_store writes.
#
# Events come in as RawEvent / NormalizedEvent pairs but the runtime
# downstream (ContextBuilder, decision agents, DAG executor) reads
# ontology entities (Applicant, Application, CreditProfile, ...) — not
# events. This module is the bridge: each event_type maps to one or
# more entity upserts under the SHARED scope (lineage.decision_id =
# None) so every decision sees the same world. See CONTEXT.md
# "Shared-vs-scoped writes in the context store".
#
# The hydrator never owns business logic — it copies fields and stamps
# lineage. Anything richer (e.g. computing income confidence from a
# payroll record) belongs in a decision agent's reason() call.
# ─────────────────────────────────────────────────────────────────────


class EntityHydrator:
    """Maps canonical events to shared-scope entity writes."""

    def __init__(
        self,
        store: LendingContextStore,
        *,
        applicant_id_resolver: Optional[
            Callable[[BaseEvent], Awaitable[Optional[str]] | Optional[str]]
        ] = None,
    ):
        self._store = store
        # Lets callers thread their own applicant_id resolution policy
        # in (look up by email, by application_id, by header). Default
        # is "use customer_id off the event".
        self._applicant_id_resolver = applicant_id_resolver

    async def hydrate(self, event: BaseEvent) -> list[str]:
        """Apply the event to the context store and return the entity
        keys that were written. No-op for event types the hydrator
        doesn't recognise — those are still in the EventLog and a
        domain-specific extension can pick them up."""

        et = event.event_type
        applicant_id = await self._resolve_applicant_id(event)

        if et == EventType.LEAD_RECEIVED:
            return await self._hydrate_lead(event, applicant_id)
        if et == EventType.APPLICATION_SUBMITTED:
            return await self._hydrate_application(event, applicant_id)
        if et == EventType.KYC_COMPLETED:
            return await self._hydrate_kyc(event, applicant_id)
        if et == EventType.INCOME_DECLARED:
            return await self._hydrate_income_declared(event, applicant_id)
        if et == EventType.PAYROLL_RECEIVED:
            return await self._hydrate_payroll(event, applicant_id)
        if et == EventType.CREDIT_PULLED:
            return await self._hydrate_credit(event, applicant_id)
        if et == EventType.FRAUD_SIGNAL:
            return await self._hydrate_fraud(event, applicant_id)
        if et == EventType.PROPERTY_APPRAISED:
            return await self._hydrate_property(event)
        return []

    # ── Resolution ───────────────────────────────────────────────────

    async def _resolve_applicant_id(self, event: BaseEvent) -> Optional[str]:
        if self._applicant_id_resolver is not None:
            value = self._applicant_id_resolver(event)
            if hasattr(value, "__await__"):
                value = await value  # type: ignore[assignment]
            return value  # type: ignore[return-value]
        return event.customer_id

    # ── Per-event hydrators ──────────────────────────────────────────

    async def _hydrate_lead(
        self, event: BaseEvent, applicant_id: Optional[str]
    ) -> list[str]:
        assert isinstance(event, LeadReceivedEvent)
        if applicant_id is None:
            return []
        value = {
            "applicant_id": applicant_id,
            "lead_source": event.lead_source,
            "channel": event.channel,
            "utm_params": event.utm_params,
            "session_behavior": event.session_behavior,
            "prior_inquiries": event.prior_inquiries,
            "first_seen_at": event.received_at.isoformat(),
            "last_seen_at": event.received_at.isoformat(),
        }
        await self._write_shared("Applicant", applicant_id, value, event)
        return [f"Applicant:{applicant_id}"]

    async def _hydrate_application(
        self, event: BaseEvent, applicant_id: Optional[str]
    ) -> list[str]:
        assert isinstance(event, ApplicationSubmittedEvent)
        if event.application_id is None:
            return []
        value = {
            "application_id": event.application_id,
            "applicant_id": applicant_id,
            "loan_purpose": event.loan_purpose,
            "requested_amount": event.requested_amount,
            "property_state": event.property_state,
            "submitted_at": event.received_at.isoformat(),
            "status": "intake",
        }
        await self._write_shared("Application", event.application_id, value, event)
        keys = [f"Application:{event.application_id}"]
        if applicant_id is not None:
            applicant_value = {
                "applicant_id": applicant_id,
                "last_seen_at": event.received_at.isoformat(),
            }
            await self._write_shared(
                "Applicant", applicant_id, applicant_value, event, merge=True
            )
            keys.append(f"Applicant:{applicant_id}")
        return keys

    async def _hydrate_kyc(
        self, event: BaseEvent, applicant_id: Optional[str]
    ) -> list[str]:
        assert isinstance(event, KYCCompletedEvent)
        if applicant_id is None:
            return []
        await self._write_shared(
            "Applicant",
            applicant_id,
            {
                "applicant_id": applicant_id,
                "kyc_status": event.kyc_status,
                "identity_match_confidence": event.identity_match_confidence,
                "ambiguous_identity": event.ambiguous_identity,
                "last_seen_at": event.received_at.isoformat(),
            },
            event,
            merge=True,
        )
        return [f"Applicant:{applicant_id}"]

    async def _hydrate_income_declared(
        self, event: BaseEvent, applicant_id: Optional[str]
    ) -> list[str]:
        assert isinstance(event, IncomeDeclaredEvent)
        if applicant_id is None:
            return []
        income_id = _income_profile_id(applicant_id, event.application_id)
        value = {
            "income_profile_id": income_id,
            "applicant_id": applicant_id,
            "application_id": event.application_id,
            "stated_income": event.stated_income,
            "employment_type": event.employment_type,
            "multiple_income_sources": event.multiple_income_sources,
            "foreign_income": event.foreign_income,
            "verified_at": event.received_at.isoformat(),
        }
        # Merge: an applicant's IncomeProfile collects both declarations
        # and verifications into a single record per (applicant,
        # application). Keeps `latest_object()` deterministic — there is
        # always exactly one income row per app.
        await self._write_shared("IncomeProfile", income_id, value, event, merge=True)
        return [f"IncomeProfile:{income_id}"]

    async def _hydrate_payroll(
        self, event: BaseEvent, applicant_id: Optional[str]
    ) -> list[str]:
        assert isinstance(event, PayrollReceivedEvent)
        if applicant_id is None:
            return []
        income_id = _income_profile_id(applicant_id, event.application_id)
        value = {
            "income_profile_id": income_id,
            "applicant_id": applicant_id,
            "application_id": event.application_id,
            "verified_income": event.gross_amount,
            "payroll_verified": event.verified,
            "income_confidence_score": 0.95 if event.verified else 0.6,
            "verified_at": event.received_at.isoformat(),
        }
        await self._write_shared("IncomeProfile", income_id, value, event, merge=True)

        # Append-only VerificationAttempt — preserves multi-provider data
        # that the IncomeProfile merge collapses (last-write-wins). Each
        # PayrollReceivedEvent carries a unique event_id; key off it so
        # two feeds land as two distinct rows.
        attempt_id = f"verify:{applicant_id}:{event.event_id}"
        attempt_value = {
            "verification_attempt_id": attempt_id,
            "applicant_id": applicant_id,
            "application_id": event.application_id,
            "source": "payroll_feed",
            "source_request_id": (
                str(event.request_id) if event.request_id is not None else None
            ),
            "source_correlation_id": (
                str(event.correlation_id)
                if event.correlation_id is not None
                else None
            ),
            "status": "succeeded" if event.verified else "partial",
            "employer_name_raw": event.employer,
            "gross_amount": event.gross_amount,
            "period_start": event.period_start.isoformat(),
            "period_end": event.period_end.isoformat(),
            "verified": event.verified,
            "received_at": event.received_at.isoformat(),
        }
        await self._write_shared(
            "VerificationAttempt", attempt_id, attempt_value, event
        )
        return [
            f"IncomeProfile:{income_id}",
            f"VerificationAttempt:{attempt_id}",
        ]

    async def _hydrate_credit(
        self, event: BaseEvent, applicant_id: Optional[str]
    ) -> list[str]:
        assert isinstance(event, CreditPulledEvent)
        if applicant_id is None:
            return []
        cp_id = f"credit:{applicant_id}:{event.bureau}:{event.event_id}"
        value = {
            "credit_profile_id": cp_id,
            "applicant_id": applicant_id,
            "bureau": event.bureau,
            "pulled_at": event.received_at.isoformat(),
            "credit_score": event.credit_score,
            "credit_band": _band_for_score(event.credit_score),
            "derogatory_marks": event.derogatory_marks,
            "open_tradelines": event.open_tradelines,
            "credit_utilization": event.credit_utilization,
            "payment_history": event.payment_history,
            "thin_file": event.thin_file,
            "active_bankruptcy": event.active_bankruptcy,
            "no_derogatory_last_24_months": event.derogatory_marks == 0,
        }
        await self._write_shared("CreditProfile", cp_id, value, event)
        return [f"CreditProfile:{cp_id}"]

    async def _hydrate_fraud(
        self, event: BaseEvent, applicant_id: Optional[str]
    ) -> list[str]:
        assert isinstance(event, FraudSignalEvent)
        if applicant_id is None:
            return []
        fp_id = f"fraud:{applicant_id}:{event.event_id}"
        value = {
            "fraud_profile_id": fp_id,
            "applicant_id": applicant_id,
            "generated_at": event.received_at.isoformat(),
            "fraud_score": event.fraud_score,
            "device_fingerprint": event.device_fingerprint,
            "ip_geolocation": event.ip_geolocation,
            "velocity_signals": [event.velocity_signal] if event.velocity_signal else [],
            "watchlist_match": event.watchlist_match,
            "synthetic_identity_flag": event.synthetic_identity_flag,
            "identity_match_confidence": 1.0 - (event.fraud_score or 0.0),
            "document_authenticity_score": 1.0,
        }
        await self._write_shared("FraudProfile", fp_id, value, event)
        return [f"FraudProfile:{fp_id}"]

    async def _hydrate_property(self, event: BaseEvent) -> list[str]:
        assert isinstance(event, PropertyAppraisedEvent)
        if event.application_id is None:
            return []
        prop_id = f"property:{event.application_id}"
        value = {
            "property_id": prop_id,
            "application_id": event.application_id,
            "address": event.address,
            "appraised_value": event.appraised_value,
            "purchase_price": event.purchase_price,
            "appraisal_disputed": event.appraisal_disputed,
        }
        await self._write_shared("Property", prop_id, value, event)
        return [f"Property:{prop_id}"]

    # ── Internal write ───────────────────────────────────────────────

    async def _write_shared(
        self,
        entity_type: str,
        entity_id: str,
        value: dict[str, Any],
        event: BaseEvent,
        *,
        merge: bool = False,
    ) -> None:
        """Write to the SHARED scope (lineage.decision_id=None) so every
        decision sees the same world. See CONTEXT.md section
        'Shared-vs-scoped writes in the context store'."""

        if merge:
            existing = await self._store.get(entity_type, entity_id, None)
            if existing is not None and isinstance(existing.value, dict):
                merged = dict(existing.value)
                for k, v in value.items():
                    if v is not None:
                        merged[k] = v
                value = merged

        lineage = Lineage(
            decision_id=None,
            agent="api.ingest.EntityHydrator",
            source_event_id=event.event_id,
            written_by="api.ingest.EntityHydrator",
            confidence=1.0,
            notes=f"event_type={event.event_type.value}",
        )
        await self._store.set(entity_type, entity_id, value, lineage)


def _income_profile_id(applicant_id: str, application_id: Optional[str]) -> str:
    return f"income:{applicant_id}:{application_id or 'unscoped'}"


def _band_for_score(score: Optional[int]) -> Optional[str]:
    if score is None:
        return None
    if score >= 760:
        return "super_prime"
    if score >= 700:
        return "prime"
    if score >= 660:
        return "near_prime"
    if score >= 600:
        return "subprime"
    return "deep_subprime"


# ─────────────────────────────────────────────────────────────────────
# Sink composition — one EventSink that drives both the log and the
# hydrator. Push connectors and POST /events both route through here.
# ─────────────────────────────────────────────────────────────────────


def build_event_sink(
    log: EventLog, hydrator: Optional[EntityHydrator] = None
) -> EventSink:
    """Compose the canonical sink: append to log, then hydrate entities."""

    async def _sink(event: BaseEvent) -> None:
        await log.append(event)
        if hydrator is not None:
            await hydrator.hydrate(event)

    return _sink


__all__ = [
    "EntityHydrator",
    "EventLog",
    "build_event_sink",
]
