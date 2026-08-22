import asyncio
import json
import queue
import threading
from collections.abc import Callable

from code_harness.core.input_runtime import get_input_broker
from code_harness.core.loop import Loop
from code_harness.events.models import EventType
from code_harness.events.queue import EventQueue
from code_harness.team.lead_inbox import consume_lead_inbox


class QueueProcessor:
    def __init__(
        self,
        *,
        event_queue: EventQueue,
        loop: Loop,
        conversation_store,
        conversation_id,
        run_lock,
        poll_interval: float = 2.0,
        lead_inbox_consumer: Callable[[], list[dict]] = consume_lead_inbox,
    ):
        self._event_queue = event_queue
        self._loop = loop
        self._conversation_store = conversation_store
        self._conversation_id = conversation_id
        self._run_lock = run_lock
        self._poll_interval = poll_interval
        self._consume_lead_inbox = lead_inbox_consumer
        self._stop_event = threading.Event()
        self._thread = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run_forever,
            daemon=True,
            name="queue-processor",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run_forever(self) -> None:
        while not self._stop_event.is_set():
            self._process_once()
            self._stop_event.wait(self._poll_interval)

    def _process_once(self) -> None:
        if not self._run_lock.acquire(blocking=False):
            return

        try:
            try:
                event = self._event_queue.get_nowait()
            except queue.Empty:
                return

            try:
                if event.event_type == EventType.QUIT:
                    self._event_queue.complete(event)
                    self._stop_event.set()
                    print(f"  \033[35m[event complete] {event.event_id}\033[0m")
                    return

                event_content = event.content
                if event.event_type == EventType.TEAMMATE_MESSAGE:
                    messages = self._consume_lead_inbox()
                    if not messages:
                        self._event_queue.complete(event)
                        self._refresh_user_prompt()
                        return
                    event_content = (
                        "<teammate_messages>\n"
                        f"{json.dumps(messages)}\n"
                        "</teammate_messages>"
                    )

                print(
                    f"  \033[35m[event process] {event.event_type} "
                    f"from {event.source} -> {event.content[:80]}\033[0m"
                )
                result = asyncio.run(
                    self._loop.run(
                        self._conversation_store,
                        self._conversation_id,
                        event_content,
                    )
                )
                self._event_queue.complete(event, result)
                print(f"  \033[35m[event complete] {event.event_id}\033[0m")
                self._refresh_user_prompt()
            except Exception as exc:
                self._event_queue.fail(event, exc)
                if event.persistent:
                    self._event_queue.requeue(event)
                    print(
                        f"  \033[31m[event failed] {event.event_id}; "
                        "requeued for retry\033[0m"
                    )
                else:
                    print(f"  \033[31m[event failed] {event.event_id}\033[0m")
                self._refresh_user_prompt()
        finally:
            self._run_lock.release()

    @staticmethod
    def _refresh_user_prompt() -> None:
        input_broker = get_input_broker()
        if input_broker is not None:
            input_broker.refresh_user_prompt()
