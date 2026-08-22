import asyncio
import random
from dataclasses import dataclass
from typing import Any

import litellm


@dataclass(frozen=True)
class RetryConfig:
    max_retries: int = 3
    timeout_seconds: float = 50
    base_delay_seconds: float = 1
    max_delay_seconds: float = 8
    jitter_seconds: float = 0.25


class LLMClient:
    def __init__(self, retry_config: RetryConfig | None = None):
        self.retry_config = retry_config or RetryConfig()

    async def send(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any | None = None,
        **completion_options: Any,
    ) -> Any:
        last_error: Exception | None = None
        attempts = self.retry_config.max_retries + 1

        for attempt in range(attempts):
            try:
                return await asyncio.wait_for(
                    litellm.acompletion(
                        model=model,
                        messages=messages,
                        tools=tools,
                        tool_choice=tool_choice,
                        **completion_options,
                    ),
                    timeout=self.retry_config.timeout_seconds,
                )
            except Exception as exc:
                last_error = exc
                if not self._is_retryable_error(exc) or attempt == attempts - 1:
                    raise

                await asyncio.sleep(self._retry_delay(attempt))

        raise RuntimeError("LLM request failed without an exception") from last_error

    def _retry_delay(self, attempt: int) -> float:
        exponential_delay = self.retry_config.base_delay_seconds * (2**attempt)
        capped_delay = min(exponential_delay, self.retry_config.max_delay_seconds)
        if self.retry_config.jitter_seconds <= 0:
            return capped_delay
        return capped_delay + random.uniform(0, self.retry_config.jitter_seconds)

    def _is_retryable_error(self, exc: Exception) -> bool:
        if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
            return True

        status_code = getattr(exc, "status_code", None)
        if status_code is None:
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", None)

        if isinstance(status_code, int):
            if status_code in {408, 409, 425, 429, 500, 502, 503, 504}:
                return True
            if 400 <= status_code < 500:
                return False
            return status_code >= 500

        text = str(exc).lower()
        non_retryable_markers = (
            "authentication",
            "api key",
            "bad request",
            "content policy",
            "context length",
            "invalid request",
            "not found",
            "permission",
            "unsupported",
        )
        if any(marker in text for marker in non_retryable_markers):
            return False

        retryable_markers = (
            "429",
            "500",
            "502",
            "503",
            "504",
            "connection",
            "overloaded",
            "rate limit",
            "server error",
            "service unavailable",
            "temporarily unavailable",
            "timeout",
            "timed out",
        )
        return any(marker in text for marker in retryable_markers)
