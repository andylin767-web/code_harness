import json
import queue
import threading
from concurrent.futures import Future
from dataclasses import asdict
from pathlib import Path
from typing import Any

from code_harness.events.models import AgentEvent, CronEvent, EventType


class EventQueue:
    """Thread-safe FIFO for every event that should enter the lead loop."""

    def __init__(self, path: Path):
        self._queue: queue.Queue[AgentEvent] = queue.Queue()
        # Only cron events are durable today, so retain the existing storage
        # path and file format for backward compatibility.
        self._event_path = path / ".cron_events.json"
        self._futures: dict[str, Future] = {}
        self._lock = threading.RLock()

    def put(self, event: AgentEvent) -> None:
        with self._lock:
            self._queue.put(event)
            if event.persistent:
                persisted = self._read_events_from_file()
                if not any(item.event_id == event.event_id for item in persisted):
                    persisted.append(event)
                    self._write_events_to_file(persisted)

    def submit(self, event: AgentEvent) -> Future:
        future: Future = Future()
        with self._lock:
            self._futures[event.event_id] = future
        self.put(event)
        return future

    def get_nowait(self) -> AgentEvent:
        return self._queue.get_nowait()

    def requeue(self, event: AgentEvent) -> None:
        """Retry an event without duplicating its durable record."""
        self._queue.put(event)

    def complete(self, event: AgentEvent, result: Any = None) -> None:
        with self._lock:
            if event.persistent:
                self.remove_pending(event.event_id)
            future = self._futures.pop(event.event_id, None)
        if future is not None and not future.done():
            future.set_result(result)

    def fail(self, event: AgentEvent, exc: BaseException) -> None:
        with self._lock:
            future = self._futures.pop(event.event_id, None)
        if future is not None and not future.done():
            future.set_exception(exc)

    def drain(self) -> list[AgentEvent]:
        events = []
        while True:
            try:
                events.append(self.get_nowait())
            except queue.Empty:
                return events

    def has_items(self) -> bool:
        return not self._queue.empty()

    def remove_pending(self, event_id: str) -> None:
        with self._lock:
            events = self._read_events_from_file()
            remaining = [event for event in events if event.event_id != event_id]
            self._write_events_to_file(remaining)

    def load_events(self) -> int:
        events = self._read_events_from_file()
        for event in events:
            self._queue.put(event)
        return len(events)

    def save_pending(self) -> None:
        """Compatibility method; only durable events are written."""
        with self._queue.mutex:
            events = [event for event in self._queue.queue if event.persistent]
        self._write_events_to_file(events)

    def _read_events_from_file(self) -> list[AgentEvent]:
        if not self._event_path.exists():
            return []

        try:
            raw_events = json.loads(self._event_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

        events: list[AgentEvent] = []
        for raw_event in raw_events:
            if not isinstance(raw_event, dict):
                continue
            try:
                if "prompt" in raw_event:
                    events.append(CronEvent(**raw_event))
                    continue
                if raw_event.get("event_type") == EventType.CRON:
                    events.append(
                        CronEvent(
                            event_id=raw_event["event_id"],
                            job_id=raw_event["source"],
                            prompt=raw_event["content"],
                            fired_at=raw_event["created_at"],
                        )
                    )
                    continue
                raw_event["event_type"] = EventType(raw_event["event_type"])
                events.append(AgentEvent(**raw_event))
            except (KeyError, TypeError, ValueError):
                continue
        return events

    def _write_events_to_file(self, events: list[AgentEvent]) -> None:
        self._event_path.parent.mkdir(parents=True, exist_ok=True)
        serialised = []
        for event in events:
            if isinstance(event, CronEvent):
                serialised.append(
                    {
                        "event_id": event.event_id,
                        "job_id": event.job_id,
                        "prompt": event.prompt,
                        "fired_at": event.fired_at,
                    }
                )
            else:
                payload = asdict(event)
                payload["event_type"] = event.event_type.value
                serialised.append(payload)
        self._event_path.write_text(
            json.dumps(serialised, indent=2),
            encoding="utf-8",
        )


# Retained as an API alias for callers migrating from the cron-only queue.
CronEventQueue = EventQueue
