import time
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4


class ProtocolType(StrEnum):
    SHUTDOWN_REQUEST = "shutdown_request"
    SHUTDOWN_RESPONSE = "shutdown_response"
    PLAN_APPROVAL_REQUEST = "plan_approval_request"
    PLAN_APPROVAL_RESPONSE = "plan_approval_response"


class ProtocolStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


def generate_request_id() -> str:
    return f"req_{uuid4().hex}"


@dataclass
class ProtocolState:
    type: ProtocolType
    sender: str  # Sender
    target: str  # Recipient
    payload: str  # Plan text or shutdown reason
    status: ProtocolStatus = ProtocolStatus.PENDING
    request_id: str = field(default_factory=generate_request_id)
    created_at: float = field(default_factory=lambda: round(time.time(), 3))
