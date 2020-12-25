#!/usr/bin/python3

from __future__ import annotations
from rpibuttons import gpio_driver, controller
from unittest.mock import MagicMock, call
import pytest
import time
import asyncio
import threading
import typing

class TestController:
    @pytest.fixture
    def should_stop(self):
        return MagicMock(return_value=False)

    @pytest.fixture
    def gpio_driver(self) -> gpio_driver.GpioDriver:
        return MagicMock(spec=gpio_driver.GpioDriver)

    @pytest.fixture
    def engine(self, gpio_driver) -> controller.Engine:
        return controller.Engine(gpio_driver)

    @pytest.fixture
    def engine_in_thread(self, should_stop, engine) -> typing.Generator[controller.Engine, None, None]:
        engine.run_in_thread(should_stop=should_stop)
        yield engine
        should_stop.return_value = True

    def test_button_configuration(self, engine) -> None:
        """Checks the GPIO driver is used to configure a new button."""
        button = engine.make_button(12)
        engine.driver.configure_button.assert_called_once_with(12)

    @pytest.mark.asyncio
    @pytest.mark.timeout(7)
    async def test_engine_stop(self, engine) -> None:
        """Checks the stop predicate is called to stop the engine."""
        # Setup a mock for should_stop that makes the engine stop at the third
        # iteration.
        should_stop = MagicMock(side_effect=[False, False, True])

        # Run engine => returns once engine has stopped.
        await engine.run_async(should_stop)

        # Check should_stop was called for every iteration.
        should_stop.assert_has_calls((call(), call(), call()))

    def test_button_click(self, should_stop, engine_in_thread) -> None:
        button_states = {10: False, 11: False}
        engine_in_thread.driver.is_button_pressed = MagicMock(side_effect=lambda pin_id: button_states[pin_id])
        button10 = engine_in_thread.make_button(10)
        button11 = engine_in_thread.make_button(11)
        assert not button10.pressed
        assert not button11.pressed
        button_states[10] = True
        time.sleep(0.1)
        assert button10.pressed
        assert not button11.pressed
        button_states[11] = True
        time.sleep(0.1)
        assert button10.pressed
        assert button11.pressed
