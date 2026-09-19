import json
import threading
import time
from dataclasses import asdict
from pathlib import Path

from code_harness.team.protocol_state import (
    ProtocolState,
    ProtocolStatus,
    ProtocolType,
    generate_request_id,
)

DEFAULT_PROTOCOL_PATH = Path(__file__).resolve().parents[1] / ".protocol_requests.json"

RESPONSE_TYPE_BY_REQUEST_TYPE = {
    ProtocolType.SHUTDOWN_REQUEST: ProtocolType.SHUTDOWN_RESPONSE,
    ProtocolType.PLAN_APPROVAL_REQUEST: (ProtocolType.PLAN_APPROVAL_RESPONSE),
}


class ProtocolManager:
    """Manage protocol request lifecycle and durable state."""

    def __init__(
        self,
        path: Path | None = None,
        request_ttl_seconds: float = 300.0,
    ):
        if request_ttl_seconds < 0:
            raise ValueError("request_ttl_seconds must be non-negative")
        self.path = path or DEFAULT_PROTOCOL_PATH
        self.request_ttl_seconds = request_ttl_seconds
        self.pending_requests: dict[str, ProtocolState] = {}
        self._lock = threading.RLock()

    def create_request(
        self,
        *,
        type: ProtocolType | str,
        sender: str,
        target: str,
        payload: str,
        request_id: str | None = None,
        created_at: float | None = None,
    ) -> ProtocolState:
        protocol_type = ProtocolType(type)
        if protocol_type not in RESPONSE_TYPE_BY_REQUEST_TYPE:
            raise ValueError(
                f"Cannot create a request with response type: {protocol_type.value}"
            )
        state = ProtocolState(
            type=protocol_type,
            sender=sender,
            target=target,
            payload=payload,
            request_id=request_id or generate_request_id(),
            created_at=(
                round(time.time(), 3) if created_at is None else round(created_at, 3)
            ),
        )
        with self._lock:
            if state.request_id in self.pending_requests:
                raise ValueError(f"Protocol request already exists: {state.request_id}")
            self.pending_requests[state.request_id] = state
        return state

    def get_request(self, request_id: str) -> ProtocolState | None:
        with self._lock:
            return self.pending_requests.get(request_id)

    def approve(self, request_id: str) -> ProtocolState:
        return self._transition(
            request_id,
            expected=ProtocolStatus.PENDING,
            target=ProtocolStatus.APPROVED,
        )

    def reject(self, request_id: str) -> ProtocolState:
        return self._transition(
            request_id,
            expected=ProtocolStatus.PENDING,
            target=ProtocolStatus.REJECTED,
        )

    def process_response(
        self,
        response_type: ProtocolType | str,
        request_id: str,
        approve: bool,
    ) -> ProtocolState | None:
        """Validate and correlate a response before resolving its request."""
        with self._lock:
            state = self.pending_requests.get(request_id)
            if state is None:
                print(f"  \033[31m[protocol] unknown request_id: {request_id}\033[0m")
                return None

            expected_response_type = RESPONSE_TYPE_BY_REQUEST_TYPE.get(state.type)
            try:
                actual_response_type = ProtocolType(response_type)
            except ValueError:
                actual_response_type = None

            if actual_response_type is not expected_response_type:
                expected_value = (
                    expected_response_type.value
                    if expected_response_type is not None
                    else "no response type"
                )
                print(
                    f"  \033[31m[protocol] type mismatch: expected "
                    f"{expected_value}, got {response_type}\033[0m"
                )
                return None

            target_status = (
                ProtocolStatus.APPROVED if approve else ProtocolStatus.REJECTED
            )
            resolved, transitioned = self._try_transition(
                request_id,
                expected=ProtocolStatus.PENDING,
                target=target_status,
            )
            if not transitioned:
                print(
                    f"  \033[33m[protocol] {request_id} already "
                    f"{resolved.status.value}, ignoring duplicate\033[0m"
                )
                return None

        icon = "✓" if approve else "✗"
        color = "32" if approve else "31"
        print(
            f"  \033[{color}m[protocol] {state.type.value} {icon} "
            f"({request_id}: {resolved.status.value})\033[0m"
        )
        return resolved

    def cancel(self, request_id: str) -> ProtocolState:
        with self._lock:
            state = self._require_request(request_id)
            if state.status is not ProtocolStatus.PENDING:
                raise ValueError(
                    f"Cannot cancel {request_id} with status {state.status}"
                )
            return self.remove(request_id)

    def complete(self, request_id: str) -> ProtocolState:
        with self._lock:
            state = self._require_request(request_id)
            if state.status not in {
                ProtocolStatus.APPROVED,
                ProtocolStatus.REJECTED,
            }:
                raise ValueError(
                    f"Cannot complete {request_id} with status {state.status}"
                )
            return self.remove(request_id)

    def remove(self, request_id: str) -> ProtocolState:
        with self._lock:
            try:
                return self.pending_requests.pop(request_id)
            except KeyError as exc:
                raise KeyError(f"Protocol request not found: {request_id}") from exc

    def expire_requests(self, now: float | None = None) -> list[ProtocolState]:
        cutoff = (time.time() if now is None else now) - self.request_ttl_seconds
        with self._lock:
            expired_ids = [
                request_id
                for request_id, state in self.pending_requests.items()
                if state.created_at <= cutoff
            ]
            return [self.pending_requests.pop(request_id) for request_id in expired_ids]

    def save(self) -> Path:
        with self._lock:
            payload = [
                {
                    **asdict(state),
                    "type": state.type.value,
                    "status": state.status.value,
                }
                for state in self.pending_requests.values()
            ]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
            temporary_path.write_text(
                json.dumps(payload, indent=2),
                encoding="utf-8",
            )
            temporary_path.replace(self.path)
        return self.path

    def load(self) -> int:
        if not self.path.exists():
            return 0

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return 0
        if not isinstance(payload, list):
            return 0

        loaded: dict[str, ProtocolState] = {}
        for item in payload:
            if not isinstance(item, dict):
                continue
            try:
                state = ProtocolState(
                    request_id=item["request_id"],
                    type=ProtocolType(item["type"]),
                    sender=item["sender"],
                    target=item["target"],
                    status=ProtocolStatus(item["status"]),
                    payload=item["payload"],
                    created_at=round(float(item["created_at"]), 3),
                )
            except (KeyError, TypeError, ValueError):
                continue
            loaded[state.request_id] = state

        with self._lock:
            self.pending_requests = loaded
        return len(loaded)

    def _transition(
        self,
        request_id: str,
        *,
        expected: ProtocolStatus,
        target: ProtocolStatus,
    ) -> ProtocolState:
        state, transitioned = self._try_transition(
            request_id,
            expected=expected,
            target=target,
        )
        if not transitioned:
            raise ValueError(
                f"Cannot transition {request_id} from {state.status} to {target}"
            )
        return state

    def _try_transition(
        self,
        request_id: str,
        *,
        expected: ProtocolStatus,
        target: ProtocolStatus,
    ) -> tuple[ProtocolState, bool]:
        """Atomically transition a request, returning whether it changed."""
        with self._lock:
            state = self._require_request(request_id)
            if state.status is not expected:
                return state, False
            state.status = target
            return state, True

    def _require_request(self, request_id: str) -> ProtocolState:
        with self._lock:
            state = self.pending_requests.get(request_id)
            if state is None:
                raise KeyError(f"Protocol request not found: {request_id}")
            return state
