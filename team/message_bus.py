import json
from pathlib import Path
import threading
import time
from typing import Any

from code_harness.events.models import EventType, new_event
from code_harness.events.runtime import get_event_queue
from code_harness.team.message_type import (
    MessageKind,
    MessageType,
    message_type_value,
)


_mailbox_lock = threading.RLock()


class MessageBus:

    def __init__(self, mail_box_dir: Path):
        self.mailbox_dir = mail_box_dir
        self.mailbox_dir.mkdir(parents=True, exist_ok=True)

    def send(
        self,
        from_agent: str,
        to_agent: str,
        content: str,
        msg_type: MessageKind = MessageType.MESSAGE,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        wire_type = message_type_value(msg_type)
        message = {
            "from": from_agent,
            "to": to_agent,
            "content": content,
            "type": wire_type,
            "ts": time.time(),
            "metadata": metadata or {},
        }

        inbox_path = self.mailbox_dir / f"{to_agent}.jsonl"
        with _mailbox_lock:
            with inbox_path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(message) + "\n")

        event_queue = get_event_queue()
        if to_agent == "lead" and event_queue is not None:
            event_queue.put(
                new_event(
                    EventType.TEAMMATE_MESSAGE,
                    (
                        "<teammate_message>\n"
                        f"{json.dumps(message)}\n"
                        "</teammate_message>"
                    ),
                    source=from_agent,
                    created_at=str(message["ts"]),
                    metadata={"message_type": wire_type},
                )
            )
            return

    def read_inbox(self, agent: str) -> list[dict]:
        inbox_path = self.mailbox_dir / f"{agent}.jsonl"

        with _mailbox_lock:
            if not inbox_path.exists():
                return []

            messages = [
                json.loads(line)
                for line in inbox_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            inbox_path.unlink()
        return messages

    def peek(self, agent: str) -> bool:
        inbox_path = self.mailbox_dir / f"{agent}.jsonl"
        return inbox_path.exists() and inbox_path.stat().st_size > 0
