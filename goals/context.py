import json
from typing import Any

from code_harness.memory.context import (
    ConversationStore,
    MessageRecord,
    MessageType,
    TokenEstimator,
)

DEFAULT_GOAL_CONTEXT_TOKENS = 12_000


class GoalContextBuilder:
    def __init__(
        self,
        max_tokens: int = DEFAULT_GOAL_CONTEXT_TOKENS,
        estimator: TokenEstimator | None = None,
    ):
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")

        self.max_tokens = max_tokens
        self.estimator = estimator or TokenEstimator()

    def build(
        self,
        store: ConversationStore,
        conversation_id: str,
    ) -> list[dict[str, Any]]:
        summary = store.get_active_summary(conversation_id)
        history = store.get_messages_after(conversation_id, summary)
        selected = []
        used_tokens = 0

        for record in reversed(history):
            if self._should_include(record):
                message = record.to_llm_dict()
                size = self.estimator.estimate_message(message)

                if used_tokens + size > self.max_tokens:
                    if not selected:
                        selected.append(
                            self._truncate_oversized_message(
                                message,
                                self.max_tokens,
                            )
                        )
                    break

                selected.append(message)
                used_tokens += size

        selected.reverse()

        if summary is not None:
            summary_message = summary.to_llm_dict()
            summary_size = self.estimator.estimate_message(summary_message)
            remaining_tokens = self.max_tokens - used_tokens
            if summary_size <= remaining_tokens:
                selected.insert(0, summary_message)
            elif not selected:
                selected.append(
                    self._truncate_oversized_message(
                        summary_message,
                        self.max_tokens,
                    )
                )

        return selected

    def _truncate_oversized_message(
        self,
        message: dict[str, Any],
        max_tokens: int,
    ) -> dict[str, Any]:
        """Keep the head and tail of one message within the token budget."""
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")

        if self.estimator.estimate_message(message) <= max_tokens:
            return dict(message)

        serialized = json.dumps(message, ensure_ascii=False, default=str)
        role = str(message.get("role", "unknown"))
        marker = "\n... truncated for goal evaluation ...\n"

        def candidate(kept_characters: int) -> dict[str, Any]:
            head_length = (kept_characters + 1) // 2
            tail_length = kept_characters // 2
            head = serialized[:head_length]
            tail = serialized[-tail_length:] if tail_length else ""
            return {
                "role": role,
                "content": f"{head}{marker}{tail}",
                "goal_context_truncated": True,
            }

        smallest = candidate(0)
        if self.estimator.estimate_message(smallest) > max_tokens:
            raise ValueError(
                "max_tokens is too small to encode a truncated goal message"
            )

        best = smallest
        low = 0
        high = len(serialized)
        while low <= high:
            midpoint = (low + high) // 2
            current = candidate(midpoint)
            if self.estimator.estimate_message(current) <= max_tokens:
                best = current
                low = midpoint + 1
            else:
                high = midpoint - 1

        return best

    def _should_include(self, message: MessageRecord) -> bool:
        if message.type == MessageType.SYSTEM:
            return False

        if message.type == MessageType.DEVELOPER:
            return False

        if message.type == MessageType.SUMMARY:
            return True  # build() must select only the latest summary

        if message.type == MessageType.USER:
            content = self._text_content(message)
            if content.lstrip().startswith("<reminder>"):
                return False

        return message.type in {
            MessageType.USER,
            MessageType.ASSISTANT,
            MessageType.TOOL,
        }

    @staticmethod
    def _text_content(message: MessageRecord) -> str:
        content = message.content
        if isinstance(content, dict):
            content = content.get("content", content.get("text", ""))
        return content if isinstance(content, str) else str(content)
