"""Goal lifecycle and stop-hook domain models."""

from code_harness.goals.command import GoalCommandHandler, GoalCommandResult
from code_harness.goals.models import (
    GoalEvaluation,
    GoalLifecycle,
    GoalState,
    StopAction,
    StopDecision,
)
from code_harness.goals.store import GoalStore, GoalStoreError

__all__ = [
    "GoalCommandHandler",
    "GoalCommandResult",
    "GoalEvaluation",
    "GoalLifecycle",
    "GoalState",
    "GoalStore",
    "GoalStoreError",
    "StopAction",
    "StopDecision",
]
