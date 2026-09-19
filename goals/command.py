from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from code_harness.goals.controller import GoalController


GOAL_CLEAR_ALIASES = frozenset({"clear", "stop", "off", "reset", "none", "cancel"})
GOAL_STATUS_ALIASES = frozenset({"status", "show", "inspect"})


@dataclass(frozen=True)
class GoalCommandResult:
    """Result of parsing a possible `/goal` terminal command."""

    handled: bool
    output: str = ""
    work_request: str | None = None
    error: str | None = None

    @property
    def starts_work(self) -> bool:
        return self.work_request is not None


class GoalCommandHandler:
    """Parse `/goal` commands without owning terminal or queue behavior."""

    def __init__(self, controller: GoalController):
        self.controller = controller

    def handle(
        self,
        user_input: str,
        *,
        conversation_id: str,
        current_tokens: int = 0,
    ) -> GoalCommandResult:
        parts = user_input.strip().split(maxsplit=1)
        command = parts[0] if parts else ""
        if command.casefold() != "/goal":
            return GoalCommandResult(handled=False)

        option = parts[1].strip() if len(parts) == 2 else ""
        normalized_option = option.casefold()

        if not option or normalized_option in GOAL_STATUS_ALIASES:
            return GoalCommandResult(
                handled=True,
                output=self._format_status(
                    self.controller.inspect(current_tokens=current_tokens)
                ),
            )

        if normalized_option in GOAL_CLEAR_ALIASES:
            cleared = self.controller.clear("cleared by user")
            if cleared is None:
                output = "No active goal to clear."
            else:
                output = f"Cleared goal: {cleared.condition}"
            return GoalCommandResult(handled=True, output=output)

        if normalized_option == "help":
            return GoalCommandResult(handled=True, output=self.help_text())

        try:
            goal = self.controller.set_goal(
                condition=option,
                conversation_id=conversation_id,
                tokens_at_start=current_tokens,
            )
        except ValueError as exc:
            error = str(exc)
            return GoalCommandResult(
                handled=True,
                output=f"Could not set goal: {error}",
                error=error,
            )

        return GoalCommandResult(
            handled=True,
            output=f"Goal set: {goal.condition}",
            work_request=goal.condition,
        )

    @staticmethod
    def help_text() -> str:
        return (
            "/goal                     Show the current or latest goal status.\n"
            "/goal <condition>         Set or replace the goal and begin work.\n"
            "/goal clear               Clear the active goal.\n"
            "/goal help                Show this help.\n"
            "Clear aliases: stop, off, reset, none, cancel."
        )

    @staticmethod
    def _format_status(status: dict[str, Any] | None) -> str:
        if status is None:
            return "No goal has been set."

        lines = [
            f"Goal: {status.get('condition', '(unknown)')}",
            f"Status: {status.get('lifecycle', 'unknown')}",
        ]

        optional_fields = (
            ("Evaluations", "evaluation_count"),
            ("Consecutive blocks", "consecutive_blocks"),
            ("Tokens used", "tokens_used"),
        )
        for label, key in optional_fields:
            value = status.get(key)
            if value is not None:
                lines.append(f"{label}: {value}")

        elapsed_seconds = status.get("elapsed_seconds")
        if elapsed_seconds is not None:
            lines.append(f"Elapsed: {float(elapsed_seconds):.1f}s")

        latest_reason = status.get("latest_reason") or status.get("reason")
        if latest_reason:
            lines.append(f"Latest reason: {latest_reason}")

        return "\n".join(lines)
