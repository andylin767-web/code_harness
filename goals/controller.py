from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from code_harness.core.tracing import record_goal_stage
from code_harness.goals.context import GoalContextBuilder
from code_harness.goals.evaluator import GoalEvaluationError, GoalEvaluator
from code_harness.goals.models import (
    GoalEvaluation,
    GoalLifecycle,
    GoalState,
    StopAction,
    StopDecision,
)
from code_harness.memory.context import ConversationStore

DEFAULT_STOP_HOOK_BLOCK_CAP = 8
MAX_GOAL_LENGTH = 4000


class GoalError(ValueError):
    """Raised when a goal operation is invalid."""


class GoalController:
    def __init__(
        self,
        *,
        evaluator: GoalEvaluator,
        context_builder: GoalContextBuilder,
        block_cap: int = DEFAULT_STOP_HOOK_BLOCK_CAP,
        events: list[dict[str, Any]] | None = None,
        trace_recorder: Callable[..., Any] = record_goal_stage,
    ):
        if block_cap < 1:
            raise GoalError("block_cap must be at least 1")

        self.evaluator = evaluator
        self.context_builder = context_builder
        self.block_cap = block_cap
        self.events = events if events is not None else []
        self.trace_recorder = trace_recorder
        self.active: GoalState | None = None
        self.last_status: dict[str, Any] | None = None

    def set_goal(
        self,
        condition: str,
        conversation_id: str,
        tokens_at_start: int = 0,
    ) -> GoalState:
        condition = condition.strip()

        if not condition:
            raise GoalError("goal condition cannot be empty")
        if len(condition) > MAX_GOAL_LENGTH:
            raise GoalError(
                f"goal condition cannot exceed {MAX_GOAL_LENGTH} characters"
            )
        if tokens_at_start < 0:
            raise GoalError("tokens_at_start cannot be negative")

        if self.active is not None:
            self.clear("replaced by a new goal")

        self.active = GoalState(
            id=f"goal_{uuid4().hex}",
            conversation_id=conversation_id,
            condition=condition,
            tokens_at_start=tokens_at_start,
        )
        self._record(self.active, "goal set")
        self._trace(self.active, "goal_set", details={"condition": condition})
        return self.active

    def inspect(self, current_tokens: int = 0) -> dict[str, Any] | None:
        if self.active is None:
            return self.last_status

        now = datetime.now(UTC)
        goal = self.active

        return {
            "goal_id": goal.id,
            "conversation_id": goal.conversation_id,
            "condition": goal.condition,
            "lifecycle": goal.lifecycle.value,
            "elapsed_seconds": max(
                0.0,
                (now - goal.created_at).total_seconds(),
            ),
            "evaluation_count": goal.evaluation_count,
            "consecutive_blocks": goal.consecutive_blocks,
            "latest_reason": goal.latest_reason,
            "tokens_used": max(0, current_tokens - goal.tokens_at_start),
        }

    def clear(self, reason: str = "cleared by user") -> GoalState | None:
        if self.active is None:
            return None

        goal = self.active
        goal.lifecycle = GoalLifecycle.CLEARED
        goal.latest_reason = reason
        goal.updated_at = datetime.now(UTC)

        self._record(goal, reason)
        self._trace(goal, "goal_cleared", details={"reason": reason})
        self.active = None
        return goal

    def restore(
        self,
        goal: GoalState,
        tokens_at_start: int = 0,
    ) -> GoalState | None:
        if goal.lifecycle is not GoalLifecycle.ACTIVE:
            return None
        if self.active is not None:
            raise GoalError("cannot restore while another goal is active")
        if tokens_at_start < 0:
            raise GoalError("tokens_at_start cannot be negative")

        now = datetime.now(UTC)
        self.active = GoalState(
            id=goal.id,
            conversation_id=goal.conversation_id,
            condition=goal.condition,
            created_at=now,
            updated_at=now,
            tokens_at_start=tokens_at_start,
        )

        self._record(self.active, "goal restored")
        self._trace(self.active, "goal_restored")
        return self.active

    async def evaluate_after_turn(
        self,
        *,
        store: ConversationStore,
        conversation_id: str,
        background_pending: bool = False,
        event_id: str | None = None,
        run_id: str | None = None,
    ) -> StopDecision:
        if self.active is None:
            return StopDecision(StopAction.ALLOW)

        goal = self.active

        if goal.conversation_id != conversation_id:
            raise GoalError("active goal belongs to a different conversation")

        if background_pending:
            return self._defer_for_background(
                goal,
                event_id=event_id,
                run_id=run_id,
            )

        messages = self.context_builder.build(
            store,
            conversation_id,
        )

        goal.evaluation_count += 1
        goal.updated_at = datetime.now(UTC)
        estimated_tokens = sum(
            self.context_builder.estimator.estimate_message(message)
            for message in messages
        )
        self._trace(
            goal,
            "evaluation_started",
            details={
                "evaluator_model": getattr(self.evaluator, "model", None),
                "message_count": len(messages),
                "estimated_tokens": estimated_tokens,
                "evaluation_count": goal.evaluation_count,
            },
            event_id=event_id,
            run_id=run_id,
        )

        try:
            result = await self.evaluator.evaluate(goal, messages)
        except GoalEvaluationError as exc:
            return self._evaluation_error(
                goal,
                exc,
                event_id=event_id,
                run_id=run_id,
            )
        return self._apply_evaluation(
            goal,
            result,
            event_id=event_id,
            run_id=run_id,
        )

    def _defer_for_background(
        self,
        goal: GoalState,
        *,
        event_id: str | None,
        run_id: str | None,
    ) -> StopDecision:
        reason = "Waiting for background work to finish."
        self._trace_evaluation(
            goal,
            StopAction.DEFER,
            reason,
            event_id=event_id,
            run_id=run_id,
        )
        return StopDecision(StopAction.DEFER, reason)

    def _evaluation_error(
        self,
        goal: GoalState,
        error: GoalEvaluationError,
        *,
        event_id: str | None,
        run_id: str | None,
    ) -> StopDecision:
        reason = str(error)
        goal.latest_reason = reason
        self._record(goal, "goal evaluation failed")
        self._trace_evaluation(
            goal,
            StopAction.ERROR,
            reason,
            event_id=event_id,
            run_id=run_id,
        )
        return StopDecision(StopAction.ERROR, reason)

    def _apply_evaluation(
        self,
        goal: GoalState,
        result: GoalEvaluation,
        *,
        event_id: str | None,
        run_id: str | None,
    ) -> StopDecision:
        if result.ok:
            return self._complete_goal(goal, result.reason, event_id, run_id)
        if result.impossible:
            return self._mark_impossible(goal, result.reason, event_id, run_id)

        goal.latest_reason = result.reason
        goal.consecutive_blocks += 1
        goal.updated_at = datetime.now(UTC)
        self._record(goal, "goal incomplete")
        if goal.consecutive_blocks >= self.block_cap:
            reason = (
                "Automatic goal continuation paused after "
                f"{goal.consecutive_blocks} blocked stops. "
                f"Latest reason: {result.reason}"
            )
            self._trace_evaluation(
                goal,
                StopAction.PAUSE,
                reason,
                event_id=event_id,
                run_id=run_id,
                ok=False,
                impossible=False,
            )
            self._trace(
                goal,
                "goal_paused",
                details={"reason": reason},
                event_id=event_id,
                run_id=run_id,
            )
            return StopDecision(StopAction.PAUSE, reason)

        self._trace_evaluation(
            goal,
            StopAction.BLOCK,
            result.reason,
            event_id=event_id,
            run_id=run_id,
            ok=False,
            impossible=False,
        )
        return StopDecision(StopAction.BLOCK, result.reason)

    def _complete_goal(
        self, goal: GoalState, reason: str, event_id: str | None, run_id: str | None
    ) -> StopDecision:
        now = datetime.now(UTC)
        goal.lifecycle = GoalLifecycle.COMPLETED
        goal.completed_at = now
        goal.updated_at = now
        goal.latest_reason = reason
        goal.consecutive_blocks = 0
        self._record(goal, "goal completed")
        self._trace_evaluation(
            goal,
            StopAction.ALLOW,
            reason,
            event_id=event_id,
            run_id=run_id,
            ok=True,
            impossible=False,
        )
        self._trace(
            goal,
            "goal_completed",
            details={"reason": reason},
            event_id=event_id,
            run_id=run_id,
        )
        self.active = None
        return StopDecision(StopAction.ALLOW, reason)

    def _mark_impossible(
        self, goal: GoalState, reason: str, event_id: str | None, run_id: str | None
    ) -> StopDecision:
        goal.lifecycle = GoalLifecycle.IMPOSSIBLE
        goal.latest_reason = reason
        goal.updated_at = datetime.now(UTC)
        goal.consecutive_blocks = 0
        self._record(goal, "goal impossible")
        self._trace_evaluation(
            goal,
            StopAction.IMPOSSIBLE,
            reason,
            event_id=event_id,
            run_id=run_id,
            ok=False,
            impossible=True,
        )
        self._trace(
            goal,
            "goal_impossible",
            details={"reason": reason},
            event_id=event_id,
            run_id=run_id,
        )
        self.active = None
        return StopDecision(StopAction.IMPOSSIBLE, reason)

    def _trace_evaluation(
        self,
        goal: GoalState,
        action: StopAction,
        reason: str,
        *,
        event_id: str | None,
        run_id: str | None,
        **details: Any,
    ) -> None:
        self._trace(
            goal,
            "evaluation_completed",
            details={"action": action.value, "reason": reason, **details},
            event_id=event_id,
            run_id=run_id,
        )

    def _record(self, goal: GoalState, reason: str) -> dict[str, Any]:
        event = {
            "type": "goal_status",
            "goal_id": goal.id,
            "conversation_id": goal.conversation_id,
            "condition": goal.condition,
            "lifecycle": goal.lifecycle.value,
            "evaluation_count": goal.evaluation_count,
            "consecutive_blocks": goal.consecutive_blocks,
            "latest_reason": goal.latest_reason,
            "reason": reason,
            "created_at": goal.created_at.isoformat(),
            "updated_at": goal.updated_at.isoformat(),
            "completed_at": (
                goal.completed_at.isoformat() if goal.completed_at is not None else None
            ),
            "tokens_at_start": goal.tokens_at_start,
        }
        self.events.append(event)
        self.last_status = event
        return event

    def _trace(
        self,
        goal: GoalState,
        stage: str,
        *,
        details: dict[str, Any] | None = None,
        event_id: str | None = None,
        run_id: str | None = None,
    ) -> None:
        self.trace_recorder(
            stage,
            goal_id=goal.id,
            conversation_id=goal.conversation_id,
            event_id=event_id,
            run_id=run_id,
            details=details,
        )
