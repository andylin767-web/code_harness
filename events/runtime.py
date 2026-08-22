from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from code_harness.events.queue import EventQueue


_event_queue: "EventQueue | None" = None


def set_event_queue(event_queue: "EventQueue | None") -> None:
    global _event_queue
    _event_queue = event_queue


def get_event_queue() -> "EventQueue | None":
    return _event_queue
