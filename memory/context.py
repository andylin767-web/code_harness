from dataclasses import dataclass, field
import json
from enum import StrEnum
from typing import Any
from datetime import datetime, timezone
from uuid import uuid4


class MessageType(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"
    SUMMARY = "summary"
    DEVELOPER ="developer"

MAX_TOOL_OUTPUT = 4000


class TokenEstimator:
    def estimate_message(self, msg: dict) -> int:
        payload = {
            k: v
            for k, v in msg.items()
            if v is not None
        }
        return self._estimate(json.dumps(payload, separators=(",", ":")))

    def estimate_content(self, content: Any) -> int:
        if isinstance(content, str):
            return self._estimate(content)

        return self._estimate(json.dumps(content, separators=(",", ":"), default=str))
    
    def _estimate(self, text: str) -> int:
        return len(text) // 4
    

@dataclass(frozen=True)
class MessageRecord:
    id: str
    role: str
    content: Any
    type: MessageType
    conversation_id: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)
    estimated_tokens: int | None = None

    @classmethod
    def create(
        cls,
        *,
        type: MessageType | str,
        conversation_id: str,
        content: Any,
        id: str | None = None,
        role: str | None = None,
        metadata: dict[str, Any] | None = None,
        estimated_tokens: int | None = None,
    ) -> "MessageRecord":
        message_type = MessageType(type)
        return cls(
            id=id or f"{message_type.value}_{uuid4().hex}",
            role=role or cls.role_for_type(message_type),
            content=content,
            type=message_type,
            conversation_id=conversation_id,
            metadata=metadata or {},
            estimated_tokens=estimated_tokens,
        )

    @classmethod
    def user(
        cls,
        *,
        conversation_id: str,
        content: Any,
        **kwargs: Any,
    ) -> "MessageRecord":
        return cls.create(
            type=MessageType.USER,
            conversation_id=conversation_id,
            content=content,
            **kwargs,
        )

    @classmethod
    def assistant(
        cls,
        *,
        conversation_id: str,
        content: Any,
        **kwargs: Any,
    ) -> "MessageRecord":
        return cls.create(
            type=MessageType.ASSISTANT,
            conversation_id=conversation_id,
            content=content,
            **kwargs,
        )

    @classmethod
    def tool(
        cls,
        *,
        conversation_id: str,
        content: Any,
        tool_call_id: str | None = None,
        **kwargs: Any,
    ) -> "MessageRecord":
        metadata = dict(kwargs.pop("metadata", {}) or {})
        if tool_call_id is not None:
            metadata["tool_call_id"] = tool_call_id
            if isinstance(content, dict):
                content = dict(content)
                content.setdefault("tool_call_id", tool_call_id)
            else:
                content = {
                    "tool_call_id": tool_call_id,
                    "content": content,
                }

        return cls.create(
            type=MessageType.TOOL,
            conversation_id=conversation_id,
            content=content,
            metadata=metadata,
            **kwargs,
        )

    @classmethod
    def system(
        cls,
        *,
        conversation_id: str,
        content: Any,
        **kwargs: Any,
    ) -> "MessageRecord":
        return cls.create(
            type=MessageType.SYSTEM,
            conversation_id=conversation_id,
            content=content,
            **kwargs,
        )

    @classmethod
    def developer(
        cls,
        *,
        conversation_id: str,
        content: Any,
        **kwargs: Any,
    ) -> "MessageRecord":
        return cls.create(
            type=MessageType.DEVELOPER,
            conversation_id=conversation_id,
            content=content,
            **kwargs,
        )

    @classmethod
    def summary(
        cls,
        *,
        conversation_id: str,
        content: Any,
        **kwargs: Any,
    ) -> "MessageRecord":
        return cls.create(
            type=MessageType.SUMMARY,
            conversation_id=conversation_id,
            content=content,
            **kwargs,
        )

    @staticmethod
    def role_for_type(type: MessageType | str) -> str:
        message_type = MessageType(type)
        if message_type == MessageType.SUMMARY:
            return MessageType.SYSTEM.value

        return message_type.value

    def __post_init__(self):
        if isinstance(self.type, str):
            object.__setattr__(self, "type", MessageType(self.type))

        if self.estimated_tokens is None:
            token_count = TokenEstimator().estimate_content(self.to_llm_dict())
            object.__setattr__(self, "estimated_tokens", token_count)

    def to_llm_dict(self) -> dict[str, Any]:
        if isinstance(self.content, dict):
            payload = dict(self.content)
            payload.setdefault("role", self.role)
            return payload

        return {"role": self.role, "content": self.content}

    def to_trace_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "type": self.type.value,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at,
            "metadata": self.metadata,
            "estimated_tokens": self.estimated_tokens,
            "llm_message": self.to_llm_dict(),
        }
    

