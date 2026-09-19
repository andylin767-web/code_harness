import unittest

from code_harness.memory.context import ConversationStore, MessageRecord, MessageType


class MessageRecordFactoryTests(unittest.TestCase):
    def test_create_derives_role_from_message_type(self):
        record = MessageRecord.create(
            type=MessageType.USER,
            conversation_id="conversation-1",
            content="hello",
        )

        self.assertEqual(record.type, MessageType.USER)
        self.assertEqual(record.role, "user")
        self.assertTrue(record.id.startswith("user_"))
        self.assertEqual(record.to_llm_dict(), {"role": "user", "content": "hello"})

    def test_summary_uses_system_role(self):
        record = MessageRecord.summary(
            conversation_id="conversation-1",
            content="summary",
        )

        self.assertEqual(record.type, MessageType.SUMMARY)
        self.assertEqual(record.role, "system")
        self.assertEqual(record.to_llm_dict(), {"role": "system", "content": "summary"})

    def test_developer_uses_developer_role(self):
        record = MessageRecord.developer(
            conversation_id="conversation-1",
            content="follow app rules",
        )

        self.assertEqual(record.type, MessageType.DEVELOPER)
        self.assertEqual(record.role, "developer")

    def test_tool_includes_tool_call_id_in_llm_payload(self):
        record = MessageRecord.tool(
            conversation_id="conversation-1",
            tool_call_id="call-1",
            content="done",
        )

        self.assertEqual(record.type, MessageType.TOOL)
        self.assertEqual(record.role, "tool")
        self.assertEqual(record.metadata["tool_call_id"], "call-1")
        self.assertEqual(
            record.to_llm_dict(),
            {"tool_call_id": "call-1", "content": "done", "role": "tool"},
        )

    def test_trace_dict_includes_record_fields_and_llm_message(self):
        record = MessageRecord.user(
            conversation_id="conversation-1",
            content="hello",
            metadata={"source": "test"},
        )

        trace = record.to_trace_dict()

        self.assertEqual(trace["id"], record.id)
        self.assertEqual(trace["conversation_id"], "conversation-1")
        self.assertEqual(trace["type"], "user")
        self.assertEqual(trace["role"], "user")
        self.assertEqual(trace["content"], "hello")
        self.assertEqual(trace["metadata"], {"source": "test"})
        self.assertEqual(trace["estimated_tokens"], record.estimated_tokens)
        self.assertEqual(trace["llm_message"], {"role": "user", "content": "hello"})

    def test_conversation_store_get_records_since_filters_by_conversation(self):
        store = ConversationStore()
        store.append_record(
            MessageRecord.user(conversation_id="conversation-1", content="first")
        )
        start_index = len(store.records)
        expected = MessageRecord.user(
            conversation_id="conversation-1", content="second"
        )
        store.append_record(expected)
        store.append_record(
            MessageRecord.user(conversation_id="conversation-2", content="other")
        )

        self.assertEqual(
            store.get_records_since("conversation-1", start_index), [expected]
        )


if __name__ == "__main__":
    unittest.main()
