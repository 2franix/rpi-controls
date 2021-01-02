#!/usr/bin/python3

from __future__ import annotations
from rpibuttons import gpio_driver, controller
from unittest.mock import MagicMock, call
import pytest
import time
import asyncio
import threading
from typing import Callable, Coroutine, Any, Generator

class TestController:
    @pytest.fixture
    def gpio_driver_mock(self) -> gpio_driver.GpioDriver:
        return MagicMock(spec=gpio_driver.GpioDriver)

    @pytest.fixture
    def contrller(self, gpio_driver_mock: gpio_driver.GpioDriver) -> controller.Controller:
        return controller.Controller(gpio_driver_mock)

    @pytest.fixture
    def controller_in_thread(self, contrller: controller.Controller) -> Generator[controller.Controller, None, None]:
        contrller.run_in_thread()
        yield contrller
        contrller.stop()

    def test_button_configuration(self, contrller) -> None:
        """Checks the GPIO driver is used to configure a new button."""
        button = contrller.make_button(12)
        contrller.driver.configure_button.assert_called_once_with(12)

    def test_button_update(self, controller_in_thread) -> None:
        """Checks that buttons update their pressed state as expected."""
        # Mock the GPIO for button pressed status.
        button_states = {10: False, 11: False}
        controller_in_thread.driver.is_button_pressed = MagicMock(side_effect=lambda pin_id: button_states[pin_id])

        # Create two buttons.
        button10 = controller_in_thread.make_button(10)
        button11 = controller_in_thread .make_button(11)

        # According to our GPIO mock, they should not be 'pressed'.
        assert not button10.pressed
        assert not button11.pressed

        # Alter mock so that first button should now be pressed.
        button_states[10] = True

        # Give some time for the controller to update.
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
    async def test_press_release_click_events(self, controller_in_thread: controller.Controller) -> None:
        # Setup mocked GPIO driver.
        pressed: bool = False
        driver: Any = controller_in_thread.driver # Downgrades type hint to allow assignment of the is_button_pressed method (see mypy issue 2427)
        driver.is_button_pressed = lambda pin_id: pressed

        # Create a button and subscribe to its events.
        button: controller.Button = controller_in_thread.make_button(2)
        listener = ButtonListener(button)

        # Give the controller some time to update. Event should not be raised.
        iteration_sleep = controller_in_thread.iteration_sleep * 2
        time.sleep(iteration_sleep)
        listener.assert_calls()

        # Change button state to pressed, wait for an update => click event should not
        # be raised yet (it is when button is released).
        pressed = True
        press_time = time.time()
        await asyncio.sleep(iteration_sleep)
        assert button.pressed
        listener.assert_calls(press = 1)

        # Release button => event should not be called until double click
        # timeout is reached.
        pressed = False
        await asyncio.sleep(button.double_click_timeout - time.time() + press_time)
        assert not button.pressed
        listener.assert_calls(press = 1, release = 1)

        # Now double click timeout has been reached, click should happen.
        await asyncio.sleep(iteration_sleep)
        listener.assert_calls(press = 1, release = 1, click = 1)

        # Click again. Event handler should be called immediately, even though
        # the first execution is still running.
        pressed = True
        press_time = time.time()
        await asyncio.sleep(iteration_sleep)
        pressed = False
        await asyncio.sleep(button.double_click_timeout - time.time() + press_time + iteration_sleep)
        assert not button.pressed
        listener.assert_calls(press = 2, release = 2, click = 2)

    @pytest.mark.asyncio
    @pytest.mark.timeout(7)
    async def test_long_press_double_click_events(self, controller_in_thread: controller.Controller) -> None:
        # Setup mocked GPIO driver.
        pressed: bool = False
        driver: Any = controller_in_thread.driver # Downgrades type hint to allow assignment of the is_button_pressed method (see mypy issue 2427)
        driver.is_button_pressed = lambda pin_id: pressed

        # Create a button and subscribe to its click event.
        button: controller.Button = controller_in_thread.make_button(2)
        button.long_press_timeout = 0.4
        button.double_click_timeout = 0.3
        async def nothing(): pass
        listener = ButtonListener(button, nothing)

        # Give the controller some time to update. Event should not be raised.
        iteration_sleep = controller_in_thread.iteration_sleep * 2
        time.sleep(iteration_sleep)
        listener.assert_calls()

        # Change button state to pressed and wait for long press.
        pressed = True
        press_time = time.time()
        await asyncio.sleep(button.long_press_timeout + iteration_sleep)
        assert button.pressed
        assert button.long_pressed
        listener.assert_calls(press = 1, long_press = 1)

        # Release button, click event should be raised immediately since
        # the double click timeout has been reached (it's too late to hope for a
        # double click).
        pressed = False
        await asyncio.sleep(iteration_sleep)
        assert not button.pressed
        assert not button.long_pressed
        listener.assert_calls(press = 1, long_press = 1, release = 1, click = 1)

        # Perform a double click.
        assert not pressed # Make sure we start off with the expected state.
        for i in range(4):
            pressed = not pressed
            await asyncio.sleep(iteration_sleep)
        listener.assert_calls(press = 3, long_press = 1, release = 3, click = 1, double_click = 1)

class ButtonListener:
    def __init__(self, button: controller.Button, common_event_handler: Callable[[], Coroutine[Any, Any, Any]] = None):
        assert not button is None
        self.button: controller.Button = button
        self.press_call_count: int = 0
        self.long_press_call_count: int = 0
        self.release_call_count: int = 0
        self.click_call_count: int = 0
        self.double_click_call_count: int = 0
        self.button.add_on_press(self.on_press)
        self.button.add_on_long_press(self.on_long_press)
        self.button.add_on_release(self.on_release)
        self.button.add_on_click(self.on_click)
        self.button.add_on_double_click(self.on_double_click)
        self._common_event_handler: Callable[[], Coroutine[Any, Any, Any]] = self._default_common_event_handler
        if common_event_handler is not None:
            self._common_event_handler = common_event_handler

    async def _default_common_event_handler(self):
        await asyncio.sleep(2)

    async def on_press(self, button: controller.Button) -> None:
        assert button == self.button
        assert button.pressed
        self.press_call_count += 1
        await self._common_event_handler()

    async def on_long_press(self, button: controller.Button) -> None:
        assert button == self.button
        assert button.pressed
        assert button.long_pressed
        self.long_press_call_count += 1
        await self._common_event_handler()

    async def on_release(self, button: controller.Button) -> None:
        assert button == self.button
        assert not button.pressed
        assert not button.long_pressed
        self.release_call_count += 1
        await self._common_event_handler()

    async def on_click(self, button: controller.Button) -> None:
        assert button == self.button
        self.click_call_count += 1
        await self._common_event_handler()

    async def on_double_click(self, button: controller.Button) -> None:
        assert button == self.button
        self.double_click_call_count += 1
        await self._common_event_handler()

    def assert_calls(self, press: int = 0, long_press: int = 0, release: int = 0, click: int = 0, double_click: int = 0):
        assert self.press_call_count == press
        assert self.long_press_call_count == long_press
        assert self.release_call_count == release
        assert self.click_call_count == click
        assert self.double_click_call_count == double_click
