from typing import Any

from pydantic import BaseModel, Field

from code_harness.core.agent_runtime import get_lead_agent
from code_harness.core.permissions import PROJECT_ROOT
from code_harness.team.lead_inbox import consume_lead_inbox
from code_harness.team.message_bus import MessageBus
from code_harness.team.message_type import MessageType
from code_harness.team.protocol_manager import ProtocolManager
from code_harness.team.protocol_runtime import get_protocol_manager
from code_harness.team.protocol_state import ProtocolType
from code_harness.team.send import Sender
from code_harness.tools.tools import BaseTool


def _default_sender() -> Sender:
    return Sender(MessageBus(PROJECT_ROOT / ".mailboxes"))


class SenderTool(BaseTool):
    """Base class for tools that send or inspect team messages."""

    def __init__(self, sender: Sender | None = None, services=None):
        if sender is not None:
            self.sender = sender
        elif services is not None:
            self.sender = Sender(services.message_bus)
        else:
            self.sender = _default_sender()
        self.services = services


class ProtocolTool(SenderTool):
    """Base class for team tools that also manage protocol state."""

    def __init__(
        self,
        sender: Sender | None = None,
        protocol_manager: ProtocolManager | None = None,
        services=None,
    ):
        super().__init__(sender, services)
        self.protocol_manager = (
            protocol_manager
            if protocol_manager is not None
            else (
                services.protocol_manager
                if services is not None
                else get_protocol_manager()
            )
        )


class SendMessageInput(BaseModel):
    to: str
    content: str


class SendMessageTool(SenderTool):
    name = "send_message"
    description = "Send a message to a teammate."
    input_model = SendMessageInput
    agent_types = {"parent"}

    def run(self, arguments: SendMessageInput) -> str:
        return self.sender.send_from_lead(
            to=arguments.to,
            content=arguments.content,
            msg_type=MessageType.MESSAGE,
        )


class CheckInBoxInput(BaseModel):
    agent: str


class CheckInboxTool(SenderTool):
    name = "check_inbox"
    description = (
        "Consume lead messages with protocol routing, or check whether another "
        "agent has unread messages."
    )
    input_model = CheckInBoxInput
    agent_types = {"parent"}

    def run(self, arguments: CheckInBoxInput) -> bool | list[dict]:
        if arguments.agent == "lead":
            if self.services is not None and self.services.lead_inbox is not None:
                return self.services.lead_inbox.consume()
            return consume_lead_inbox()
        return self.sender.peek(arguments.agent)


class TeammateSendMessageInput(BaseModel):
    to: str
    content: str
    name: str
    msg_type: MessageType | ProtocolType = MessageType.MESSAGE
    metadata: dict[str, Any] = Field(default_factory=dict)


class TeammateSendMessageTool(SenderTool):
    name = "teammate_send_message"
    description = "Send a typed message from a teammate."
    input_model = TeammateSendMessageInput

    def run(self, arguments: TeammateSendMessageInput) -> str:
        return self.sender.send_from_teammate(
            name=arguments.name,
            to=arguments.to,
            content=arguments.content,
            msg_type=arguments.msg_type,
            metadata=arguments.metadata,
        )


class SpawnTeammateInput(BaseModel):
    name: str = Field(description="Unique name for the teammate.")
    role: str = Field(description="The teammate's role or specialty.")
    assignment: str = Field(description="The task the teammate should complete.")
    parent_conversation_id: str = Field(
        default="",
        description="Injected by the parent loop for trace linking.",
    )


class SpawnTeammateTool(BaseTool):
    name = "spawn_teammate"
    description = "Spawn a teammate in a background thread."
    input_model = SpawnTeammateInput
    agent_types = {"parent"}

    def __init__(self, services=None):
        self.services = services

    def run(self, arguments: SpawnTeammateInput) -> str:
        lead_agent = (
            self.services.lead_agent if self.services is not None else get_lead_agent()
        )
        return lead_agent.spawn_teammate_thread(
            name=arguments.name,
            role=arguments.role,
            assignment=arguments.assignment,
            parent_conversation_id=arguments.parent_conversation_id,
        )


