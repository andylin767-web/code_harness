import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from code_harness.core.agent import Agent


class AgentTests(unittest.TestCase):
    def test_agent_owns_identity_prompt_model_and_toolset(self):
        toolset = object()
        agent = Agent(
            name="Main agent",
            role="coding agent",
            assignment="Implement requested changes.",
            toolset=toolset,
            system_prompt="Base instructions.",
            model="test-model",
        )

        prompt = agent.build_system_prompt()

        self.assertIs(agent.toolset, toolset)
        self.assertIs(agent.tool_registry, toolset)
        self.assertEqual(agent.model, "test-model")
        self.assertIn("Agent name: Main agent", prompt)
        self.assertIn("Role: coding agent", prompt)
        self.assertIn("Assignment: Implement requested changes.", prompt)
        self.assertIn("Base instructions.", prompt)

    def test_agent_workspace_root_is_resolved_and_mutable(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            agent = Agent(
                name="worker",
                role="developer",
                assignment="work",
                toolset=object(),
                system_prompt="",
                model="test-model",
                workspace_root=root,
            )

            self.assertEqual(agent.workspace_root, root.resolve())
            self.assertIn(str(root.resolve()), agent.build_system_prompt())

    def test_agents_have_independent_workspace_roots(self):
        with TemporaryDirectory() as first, TemporaryDirectory() as second:
            first_agent = Agent(
                "first", "developer", "work", object(), "", "model"
            )
            second_agent = Agent(
                "second", "developer", "work", object(), "", "model"
            )

            first_agent.set_workspace_root(Path(first))
            second_agent.set_workspace_root(Path(second))

            self.assertNotEqual(
                first_agent.workspace_root,
                second_agent.workspace_root,
            )


if __name__ == "__main__":
    unittest.main()
