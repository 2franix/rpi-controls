#!/usr/bin/python3

import RPi.GPIO as GPIO
from . import gpio_driver

class RpiGpioDriver(gpio_driver.GpioDriver):
    def __init__(self):
        IGpioDriver.__init__(self)
        assert not INSTANCE, "RpiGpioDriver has already been initialized."
        INSTANCE = self
        GPIO.setmode(GPIO.BOARD)

    def is_button_pressed(self, pin_id: int) -> bool:
        return GPIO.input(pin_id)

    def configure_button(self, pin_id: int) -> None:
        GPIO.setup(pin_id, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
