import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from code_harness.tools.task_system import TaskManager
from code_harness.tools.tools import get_tools


class TaskSystemTests(unittest.TestCase):
    def test_task_tools_are_registered(self):
        lead_tools = {tool.name for tool in get_tools("parent").values()}
        teammate_tools = {tool.name for tool in get_tools("sub_agent").values()}

        self.assertIn("task_create", lead_tools)
        self.assertIn("task_get", lead_tools)

        teammate_only = {"list_tasks", "claim_task", "complete_task"}
        self.assertTrue(teammate_only.issubset(teammate_tools))
        self.assertTrue(teammate_only.isdisjoint(lead_tools))

        legacy_names = {"task_list", "task_claim", "task_complete"}
        self.assertTrue(legacy_names.isdisjoint(lead_tools))
        self.assertTrue(legacy_names.isdisjoint(teammate_tools))

    def test_create_claim_and_complete_task(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = TaskManager(Path(tmpdir))

            created = json.loads(
                manager.create_task("Build thing", "Use local patterns")
            )
            task_id = created["id"]

            self.assertEqual(created["status"], "pending")
            self.assertEqual(
                manager.claim_task(task_id, owner="agent-1"),
                "Claimed " + task_id + " (Build thing)",
            )
            claimed = json.loads(manager.get_task(task_id))
            self.assertEqual(claimed["status"], "in_progress")
            self.assertEqual(claimed["owner"], "agent-1")

            self.assertEqual(
                manager.complete_task(task_id, owner="agent-1"),
                "Completed " + task_id + " (Build thing)",
            )
            completed = json.loads(manager.get_task(task_id))
            self.assertEqual(completed["status"], "completed")

    def test_claim_respects_dependencies(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = TaskManager(Path(tmpdir))

            dependency = json.loads(manager.create_task("Dependency", ""))
            dependent = json.loads(
                manager.create_task("Dependent", "", blockedBy=[dependency["id"]])
            )

            self.assertIn("Blocked by", manager.claim_task(dependent["id"]))

            manager.complete_task(dependency["id"])
            self.assertIn(
                "Claimed", manager.claim_task(dependent["id"], owner="agent-1")
            )

    def test_concurrent_claims_allow_only_one_owner(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_dir = Path(tmpdir)
            save_started = threading.Event()
            release_save = threading.Event()

            class SlowTaskManager(TaskManager):
                def save_task(self, task):
                    if task.status == "in_progress":
                        save_started.set()
                        release_save.wait(timeout=2)
                    super().save_task(task)

            first_manager = SlowTaskManager(tasks_dir)
            second_manager = TaskManager(tasks_dir)
            created = json.loads(first_manager.create_task("Exclusive task", ""))

            with ThreadPoolExecutor(max_workers=2) as executor:
                first_claim = executor.submit(
                    first_manager.claim_task,
                    created["id"],
                    "agent-1",
                )
                self.assertTrue(save_started.wait(timeout=1))
                second_claim = executor.submit(
                    second_manager.claim_task,
                    created["id"],
                    "agent-2",
                )

                time.sleep(0.05)
                self.assertFalse(second_claim.done())
                release_save.set()
                results = [first_claim.result(), second_claim.result()]

            claimed_results = [
                result for result in results if result.startswith("Claimed ")
            ]
            self.assertEqual(len(claimed_results), 1)
            self.assertIn("in_progress, cannot claim", results[1])
            task = second_manager.load_task(created["id"])
            self.assertEqual(task.owner, "agent-1")
            self.assertTrue((tasks_dir / ".claim.lock").exists())

    def test_scan_unclaimed_tasks_returns_only_startable_tasks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = TaskManager(Path(tmpdir))
            ready = json.loads(manager.create_task("Ready", ""))
            dependency = json.loads(manager.create_task("Dependency", ""))
            manager.create_task(
                "Blocked",
                "",
                blockedBy=[dependency["id"]],
            )
            claimed = json.loads(manager.create_task("Claimed", ""))
            manager.claim_task(claimed["id"], owner="agent-1")

            tasks = manager.scan_unclaimed_tasks()

            self.assertEqual(
                {task.id for task in tasks},
                {ready["id"], dependency["id"]},
            )


if __name__ == "__main__":
    unittest.main()
