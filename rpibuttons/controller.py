#!/usr/bin/python3

from __future__ import annotations # PEP 563
import time
import threading
import subprocess
import signal
import os
from collections.abc import Callable
from . import gpio_driver

status = 'off'
stopped = False
buttonPressedRisingEdgeTimestamp = None # Timestamp of the last button pressed event.

class Engine:
    def __init__(self, driver: gpio_driver.GpioDriver, value: int):
        self.driver = driver

    def configure_button(self, pin_id: int) -> None:
        self.driver.configure_button(pin_id)

class Button:
    def __init__(self, pin_id: int, engine: Engine):
        assert engine, "No engine."
        self._engine = engine
        self.pin_id = pin_id
        self._click_handlers = []
        self._double_click_handlers = []
        self._engine.configure_button(self.pin_id)

    def add_on_click(self, func: Callable[[Button], None]) -> None:
        self._click_handlers.append(func)

    def remove_on_click(self, func) -> None:
        self._click_handlers.remove(func)

    def add_on_double_click(self, func) -> None:
        self._double_click_handlers.append(func)

    def remove_on_double_click(self, func) -> None:
        self._double_click_handlers.remove(func)
