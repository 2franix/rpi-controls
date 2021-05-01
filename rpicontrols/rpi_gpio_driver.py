#!/usr/bin/python3

import RPi.GPIO as GPIO
from . import gpio_driver
import logging
from typing import Callable
import time

class RpiGpioDriver(gpio_driver.GpioDriver):
    def __init__(self):
        gpio_driver.GpioDriver.__init__(self)
        GPIO.setmode(GPIO.BOARD)
        self._edge_callback: Callable[[int, gpio_driver.EdgeType], None] = None

    def input(self, pin_id: int) -> bool:
        input_value: bool = GPIO.input(pin_id)
        logging.debug(f'Pin {pin_id} input state is {input_value}.')
        return input_value

    def configure_button(self, pin_id: int, pull: gpio_driver.PullType) -> None:
        pull_up_down: int = 0
        if pull == gpio_driver.PullType.NONE:
            pull_up_down = GPIO.PUD_OFF
        elif pull == gpio_driver.PullType.UP:
            pull_up_down = GPIO.PUD_UP
        elif pull == gpio_driver.PullType.DOWN:
            pull_up_down = GPIO.PUD_DOWN
        else:
            raise Exception('Unsupported pull type {pull}')

        GPIO.setup(pin_id, GPIO.IN, pull_up_down=pull_up_down)
        GPIO.add_event_detect(pin_id, GPIO.BOTH, callback=self._on_edge)
        logging.debug(f'Configured pin {pin_id} on GPIO.')

    def _on_edge(self, pin_id: int) -> None:
        bounce_time = 0.010 #seconds => 10 milliseconds
        time.sleep(bounce_time)
        edge: gpio_driver.EdgeType = gpio_driver.EdgeType.RISING if GPIO.input(pin_id) else gpio_driver.EdgeType.FALLING
        if self._edge_callback:
            self._edge_callback(pin_id, edge)

    def set_edge_callback(self, callback: Callable[[int, gpio_driver.EdgeType], None]):
        self._edge_callback = callback
