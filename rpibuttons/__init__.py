#!/usr/bin/python3

# This file is part of Foobar.
# 
# Foobar is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# Foobar is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with Foobar.  If not, see <https://www.gnu.org/licenses/>.

from . import controller, gpio_driver

def make_controller(gpio_driver: gpio_driver.GpioDriver = None) -> controller.Controller:
    if not gpio_driver:
        from . import rpi_gpio_driver
        gpio_driver = rpi_gpio_driver.RpiGpioDriver()
    return controller.Controller(gpio_driver)
