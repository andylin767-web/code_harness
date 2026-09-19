import unittest

from code_harness.goals.context import GoalContextBuilder
from code_harness.memory.context import ConversationStore, MessageRecord


class GoalContextBuilderTests(unittest.TestCase):
    def test_includes_evidence_messages_and_latest_summary(self):
        store = ConversationStore()
        old_message = MessageRecord.user(
            conversation_id="conv_123",
            content="original requirement",
        )
        store.append_record(old_message)
        store.append_record(
            MessageRecord.system(
                conversation_id="conv_123",
                content="worker system prompt",
            )
        )
        store.append_record(
            MessageRecord.summary(
                conversation_id="conv_123",
                content="earlier work summary",
                metadata={"covers_through_message_id": old_message.id},
            )
        )
        store.append_record(
            MessageRecord.user(
                conversation_id="conv_123",
                content="new requirement",
            )
        )
        store.append_record(
            MessageRecord.assistant(
                conversation_id="conv_123",
                content="I will run the tests.",
            )
        )
        store.append_record(
            MessageRecord.tool(
                conversation_id="conv_123",
                tool_call_id="call_1",
                content="Exit code: 0",
            )
        )
        store.append_record(
            MessageRecord.developer(
                conversation_id="conv_123",
                content="internal run limit",
            )
        )
        store.append_record(
            MessageRecord.user(
                conversation_id="conv_123",
                content="<reminder>Update todos</reminder>",
            )
        )
        store.append_record(
            MessageRecord.user(
                conversation_id="conv_123",
                content=(
                    "<task_notification><status>completed</status></task_notification>"
                ),
            )
        )

        messages = GoalContextBuilder().build(store, "conv_123")
        rendered = str(messages)

        self.assertEqual(
            [message["role"] for message in messages],
            ["system", "user", "assistant", "tool", "user"],
        )
        self.assertIn("earlier work summary", rendered)
        self.assertIn("new requirement", rendered)
        self.assertIn("Exit code: 0", rendered)
        self.assertIn("task_notification", rendered)
        self.assertNotIn("worker system prompt", rendered)
        self.assertNotIn("internal run limit", rendered)
        self.assertNotIn("Update todos", rendered)

    def test_recent_evidence_takes_priority_over_summary(self):
        store = ConversationStore()
        covered = MessageRecord.user(
            conversation_id="conv_123",
            content="old",
        )
        store.append_record(covered)
        store.append_record(
            MessageRecord.summary(
                conversation_id="conv_123",
                content="s" * 400,
                metadata={"covers_through_message_id": covered.id},
            )
        )
        store.append_record(
            MessageRecord.tool(
                conversation_id="conv_123",
                tool_call_id="call_1",
                content="RECENT-EVIDENCE",
            )
        )

        messages = GoalContextBuilder(max_tokens=30).build(store, "conv_123")

        self.assertEqual(len(messages), 1)
        self.assertIn("RECENT-EVIDENCE", str(messages[0]))

    def test_oversized_newest_message_keeps_its_beginning_and_end(self):
        store = ConversationStore()
        store.append_record(
            MessageRecord.user(
                conversation_id="conv_123",
                content="BEGIN-EVIDENCE-" + ("x" * 2_000) + "-END-EVIDENCE",
            )
        )
        builder = GoalContextBuilder(max_tokens=100)

        messages = builder.build(store, "conv_123")

        self.assertEqual(len(messages), 1)
        message = messages[0]
        self.assertTrue(message["goal_context_truncated"])
        self.assertIn("BEGIN-EVIDENCE", message["content"])
        self.assertIn("END-EVIDENCE", message["content"])
        self.assertIn("truncated for goal evaluation", message["content"])
        self.assertLessEqual(
            builder.estimator.estimate_message(message),
            builder.max_tokens,
        )

    def test_message_within_budget_is_not_truncated(self):
        builder = GoalContextBuilder(max_tokens=100)
        message = {"role": "user", "content": "short message"}

        result = builder._truncate_oversized_message(message, max_tokens=100)

        self.assertEqual(result, message)
        self.assertIsNot(result, message)

    def test_truncation_rejects_budget_too_small_for_marker(self):
        builder = GoalContextBuilder(max_tokens=100)

        with self.assertRaisesRegex(ValueError, "too small"):
            builder._truncate_oversized_message(
                {"role": "user", "content": "x" * 1_000},
                max_tokens=1,
            )


if __name__ == "__main__":
    unittest.main()
