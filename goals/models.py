from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class GoalLifecycle(StrEnum):
    """Persisted lifecycle of a goal."""

    ACTIVE = "active"
    COMPLETED = "completed"
    IMPOSSIBLE = "impossible"
    CLEARED = "cleared"

    @property
    def is_terminal(self) -> bool:
        return self is not GoalLifecycle.ACTIVE


class StopAction(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"
    DEFER = "defer"
    IMPOSSIBLE = "impossible"
    PAUSE = "pause"
    ERROR = "error"


@dataclass(frozen=True)
class GoalEvaluation:
    """Structured result returned by the independent goal evaluator."""

    ok: bool
    reason: str
    impossible: bool = False

    def __post_init__(self) -> None:
        if self.ok and self.impossible:
            raise ValueError(
                "A goal evaluation cannot be both satisfied and impossible"
            )


@dataclass(frozen=True)
class StopDecision:
    """Decision made at the worker loop's normal return boundary."""

    action: StopAction
    reason: str = ""


@dataclass
class GoalState:
    """Mutable, session-scoped state for one checkable completion condition."""

    id: str
    conversation_id: str
    condition: str
    lifecycle: GoalLifecycle = GoalLifecycle.ACTIVE
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    evaluation_count: int = 0
    consecutive_blocks: int = 0
    latest_reason: str | None = None
    tokens_at_start: int = 0

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("Goal id cannot be empty")
        if not self.conversation_id.strip():
            raise ValueError("Goal conversation_id cannot be empty")
        if not self.condition.strip():
            raise ValueError("Goal condition cannot be empty")
        if self.evaluation_count < 0:
            raise ValueError("Goal evaluation_count cannot be negative")
        if self.consecutive_blocks < 0:
            raise ValueError("Goal consecutive_blocks cannot be negative")
        if self.tokens_at_start < 0:
            raise ValueError("Goal tokens_at_start cannot be negative")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Goal timestamps must be timezone-aware")
        if self.completed_at is not None and self.completed_at.tzinfo is None:
            raise ValueError("Goal completed_at must be timezone-aware")

    @property
    def is_active(self) -> bool:
        return self.lifecycle is GoalLifecycle.ACTIVE
