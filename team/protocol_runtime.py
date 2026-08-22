import threading

from code_harness.team.protocol_manager import ProtocolManager
from code_harness.team.protocol_state import ProtocolState, ProtocolType


_lock = threading.RLock()
_protocol_manager: ProtocolManager | None = None


def get_protocol_manager() -> ProtocolManager:
    global _protocol_manager
    with _lock:
        if _protocol_manager is None:
            _protocol_manager = ProtocolManager()
        return _protocol_manager


def set_protocol_manager(manager: ProtocolManager | None) -> None:
    global _protocol_manager
    with _lock:
        _protocol_manager = manager


def match_response(
    response_type: ProtocolType | str,
    request_id: str,
    approve: bool,
) -> ProtocolState | None:
    return get_protocol_manager().process_response(
        response_type=response_type,
        request_id=request_id,
        approve=approve,
    )
