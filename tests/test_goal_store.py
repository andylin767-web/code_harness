import json
import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from code_harness.goals.models import GoalLifecycle, GoalState
from code_harness.goals.store import GoalStore, GoalStoreError


class GoalStoreTests(unittest.TestCase):
    def test_save_and_load_active_goal_round_trip(self):
        with TemporaryDirectory() as tmpdir:
            store = GoalStore(tmpdir)
            created_at = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
            updated_at = datetime(2026, 9, 8, 12, 5, tzinfo=UTC)
            expected = GoalState(
                id="goal_123",
                conversation_id="conv_123",
                condition="pytest exits with code 0",
                created_at=created_at,
                updated_at=updated_at,
                evaluation_count=2,
                consecutive_blocks=1,
                latest_reason="Need a final test run.",
                tokens_at_start=150,
            )

            store.save(expected)
            actual = store.load_active("conv_123")

            self.assertEqual(actual, expected)
            payload = json.loads((Path(tmpdir) / "conv_123.json").read_text())
            self.assertEqual(payload["version"], 1)
            self.assertEqual(payload["lifecycle"], "active")

    def test_load_active_returns_none_when_file_is_missing(self):
        with TemporaryDirectory() as tmpdir:
            store = GoalStore(tmpdir)

            self.assertIsNone(store.load_active("conv_missing"))

    def test_load_active_ignores_terminal_goal(self):
        with TemporaryDirectory() as tmpdir:
            store = GoalStore(tmpdir)
            goal = GoalState(
                id="goal_123",
                conversation_id="conv_123",
                condition="pytest exits with code 0",
                lifecycle=GoalLifecycle.COMPLETED,
                completed_at=datetime.now(UTC),
            )

            store.save(goal)

            self.assertIsNone(store.load_active("conv_123"))

    def test_save_atomically_replaces_previous_state(self):
        with TemporaryDirectory() as tmpdir:
            store = GoalStore(tmpdir)
            goal = GoalState(
                id="goal_123",
                conversation_id="conv_123",
                condition="first condition",
            )
            store.save(goal)
            goal.condition = "updated condition"

            store.save(goal)

            self.assertEqual(
                store.load_active("conv_123").condition,
                "updated condition",
            )
            self.assertEqual(
                [path.name for path in Path(tmpdir).iterdir()],
                ["conv_123.json"],
            )

    def test_rejects_unsafe_conversation_id(self):
        with TemporaryDirectory() as tmpdir:
            store = GoalStore(tmpdir)
            goal = GoalState(
                id="goal_123",
                conversation_id="../outside",
                condition="condition",
            )

            with self.assertRaisesRegex(GoalStoreError, "conversation_id"):
                store.save(goal)
            with self.assertRaisesRegex(GoalStoreError, "conversation_id"):
                store.load_active("../outside")

    def test_corrupt_json_raises_store_error(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "conv_123.json"
            path.write_text("not-json", encoding="utf-8")

            with self.assertRaisesRegex(GoalStoreError, "Could not load"):
                GoalStore(tmpdir).load_active("conv_123")

    def test_mismatched_embedded_conversation_id_fails_closed(self):
        with TemporaryDirectory() as tmpdir:
            store = GoalStore(tmpdir)
            goal = GoalState(
                id="goal_123",
                conversation_id="conv_other",
                condition="condition",
            )
            payload = store._serialize(goal)
            (Path(tmpdir) / "conv_123.json").write_text(
                json.dumps(payload),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(GoalStoreError, "does not match"):
                store.load_active("conv_123")

    def test_unsupported_version_raises_store_error(self):
        with TemporaryDirectory() as tmpdir:
            store = GoalStore(tmpdir)
            goal = GoalState(
                id="goal_123",
                conversation_id="conv_123",
                condition="condition",
            )
            payload = store._serialize(goal)
            payload["version"] = 999
            (Path(tmpdir) / "conv_123.json").write_text(
                json.dumps(payload),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(GoalStoreError, "Unsupported"):
                store.load_active("conv_123")


if __name__ == "__main__":
    unittest.main()
