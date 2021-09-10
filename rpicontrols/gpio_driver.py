#!/usr/bin/python3

from __future__ import annotations
import enum
from typing import Callable
from abc import ABC, abstractmethod


class PullType(enum.Enum):
    NONE = 1
    UP = 2
    DOWN = 3


class EdgeType(enum.Enum):

    RISING = 1
    FALLING = 2


class GpioDriver(ABC):
    @abstractmethod
    def input(self, pin_id: int) -> bool:
        pass

    @abstractmethod
    def configure_button(self, pin_id: int, pull: PullType, bounce_time: int) -> None:
        pass

    @abstractmethod
    def unconfigure_button(self, pin_id: int) -> None:
        pass

    @abstractmethod
    def set_edge_callback(self, callback: Callable[[int, EdgeType], None]):
        pass
