from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

from code_harness.core.application import ApplicationConfig, HarnessApplication


class HarnessApplicationLifecycleTests(IsolatedAsyncioTestCase):
    def make_application(self):
        input_broker = Mock()
        event_queue = Mock()
        queue_processor = Mock()
        scheduler = Mock()
        mcp_registry = Mock()
        mcp_registry.close = AsyncMock()
        tool_registry = Mock()
        application = HarnessApplication(
            config=ApplicationConfig(Path.cwd()),
            conversation_id="conv_test",
            conversation_store=Mock(),
            tool_registry=tool_registry,
            mcp_registry=mcp_registry,
            input_broker=input_broker,
            event_queue=event_queue,
            queue_processor=queue_processor,
            scheduler=scheduler,
            goal_command_handler=Mock(),
        )
        return application

    async def test_start_and_close_manage_every_owned_service(self):
        application = self.make_application()

        application.start()
        await application.close()

        application.event_queue.load_events.assert_called_once_with()
        application.scheduler.load_durable_jobs.assert_called_once_with()
        application.scheduler.start.assert_called_once_with()
        application.queue_processor.start.assert_called_once_with()
        application.input_broker.start.assert_called_once_with()
        application.input_broker.stop.assert_called_once_with()
        application.scheduler.stop.assert_called_once_with()
        application.queue_processor.stop.assert_called_once_with()
        application.mcp_registry.close.assert_awaited_once_with(
            application.tool_registry
        )

    async def test_start_and_close_are_idempotent(self):
        application = self.make_application()

        application.start()
        application.start()
        await application.close()
        await application.close()

        application.scheduler.start.assert_called_once_with()
        application.scheduler.stop.assert_called_once_with()
        application.mcp_registry.close.assert_awaited_once()
