import unittest
from unittest.mock import Mock

from code_harness.core.agent_runtime import set_lead_agent
from code_harness.tools.spawn_teammate import (
    SpawnTeammateInput,
    SpawnTeammateTool,
)


class SpawnTeammateToolTests(unittest.TestCase):
    def tearDown(self):
        set_lead_agent(None)

    def test_tool_delegates_to_active_lead_agent(self):
        lead_agent = Mock()
        lead_agent.spawn_teammate_thread.return_value = (
            "Teammate 'researcher' spawned as researcher"
        )
        set_lead_agent(lead_agent)

        result = SpawnTeammateTool().run(
            SpawnTeammateInput(
                name="researcher",
                role="researcher",
                assignment="Inspect the authentication flow.",
                parent_conversation_id="conv_parent",
            )
        )

        self.assertEqual(
            result,
            "Teammate 'researcher' spawned as researcher",
        )
        lead_agent.spawn_teammate_thread.assert_called_once_with(
            name="researcher",
            role="researcher",
            assignment="Inspect the authentication flow.",
            parent_conversation_id="conv_parent",
        )


if __name__ == "__main__":
    unittest.main()
