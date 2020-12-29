#!/usr/bin/python3

from __future__ import annotations # PEP 563
import time
import threading
import subprocess
import signal
import asyncio
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
        self._is_stopping = False
        # Thread that actually executes event handlers.
        self._event_loop = asyncio.new_event_loop()
        self._event_loop_thread: threading.Thread = threading.Thread(target=self._event_loop.run_forever)

    def make_button(self, pin_id) -> Button:
        button = Button(pin_id, self)
        self._buttons.append(button)
        return button

    def stop(self) -> None:
        self._is_stopping = True
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
        self._is_stopping = False
        self._event_loop_thread.start()
        while not self._is_stopping:
            for button in self._buttons:
                button.update(self._event_loop)
            time.sleep(self.iteration_sleep)

    def configure_button(self, pin_id: int) -> None:
        self.driver.configure_button(pin_id)

class Button:
    EventHandler = Callable[['Button'], Coroutine[Any, Any, Any]]
    EventHandlerList = List[EventHandler]

    def __init__(self, pin_id: int, engine: Engine):
        self._me: Button = self
        assert engine, "No engine."
        self._engine = engine
        self.pin_id = pin_id
        self._pressed: bool = False
        self._click_handlers: Button.EventHandlerList = []
        self._double_click_handlers: Button.EventHandlerList = []
        self._engine.configure_button(self.pin_id)
        self._events: List[str] = []
        self.update(None)

    @property
    def pressed(self) -> bool:
        return self._pressed

    def update(self, event_loop) -> None:
        assert threading.current_thread() != self._engine._event_loop_thread
        new_pressed = self._engine.driver.is_button_pressed(self.pin_id)
        raise_event = self._pressed != new_pressed and not event_loop is None
        self._pressed = new_pressed
        if raise_event:
            if not self.pressed:
                for handler in self._click_handlers:
                    event_loop.call_soon_threadsafe(lambda: event_loop.create_task(handler(self)))

    def add_on_click(self, func: EventHandler) -> None:
        self._click_handlers.append(func)

    def remove_on_click(self, func: EventHandler) -> None:
        self._click_handlers.remove(func)

    def add_on_double_click(self, func: EventHandler) -> None:
        self._double_click_handlers.append(func)

    def remove_on_double_click(self, func: EventHandler) -> None:
        self._double_click_handlers.remove(func)
