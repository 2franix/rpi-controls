#!/usr/bin/python3

from __future__ import annotations
from rpibuttons import gpio_driver, controller
from unittest.mock import MagicMock, call
import pytest
import time
import asyncio
import threading
from typing import Optional, Callable, Coroutine, Any, Generator

class TestController:
    @pytest.fixture
    def gpio_driver_mock(self) -> gpio_driver.GpioDriver:
        return MagicMock(spec=gpio_driver.GpioDriver)

    @pytest.fixture
    def contrller(self, gpio_driver_mock: gpio_driver.GpioDriver) -> controller.Controller:
        c = controller.Controller(gpio_driver_mock)
        assert c.status == controller.Controller.Status.READY
        return c

    @pytest.fixture
    def controller_in_thread(self, contrller: controller.Controller) -> Generator[controller.Controller, None, None]:
        # Start controller in a separate thread.
        contrller.run_in_thread()
        assert contrller.status == controller.Controller.Status.RUNNING

        # Let the test use it.
        yield contrller

        # Stop it.
        contrller.stop()
        assert contrller.status == controller.Controller.Status.STOPPED

    def test_button_name(self, contrller: controller.Controller) -> None:
        button_with_default_name = contrller.make_button(10)
        assert button_with_default_name.name == 'button for pin 10'
        button_with_explicit_name = contrller.make_button(11, 'Light ON/OFF')
        assert button_with_explicit_name.name == 'Light ON/OFF'

    def test_button_configuration(self, contrller) -> None:
        """Checks the GPIO driver is used to configure a new button."""
        button = contrller.make_button(12)
        contrller.driver.configure_button.assert_called_once_with(12)

    def test_button_update(self, controller_in_thread) -> None:
        """Checks that buttons update their pressed state as expected."""
        # Mock the GPIO for button pressed status.
        button_states = {10: False, 11: False}
        controller_in_thread.driver.input = MagicMock(side_effect=lambda pin_id: button_states[pin_id])

        # Create two buttons.
        button10 = controller_in_thread.make_button(10)
        button11 = controller_in_thread .make_button(11, contact_type = controller.ContactType.NORMALLY_CLOSED)

        # According to our GPIO mock, their GPIO pins are not active.
        assert not button10.pressed # Normally open.
        assert button11.pressed # Normally closed.

        # Alter mock so that pin of first button is now active.
        button_states[10] = True

        # Give some time for the controller to update.
        time.sleep(0.1)

        # Check pressed state again.
        assert button10.pressed
        assert button11.pressed # Normally closed.

        # Alter mock once again so that both pins are active and wait for
        # update. Last, check button states.
        button_states[11] = True
        time.sleep(0.1)
        assert button10.pressed
        assert not button11.pressed

    @pytest.mark.asyncio
    @pytest.mark.timeout(5)
    async def test_illegal_start(self, controller_in_thread: controller.Controller) -> None:
        # Controller is expected to be already running. Start it again to make
        # sure we handle that gracefully.
        assert controller_in_thread.status == controller.Controller.Status.RUNNING
        with pytest.raises(Exception):
            # Do not call run_in_thread here, because exception would be raised
            # on another thread. This thread would not see it.
            controller_in_thread.run()

        # Make sure the controller is still running.
        assert controller_in_thread.status == controller.Controller.Status.RUNNING

        # Stop it and try to restart => not supported.
        await controller_in_thread.stop_async()
        with pytest.raises(Exception):
            controller_in_thread.run()

    @pytest.mark.timeout(7)
    def test_press_release_click_events(self, controller_in_thread: controller.Controller) -> None:
        # Setup mocked GPIO driver.
        pressed: bool = False
        driver: Any = controller_in_thread.driver # Downgrades type hint to allow assignment of the input method (see mypy issue 2427)
        driver.input = lambda pin_id: pressed

        # Create a button and subscribe to its events.
        button: controller.Button = controller_in_thread.make_button(2)
        async def wait_2_secs():
            await asyncio.sleep(2)
        listener = ButtonListener(button, common_event_handler = wait_2_secs)

        # Give the controller some time to update. Event should not be raised.
        iteration_sleep = controller_in_thread.iteration_sleep * 2
        time.sleep(iteration_sleep)
        listener.assert_calls()

        # Change button state to pressed, wait for an update => click event should not
        # be raised yet (it is when button is released).
        pressed = True
        press_time = time.time()
        time.sleep(iteration_sleep)
        assert button.pressed
        listener.assert_calls(press = 1)

        # Release button => event should not be called until double click
        # timeout is reached.
        pressed = False
        time.sleep(0.9*button.double_click_timeout - time.time() + press_time)
        assert not button.pressed
        listener.assert_calls(press = 1, release = 1)

        # Now double click timeout has been reached, click should happen.
        time.sleep(0.2*button.double_click_timeout + iteration_sleep)
        listener.assert_calls(press = 1, release = 1, click = 1)

        # Click again. Event handler should be called immediately, even though
        # the first execution is still running.
        pressed = True
        press_time = time.time()
        time.sleep(iteration_sleep)
        pressed = False
        time.sleep(button.double_click_timeout - time.time() + press_time + iteration_sleep)
        assert not button.pressed
        listener.assert_calls(press = 2, release = 2, click = 2)

    @pytest.mark.timeout(7)
    def test_long_press_double_click_events(self, controller_in_thread: controller.Controller) -> None:
        # Setup mocked GPIO driver.
        pressed: bool = False
        driver: Any = controller_in_thread.driver # Downgrades type hint to allow assignment of the input method (see mypy issue 2427)
        driver.input = lambda pin_id: pressed

        # Create a button and subscribe to its click event.
        button: controller.Button = controller_in_thread.make_button(2)
        button.long_press_timeout = 0.4
        button.double_click_timeout = 0.3
        async def wait_2_secs():
            await asyncio.sleep(2)
        listener = ButtonListener(button, common_event_handler = wait_2_secs)

        # Give the controller some time to update. Event should not be raised.
        iteration_sleep = controller_in_thread.iteration_sleep * 2
        time.sleep(iteration_sleep)
        listener.assert_calls()

        # Change button state to pressed and wait for long press.
        pressed = True
        time.sleep(button.long_press_timeout + iteration_sleep)
        assert button.pressed
        assert button.long_pressed
        listener.assert_calls(press = 1, long_press = 1)

        # Release button, click event should be raised immediately since
        # the double click timeout has been reached (it's too late to hope for a
        # double click).
        pressed = False
        time.sleep(iteration_sleep)
        assert not button.pressed
        assert not button.long_pressed
        listener.assert_calls(press = 1, long_press = 1, release = 1, click = 1)

        # Perform a double click.
        assert not pressed # Make sure we start off with the expected state.
        for i in range(4):
            pressed = not pressed
            time.sleep(iteration_sleep)
        listener.assert_calls(press = 3, long_press = 1, release = 3, click = 1, double_click = 1)

    def test_exception_in_event_handler(self, controller_in_thread: controller.Controller) -> None:
        """Makes sure the controller handles in exceptions thrown by event handlers."""

        # Setup mocked GPIO driver.
        pressed: bool = False
        driver: Any = controller_in_thread.driver # Downgrades type hint to allow assignment of the input method (see mypy issue 2427)
        driver.input = lambda pin_id: pressed

        # Create a button and subscribe to its events.
        button: controller.Button = controller_in_thread.make_button(2)
        async def raise_exception():
            raise Exception('Mocks a problem in the event handler!')
        listener = ButtonListener(button, common_event_handler=raise_exception)

        # Press a button.
        pressed = True
        iteration_sleep = controller_in_thread.iteration_sleep * 2
        time.sleep(iteration_sleep)
        listener.assert_calls(press=1)

        # Release button => release should be raised even though there was an
        # exception while handling the previous event. That means the controller
        # is still alive.
        pressed = False
        time.sleep(iteration_sleep)
        listener.assert_calls(press = 1, release = 1)

    @pytest.mark.asyncio
    @pytest.mark.timeout(5)
    async def test_exception_in_event_handler_when_stopping(self, controller_in_thread: controller.Controller) -> None:
        """Makes sure the controller handles in exceptions thrown by event handlers."""

        # Setup mocked GPIO driver.
        pressed: bool = False
        driver: Any = controller_in_thread.driver # Downgrades type hint to allow assignment of the input method (see mypy issue 2427)
        driver.input = lambda pin_id: pressed

        # Create a button and subscribe to its events.
        button: controller.Button = controller_in_thread.make_button(2)

        # Make event handler last long enough so that it is still
        # running when we stop the controller.
        # In that scenario, the Future corresponding
        # to the event handler is awaited differently. What may work
        # when the controller is running may fail here, then.
        async def raise_exception_with_delay():
            if not controller_in_thread.is_stopping:
                await asyncio.sleep(0.01)
            # Wait a little more to make sure the controller has reached the
            # point where it waits for the event handlers to complete.
            await asyncio.sleep(0.5)
            raise Exception('Mocks a problem in the event handler!')
        listener = ButtonListener(button, common_event_handler=raise_exception_with_delay)
        pressed = True
        iteration_sleep = controller_in_thread.iteration_sleep * 2
        await asyncio.sleep(iteration_sleep) # So that event is raised BEFORE stopping.
        await controller_in_thread.stop_async() # Explicit stop as this is part of the tested scenario. But the fixture would have stopped it anyway.
        assert controller_in_thread.status == controller.Controller.Status.STOPPED
        listener.assert_calls(press = 1)

    @pytest.mark.asyncio
    @pytest.mark.timeout(5)
    async def test_gpio_changes_when_controller_is_stopped(self, controller_in_thread: controller.Controller) -> None:
        """Makes sure no events are raised after the controller has been stopping."""

        # Setup mocked GPIO driver.
        pressed: bool = False
        driver: Any = controller_in_thread.driver # Downgrades type hint to allow assignment of the input method (see mypy issue 2427)
        driver.input = lambda pin_id: pressed

        # Create a button and subscribe to its events.
        button: controller.Button = controller_in_thread.make_button(2)

        listener = ButtonListener(button)
        pressed = True
        iteration_sleep = controller_in_thread.iteration_sleep * 2
        await asyncio.sleep(iteration_sleep) # So that event is raised BEFORE stopping.
        await controller_in_thread.stop_async()
        assert controller_in_thread.status == controller.Controller.Status.STOPPED
        listener.assert_calls(press = 1)

        # Release button. Since controller is stopped, no new event is expected.
        pressed = False
        await asyncio.sleep(iteration_sleep)
        listener.assert_calls(press = 1)

