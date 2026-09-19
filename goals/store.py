import json
import os
import re
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from code_harness.goals.models import GoalLifecycle, GoalState

DEFAULT_GOALS_DIR = Path(__file__).resolve().parents[1] / ".goals"
GOAL_STATE_VERSION = 1
_SAFE_CONVERSATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,254}$")


class GoalStoreError(RuntimeError):
    """Raised when persisted goal state cannot be safely read or written."""


class GoalStore:
    """Persist the latest goal state for each conversation as JSON."""

    def __init__(self, goals_dir: str | Path | None = None):
        self.goals_dir = Path(goals_dir or DEFAULT_GOALS_DIR).expanduser().resolve()
        try:
            self.goals_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise GoalStoreError(
                f"Could not create goal store directory {self.goals_dir}: {exc}"
            ) from exc

    def save(self, goal: GoalState) -> None:
        """Atomically save the latest state for the goal's conversation."""
        destination = self._goal_path(goal.conversation_id)
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
        payload = self._serialize(goal)

        try:
            with temporary.open("x", encoding="utf-8") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, destination)
        except (OSError, TypeError, ValueError) as exc:
            raise GoalStoreError(
                f"Could not save goal state to {destination}: {exc}"
            ) from exc
        finally:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)

    def load_active(self, conversation_id: str) -> GoalState | None:
        """Load the conversation's active goal, ignoring terminal states."""
        source = self._goal_path(conversation_id)
        if not source.exists():
            return None

        try:
            raw_payload = json.loads(source.read_text(encoding="utf-8"))
            goal = self._deserialize(raw_payload)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise GoalStoreError(
                f"Could not load goal state from {source}: {exc}"
            ) from exc

        if goal.conversation_id != conversation_id:
            raise GoalStoreError(
                "Persisted goal conversation_id does not match its store key"
            )
        if goal.lifecycle is not GoalLifecycle.ACTIVE:
            return None
        return goal

    def _goal_path(self, conversation_id: str) -> Path:
        """Return a safe per-conversation path within the goal store."""
        if not isinstance(conversation_id, str) or not _SAFE_CONVERSATION_ID.fullmatch(
            conversation_id
        ):
            raise GoalStoreError(
                "conversation_id must contain only letters, numbers, '.', '_', or '-'"
            )

        path = (self.goals_dir / f"{conversation_id}.json").resolve()
        if not path.is_relative_to(self.goals_dir):
            raise GoalStoreError("Goal path escapes the configured store directory")
        return path

    @staticmethod
    def _serialize(goal: GoalState) -> dict[str, Any]:
        return {
            "version": GOAL_STATE_VERSION,
            "id": goal.id,
            "conversation_id": goal.conversation_id,
            "condition": goal.condition,
            "lifecycle": goal.lifecycle.value,
            "created_at": goal.created_at.isoformat(),
            "updated_at": goal.updated_at.isoformat(),
            "completed_at": (
                goal.completed_at.isoformat() if goal.completed_at is not None else None
            ),
            "evaluation_count": goal.evaluation_count,
            "consecutive_blocks": goal.consecutive_blocks,
            "latest_reason": goal.latest_reason,
            "tokens_at_start": goal.tokens_at_start,
        }

    @staticmethod
    def _deserialize(payload: Any) -> GoalState:
        if not isinstance(payload, dict):
            raise ValueError("Persisted goal state must be a JSON object")
        if payload.get("version") != GOAL_STATE_VERSION:
            raise ValueError(
                f"Unsupported goal state version: {payload.get('version')!r}"
            )

        completed_at = payload["completed_at"]
        return GoalState(
            id=payload["id"],
            conversation_id=payload["conversation_id"],
            condition=payload["condition"],
            lifecycle=GoalLifecycle(payload["lifecycle"]),
            created_at=datetime.fromisoformat(payload["created_at"]),
            updated_at=datetime.fromisoformat(payload["updated_at"]),
            completed_at=(
                datetime.fromisoformat(completed_at)
                if completed_at is not None
                else None
            ),
            evaluation_count=payload["evaluation_count"],
            consecutive_blocks=payload["consecutive_blocks"],
            latest_reason=payload["latest_reason"],
            tokens_at_start=payload["tokens_at_start"],
        )
