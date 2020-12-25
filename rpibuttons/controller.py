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
        driver -- object abstracting accessing to the GPIO.
        iteration_sleep -- pause in seconds before entering the next iteration of the mainloop.
        """
        self.driver: gpio_driver.GpioDriver = driver
        self._buttons: List[Button] = []
        self.iteration_sleep: float = 0.01

    def make_button(self, pin_id) -> Button:
        button = Button(pin_id, self)
        self._buttons.append(button)
        return button

    def run_in_thread(self, should_stop: Callable[[], bool]) -> None:
        def invoke_run():
            asyncio.run(self.run_async(should_stop))
        thread = threading.Thread(target=invoke_run)
        thread.start()

    async def run_async(self, should_stop: Callable[[], bool]) -> None:
        """Runs the engine controlling the GPIO.

        Keyword arguments:
        should_stop -- function evaluated at the end of every iteration to determine if the mainloop should break.
        """
        while not await self._run_iteration(should_stop):
            await asyncio.sleep(self.iteration_sleep)

    async def _run_iteration(self, should_stop: Callable[[], bool]) -> bool:
        if not should_stop():
            for button in self._buttons:
                events: List[asyncio.Task] = button.update_pressed()
                await asyncio.gather(*events)
            return False
        else:
            return True

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
        self.update_pressed()

    @property
    def pressed(self) -> bool:
        return self._pressed

    def update_pressed(self) -> List[asyncio.Task]:
        new_pressed = self._engine.driver.is_button_pressed(self.pin_id)
        raise_event = self._pressed != new_pressed
        self._pressed = new_pressed
        events: List[asyncio.Task] = []
        if raise_event:
            if not self.pressed:
                events.append(asyncio.create_task(self.raise_event(self._click_handlers)))
        return events

    async def raise_event(self, handlers: EventHandlerList) -> None:
        await asyncio.gather(*(handler(self) for handler in self._click_handlers))

    def add_on_click(self, func: EventHandler) -> None:
        self._click_handlers.append(func)

    def remove_on_click(self, func: EventHandler) -> None:
        self._click_handlers.remove(func)

    def add_on_double_click(self, func: EventHandler) -> None:
        self._double_click_handlers.append(func)

    def remove_on_double_click(self, func: EventHandler) -> None:
        self._double_click_handlers.remove(func)
