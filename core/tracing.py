# code_harness/core/tracing.py
from contextvars import ContextVar
import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

TRACE_DIR = Path(__file__).resolve().parents[1] / "traces"
EASTERN_TIME = ZoneInfo("America/New_York")
_NESTED_LLM_CALLS: ContextVar[list[dict] | None] = ContextVar(
    "nested_llm_calls",
    default=None,
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
