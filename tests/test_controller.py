#!/usr/bin/python3

from rpibuttons import gpio_driver, controller
from unittest.mock import MagicMock

class TestController:
    def test_button_configuration(self):
        gpioMock = MagicMock(spec=gpio_driver.GpioDriver)
        engine = controller.Engine(gpioMock, self)
        button = controller.Button(12, engine)
        gpioMock.configure_button.assert_called_once_with(12)