class RequestPlanInput(BaseModel):
    teammate: str = Field(description="The teammate to request a plan from")
    task: str = Field(description="The task the teammate should plan")


class RequestPlanTool(SenderTool):
    name = "request_plan"
    description = "Request an implementation plan from a teammate."
    input_model = RequestPlanInput
    agent_types = {"parent"}

    def run(self, arguments: RequestPlanInput) -> str:
        self.sender.send_from_lead(
            to=arguments.teammate,
            content=f"Please create a plan for this task: {arguments.task}",
            msg_type=MessageType.MESSAGE,
        )
        return f"Asked {arguments.teammate} to submit a plan"


class SubmitPlanInput(BaseModel):
    from_name: str = Field(description="The teammate submitting the plan")
    plan: str = Field(description="The implementation plan to review")


class SubmitPlanTool(ProtocolTool):
    name = "submit_plan"
    description = "Submit an implementation plan to the lead for approval."
    input_model = SubmitPlanInput
    agent_types = {"sub_agent"}

    def run(self, arguments: SubmitPlanInput) -> str:
        pending_request = self.protocol_manager.create_request(
            type=ProtocolType.PLAN_APPROVAL_REQUEST,
            sender=arguments.from_name,
            target="lead",
            payload=arguments.plan,
        )
        self.sender.send_from_teammate(
            name=arguments.from_name,
            to="lead",
            content=arguments.plan,
            msg_type=ProtocolType.PLAN_APPROVAL_REQUEST,
            metadata={"request_id": pending_request.request_id},
        )
        return f"Plan submitted for approval (req: {pending_request.request_id})"


class ReviewPlanInput(BaseModel):
    request_id: str = Field(description="The plan request to review")
    approve: bool = Field(description="Whether to approve the plan")
    feedback: str = Field(description="Feedback for the teammate")


class ReviewPlanTool(ProtocolTool):
    name = "review_plan"
    description = "Approve or reject a teammate's implementation plan."
    input_model = ReviewPlanInput
    agent_types = {"parent"}

    def run(self, arguments: ReviewPlanInput) -> str:
        state = self.protocol_manager.get_request(arguments.request_id)
        if state is None:
            return f"Request {arguments.request_id} not found"

        resolved = self.protocol_manager.process_response(
            response_type=ProtocolType.PLAN_APPROVAL_RESPONSE,
            request_id=arguments.request_id,
            approve=arguments.approve,
        )
        if resolved is None:
            return f"Request {arguments.request_id} could not be reviewed"

        content = arguments.feedback or (
            "Approved" if arguments.approve else "Rejected"
        )
        self.sender.send_from_lead(
            to=state.sender,
            content=content,
            msg_type=ProtocolType.PLAN_APPROVAL_RESPONSE,
            metadata={
                "request_id": state.request_id,
                "approve": arguments.approve,
            },
        )

        decision = "approved" if arguments.approve else "rejected"
        return f"Plan {decision} ({state.request_id})"


class RequestShutDownInput(BaseModel):
    teammate: str = Field(description="The teammate to shut down")


class RequestShutDownTool(ProtocolTool):
    name = "request_shutdown"
    description = "Request a teammate to shut down gracefully."
    input_model = RequestShutDownInput
    agent_types = {"parent"}

    def run(self, arguments: RequestShutDownInput) -> str:
        pending_request = self.protocol_manager.create_request(
            type=ProtocolType.SHUTDOWN_REQUEST,
            sender="lead",
            target=arguments.teammate,
            payload="",
        )
        self.sender.send_from_lead(
            to=arguments.teammate,
            content="Please shut down gracefully.",
            msg_type=ProtocolType.SHUTDOWN_REQUEST,
            metadata={"request_id": pending_request.request_id},
        )
        return (
            f"Shutdown request sent to {arguments.teammate} "
            f"(req: {pending_request.request_id})"
        )
