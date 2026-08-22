from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
import queue
import threading


@dataclass
class _PermissionRequest:
    prompt: str
    answer: str | None = None
    completed: threading.Event = field(default_factory=threading.Event)


class InputBroker:
    """Own stdin and route lines to permissions or normal user input."""

    def __init__(
        self,
        input_fn: Callable[[], str] = input,
        output_fn: Callable[[str], None] = print,
        flush_fn: Callable[[], None] | None = None,
    ):
        self._input_fn = input_fn
        self._output_fn = output_fn
        self._flush_fn = flush_fn
        self._user_inputs: queue.Queue[str | None] = queue.Queue()
        self._permission_requests: deque[_PermissionRequest] = deque()
        self._lock = threading.Lock()
        self._closed = False
        self._waiting_for_user = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._read_forever,
            daemon=True,
            name="input-broker",
        )
        self._thread.start()

    def get_user_input(self) -> str | None:
        """Wait for the next line that is not a permission response."""
        try:
            return self._user_inputs.get_nowait()
        except queue.Empty:
            pass

        with self._lock:
            self._waiting_for_user = True
            should_show_prompt = not self._permission_requests
        if should_show_prompt:
            self._emit("[bold cyan]you: [/bold cyan]")

        user_input = self._user_inputs.get()
        with self._lock:
            self._waiting_for_user = False
        return user_input

    def request_permission(self, prompt: str) -> str:
        """Wait until the input reader routes a response to this request."""
        request = _PermissionRequest(prompt=prompt)
        with self._lock:
            if self._closed:
                return "no"
            should_show_prompt = not self._permission_requests
            self._permission_requests.append(request)

        if should_show_prompt:
            self._emit(prompt)
        request.completed.wait()
        return request.answer or "no"

    def _emit(self, message: str) -> None:
        """Write a prompt and immediately flush interactive output."""
        self._output_fn(message)
        if self._flush_fn is not None:
            self._flush_fn()

    def refresh_user_prompt(self) -> None:
        """Redisplay the prompt if event output interrupted an active input wait."""
        with self._lock:
            should_show_prompt = (
                self._waiting_for_user
                and not self._permission_requests
                and not self._closed
            )
        if should_show_prompt:
            self._emit("[bold cyan]you: [/bold cyan]")

    def stop(self) -> None:
        """Stop accepting input; the daemon reader may remain blocked on stdin."""
        self._close()

    def _read_forever(self) -> None:
        while True:
            with self._lock:
                if self._closed:
                    return

            try:
                line = self._input_fn().strip()
            except (EOFError, KeyboardInterrupt):
                self._close()
                return

            with self._lock:
                if self._closed:
                    return
                request = (
                    self._permission_requests.popleft()
                    if self._permission_requests
                    else None
                )
                next_request = (
                    self._permission_requests[0]
                    if self._permission_requests
                    else None
                )
                show_user_prompt = (
                    request is not None
                    and next_request is None
                    and self._waiting_for_user
                )

            if request is None:
                self._user_inputs.put(line)
                continue

            request.answer = line
            request.completed.set()
            if next_request is not None:
                self._emit(next_request.prompt)
            elif show_user_prompt:
                self._emit("[bold cyan]you: [/bold cyan]")

    def _close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            pending = list(self._permission_requests)
            self._permission_requests.clear()

        for request in pending:
            request.answer = "no"
            request.completed.set()
        self._user_inputs.put(None)
