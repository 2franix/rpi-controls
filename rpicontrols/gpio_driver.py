#!/usr/bin/python3

from __future__ import annotations
import enum
from typing import Callable

class PullType(enum.Enum):
    NONE = 1
    UP = 2
    DOWN = 3

class GpioDriver:
    def input(self, pin_id: int) -> bool:
        raise NotImplementedError("Missing function 'input'.")

    def configure_button(self, pin_id: int, pull: PullType) -> None:
        raise NotImplementedError("Missing function 'configure_button'.")

    def set_edge_callback(self, callback: Callable[[int], None]):
        raise NotImplementedError("Missing function 'set_edge_callback'.")
