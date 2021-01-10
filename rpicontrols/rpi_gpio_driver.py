#!/usr/bin/python3

import RPi.GPIO as GPIO
from . import gpio_driver
import logging

class RpiGpioDriver(gpio_driver.GpioDriver):
    def __init__(self):
        gpio_driver.GpioDriver.__init__(self)
        GPIO.setmode(GPIO.BOARD)

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
        logging.debug(f'Configured pin {pin_id} on GPIO.')
