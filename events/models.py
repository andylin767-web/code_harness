from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4


class EventType(StrEnum):
    USER = "user"
    CRON = "cron"
    BACKGROUND_TASK = "background_task"
    TEAMMATE_MESSAGE = "teammate_message"
    QUIT = "quit"


@dataclass
class AgentEvent:
    event_id: str
    event_type: EventType
    content: str
    source: str
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)
    persistent: bool = False


@dataclass(init=False)
class CronEvent(AgentEvent):
    """Event produced when a cron job fires."""

    def __init__(
        self,
        event_id: str,
        job_id: str,
        prompt: str,
        fired_at: str,
    ):
        super().__init__(
            event_id=event_id,
            event_type=EventType.CRON,
            content=prompt,
            source=job_id,
            created_at=fired_at,
            metadata={"job_id": job_id},
            persistent=True,
        )

    @property
    def job_id(self) -> str:
        return self.source

    @property
    def prompt(self) -> str:
        return self.content

    @property
    def fired_at(self) -> str:
        return self.created_at


def new_event(
    event_type: EventType,
    content: str,
    *,
    source: str,
    created_at: str,
    metadata: dict[str, Any] | None = None,
) -> AgentEvent:
    return AgentEvent(
        event_id=f"event_{uuid4().hex}",
        event_type=event_type,
        content=content,
        source=source,
        created_at=created_at,
        metadata=metadata or {},
    )
