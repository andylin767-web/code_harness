import json
from collections.abc import Callable
from typing import Any

from code_harness.team.message_type import (
    MessageKind,
    MessageType,
    message_type_value,
)
from code_harness.team.protocol_manager import ProtocolManager
from code_harness.team.protocol_state import ProtocolState, ProtocolType
from code_harness.team.send import Sender

type TeamMessage = dict[str, Any]
type ConversationMessage = dict[str, Any]
type TeammateHandler = Callable[
    [str, TeamMessage, list[ConversationMessage]],
    bool,
]
type LeadHandler = Callable[
    [TeamMessage, list[ConversationMessage]],
    bool,
]


class ProtocolDispatcher:
    """Dispatch typed team messages and coordinate protocol side effects."""

    def __init__(self, sender: Sender, protocol_manager: ProtocolManager):
        self.sender = sender
        self.protocol_manager = protocol_manager
        self._teammate_handlers: dict[str, TeammateHandler] = {}
        self._lead_handlers: dict[str, LeadHandler] = {}
        self._register_default_handlers()

    def register_teammate_handler(
        self,
        msg_type: MessageKind,
        handler: TeammateHandler,
    ) -> None:
        self._teammate_handlers[message_type_value(msg_type)] = handler

    def register_lead_handler(
        self,
        msg_type: MessageKind,
        handler: LeadHandler,
    ) -> None:
        self._lead_handlers[message_type_value(msg_type)] = handler

    def dispatch_to_teammate(
        self,
        agent_name: str,
        message: TeamMessage,
        messages: list[ConversationMessage],
    ) -> bool:
        """Dispatch an inbox message, returning whether the agent should stop."""
        handler = self._teammate_handlers.get(
            self._message_type(message),
            self._handle_normal_teammate_message,
        )
        return handler(agent_name, message, messages)

    def dispatch(
        self,
        agent_name: str,
        message: TeamMessage,
        messages: list[ConversationMessage],
    ) -> bool:
        """Dispatch a teammate inbox message."""
        return self.dispatch_to_teammate(agent_name, message, messages)

    def dispatch_to_lead(
        self,
        message: TeamMessage,
        messages: list[ConversationMessage],
    ) -> bool:
        """Dispatch a lead inbox message, returning whether the lead should stop."""
        handler = self._lead_handlers.get(
            self._message_type(message),
            self._handle_normal_lead_message,
        )
        return handler(message, messages)

    def _register_default_handlers(self) -> None:
        self.register_teammate_handler(
            ProtocolType.SHUTDOWN_REQUEST,
            self._handle_shutdown_request,
        )
        self.register_teammate_handler(
            ProtocolType.PLAN_APPROVAL_RESPONSE,
            self._handle_plan_approval_response,
        )
        self.register_teammate_handler(
            MessageType.MESSAGE,
            self._handle_normal_teammate_message,
        )
        self.register_teammate_handler(
            MessageType.RESULT,
            self._handle_normal_teammate_message,
        )

        self.register_lead_handler(
            ProtocolType.SHUTDOWN_RESPONSE,
            self._handle_shutdown_response,
        )
        self.register_lead_handler(
            ProtocolType.PLAN_APPROVAL_REQUEST,
            self._handle_plan_approval_request,
        )
        self.register_lead_handler(
            MessageType.MESSAGE,
            self._handle_normal_lead_message,
        )
        self.register_lead_handler(
            MessageType.RESULT,
            self._handle_normal_lead_message,
        )

    def _handle_shutdown_request(
        self,
        agent_name: str,
        message: TeamMessage,
        messages: list[ConversationMessage],
    ) -> bool:
        request_id = self._request_id(self._metadata(message)) or ""
        self.sender.send_from_teammate(
            name=agent_name,
            to="lead",
            content="Shutting down gracefully.",
            msg_type=ProtocolType.SHUTDOWN_RESPONSE,
            metadata={
                "request_id": request_id,
                "approve": True,
            },
        )
        return True

    def _handle_plan_approval_response(
        self,
        agent_name: str,
        message: TeamMessage,
        messages: list[ConversationMessage],
    ) -> bool:
        approve = self._approval(self._metadata(message))
        if approve:
            content = "[Plan approved] Proceed with the task."
        else:
            content = f"[Plan rejected] Feedback: {message.get('content', '')}"
        messages.append({"role": "user", "content": content})
        return False

    def _handle_normal_teammate_message(
        self,
        agent_name: str,
        message: TeamMessage,
        messages: list[ConversationMessage],
    ) -> bool:
        messages.append(
            {
                "role": "user",
                "content": f"<inbox>{json.dumps([message])}</inbox>",
            }
        )
        return False

    def _handle_shutdown_response(
        self,
        message: TeamMessage,
        messages: list[ConversationMessage],
    ) -> bool:
        metadata = self._metadata(message)
        request_id = self._request_id(metadata)
        if not request_id:
            self._append_protocol_error(
                messages,
                "Shutdown response is missing request_id.",
            )
            return False

        resolved = self.protocol_manager.process_response(
            response_type=ProtocolType.SHUTDOWN_RESPONSE,
            request_id=request_id,
            approve=self._approval(metadata),
        )
        if resolved is None:
            self._append_protocol_error(
                messages,
                f"Shutdown response could not resolve request {request_id}.",
            )
        return False

    def _handle_plan_approval_request(
        self,
        message: TeamMessage,
        messages: list[ConversationMessage],
    ) -> bool:
        metadata = self._metadata(message)
        request_id = self._request_id(metadata)
        sender = str(message.get("from", "unknown"))
        plan = str(message.get("content", ""))

        try:
            state = self._get_or_create_plan_request(
                request_id=request_id,
                sender=sender,
                plan=plan,
            )
        except ValueError as exc:
            self._append_protocol_error(messages, str(exc))
            return False
        messages.append(
            {
                "role": "user",
                "content": (
                    "[Plan approval request]\n"
                    f"From: {sender}\n"
                    f"Request ID: {state.request_id}\n"
                    f"Plan:\n{state.payload}\n\n"
                    "Use review_plan(request_id, approve, feedback) to "
                    "approve or reject."
                ),
            }
        )
        return False

    def _handle_normal_lead_message(
        self,
        message: TeamMessage,
        messages: list[ConversationMessage],
    ) -> bool:
        messages.append(
            {
                "role": "user",
                "content": (
                    "[Inbox message]\n"
                    f"From: {message.get('from')}\n"
                    f"Type: {self._message_type(message)}\n"
                    f"Content: {message.get('content')}"
                ),
            }
        )
        return False

    def _get_or_create_plan_request(
        self,
        *,
        request_id: str | None,
        sender: str,
        plan: str,
    ) -> ProtocolState:
        if request_id is not None:
            existing = self.protocol_manager.get_request(request_id)
            if existing is not None:
                if existing.type is not ProtocolType.PLAN_APPROVAL_REQUEST:
                    raise ValueError(f"Request {request_id} is not a plan request.")
                if existing.sender != sender:
                    raise ValueError(f"Request {request_id} belongs to another sender.")
                if existing.payload != plan:
                    raise ValueError(
                        f"Request {request_id} has conflicting plan content."
                    )
                return existing

        return self.protocol_manager.create_request(
            type=ProtocolType.PLAN_APPROVAL_REQUEST,
            sender=sender,
            target="lead",
            payload=plan,
            request_id=request_id,
        )

    @staticmethod
    def _message_type(message: TeamMessage) -> str:
        raw_type = message.get("type", MessageType.MESSAGE)
        if isinstance(raw_type, (MessageType, ProtocolType)):
            return raw_type.value
        if isinstance(raw_type, str):
            return raw_type
        return MessageType.MESSAGE.value

    @staticmethod
    def _metadata(message: TeamMessage) -> dict[str, Any]:
        metadata = message.get("metadata")
        return metadata if isinstance(metadata, dict) else {}

    @staticmethod
    def _approval(metadata: dict[str, Any]) -> bool:
        return metadata.get("approve") is True

    @staticmethod
    def _request_id(metadata: dict[str, Any]) -> str | None:
        request_id = metadata.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            return None
        return request_id

    @staticmethod
    def _append_protocol_error(
        messages: list[ConversationMessage],
        content: str,
    ) -> None:
        messages.append(
            {
                "role": "user",
                "content": f"[Protocol error] {content}",
            }
        )
