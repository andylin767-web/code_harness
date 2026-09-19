import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

from code_harness.core.background_task import BackgroundTaskRunner
from code_harness.core.input_runtime import set_input_broker
from code_harness.events.models import EventType, new_event
from code_harness.events.processor import QueueProcessor
from code_harness.events.queue import EventQueue
from code_harness.events.runtime import set_event_queue
from code_harness.memory.context import ConversationStore, MessageRecord
from code_harness.team.message_bus import MessageBus


class FakeLoop:
    def __init__(self):
        self.messages = []

    async def run(self, conversation_store, conversation_id, message, **kwargs):
        self.messages.append(message)
        return f"handled: {message}"


class EventQueueTests(unittest.TestCase):
    def tearDown(self):
        set_event_queue(None)
        set_input_broker(None)

    def test_processor_passes_only_one_fifo_event_per_call_to_loop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            event_queue = EventQueue(Path(tmpdir))
            loop = FakeLoop()
            processor = QueueProcessor(
                event_queue=event_queue,
                loop=loop,
                conversation_store=object(),
                conversation_id="conversation-1",
                run_lock=threading.Lock(),
            )
            first = new_event(
                EventType.USER,
                "first",
                source="terminal",
                created_at="2026-07-26T12:00:00Z",
            )
            second = new_event(
                EventType.CRON,
                "second",
                source="cron-1",
                created_at="2026-07-26T12:01:00Z",
            )
            event_queue.put(first)
            event_queue.put(second)

            processor._process_once()

            self.assertEqual(loop.messages, ["first"])
            self.assertTrue(event_queue.has_items())

            processor._process_once()
            self.assertEqual(loop.messages, ["first", "second"])
            self.assertFalse(event_queue.has_items())

    def test_submit_future_completes_with_loop_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            event_queue = EventQueue(Path(tmpdir))
            loop = FakeLoop()
            processor = QueueProcessor(
                event_queue=event_queue,
                loop=loop,
                conversation_store=object(),
                conversation_id="conversation-1",
                run_lock=threading.Lock(),
            )
            event = new_event(
                EventType.USER,
                "hello",
                source="terminal",
                created_at="2026-07-26T12:00:00Z",
            )

            future = event_queue.submit(event)
            processor._process_once()

            self.assertEqual(future.result(timeout=0), "handled: hello")

    def test_processor_saves_trace_for_background_event(self):
        class RecordingLoop:
            async def run(
                self,
                conversation_store,
                conversation_id,
                message,
                **kwargs,
            ):
                conversation_store.append_record(
                    MessageRecord.user(
                        conversation_id=conversation_id,
                        content=message,
                    )
                )
                return "handled"

        with tempfile.TemporaryDirectory() as tmpdir:
            event_queue = EventQueue(Path(tmpdir))
            trace_saver = Mock(return_value=Path(tmpdir) / "trace.json")
            store = ConversationStore()
            processor = QueueProcessor(
                event_queue=event_queue,
                loop=RecordingLoop(),
                conversation_store=store,
                conversation_id="conversation-1",
                run_lock=threading.Lock(),
                trace_saver=trace_saver,
            )
            event_queue.put(
                new_event(
                    EventType.BACKGROUND_TASK,
                    "<task_notification>done</task_notification>",
                    source="background-task",
                    created_at="2026-09-11T12:00:00Z",
                    metadata={"run_id": "run-background"},
                )
            )

            processor._process_once()

            trace_saver.assert_called_once()
            arguments = trace_saver.call_args.kwargs
            self.assertEqual(arguments["run_id"], "run-background")
            self.assertEqual(arguments["trace_type"], "event_background_task")
            self.assertEqual(len(arguments["messages"]), 1)

    def test_processor_refreshes_waiting_user_prompt_after_event(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            event_queue = EventQueue(Path(tmpdir))
            input_broker = Mock()
            set_input_broker(input_broker)
            processor = QueueProcessor(
                event_queue=event_queue,
                loop=FakeLoop(),
                conversation_store=object(),
                conversation_id="conversation-1",
                run_lock=threading.Lock(),
            )
            event_queue.put(
                new_event(
                    EventType.TEAMMATE_MESSAGE,
                    "work finished",
                    source="reviewer",
                    created_at="2026-07-27T12:00:00Z",
                )
            )

            processor._process_once()

            input_broker.refresh_user_prompt.assert_called_once_with()

    def test_quit_event_stops_processor_without_calling_loop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            event_queue = EventQueue(Path(tmpdir))
            loop = FakeLoop()
            processor = QueueProcessor(
                event_queue=event_queue,
                loop=loop,
                conversation_store=object(),
                conversation_id="conversation-1",
                run_lock=threading.Lock(),
            )
            event = new_event(
                EventType.QUIT,
                "quit",
                source="terminal",
                created_at="2026-07-26T12:00:00Z",
            )

            future = event_queue.submit(event)
            processor._process_once()

            self.assertIsNone(future.result(timeout=0))
            self.assertEqual(loop.messages, [])
            self.assertTrue(processor._stop_event.is_set())

    def test_background_completion_is_enqueued(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            event_queue = EventQueue(Path(tmpdir))
            runner = BackgroundTaskRunner(
                lambda block: "finished",
                on_complete=lambda notification: event_queue.put(
                    new_event(
                        EventType.BACKGROUND_TASK,
                        notification,
                        source="background-task",
                        created_at="2026-07-26T12:00:00Z",
                    )
                ),
            )

            runner.start(type("Block", (), {"id": "call-1", "input": {}})())
            deadline = time.time() + 2
            while not event_queue.has_items() and time.time() < deadline:
                time.sleep(0.01)

            event = event_queue.get_nowait()
            self.assertEqual(event.event_type, EventType.BACKGROUND_TASK)
            self.assertIn("<status>completed</status>", event.content)

    def test_lead_teammate_message_is_persisted_and_enqueued(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mailbox_dir = Path(tmpdir) / "mailboxes"
            mailbox_dir.mkdir()
            event_queue = EventQueue(Path(tmpdir))
            set_event_queue(event_queue)
            bus = MessageBus(mailbox_dir)

            bus.send("reviewer", "lead", "Review complete", msg_type="result")

            event = event_queue.get_nowait()
            self.assertEqual(event.event_type, EventType.TEAMMATE_MESSAGE)
            self.assertEqual(event.source, "reviewer")
            self.assertIn("Review complete", event.content)
            self.assertTrue((mailbox_dir / "lead.jsonl").exists())

    def test_processor_consumes_lead_inbox_for_teammate_event(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            event_queue = EventQueue(Path(tmpdir))
            loop = FakeLoop()
            messages = [
                {
                    "from": "reviewer",
                    "to": "lead",
                    "content": "Review complete",
                    "type": "result",
                    "metadata": {},
                }
            ]
            consume = Mock(return_value=messages)
            processor = QueueProcessor(
                event_queue=event_queue,
                loop=loop,
                conversation_store=object(),
                conversation_id="conversation-1",
                run_lock=threading.Lock(),
                lead_inbox_consumer=consume,
            )
            event_queue.put(
                new_event(
                    EventType.TEAMMATE_MESSAGE,
                    "lead inbox updated",
                    source="reviewer",
                    created_at="2026-08-05T12:00:00Z",
                )
            )

            processor._process_once()

            consume.assert_called_once_with()
            self.assertIn("<teammate_messages>", loop.messages[0])
            self.assertIn("Review complete", loop.messages[0])


if __name__ == "__main__":
    unittest.main()
