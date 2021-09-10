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

import typing
from .controller import Controller, Button
from .gpio_driver import GpioDriver, PullType

# Define public modules and functions.
__all__: typing.Sequence[str] = [m.__name__ for m in (Controller, Button, GpioDriver, PullType)] + ['make_controller']
__version__ = '1.0.0'


def make_controller(gpio_driver: GpioDriver = None) -> Controller:
    if not gpio_driver:
        from . import rpi_gpio_driver
        gpio_driver = rpi_gpio_driver.RpiGpioDriver()
    return Controller(gpio_driver)
