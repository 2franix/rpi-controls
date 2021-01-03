#!/usr/bin/python3

from __future__ import annotations # PEP 563
import time
import threading
import subprocess
import signal
import asyncio
import concurrent.futures
import inspect
import os
from typing import cast, Callable, Coroutine, List, Iterable, Type, Any, Union, Awaitable
from . import gpio_driver
import threading

status = 'off'
stopped = False
buttonPressedRisingEdgeTimestamp = None # Timestamp of the last button pressed event.

class Controller:
    def __init__(self, driver: gpio_driver.GpioDriver, iteration_sleep=0.01):
        """Initializes a new instance of the engine controlling the GPIO.

        Keyword arguments:
        driver -- object abstracting access to the GPIO.
        iteration_sleep -- pause in seconds before entering the next iteration of the mainloop.
        """
        self.driver: gpio_driver.GpioDriver = driver
        self._buttons: List[Button] = []
        self.iteration_sleep: float = 0.01
        self._lock: threading.Lock = threading.Lock()
        self._is_stopping = False
        # Thread that actually executes event handlers.
        self._event_loop = asyncio.new_event_loop()
        self._event_loop_thread: threading.Thread = threading.Thread(target=self._event_loop.run_forever)
        self._running_event_handlers: List[concurrent.futures.Future] = []

    @property
    def is_stopping(self):
        return self._is_stopping

    def make_button(self, pin_id) -> Button:
        button = Button(pin_id)
        self.driver.configure_button(pin_id)

        # Do an initial update to initialize the internal state of the button.
        # No event loop is passed, so that it does not attempt to raise any
        # event.
        button.update(None, self.driver)
        self._buttons.append(button)
        return button

    def stop(self, kills_running_events: bool = False) -> None:
        asyncio.run(self.stop_async(kills_running_events))

    async def stop_async(self, kills_running_events: bool = False) -> None:
        with self._lock:
            self._is_stopping = True

        # Wait for any event handlers to complete.
        if not kills_running_events:
            # Convert concurrent futures to asyncio ones. Can be done here since
            # we are in an async event loop.
            await asyncio.gather(*[asyncio.wrap_future(handler_future) for handler_future in self._running_event_handlers])

        # Request the event loop to stop (so will end its thread).
        # https://stackoverflow.com/a/51647591
        self._event_loop.call_soon_threadsafe(self._event_loop.stop)

    def run_in_thread(self) -> None:
        thread = threading.Thread(target=self.run)
        thread.start()

    def run(self) -> None:
        """Runs the engine controlling the GPIO.

        Keyword arguments:
        should_stop -- function evaluated at the end of every iteration to determine if the mainloop should break.
        """
        # Already stopping or stopped.
        if self._is_stopping:
            return

        self._event_loop_thread.start()
        while True:
            with self._lock:
                # Exit GPIO monitoring loop as soon as stop is requested.
                if self._is_stopping: return
                # Clean up old event tasks.
                for complete_event in [future for future in self._running_event_handlers if future.done()]:
                    self._running_event_handlers.remove(complete_event)
                # Maybe raise new events. Make sure the controller cannot stop in
                # the meantime.
                for button in self._buttons:
                    event_futures: List[concurrent.futures.Future] = button.update(self._event_loop, self.driver)
                    self._running_event_handlers += event_futures

            if not self._is_stopping: time.sleep(self.iteration_sleep)

