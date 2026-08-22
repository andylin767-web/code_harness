import queue
import threading
import time
import unittest
from unittest.mock import Mock

from code_harness.core.input_broker import InputBroker


class InputBrokerTests(unittest.TestCase):
    def setUp(self):
        self.lines = queue.Queue()
        self.output = []
        self.broker = InputBroker(
            input_fn=self.lines.get,
            output_fn=self.output.append,
        )
        self.broker.start()

    def tearDown(self):
        self.broker.stop()
        self.lines.put("")

    def _wait_for_output(self, expected: str) -> None:
        deadline = time.time() + 2
        while time.time() < deadline:
            if expected in self.output:
                return
            time.sleep(0.01)
        self.fail(f"Timed out waiting for output: {expected}")

    def test_pending_permission_receives_line_instead_of_user_queue(self):
        answers = []
        permission_thread = threading.Thread(
            target=lambda: answers.append(
                self.broker.request_permission("Allow write?"),
            )
        )
        permission_thread.start()
        self._wait_for_output("Allow write?")

        self.lines.put("yes")
        permission_thread.join(timeout=2)
        self.assertEqual(answers, ["yes"])

        self.lines.put("next user task")
        self.assertEqual(
            self.broker.get_user_input(),
            "next user task",
        )

    def test_concurrent_permission_requests_are_answered_fifo(self):
        answers = {}
        first = threading.Thread(
            target=lambda: answers.setdefault(
                "first",
                self.broker.request_permission("Allow first?"),
            )
        )
        second = threading.Thread(
            target=lambda: answers.setdefault(
                "second",
                self.broker.request_permission("Allow second?"),
            )
        )

        first.start()
        self._wait_for_output("Allow first?")
        second.start()
        self.lines.put("yes")
        self._wait_for_output("Allow second?")
        self.lines.put("no")
        first.join(timeout=2)
        second.join(timeout=2)

        self.assertEqual(answers, {"first": "yes", "second": "no"})

    def test_user_prompt_is_shown_when_consumer_is_ready_not_after_input(self):
        received = []
        first_consumer = threading.Thread(
            target=lambda: received.append(self.broker.get_user_input())
        )
        first_consumer.start()
        self._wait_for_output("[bold cyan]you: [/bold cyan]")

        self.lines.put("first task")
        first_consumer.join(timeout=2)
        self.assertEqual(received, ["first task"])
        self.assertEqual(
            self.output.count("[bold cyan]you: [/bold cyan]"),
            1,
        )

        second_consumer = threading.Thread(
            target=lambda: received.append(self.broker.get_user_input())
        )
        second_consumer.start()
        deadline = time.time() + 2
        while time.time() < deadline:
            if self.output.count("[bold cyan]you: [/bold cyan]") == 2:
                break
            time.sleep(0.01)

        self.assertEqual(
            self.output.count("[bold cyan]you: [/bold cyan]"),
            2,
        )
        self.lines.put("second task")
        second_consumer.join(timeout=2)
        self.assertEqual(received, ["first task", "second task"])

    def test_event_completion_can_refresh_an_interrupted_prompt(self):
        received = []
        consumer = threading.Thread(
            target=lambda: received.append(self.broker.get_user_input())
        )
        consumer.start()
        self._wait_for_output("[bold cyan]you: [/bold cyan]")

        self.broker.refresh_user_prompt()

        self.assertEqual(
            self.output.count("[bold cyan]you: [/bold cyan]"),
            2,
        )
        self.lines.put("next task")
        consumer.join(timeout=2)
        self.assertEqual(received, ["next task"])

    def test_permission_prompt_is_flushed_before_waiting_for_answer(self):
        lines = queue.Queue()
        output = []
        flush = Mock()
        broker = InputBroker(
            input_fn=lines.get,
            output_fn=output.append,
            flush_fn=flush,
        )
        broker.start()
        answers = []
        permission_thread = threading.Thread(
            target=lambda: answers.append(
                broker.request_permission("Allow subagent action?"),
            )
        )

        try:
            permission_thread.start()
            deadline = time.time() + 2
            while time.time() < deadline and not output:
                time.sleep(0.01)

            self.assertEqual(output, ["Allow subagent action?"])
            flush.assert_called_once_with()
            self.assertTrue(permission_thread.is_alive())

            lines.put("yes")
            permission_thread.join(timeout=2)
            self.assertEqual(answers, ["yes"])
        finally:
            broker.stop()
            lines.put("")


if __name__ == "__main__":
    unittest.main()
