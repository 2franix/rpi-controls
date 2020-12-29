#!/usr/bin/python3

from __future__ import annotations # PEP 563
import time
import threading
import subprocess
import signal
import asyncio
import concurrent.futures
import os
from typing import Callable, Coroutine, List, Type, Any
from . import gpio_driver
import threading

status = 'off'
stopped = False
buttonPressedRisingEdgeTimestamp = None # Timestamp of the last button pressed event.

class Engine:
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

    def make_button(self, pin_id) -> Button:
        button = Button(pin_id, self)
        self._buttons.append(button)
        return button

    def stop(self, kills_running_events: bool = False) -> None:
        with self._lock:
            self._is_stopping = True

        # Wait for any event handlers to complete.
        if not kills_running_events:
            for future in self._running_event_handlers:
                future.result()

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
                # Maybe raise new events. Make sure the engine cannot stop in
                # the meantime.
                for button in self._buttons:
                    event_futures: List[concurrent.futures.Future] = button.update(self._event_loop)
                    self._running_event_handlers += event_futures

            if not self._is_stopping: time.sleep(self.iteration_sleep)

    def configure_button(self, pin_id: int) -> None:
        self.driver.configure_button(pin_id)

class Button:
    EventHandler = Callable[['Button'], Coroutine[Any, Any, Any]]
    EventHandlerList = List[EventHandler]

    def __init__(self, pin_id: int, engine: Engine):
        assert engine, "No engine."
        self._engine = engine
        self.pin_id = pin_id
        self._pressed: bool = False
        self._long_pressed: bool = False
        self._press_handlers: Button.EventHandlerList = []
        self._release_handlers: Button.EventHandlerList = []
        self._long_press_handlers: Button.EventHandlerList = []
        self._click_handlers: Button.EventHandlerList = []
        self._double_click_handlers: Button.EventHandlerList = []
        self._engine.configure_button(self.pin_id)
        # Maximum elapsed seconds between a press and the second release to qualify
        # for a double click.
        self.double_click_timeout: float = 0.4
        # Number of seconds a press must be maintained to qualify as a long
        # press.
        self.long_press_timeout: float = 0.5
        # Timestamps of previous presses.
        self._press_times: List[float] = []
        # Do initial update to capture initial button state without raising
        # events.
        self.update(None)

    @property
    def pressed(self) -> bool:
        return self._pressed

    def update(self, event_loop) -> List[concurrent.futures.Future]:
        assert threading.current_thread() != self._engine._event_loop_thread
        was_pressed = self._pressed
        was_long_pressed = self._long_pressed
        new_pressed = self._engine.driver.is_button_pressed(self.pin_id)
        self._pressed = new_pressed
        if not self._pressed: self._long_pressed = False
        current_time: float = time.time()

        event_futures: List[concurrent.futures.Future] = []
        if self._pressed and not was_pressed: # PRESS
            # Record time of this new press.
            self._press_times.append(current_time)
            self.raise_event(event_loop, self._press_handlers, event_futures)
        elif not self._pressed and was_pressed: # RELEASE
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

        # Maybe raise 'click' event?
        if (not self._pressed # CLICK
            and self._press_times # Release but was pressed not long ago.
            and current_time - self._press_times[-1] >= self.double_click_timeout): # Last press cannot qualify as a double click anymore.
            self.raise_event(event_loop, self._click_handlers, event_futures)
            # Consume press times not to reuse them in further events.
            self._press_times.clear()

        return event_futures

    def raise_event(self, event_loop, handlers: EventHandlerList, event_futures: List[concurrent.futures.Future]) -> None:
        if event_loop is None: return
        event_futures += [asyncio.run_coroutine_threadsafe(handler(self), event_loop) for handler in handlers]
        # event_loop.call_soon_threadsafe(lambda: event_loop.create_task(handler(self)))

    def add_on_click(self, func: EventHandler) -> None:
        self._click_handlers.append(func)

    def remove_on_click(self, func: EventHandler) -> None:
        self._click_handlers.remove(func)

    def add_on_double_click(self, func: EventHandler) -> None:
        self._double_click_handlers.append(func)

    def remove_on_double_click(self, func: EventHandler) -> None:
        self._double_click_handlers.remove(func)
