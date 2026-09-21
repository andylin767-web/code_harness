from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class RuntimeServices:
    """Explicit dependencies shared by tools and long-lived runtime components."""

    state_root: Path
    event_queue: Any
    input_broker: Any
    scheduler: Any
    message_bus: Any
    protocol_manager: Any
    settings_path: Path | None = None
    task_manager: Any | None = None
    worktree_manager: Any | None = None
    lead_inbox: Any | None = None
    lead_agent: Any | None = None
