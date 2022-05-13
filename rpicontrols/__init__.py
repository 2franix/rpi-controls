#!/usr/bin/python3

# This file is part of rpi-controls.
#
# rpi-controls is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# rpi-controls is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with rpi-controls.  If not, see <https://www.gnu.org/licenses/>.

from typing import Optional
import importlib_metadata

from .controller import Controller as Controller
from .controller import Button as Button
from .gpio_driver import GpioDriver as GpioDriver
from .gpio_driver import PullType as PullType

# Define public modules and functions.
__all__ = ["Controller", "Button", "GpioDriver", "PullType", "make_controller"]
__version__ = importlib_metadata.version("rpi-controls")


def make_controller(gpio_driver: Optional[GpioDriver] = None) -> Controller:
    """Creates a new instance of a button controller. One instance of a controller is required
    to work with any number of buttons, so a call to this function is mandatory when initializing
    the client code.

    :param gpio_driver: object abstracting access to the GPIO, defaults to None in which case
        an implementation based on `RPi.GPIO <https://pypi.org/project/RPi.GPIO/>`_ will be
        used (see :class:`rpicontrols.rpi_gpio_driver.RpiGpioDriver`).
        This parameter is unlikely to require a different value in a production context.
        It is mostly here to help mocking the GPIO access when testing.
    :rtype: A new controller, accepting button declaration and ready to be started.
    """
    if not gpio_driver:
        from . import rpi_gpio_driver

        gpio_driver = rpi_gpio_driver.RpiGpioDriver()
    return Controller(gpio_driver)
