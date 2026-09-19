# code_harness/core/tracing.py
import json
import re
import threading
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

TRACE_DIR = Path(__file__).resolve().parents[1] / "traces"
EASTERN_TIME = ZoneInfo("America/New_York")
_NESTED_LLM_CALLS: ContextVar[list[dict] | None] = ContextVar(
    "nested_llm_calls",
    default=None,
)
_GOAL_TRACE_LOCK = threading.Lock()
_SAFE_TRACE_ID = re.compile(r"[^A-Za-z0-9_.-]")
_SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|authorization|credential|password|secret|token)",
    re.IGNORECASE,
)
MAX_GOAL_TRACE_TEXT = 2_000
_INLINE_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|authorization|credential|password|secret|token)"
    r"\s*[:=]\s*([^\s]+)"
)


def utc_now_iso():
    return datetime.now(EASTERN_TIME).isoformat()


def record_nested_llm_call(event: dict) -> None:
    events = _NESTED_LLM_CALLS.get()
    if events is None:
        events = []
        _NESTED_LLM_CALLS.set(events)
    events.append(event)


def init_nested_llm_calls() -> list[dict]:
    events: list[dict] = []
    _NESTED_LLM_CALLS.set(events)
    return events


def pop_nested_llm_calls() -> list[dict]:
    events = _NESTED_LLM_CALLS.get() or []
    _NESTED_LLM_CALLS.set([])
    return events


def _sanitize_goal_trace_value(value: Any, key: str = "") -> Any:
    if _SENSITIVE_KEY.search(key):
        return "[redacted]"
    if isinstance(value, dict):
        return {
            str(item_key): _sanitize_goal_trace_value(item_value, str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_goal_trace_value(item) for item in value]
    if isinstance(value, str):
        value = _INLINE_SECRET.sub(r"\1=[redacted]", value)
        if len(value) > MAX_GOAL_TRACE_TEXT:
            return f"{value[:MAX_GOAL_TRACE_TEXT]}... [truncated]"
    return value


def record_goal_stage(
    stage: str,
    *,
    goal_id: str,
    conversation_id: str,
    event_id: str | None = None,
    run_id: str | None = None,
    background_task_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one sanitized lifecycle event to a goal-correlated JSONL trace."""
    event = {
        "stage": stage,
        "timestamp": utc_now_iso(),
        "goal_id": goal_id,
        "conversation_id": conversation_id,
        "event_id": event_id,
        "run_id": run_id,
        "background_task_id": background_task_id,
        "details": _sanitize_goal_trace_value(details or {}),
    }

    safe_goal_id = _SAFE_TRACE_ID.sub("_", goal_id)
    goal_trace_dir = TRACE_DIR / "goals"
    try:
        with _GOAL_TRACE_LOCK:
            goal_trace_dir.mkdir(parents=True, exist_ok=True)
            with (goal_trace_dir / f"{safe_goal_id}.jsonl").open(
                "a", encoding="utf-8"
            ) as trace_file:
                trace_file.write(json.dumps(event, ensure_ascii=False, default=str))
                trace_file.write("\n")
    except OSError:
        # Tracing must never prevent goal execution.
        pass
    return event


def save_trace(
    *,
    run_id: str,
    started_at: str,
    ended_at: str,
    user_input: str,
    conversation_id: str,
    messages,
    trace_type: str = "agent",
    parent_conversation_id: str | None = None,
):
    TRACE_DIR.mkdir(exist_ok=True)

    trace = {
        "run_id": run_id,
        "trace_type": trace_type,
        "conversation_id": conversation_id,
        "parent_conversation_id": parent_conversation_id,
        "started_at": started_at,
        "ended_at": ended_at,
        "user_input": user_input,
        "messages": [msg.to_trace_dict() for msg in messages],
        "nested_llm_calls": pop_nested_llm_calls(),
    }

    trace_path = TRACE_DIR / f"{trace_type}_{run_id}.json"
    trace_path.write_text(json.dumps(trace, indent=2, default=str), encoding="utf-8")
    return trace_path
