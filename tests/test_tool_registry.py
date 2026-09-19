import unittest

from code_harness.tools.read_file import ReadFile
from code_harness.tools.tools import ToolRegistry, get_tools


class ToolRegistryTests(unittest.TestCase):
    def test_duplicate_registration_is_rejected(self):
        registry = ToolRegistry([ReadFile()])

        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register(ReadFile())

    def test_register_many_is_atomic(self):
        existing = ReadFile()
        registry = ToolRegistry([existing])

        with self.assertRaisesRegex(ValueError, "Tool name collision"):
            registry.register_many([ReadFile()])

        self.assertIs(registry.get("read_file"), existing)

    def test_unregister_can_require_instance_ownership(self):
        tool = ReadFile()
        registry = ToolRegistry([tool])

        self.assertFalse(registry.unregister("read_file", tool=ReadFile()))
        self.assertTrue(registry.unregister("read_file", tool=tool))
        self.assertIsNone(registry.get("read_file"))

    def test_parent_tools_include_task(self):
        tool_names = {tool.name for tool in get_tools("parent").values()}

        self.assertIn("task", tool_names)
        self.assertIn("spawn_teammate", tool_names)
        self.assertIn("todo", tool_names)

    def test_sub_agent_tools_exclude_task(self):
        tool_names = {tool.name for tool in get_tools("sub_agent").values()}

        self.assertNotIn("task", tool_names)
        self.assertNotIn("spawn_teammate", tool_names)
        self.assertIn("read_file", tool_names)
        self.assertNotIn("summarize_python_files", tool_names)
        self.assertIn("llm_summarize_python_files", tool_names)
        self.assertTrue(
            {"list_tasks", "claim_task", "complete_task"}.issubset(tool_names)
        )

    def test_llm_summarizer_is_terminal(self):
        tool = get_tools("sub_agent").get("llm_summarize_python_files")

        self.assertIsNotNone(tool)
        self.assertTrue(tool.terminal_after_run)

    def test_protocol_tools_are_registered_for_correct_agent_types(self):
        parent_tools = {tool.name for tool in get_tools("parent").values()}
        teammate_tools = {tool.name for tool in get_tools("sub_agent").values()}

        lead_only = {"request_shutdown", "request_plan", "review_plan"}
        self.assertTrue(lead_only.issubset(parent_tools))
        self.assertTrue(lead_only.isdisjoint(teammate_tools))

        self.assertIn("submit_plan", teammate_tools)
        self.assertNotIn("submit_plan", parent_tools)

    def test_worktree_tools_are_available_only_to_team_lead(self):
        parent_tools = {tool.name for tool in get_tools("parent").values()}
        teammate_tools = {tool.name for tool in get_tools("sub_agent").values()}
        worktree_tools = {
            "create_worktree",
            "remove_worktree",
            "keep_worktree",
        }

        self.assertTrue(worktree_tools.issubset(parent_tools))
        self.assertTrue(worktree_tools.isdisjoint(teammate_tools))


if __name__ == "__main__":
    unittest.main()
