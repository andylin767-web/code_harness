import time
import unittest

from code_harness.team.protocol_state import (
    ProtocolState,
    ProtocolStatus,
    ProtocolType,
    generate_request_id,
)


class ProtocolStateTests(unittest.TestCase):
    def test_protocol_type_values(self):
        self.assertEqual(
            ProtocolType.SHUTDOWN_REQUEST,
            "shutdown_request",
        )
        self.assertEqual(
            ProtocolType.SHUTDOWN_RESPONSE,
            "shutdown_response",
        )
        self.assertEqual(
            ProtocolType.PLAN_APPROVAL_REQUEST,
            "plan_approval_request",
        )
        self.assertEqual(
            ProtocolType.PLAN_APPROVAL_RESPONSE,
            "plan_approval_response",
        )

    def test_protocol_state_accepts_protocol_type(self):
        state = ProtocolState(
            request_id="req_004281",
            type=ProtocolType.PLAN_APPROVAL_REQUEST,
            sender="reviewer",
            target="lead",
            status=ProtocolStatus.PENDING,
            payload="Review this plan",
            created_at=1.0,
        )

        self.assertIs(state.type, ProtocolType.PLAN_APPROVAL_REQUEST)
        self.assertIs(state.status, ProtocolStatus.PENDING)

    def test_protocol_status_values(self):
        self.assertEqual(ProtocolStatus.PENDING, "pending")
        self.assertEqual(ProtocolStatus.APPROVED, "approved")
        self.assertEqual(ProtocolStatus.REJECTED, "rejected")

    def test_created_at_defaults_to_millisecond_timestamp(self):
        before = round(time.time(), 3)
        state = ProtocolState(
            request_id="req_004282",
            type=ProtocolType.SHUTDOWN_REQUEST,
            sender="lead",
            target="reviewer",
            status=ProtocolStatus.PENDING,
            payload="Work complete",
        )
        after = round(time.time(), 3)

        self.assertGreaterEqual(state.created_at, before)
        self.assertLessEqual(state.created_at, after)
        self.assertEqual(state.created_at, round(state.created_at, 3))

    def test_request_id_generator_returns_unique_prefixed_ids(self):
        first = generate_request_id()
        second = generate_request_id()

        self.assertTrue(first.startswith("req_"))
        self.assertTrue(second.startswith("req_"))
        self.assertNotEqual(first, second)

    def test_request_id_defaults_to_generated_value(self):
        state = ProtocolState(
            type=ProtocolType.PLAN_APPROVAL_REQUEST,
            sender="reviewer",
            target="lead",
            payload="Approve this plan",
        )

        self.assertTrue(state.request_id.startswith("req_"))
        self.assertIs(state.status, ProtocolStatus.PENDING)


if __name__ == "__main__":
    unittest.main()
