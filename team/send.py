from typing import Any, Callable

from code_harness.team.message_bus import MessageBus
from code_harness.team.message_type import MessageKind, MessageType


class Sender:
    def __init__(self, bus: MessageBus):
        self.bus = bus

    def send_from_lead(
        self,
        to: str,
        content: str,
        msg_type: MessageKind = MessageType.MESSAGE,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        return self._send(
            from_agent="lead",
            to=to,
            content=content,
            msg_type=msg_type,
            metadata=metadata,
        )

    def send_from_teammate(
        self,
        name: str,
        to: str,
        content: str,
        msg_type: MessageKind = MessageType.MESSAGE,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        return self._send(
            from_agent=name,
            to=to,
            content=content,
            msg_type=msg_type,
            metadata=metadata,
        )

    def peek(self, agent: str) -> bool:
        """Return whether the agent currently has unread mailbox messages."""
        return self.bus.peek(agent)
    
    def make_teammate_sender(
        self,
        name: str,
    ) -> Callable[[str, str, MessageKind, dict[str, Any] | None], str]:
        def send(
            to: str,
            content: str,
            msg_type: MessageKind = MessageType.MESSAGE,
            metadata: dict[str, Any] | None = None,
        ) -> str:
            return self.send_from_teammate(
                name=name,
                to=to,
                content=content,
                msg_type=msg_type,
                metadata=metadata,
            )

        return send

    def _send(
        self,
        *,
        from_agent: str,
        to: str,
        content: str,
        msg_type: MessageKind,
        metadata: dict[str, Any] | None,
    ) -> str:
        self.bus.send(
            from_agent=from_agent,
            to_agent=to,
            content=content,
            msg_type=msg_type,
            metadata=metadata,
        )
        return f"Sent message to {to}"
