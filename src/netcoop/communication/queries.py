"""Peer query contracts for synchronous, bounded, read-only inter-tower interactions."""

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from netcoop.models.enums import QueryStatus, TowerId


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("Datetime must be timezone-aware (UTC required).")
    return dt.astimezone(timezone.utc)


class PeerQuery(BaseModel):
    """Synchronous read-only query directed to a specific tower's declared capability."""

    model_config = ConfigDict(extra="forbid")

    query_id: str
    incident_id: str
    requester: str
    recipient: str
    capability: str
    scope: list[str] = Field(..., description="Canonical entity IDs")
    time_window: tuple[datetime, datetime] | None = None
    constraints: dict[str, Any] = Field(default_factory=dict)
    expected_schema: str
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def validate_utc(cls, v: datetime) -> datetime:
        return _ensure_utc(v)

    @field_validator("time_window")
    @classmethod
    def validate_window_utc(
        cls, v: tuple[datetime, datetime] | None
    ) -> tuple[datetime, datetime] | None:
        if v is not None:
            return (_ensure_utc(v[0]), _ensure_utc(v[1]))
        return None


class PeerQueryResult(BaseModel):
    """Result of a synchronous peer query."""

    model_config = ConfigDict(extra="forbid")

    query_id: str
    status: QueryStatus
    result: dict[str, Any] | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    completed_at: datetime

    @field_validator("completed_at")
    @classmethod
    def validate_utc(cls, v: datetime) -> datetime:
        return _ensure_utc(v)


QueryHandler = Callable[[PeerQuery], PeerQueryResult]


class QueryRouter:
    """One-hop query router with capability validation, read-only checks, and persistence."""

    def __init__(
        self,
        registry: Any | None = None,
        repository: Any | None = None,
    ) -> None:
        self.registry = registry
        self.repo = repository
        # Map (tower_id, capability_id) -> QueryHandler
        self._handlers: dict[tuple[str, str], QueryHandler] = {}
        self._in_query: bool = False

    def register(self, tower_id: TowerId | str, capability_id: str, handler: QueryHandler) -> None:
        t_id = tower_id.value.lower() if isinstance(tower_id, TowerId) else tower_id.lower()
        self._handlers[(t_id, capability_id)] = handler

    def request(self, query: PeerQuery) -> PeerQueryResult:
        now = datetime.now(timezone.utc)

        # 1. Enforce one-hop restriction (no recursive peer queries)
        if self._in_query:
            return PeerQueryResult(
                query_id=query.query_id,
                status=QueryStatus.UNAUTHORIZED,
                result=None,
                warnings=["Recursive/nested peer query rejected. QueryRouter permits strictly one-hop queries."],
                completed_at=now,
            )

        # 2. Persist query if repository available
        if self.repo is not None:
            self.repo.insert_peer_query(query)

        # 3. Capability authorization & lookup
        recipient_id = query.recipient.lower()
        cap_id = query.capability

        # Verify capability exists in registry if available
        if self.registry is not None:
            cap = self.registry.get_capability(cap_id)
            target_tower = self.registry.get_tower_for_capability(cap_id)
            if cap is None or target_tower is None:
                res = PeerQueryResult(
                    query_id=query.query_id,
                    status=QueryStatus.UNSUPPORTED,
                    result=None,
                    warnings=[f"Capability '{cap_id}' not found in CapabilityRegistry."],
                    completed_at=now,
                )
                if self.repo is not None:
                    self.repo.update_peer_query_result(res)
                return res

            if target_tower.value.lower() != recipient_id:
                res = PeerQueryResult(
                    query_id=query.query_id,
                    status=QueryStatus.UNAUTHORIZED,
                    result=None,
                    warnings=[
                        f"Capability '{cap_id}' belongs to tower '{target_tower.value}', not recipient '{recipient_id}'."
                    ],
                    completed_at=now,
                )
                if self.repo is not None:
                    self.repo.update_peer_query_result(res)
                return res

            if not cap.read_only:
                res = PeerQueryResult(
                    query_id=query.query_id,
                    status=QueryStatus.UNAUTHORIZED,
                    result=None,
                    warnings=[
                        f"Capability '{cap_id}' is not read-only. Peer queries must be strictly read-only."
                    ],
                    completed_at=now,
                )
                if self.repo is not None:
                    self.repo.update_peer_query_result(res)
                return res

        handler = self._handlers.get((recipient_id, cap_id))
        if handler is None:
            res = PeerQueryResult(
                query_id=query.query_id,
                status=QueryStatus.UNSUPPORTED,
                result=None,
                warnings=[f"No handler registered for recipient '{recipient_id}' and capability '{cap_id}'."],
                completed_at=now,
            )
            if self.repo is not None:
                self.repo.update_peer_query_result(res)
            return res

        # 4. Dispatch with one-hop protection
        self._in_query = True
        try:
            res = handler(query)
        except Exception as exc:
            res = PeerQueryResult(
                query_id=query.query_id,
                status=QueryStatus.FAILED,
                result=None,
                warnings=[f"Handler execution error: {exc}"],
                completed_at=datetime.now(timezone.utc),
            )
        finally:
            self._in_query = False

        # 5. Persist result
        if self.repo is not None:
            self.repo.update_peer_query_result(res)

        return res
