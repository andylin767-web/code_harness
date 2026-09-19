from enum import StrEnum

from code_harness.team.protocol_state import ProtocolType


class MessageType(StrEnum):
    MESSAGE = "message"
    RESULT = "result"
    ERROR = "error"


type MessageKind = MessageType | ProtocolType | str


def message_type_value(message_type: MessageKind) -> str:
    """Return the stable wire value for a team message type."""
    if isinstance(message_type, StrEnum):
        return message_type.value
    return message_type