class ButtonListener:
    def __init__(self, button: controller.Button, common_event_handler: Callable[[], Coroutine[Any, Any, Any]] = None):
        assert not button is None
        self.button: controller.Button = button
        self.press_call_count: int = 0
        self.press_sync_call_count: int = 0
        self.long_press_call_count: int = 0
        self.long_press_sync_call_count: int = 0
        self.release_call_count: int = 0
        self.release_sync_call_count: int = 0
        self.click_call_count: int = 0
        self.click_sync_call_count: int = 0
        self.double_click_call_count: int = 0
        self.double_click_sync_call_count: int = 0
        self.button.add_on_press(self.on_press)
        self.button.add_on_press(self.on_press_sync) # Synchronous event handler
        self.button.add_on_long_press(self.on_long_press)
        self.button.add_on_long_press(self.on_long_press_sync)
        self.button.add_on_release(self.on_release)
        self.button.add_on_release(self.on_release_sync)
        self.button.add_on_click(self.on_click)
        self.button.add_on_click(self.on_click_sync)
        self.button.add_on_double_click(self.on_double_click)
        self.button.add_on_double_click(self.on_double_click_sync)
        self._custom_common_event_handler: Optional[Callable[[], Coroutine[Any, Any, Any]]] = common_event_handler

    async def _common_event_handler(self):
        if self._custom_common_event_handler:
            await self._custom_common_event_handler()

    async def on_press(self, button: controller.Button) -> None:
        assert button == self.button
        assert button.pressed
        self.press_call_count += 1
        await self._common_event_handler()

    def on_press_sync(self, button: controller.Button) -> None:
        assert button == self.button
        self.press_sync_call_count += 1

    async def on_long_press(self, button: controller.Button) -> None:
        assert button == self.button
        assert button.pressed
        assert button.long_pressed
        self.long_press_call_count += 1
        await self._common_event_handler()

    def on_long_press_sync(self, button: controller.Button) -> None:
        assert button == self.button
        assert button.pressed
        assert button.long_pressed
        self.long_press_sync_call_count += 1

    async def on_release(self, button: controller.Button) -> None:
        assert button == self.button
        assert not button.pressed
        assert not button.long_pressed
        self.release_call_count += 1
        await self._common_event_handler()

    def on_release_sync(self, button: controller.Button) -> None:
        assert button == self.button
        assert not button.pressed
        assert not button.long_pressed
        self.release_sync_call_count += 1

    async def on_click(self, button: controller.Button) -> None:
        assert button == self.button
        self.click_call_count += 1
        await self._common_event_handler()

    def on_click_sync(self, button: controller.Button) -> None:
        assert button == self.button
        self.click_sync_call_count += 1

    async def on_double_click(self, button: controller.Button) -> None:
        assert button == self.button
        self.double_click_call_count += 1
        await self._common_event_handler()

    def on_double_click_sync(self, button: controller.Button) -> None:
        assert button == self.button
        self.double_click_sync_call_count += 1

    def assert_calls(self, press: int = 0, long_press: int = 0, release: int = 0, click: int = 0, double_click: int = 0):
        assert self.press_call_count == press
        assert self.press_sync_call_count == press
        assert self.long_press_call_count == long_press
        assert self.long_press_sync_call_count == long_press
        assert self.release_call_count == release
        assert self.release_sync_call_count == release
        assert self.click_call_count == click
        assert self.click_sync_call_count == click
        assert self.double_click_call_count == double_click
        assert self.double_click_sync_call_count == double_click
