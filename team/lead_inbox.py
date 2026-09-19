import threading
from collections.abc import Callable

from code_harness.core.permissions import PROJECT_ROOT
from code_harness.team.message_bus import MessageBus
from code_harness.team.protocol_runtime import match_response
from code_harness.team.protocol_state import ProtocolState, ProtocolType

ResponseMatcher = Callable[
    [ProtocolType | str, str, bool],
    ProtocolState | None,
]


class LeadInbox:
    """Consume lead messages and correlate protocol responses exactly once."""

    def __init__(
        self,
        bus: MessageBus,
        response_matcher: ResponseMatcher = match_response,
    ):
        self.bus = bus
        self.response_matcher = response_matcher

    def consume(self, route_protocol: bool = True) -> list[dict]:
        messages = self.bus.read_inbox("lead")
        if route_protocol:
            for message in messages:
                self._route_protocol_response(message)
        return messages

    def _route_protocol_response(self, message: dict) -> None:
        metadata = message.get("metadata")
        if not isinstance(metadata, dict):
            return

        request_id = metadata.get("request_id")
        message_type = message.get("type")
        if not isinstance(request_id, str) or not request_id:
            return
        if not isinstance(message_type, str):
            return
        if not message_type.endswith("_response"):
            return

        self.response_matcher(
            message_type,
            request_id,
            metadata.get("approve") is True,
        )


_runtime_lock = threading.RLock()
_lead_inbox: LeadInbox | None = None


def set_lead_inbox(lead_inbox: LeadInbox | None) -> None:
    global _lead_inbox
    with _runtime_lock:
        _lead_inbox = lead_inbox


def get_lead_inbox() -> LeadInbox:
    global _lead_inbox
    with _runtime_lock:
        if _lead_inbox is None:
            bus = MessageBus(PROJECT_ROOT / ".mailboxes")
            _lead_inbox = LeadInbox(bus)
        return _lead_inbox


def consume_lead_inbox(route_protocol: bool = True) -> list[dict]:
    """Read lead inbox messages and route protocol responses before return."""
    return get_lead_inbox().consume(route_protocol=route_protocol)
