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
    def gpio_driver(self) -> gpio_driver.GpioDriver:
        return MagicMock(spec=gpio_driver.GpioDriver)

    @pytest.fixture
    def engine(self, gpio_driver) -> controller.Engine:
        return controller.Engine(gpio_driver)

    @pytest.fixture
    def engine_in_thread(self, engine) -> typing.Generator[controller.Engine, None, None]:
        engine.run_in_thread()
        yield engine
        engine.stop()

    def test_button_configuration(self, engine) -> None:
        """Checks the GPIO driver is used to configure a new button."""
        button = engine.make_button(12)
        engine.driver.configure_button.assert_called_once_with(12)

    def test_button_update(self, engine_in_thread) -> None:
        """Checks that buttons update their pressed state as expected."""
        # Mock the GPIO for button pressed status.
        button_states = {10: False, 11: False}
        engine_in_thread.driver.is_button_pressed = MagicMock(side_effect=lambda pin_id: button_states[pin_id])

        # Create two buttons.
        button10 = engine_in_thread.make_button(10)
        button11 = engine_in_thread.make_button(11)

        # According to our GPIO mock, they should not be 'pressed'.
        assert not button10.pressed
        assert not button11.pressed

        # Alter mock so that first button should now be pressed.
        button_states[10] = True

        # Give some time for the engine to update.
        time.sleep(0.1)

        # Check pressed state again.
        assert button10.pressed
        assert not button11.pressed

        # Alter mock once again so that all buttons are pressed and wait for
        # update. Last, check button states.
        button_states[11] = True
        time.sleep(0.1)
        assert button10.pressed
        assert button11.pressed

    @pytest.mark.asyncio
    @pytest.mark.timeout(7)
    async def test_on_click_event(self, engine_in_thread) -> None:
        # Prepare a mocked event handler.
        callback_mock = MagicMock()
        async def event_callback_mock(button: controller.Button) -> None:
            callback_mock(button)

        # Setup mocked GPIO driver.
        pressed: bool = False
        engine_in_thread.driver.is_button_pressed = lambda pin_id: pressed

        # Create a button and subscribe to its click event.
        button: controller.Button = engine_in_thread.make_button(2)
        button.add_on_click(event_callback_mock)

        # Give the engine some time to update. Event should not be raised.
        time.sleep(0.1)
        callback_mock.assert_not_called()

        # Change button state to pressed, wait for an update => event should not
        # be raised yet (it is when button is released).
        pressed = True
        time.sleep(0.1)
        assert button.pressed
        callback_mock.assert_not_called()

        # Release button => event should be called once.
        pressed = False
        time.sleep(0.1)
        assert not button.pressed
        callback_mock.assert_called_once_with(button)
