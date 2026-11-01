"""Structured execution event sink and Server-Sent Events (SSE) broadcaster."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections import defaultdict
from typing import AsyncGenerator

from netcoop_api.schemas import ExecutionEventModel

logger = logging.getLogger(__name__)


class ExecutionEventSink:
    """Thread-safe event sink that stores execution events per run_id and broadcasts them."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[str, list[ExecutionEventModel]] = defaultdict(list)
        self._subscribers: dict[str, list[asyncio.Queue[ExecutionEventModel | None]]] = defaultdict(list)
        self._closed_runs: dict[str, str] = {}
        self._main_loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._main_loop = loop

    def emit(self, event: ExecutionEventModel) -> None:
        """Stores an event and signals any active SSE subscribers for this run_id."""
        with self._lock:
            self._events[event.run_id].append(event)
            queues = list(self._subscribers.get(event.run_id, []))

        if not queues:
            return

        for q in queues:
            try:
                if self._main_loop and self._main_loop.is_running():
                    self._main_loop.call_soon_threadsafe(q.put_nowait, event)
                else:
                    q.put_nowait(event)
            except Exception as exc:
                logger.debug(f"Failed to deliver event to subscriber: {exc}")

    def close_run(self, run_id: str, status: str = "completed") -> None:
        """Notifies subscribers that the run stream has ended."""
        if status not in {"completed", "failed"}:
            status = "closed"
        with self._lock:
            self._closed_runs[run_id] = status
            queues = list(self._subscribers.get(run_id, []))

        for q in queues:
            try:
                if self._main_loop and self._main_loop.is_running():
                    self._main_loop.call_soon_threadsafe(q.put_nowait, None)
                else:
                    q.put_nowait(None)
            except Exception as exc:
                logger.debug(f"Failed to signal end of stream: {exc}")

    def get_events(self, run_id: str) -> list[ExecutionEventModel]:
        """Returns all recorded events for a given run_id."""
        with self._lock:
            return list(self._events.get(run_id, []))

    def restore_run(
        self,
        run_id: str,
        events: list[ExecutionEventModel],
        *,
        closed: bool,
        status: str = "completed",
    ) -> None:
        """Restore persisted event history for a completed or interrupted run."""
        if status not in {"completed", "failed"}:
            status = "closed"
        with self._lock:
            self._events[run_id] = list(events)
            if closed:
                self._closed_runs[run_id] = status

    async def subscribe(self, run_id: str) -> AsyncGenerator[str, None]:
        """Async generator yielding Server-Sent Events for a run_id."""
        queue: asyncio.Queue[ExecutionEventModel | None] = asyncio.Queue()

        # Snapshot and subscribe atomically so events emitted between the replay
        # snapshot and subscriber registration are not lost.
        with self._lock:
            past_events = list(self._events.get(run_id, []))
            terminal_status = self._closed_runs.get(run_id)
            if terminal_status is None:
                self._subscribers[run_id].append(queue)

        try:
            for evt in past_events:
                yield f"data: {evt.model_dump_json()}\n\n"

            if terminal_status is not None:
                payload = json.dumps({"status": terminal_status})
                yield f"event: done\ndata: {payload}\n\n"
                return

            while True:
                item = await queue.get()
                if item is None:
                    # Stream complete
                    with self._lock:
                        terminal_status = self._closed_runs.get(run_id, "closed")
                    payload = json.dumps({"status": terminal_status})
                    yield f"event: done\ndata: {payload}\n\n"
                    break
                yield f"data: {item.model_dump_json()}\n\n"
        finally:
            with self._lock:
                if queue in self._subscribers[run_id]:
                    self._subscribers[run_id].remove(queue)


# Global singleton event sink
event_sink = ExecutionEventSink()