TOTAL_CONTEXT_BUDGET = 100000
SYSTEM_PROMPT_BUDGET= TOTAL_CONTEXT_BUDGET * 0.07


    
class ConversationStore:
    def __init__(self):
        self.records: list[MessageRecord] = []
        self.index_by_id: dict[str, int] = {}
        self.summary_indexes_by_conversation: dict[str, list[int]] = {}
        self.system_indexes_by_conversation: dict[str, list[int]] = {}
       
    
    def append_record(self,record: MessageRecord):
        index = len(self.records)
        self.records.append(record)
        self.index_by_id[record.id] = index

        if record.type == MessageType.SUMMARY:
            self.summary_indexes_by_conversation.setdefault(
                record.conversation_id, []
            ).append(index)

        if record.type == MessageType.SYSTEM:
            self.system_indexes_by_conversation.setdefault(
                record.conversation_id, []
            ).append(index)

    def get_record(self, message_id):
        index = self.index_by_id.get(message_id)
        return self.records[index] if index is not None else None
    
    def get_active_summary(self, conversation_id):
        summary_indexes = self.summary_indexes_by_conversation.get(conversation_id) or []
        return self.records[summary_indexes[-1]] if summary_indexes else None

    def get_records_by_conversation_id(self, conversation_id):
        return  [ msg for msg in self.records if msg.conversation_id == conversation_id]

    def get_records_since(self, conversation_id: str, start_index: int = 0) -> list[MessageRecord]:
        return [
            msg
            for msg in self.records[start_index:]
            if msg.conversation_id == conversation_id
        ]
    
    def get_messages_after(self, conversation_id, latest_summary_msg=None):
        start_index = -1

        if latest_summary_msg is not None:
            msg_id = latest_summary_msg.metadata.get("covers_through_message_id")

            if msg_id is not None:
                start_index = self.index_by_id.get(msg_id, -1)

        return [
            msg
            for msg in self.records[start_index + 1:]
            if (
                msg.conversation_id == conversation_id
                and msg.type not in {MessageType.SYSTEM, MessageType.SUMMARY}
            )
        ]
    
    def get_active_system_prompt(self, conversation_id):
        indexes = self.system_indexes_by_conversation.get(conversation_id) or []
        return self.records[indexes[-1]] if indexes else None

    
   
