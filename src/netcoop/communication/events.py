"""Event models and envelope for NetCoop AI publish/subscribe communication."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("Datetime must be timezone-aware (UTC required).")
    return dt.astimezone(timezone.utc)


class EventEnvelope(BaseModel):
    """CloudEvents-inspired typed event envelope for publish/subscribe event distribution."""

    model_config = ConfigDict(extra="forbid")

    specversion: Literal["1.0"] = "1.0"
    id: str = Field(..., description="Unique event identifier and idempotency key")
    source: str = Field(..., description="Producer identity e.g. netcoop/performance")
    type: str = Field(..., description="Semantic event type e.g. performance.congestion_candidate")
    subject: str | None = Field(default=None, description="Canonical entity ID when relevant")
    time: datetime = Field(..., description="Event creation timestamp in timezone-aware UTC")
    datacontenttype: Literal["application/json"] = "application/json"
    dataschema: str = Field(..., description="URI or schema identifier for the payload")
    correlationid: str = Field(..., description="Incident or investigation identifier")
    causationid: str | None = Field(default=None, description="Causal event or task ID")
    data: dict[str, Any] = Field(..., description="Compact payload containing references and metadata")

    @field_validator("time")
    @classmethod
    def validate_utc(cls, v: datetime) -> datetime:
        return _ensure_utc(v)


EventHandler = Callable[[EventEnvelope], None]


@dataclass
class DeliverySummary:
    event_id: str
    delivered_to: list[str] = field(default_factory=list)
    failed_deliveries: dict[str, str] = field(default_factory=dict)
    skipped_duplicate: list[str] = field(default_factory=list)


@dataclass
class DispatchSummary:
    events_processed: int = 0
    total_deliveries: int = 0
    failed_deliveries: int = 0


class EventBus:
    """In-process publish/subscribe EventBus with deterministic subscriber ordering and SQLite persistence."""

    def __init__(self, repository: Any | None = None) -> None:
        self.repo = repository
        # Map event_type -> dict[consumer_id, handler]
        self._subscribers: dict[str, dict[str, EventHandler]] = {}
        # In-memory delivery tracking if no repository is configured
        self._delivered_in_memory: set[tuple[str, str]] = set()

    def subscribe(self, event_type: str, consumer_id: str, handler: EventHandler) -> None:
        """Subscribes a consumer to an event type. Deterministic ordering enforced by sorted consumer IDs."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = {}
        self._subscribers[event_type][consumer_id] = handler

    def publish(self, event: EventEnvelope) -> DeliverySummary:
        """Persists the event before dispatch, then dispatches to subscribers with idempotency and failure isolation."""
        if self.repo is not None:
            self.repo.insert_event(event, dispatched=False)

        summary = self._dispatch_event(event)

        if self.repo is not None and not summary.failed_deliveries:
            self.repo.mark_event_dispatched(event.id)

        return summary

    def dispatch_pending(self, limit: int = 100) -> DispatchSummary:
        """Dispatches pending outbox events from the repository."""
        if self.repo is None:
            return DispatchSummary()

        pending = self.repo.get_pending_outbox_events(limit=limit)
        dispatch_sum = DispatchSummary(events_processed=len(pending))
        for event in pending:
            d_sum = self._dispatch_event(event)
            dispatch_sum.total_deliveries += len(d_sum.delivered_to)
            dispatch_sum.failed_deliveries += len(d_sum.failed_deliveries)
            if not d_sum.failed_deliveries:
                self.repo.mark_event_dispatched(event.id)
        return dispatch_sum

    def _dispatch_event(self, event: EventEnvelope) -> DeliverySummary:
        summary = DeliverySummary(event_id=event.id)
        consumers = self._subscribers.get(event.type, {})
        # Deterministic subscriber ordering: sorted by consumer_id
        for consumer_id in sorted(consumers.keys()):
            # Idempotency check: prevent duplicate deliveries
            if self.repo is not None:
                if self.repo.is_event_delivered(event.id, consumer_id):
                    summary.skipped_duplicate.append(consumer_id)
                    continue
            else:
                if (event.id, consumer_id) in self._delivered_in_memory:
                    summary.skipped_duplicate.append(consumer_id)
                    continue

            handler = consumers[consumer_id]
            try:
                handler(event)
                summary.delivered_to.append(consumer_id)
                if self.repo is not None:
                    self.repo.record_event_delivery(event.id, consumer_id, status="completed")
                else:
                    self._delivered_in_memory.add((event.id, consumer_id))
            except Exception as exc:
                err_msg = str(exc)
                summary.failed_deliveries[consumer_id] = err_msg
                if self.repo is not None:
                    self.repo.record_event_delivery(event.id, consumer_id, status="failed", error=err_msg)

        return summary
