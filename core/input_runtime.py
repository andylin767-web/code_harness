from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from code_harness.core.input_broker import InputBroker


_input_broker: "InputBroker | None" = None


def set_input_broker(input_broker: "InputBroker | None") -> None:
    global _input_broker
    _input_broker = input_broker


def get_input_broker() -> "InputBroker | None":
    return _input_broker