class Button:
    SyncEventHandler = Callable[['Button'], None]
    AsyncEventHandler = Callable[['Button'], Coroutine[Any, Any, Any]]
    EventHandler = Union[SyncEventHandler, AsyncEventHandler]
    EventHandlerList = List[EventHandler]

    def __init__(self, pin_id: int):
        self.pin_id = pin_id
        self._pressed: bool = False
        self._long_pressed: bool = False
        self._press_handlers: Button.EventHandlerList = []
        self._release_handlers: Button.EventHandlerList = []
        self._long_press_handlers: Button.EventHandlerList = []
        self._click_handlers: Button.EventHandlerList = []
        self._double_click_handlers: Button.EventHandlerList = []
        # Maximum elapsed seconds between a press and the second release to qualify
        # for a double click.
        self.double_click_timeout: float = 0.4
        # Number of seconds a press must be maintained to qualify as a long
        # press.
        self.long_press_timeout: float = 0.5
        # Timestamps of previous presses and releases.
        self._press_times: List[float] = []
        self._release_times: List[float] = []

    @property
    def pressed(self) -> bool:
        return self._pressed

    @property
    def long_pressed(self) -> bool:
        return self._long_pressed

    def update(self, event_loop, gpio_driver: gpio_driver.GpioDriver) -> List[concurrent.futures.Future]:
        was_pressed = self._pressed
        was_long_pressed = self._long_pressed
        new_pressed = gpio_driver.is_button_pressed(self.pin_id)
        self._pressed = new_pressed
        if not self._pressed: self._long_pressed = False
        current_time: float = time.time()

        event_futures: List[concurrent.futures.Future] = []
        if self._pressed and not was_pressed: # PRESS
            # Record time of this new press.
            self._press_times.append(current_time)
            self.raise_event(event_loop, self._press_handlers, event_futures)
        elif not self._pressed and was_pressed: # RELEASE
            self._release_times.append(current_time)
            self.raise_event(event_loop, self._release_handlers, event_futures)

        # Maybe raise 'long press' event?
        if self._pressed: # LONG_PRESS
            last_press_time: float = self._press_times[-1]
            if (not self._long_pressed # Raise event only once per press!
                and current_time - last_press_time > self.long_press_timeout): # Press lasted long enough?
                self._long_pressed = True
                self.raise_event(event_loop, self._long_press_handlers, event_futures)

        # Maybe raise 'double click' event?
        if (not self._pressed and was_pressed # DOUBLE_CLICK
            and len(self._press_times) >= 2 # Was pressed not long ago.
            and current_time - self._press_times[-2] < self.double_click_timeout): # First of two presses was not too long ago.
            self.raise_event(event_loop, self._double_click_handlers, event_futures)
            # Consume press times not to reuse them in further events.
            self._press_times.clear()
            self._release_times.clear()

        # Maybe raise 'click' event?
        if self._press_times and self._release_times: # CLICK
            last_press: float = self._press_times[-1]
            last_release: float = self._release_times[-1]
            if (last_release > last_press # Was pressed then released. May now be pressed again so checking self.pressed is not enough!
                and current_time - last_press >= self.double_click_timeout): # Last press cannot qualify as a double click anymore.
                self.raise_event(event_loop, self._click_handlers, event_futures)
                # Consume press times not to reuse them in further events.
                self._press_times.clear()
                self._release_times.clear()

        return event_futures

    def raise_event(self, event_loop, handlers: EventHandlerList, event_futures: List[concurrent.futures.Future]) -> None:
        if event_loop is None: return
        event_futures += [asyncio.run_coroutine_threadsafe(self._call_event_handler(handler), event_loop) for handler in handlers]

    async def _call_event_handler(self, handler: EventHandler):
        try:
            handler_result = handler(self)
            if inspect.isawaitable(handler_result):
                awaitable_result = cast(Awaitable, handler_result)
                await awaitable_result
        except BaseException as e:
            # TODO Replace that crap with a decent logger!
            print(str(e))

    def add_on_press(self, func: EventHandler) -> None:
        self._press_handlers.append(func)

    def remove_on_press(self, func: EventHandler) -> None:
        self._press_handlers.remove(func)

    def add_on_long_press(self, func: EventHandler) -> None:
        self._long_press_handlers.append(func)

    def remove_on_long_press(self, func: EventHandler) -> None:
        self._long_press_handlers.remove(func)

    def add_on_release(self, func: EventHandler) -> None:
        self._release_handlers.append(func)

    def remove_on_release(self, func: EventHandler) -> None:
        self._release_handlers.remove(func)

    def add_on_click(self, func: EventHandler) -> None:
        self._click_handlers.append(func)

    def remove_on_click(self, func: EventHandler) -> None:
        self._click_handlers.remove(func)

    def add_on_double_click(self, func: EventHandler) -> None:
        self._double_click_handlers.append(func)

    def remove_on_double_click(self, func: EventHandler) -> None:
        self._double_click_handlers.remove(func)
