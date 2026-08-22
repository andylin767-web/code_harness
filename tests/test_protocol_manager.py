import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from code_harness.team.protocol_manager import ProtocolManager
from code_harness.team.protocol_state import ProtocolStatus, ProtocolType


class ProtocolManagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "requests.json"
        self.manager = ProtocolManager(
            self.path,
            request_ttl_seconds=60,
        )

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _create_request(
        self,
        *,
        request_id: str | None = None,
        created_at: float | None = None,
    ):
        return self.manager.create_request(
            type=ProtocolType.PLAN_APPROVAL_REQUEST,
            sender="reviewer",
            target="lead",
            payload="Approve the implementation plan",
            request_id=request_id,
            created_at=created_at,
        )

    def test_create_and_get_pending_request(self):
        state = self._create_request()

        self.assertTrue(state.request_id.startswith("req_"))
        self.assertIs(state.status, ProtocolStatus.PENDING)
        self.assertIs(self.manager.get_request(state.request_id), state)

    def test_duplicate_request_id_is_rejected(self):
        self._create_request(request_id="req_duplicate")

        with self.assertRaisesRegex(ValueError, "already exists"):
            self._create_request(request_id="req_duplicate")

    def test_create_request_rejects_response_protocol_type(self):
        with self.assertRaisesRegex(ValueError, "response type"):
            self.manager.create_request(
                type=ProtocolType.SHUTDOWN_RESPONSE,
                sender="reviewer",
                target="lead",
                payload="Response payload",
            )

    def test_approve_and_complete_request(self):
        state = self._create_request()

        approved = self.manager.approve(state.request_id)
        completed = self.manager.complete(state.request_id)

        self.assertIs(approved.status, ProtocolStatus.APPROVED)
        self.assertIs(completed, state)
        self.assertIsNone(self.manager.get_request(state.request_id))

    def test_reject_and_complete_request(self):
        state = self._create_request()

        self.manager.reject(state.request_id)
        completed = self.manager.complete(state.request_id)

        self.assertIs(completed.status, ProtocolStatus.REJECTED)
        self.assertIsNone(self.manager.get_request(state.request_id))

    def test_process_response_approves_matching_shutdown_request(self):
        state = self.manager.create_request(
            type=ProtocolType.SHUTDOWN_REQUEST,
            sender="lead",
            target="reviewer",
            payload="Work is complete",
        )

        resolved = self.manager.process_response(
            ProtocolType.SHUTDOWN_RESPONSE,
            state.request_id,
            approve=True,
        )

        self.assertIs(resolved, state)
        self.assertIs(state.status, ProtocolStatus.APPROVED)

    def test_process_response_rejects_matching_plan_request(self):
        state = self._create_request()

        resolved = self.manager.process_response(
            "plan_approval_response",
            state.request_id,
            approve=False,
        )

        self.assertIs(resolved, state)
        self.assertIs(state.status, ProtocolStatus.REJECTED)

    def test_process_response_ignores_type_mismatch(self):
        state = self._create_request()
        output = StringIO()

        with redirect_stdout(output):
            resolved = self.manager.process_response(
                ProtocolType.SHUTDOWN_RESPONSE,
                state.request_id,
                approve=True,
            )

        self.assertIsNone(resolved)
        self.assertIs(state.status, ProtocolStatus.PENDING)
        self.assertIn(
            "expected plan_approval_response, got shutdown_response",
            output.getvalue(),
        )

    def test_process_response_ignores_unknown_and_duplicate_responses(self):
        output = StringIO()
        with redirect_stdout(output):
            missing = self.manager.process_response(
                ProtocolType.SHUTDOWN_RESPONSE,
                "req_missing",
                approve=True,
            )

        state = self._create_request()
        self.manager.approve(state.request_id)
        with redirect_stdout(output):
            duplicate = self.manager.process_response(
                ProtocolType.PLAN_APPROVAL_RESPONSE,
                state.request_id,
                approve=True,
            )

        self.assertIsNone(missing)
        self.assertIsNone(duplicate)
        self.assertIn("unknown request_id: req_missing", output.getvalue())
        self.assertIn("already approved", output.getvalue())

    def test_concurrent_responses_only_transition_once(self):
        state = self._create_request()
        barrier = threading.Barrier(3)

        def respond(approve):
            barrier.wait()
            return self.manager.process_response(
                ProtocolType.PLAN_APPROVAL_RESPONSE,
                state.request_id,
                approve=approve,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = [
                executor.submit(respond, True),
                executor.submit(respond, False),
            ]
            barrier.wait()
            results = [response.result() for response in responses]

        self.assertEqual(results.count(state), 1)
        self.assertEqual(results.count(None), 1)
        self.assertIn(
            state.status,
            {ProtocolStatus.APPROVED, ProtocolStatus.REJECTED},
        )

    def test_cancel_only_accepts_pending_request(self):
        pending = self._create_request(request_id="req_pending")
        approved = self._create_request(request_id="req_approved")
        self.manager.approve(approved.request_id)

        self.assertIs(self.manager.cancel(pending.request_id), pending)
        with self.assertRaisesRegex(ValueError, "Cannot cancel"):
            self.manager.cancel(approved.request_id)

    def test_complete_rejects_pending_request(self):
        state = self._create_request()

        with self.assertRaisesRegex(ValueError, "Cannot complete"):
            self.manager.complete(state.request_id)

    def test_remove_and_missing_request_behavior(self):
        state = self._create_request()

        self.assertIs(self.manager.remove(state.request_id), state)
        self.assertIsNone(self.manager.get_request(state.request_id))
        with self.assertRaisesRegex(KeyError, "not found"):
            self.manager.remove(state.request_id)

    def test_expire_requests_uses_configured_ttl(self):
        expired = self._create_request(
            request_id="req_expired",
            created_at=100.0,
        )
        active = self._create_request(
            request_id="req_active",
            created_at=151.0,
        )

        removed = self.manager.expire_requests(now=160.0)

        self.assertEqual(removed, [expired])
        self.assertIsNone(self.manager.get_request(expired.request_id))
        self.assertIs(self.manager.get_request(active.request_id), active)

    def test_save_and_load_preserve_requests_and_enums(self):
        pending = self._create_request(request_id="req_pending")
        approved = self._create_request(request_id="req_approved")
        self.manager.approve(approved.request_id)

        saved_path = self.manager.save()
        restored = ProtocolManager(saved_path)
        loaded_count = restored.load()

        self.assertEqual(loaded_count, 2)
        self.assertEqual(
            restored.get_request(pending.request_id),
            pending,
        )
        self.assertEqual(
            restored.get_request(approved.request_id),
            approved,
        )
        self.assertIs(
            restored.get_request(approved.request_id).status,
            ProtocolStatus.APPROVED,
        )

    def test_load_ignores_invalid_entries(self):
        self.path.write_text(
            '[{"request_id": "invalid"}, "not-an-object"]',
            encoding="utf-8",
        )

        self.assertEqual(self.manager.load(), 0)
        self.assertEqual(self.manager.pending_requests, {})


if __name__ == "__main__":
    unittest.main()
