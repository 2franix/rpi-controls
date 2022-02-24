#!/usr/bin/python3

import RPi.GPIO as GPIO
from . import gpio_driver
import logging
from typing import Callable, Optional
import time


class RpiGpioDriver(gpio_driver.GpioDriver):
    """Implementation of the GPIO driver interface based on `RPi.GPIO <https://pypi.org/project/RPi.GPIO/>`.
    This is the default driver for button controllers.
    """

    def __init__(self, mode: int = GPIO.BOARD):
        gpio_driver.GpioDriver.__init__(self)
        GPIO.setmode(mode)
        self._edge_callback: Optional[Callable[[int, gpio_driver.EdgeType], None]] = None
        self._bounce_times: dict[int, int] = {}  # Bounce time in ms indexed by pin id.

    def input(self, pin_id: int) -> bool:
        input_value: bool = GPIO.input(pin_id)
        logging.debug(f"Pin {pin_id} input state is {input_value}.")
        return input_value

    def configure_button(self, pin_id: int, pull: gpio_driver.PullType, bounce_time: int) -> None:
        # Parameters sanitizing.
        # - pull type:
        pull_up_down: int = 0
        if pull == gpio_driver.PullType.NONE:
            pull_up_down = GPIO.PUD_OFF
        elif pull == gpio_driver.PullType.UP:
            pull_up_down = GPIO.PUD_UP
        elif pull == gpio_driver.PullType.DOWN:
            pull_up_down = GPIO.PUD_DOWN
        else:
            raise Exception(f"Unsupported pull type {pull}")
        # - bounce time:
        if bounce_time < 0:
            raise ValueError(f"Bounce time {bounce_time} is not supported: must be positive.")

        # Make sure no button has been configured for this pin before.
        if pin_id in self._bounce_times:
            raise Exception(f"A button has already been configured for pin {pin_id}.")

        GPIO.setup(pin_id, GPIO.IN, pull_up_down=pull_up_down)
        self._bounce_times[pin_id] = bounce_time
        GPIO.add_event_detect(pin_id, GPIO.BOTH, callback=self._on_edge)
        logging.debug(f"Configured pin {pin_id} on GPIO.")

    def unconfigure_button(self, pin_id: int) -> None:
        if pin_id not in self._bounce_times:
            raise Exception(f"No button configured for pin {pin_id}.")
        del self._bounce_times[pin_id]
        GPIO.remove_event_detect(pin_id)

    def _on_edge(self, pin_id: int) -> None:
        # In case edge is called while button is being unconfigured, abort.
        bounce_time: Optional[int] = self._bounce_times.get(pin_id, None)
        if bounce_time is None:
            return

        time.sleep(bounce_time / 1000.0)
        edge: gpio_driver.EdgeType = gpio_driver.EdgeType.RISING if GPIO.input(pin_id) else gpio_driver.EdgeType.FALLING
        if self._edge_callback:
            self._edge_callback(pin_id, edge)

    def set_edge_callback(self, callback: Callable[[int, gpio_driver.EdgeType], None]):
        self._edge_callback = callback
