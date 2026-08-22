import unittest
from unittest.mock import Mock

from code_harness.team.protocol_manager import ProtocolManager
from code_harness.team.send import Sender
from code_harness.tools.team import RequestShutDownTool


class RequestShutDownToolTests(unittest.TestCase):
    def test_creates_default_protocol_manager(self):
        tool = RequestShutDownTool(sender=Mock(spec=Sender))

        self.assertIsInstance(tool.protocol_manager, ProtocolManager)

    def test_accepts_injected_protocol_manager(self):
        manager = ProtocolManager()

        tool = RequestShutDownTool(
            sender=Mock(spec=Sender),
            protocol_manager=manager,
        )

        self.assertIs(tool.protocol_manager, manager)


if __name__ == "__main__":
    unittest.main()