class ContextBuilder:
    def __init__(self, max_tokens: int= TOTAL_CONTEXT_BUDGET, keep_turns=4):
        self.max_tokens = max_tokens
        self.keep_turns=keep_turns

    async def build(self, store: ConversationStore, conversation_id: str) -> list[dict]:
        system_msg = store.get_active_system_prompt(conversation_id)
       

        if system_msg and system_msg.estimated_tokens>=SYSTEM_PROMPT_BUDGET:
            raise ValueError(f"System prompt exceeds budget {SYSTEM_PROMPT_BUDGET}")
        
        latest_summary_msg= store.get_active_summary(conversation_id)
        history_msgs = store.get_messages_after(conversation_id, latest_summary_msg)


        messages: list[MessageRecord] = []
        if system_msg:
            messages.append(system_msg)

        if latest_summary_msg:
            messages.append(latest_summary_msg)
        messages.extend(history_msgs)
        total_token_size = sum(msg.estimated_tokens or 0 for msg in messages)
        if total_token_size>=self.max_tokens*0.85:
            print(f"compact message since total_token_size: {total_token_size}")
            messages = await self._compact(
                store=store,
                conversation_id=conversation_id,
                system_msg=system_msg,
                latest_summary_msg=latest_summary_msg,
                history_msgs=history_msgs,
                keep_turns=self.keep_turns,
            )

        return [msg.to_llm_dict() for msg in messages]

    async def _compact(
        self,
        store: ConversationStore,
        conversation_id: str,
        system_msg: MessageRecord | None,
        latest_summary_msg: MessageRecord | None,
        history_msgs: list[MessageRecord],
        keep_turns: int,
    ) -> list[MessageRecord]:
        compact_msgs, keep_msgs = self._split_messages_by_turns(history_msgs, keep_turns)

        if not compact_msgs:
            messages = []
            if system_msg:
                messages.append(system_msg)
            if latest_summary_msg:
                messages.append(latest_summary_msg)
            messages.extend(keep_msgs)
            return messages

        existing_summary = self._summary_text(latest_summary_msg)
        compact_payload = [msg.to_llm_dict() for msg in compact_msgs]
        from code_harness.memory.message_summarizer import MessageSummarizer
        from code_harness.models import NVIDIA_NEMOTRON_3_SUPER_120B_A12B

        new_summary_content = await MessageSummarizer.summarize_messages(
            MessageSummarizer.summary_prompt,
            NVIDIA_NEMOTRON_3_SUPER_120B_A12B,
            compact_payload,
            existing_summary,
        )

        summary_content = {
            "type": "summary",
            "summary_type": "conversation_summary",
            "content": f"""
Earlier conversation summary:
{new_summary_content}
""".strip(),
        }
        new_summary_msg = MessageRecord.summary(
            id=f"conversation_summary_{uuid4().hex}",
            conversation_id=conversation_id,
            content=summary_content,
            estimated_tokens=TokenEstimator().estimate_message(summary_content),
            metadata={
                "supersedes_summary_id": latest_summary_msg.id if latest_summary_msg else None,
                "covers_from_message_id": compact_msgs[0].id,
                "covers_through_message_id": compact_msgs[-1].id,
                "created_from_message_ids": [
                    *([latest_summary_msg.id] if latest_summary_msg else []),
                    *[msg.id for msg in compact_msgs],
                ],
            },
        )
        store.append_record(new_summary_msg)

        messages = []
        if system_msg:
            messages.append(system_msg)
        messages.append(new_summary_msg)
        messages.extend(keep_msgs)
        return messages

    def _split_messages_by_turns(
        self,
        messages: list[MessageRecord],
        keep_turns: int,
    ) -> tuple[list[MessageRecord], list[MessageRecord]]:
        if keep_turns <= 0:
            return messages, []

        user_indexes = [
            i
            for i, msg in enumerate(messages)
            if msg.type == MessageType.USER and not self._is_synthetic_user_message(msg)
        ]

        if len(user_indexes) <= keep_turns:
            return [], messages

        keep_start = user_indexes[-keep_turns]
        return messages[:keep_start], messages[keep_start:]

    def _is_synthetic_user_message(self, msg: MessageRecord) -> bool:
        content = msg.content.get("content") if isinstance(msg.content, dict) else msg.content
        return isinstance(content, str) and content.lstrip().startswith("<reminder>")

    def _summary_text(self, summary_msg: MessageRecord | None) -> Any:
        if summary_msg is None:
            return None

        if isinstance(summary_msg.content, dict):
            return (
                summary_msg.content.get("content")
                or summary_msg.content.get("text")
                or summary_msg.content
            )

        return summary_msg.content

   
