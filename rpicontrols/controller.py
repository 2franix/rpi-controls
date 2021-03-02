#!/usr/bin/python3

from __future__ import annotations # PEP 563
import logging
import time
import threading
import subprocess
import signal
import asyncio
import concurrent.futures
import inspect
import os
import enum
import typing
from . import gpio_driver
import threading

def get_logger(): return logging.getLogger(__name__)

class Controller:
    class Status(enum.Enum):
        READY: str = "ready"
        RUNNING: str = "running"
        STOPPING: str = "stopping"
        STOPPED: str = "stopped"

    def __init__(self, driver: gpio_driver.GpioDriver):
        """Initializes a new instance of the engine controlling the GPIO.

        Keyword arguments:
        driver -- object abstracting access to the GPIO.
        """
        self.driver: gpio_driver.GpioDriver = driver
        self._buttons: typing.List[Button] = []
        self.iteration_sleep: float = 1.0
        self._status_lock: threading.Lock = threading.Lock()
        self._status: Controller.Status = Controller.Status.READY

        # Async loop running event callback.
        self._event_loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()

        # Thread used to run control updates that are time bound instead of IO bound
        # For example, after a button is released, the click event must be
        # raised once the double click delay is over (because if a double click
        # occurs, we don't want to raise the click event).
        self._scheduled_updates_thread: threading.Thread = threading.Thread(target=self._scheduled_updates_thread_main)
        # Condition that notifies the thread when something is scheduled.
        self._scheduled_updates_condition: threading.Condition = threading.Condition()

        self._running_event_handlers: typing.List[concurrent.futures.Future] = []

    @property
    def status(self) -> Controller.Status:
        return self._status

    def _scheduled_updates_thread_main(self) -> None:
        while self._status in (Controller.Status.READY, Controller.Status.RUNNING):
            # Immediately update buttons that need it.
            with self._scheduled_updates_condition:
                current_time = time.time()
                buttons_to_update = [b for b in self._buttons if b.scheduled_update_time != 0 and b.scheduled_update_time < current_time]
                for button in buttons_to_update:
                    self._update_button(button)

            # Sleep until next update or wait for the next scheduled update.
            remaining_buttons_to_update = [b for b in self._buttons if b.scheduled_update_time != 0]
            if remaining_buttons_to_update:
                next_update_time = min((b.scheduled_update_time for b in remaining_buttons_to_update))
                sleep_time = next_update_time - time.time()
                if sleep_time > 0.0:
                    time.sleep(sleep_time)
            else:
                with self._scheduled_updates_condition:
                    self._scheduled_updates_condition.wait()

    def make_button(self,
            input_pin_id: int,
            input: Button.InputType,
            pull: gpio_driver.PullType,
            name: typing.Optional[str] = None) -> Button:
        button = Button(input_pin_id, input, name)

        self.driver.configure_button(input_pin_id, pull)
        get_logger().debug(f'New button configured for pin {input_pin_id}')

        # Do an initial update to initialize the internal state of the button.
        # No event loop is passed, so that it does not attempt to raise any
        # event.
        self._update_button(button, raise_events=False)
        self._buttons.append(button)
        return button

    def stop(self, wait = False, kills_running_events: bool = False) -> None:
        get_logger().info('Stopping controller...')
        with self._status_lock:
            # Already stopped?
            if self.status == Controller.Status.STOPPED:
                get_logger().info('Controller is already stopped.')
                return
            # Otherwise, stopping only makes sense while controller is running.
            if self.status != Controller.Status.RUNNING:
                message: str = f'Controller status is {self.status} and cannot be stopped.'
                get_logger().error(message)
                raise Exception(message)

            self._status = Controller.Status.STOPPING

        # Wake up the thread for scheduled updates in case it is waiting
        # to allow it to stop gracefully.
        with self._scheduled_updates_condition:
            self._scheduled_updates_condition.notify()

        # Wait for event handler that are still running to complete.
        while [handler_future for handler_future in self._running_event_handlers if not handler_future.done()]:
            time.sleep(0.01)
        get_logger().debug('All event handlers are now complete.')

        # Request the event loop to stop (so will end its thread).
        # https://stackoverflow.com/a/51647591
        self._event_loop.call_soon_threadsafe(self._event_loop.stop)

        while wait and self._status != Controller.Status.STOPPED:
            time.sleep(0.01)

    def _get_button(self, pin_id: int) -> typing.Optional[Button]:
        buttons = [b for b in self._buttons if b.pin_id == pin_id]
        if not buttons: return None
        if len(buttons) > 1:
            raise Exception(f'Several buttons correspond to pin {pin_id}.')
        return buttons[0]

    def _on_gpio_edge(self, pin_id: int) -> None:
        with self._status_lock:
            # Maybe raise new events. Make sure the controller cannot stop in
            # the meantime.
            button: typing.Optional[Button] = self._get_button(pin_id)
            if not button:
                get_logger().info(f'Ignoring edge for GPIO pin {pin_id} because no button is registered for it.')
                return
            with self._scheduled_updates_condition:
                self._update_button(button)
                if button.scheduled_update_time != 0:
                    self._scheduled_updates_condition.notify()

    def _update_button(self, button: Button, raise_events: bool=True):
        if self._status != Controller.Status.RUNNING: return
        event_futures: typing.List[concurrent.futures.Future] = button.update(self._event_loop if raise_events else None, self.driver)
        self._running_event_handlers += event_futures

    def start_in_thread(self) -> None:
        thread = threading.Thread(target=self.run)
        thread.start()
        while self._status == Controller.Status.READY:
            time.sleep(0.01)

    def run(self) -> None:
        """Runs the engine controlling the GPIO.

        Keyword arguments:
        should_stop -- function evaluated at the end of every iteration to determine if the mainloop should break.
        """
        get_logger().info('Starting the controller...')
        with self._status_lock:
            # Already running or stopping.
            if self._status != Controller.Status.READY:
                message: str = f'Controller is currently "{self.status}" and cannot be started.'
                get_logger().error(message)
                raise Exception(message)
            self._scheduled_updates_thread.start()
            self.driver.set_edge_callback(self._on_gpio_edge)
            self._status = Controller.Status.RUNNING

        get_logger().debug('Async event loop for event handlers started.')
        self._event_loop.run_forever()
        get_logger().debug('Async event loop for event handlers is now stopped.')
        # while True:
            # with self._status_lock:
                # # Exit GPIO monitoring loop as soon as stop is requested.
                # if self._status != Controller.Status.RUNNING:
                    # get_logger().info('Stop requested, aborting the GPIO monitoring loop.')
                    # break
# 
                # # Clean up old event tasks.
                # for complete_event in [future for future in self._running_event_handlers if future.done()]:
                    # self._running_event_handlers.remove(complete_event)
# 
            # if self._status == Controller.Status.RUNNING:
                # time.sleep(self.iteration_sleep)

        # Wait for any event handlers to complete.
        #if not kills_running_events:
        # if self._running_event_handlers:
            # get_logger().debug('Waiting for currently running event handlers to complete...')
# 
            # # Convert concurrent futures to asyncio ones. Can be done here since
            # # we are in an async event loop.
            # while [handler_future for handler_future in self._running_event_handlers if not handler_future.done()]:
                # time.sleep(0.01)
            # get_logger().debug('All event handlers are now complete.')

        with self._status_lock:
            self._status = Controller.Status.STOPPED
            get_logger().info('Controller is now stopped')

    def stop_on_signals(self, signals=[signal.SIGINT, signal.SIGTERM]):
        for sig in signals:
            signal.signal(sig, self._signal_handler)

    def _signal_handler(self, signal, frame):
        self.stop(wait=False)

class Button:
    class InputType(enum.Enum):
        PRESSED_WHEN_ON = 1
        PRESSED_WHEN_OFF = 2

    SyncEventHandler = typing.Callable[['Button'], None]
    AsyncEventHandler = typing.Callable[['Button'], typing.Coroutine[typing.Any, typing.Any, typing.Any]]
    EventHandler = typing.Union[SyncEventHandler, AsyncEventHandler]
    EventHandlerList = typing.List[EventHandler]

    def __init__(self, input_pin_id: int, input_type: Button.InputType, name: typing.Optional[str]):
        self._pin_id: int = input_pin_id
        self._name: str = name or f'button for pin {input_pin_id}'
        self._input_type: Button.InputType = input_type
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
        self._press_times: typing.List[float] = []
        self._release_times: typing.List[float] = []
        self.scheduled_update_time: float = 0.0

    @property
    def pin_id(self) -> int:
        return self._pin_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def input_type(self) -> InputType:
        return self._input_type

    @property
    def pressed(self) -> bool:
        return self._pressed

    @property
    def long_pressed(self) -> bool:
        return self._long_pressed

    def update(self, event_loop: typing.Optional[asyncio.AbstractEventLoop], gpio_driver: gpio_driver.GpioDriver) -> typing.List[concurrent.futures.Future]:
        was_pressed: bool = self._pressed
        was_long_pressed: bool = self._long_pressed
        pin_input: bool = gpio_driver.input(self.pin_id)
        new_pressed: bool = pin_input if self._input_type == Button.InputType.PRESSED_WHEN_ON else not pin_input
        self._pressed = new_pressed
        if not self._pressed: self._long_pressed = False
        current_time: float = time.time()

        # Mark button as updated.
        if self.scheduled_update_time < current_time:
            self._schedule_update(0.0)

        event_futures: typing.List[concurrent.futures.Future] = []
        if self._pressed and not was_pressed: # PRESS
            # Record time of this new press.
            get_logger().debug(f'Button {self.pin_id} is pressed.')
            self._press_times.append(current_time)
            self.raise_event('press', event_loop, self._press_handlers, event_futures)
        elif not self._pressed and was_pressed: # RELEASE
            get_logger().debug(f'Button {self.pin_id} is released.')
            self._release_times.append(current_time)
            self.raise_event('release', event_loop, self._release_handlers, event_futures)

        # Maybe raise 'long press' event?
        if self._pressed: # LONG_PRESS
            last_press_time: float = self._press_times[-1]
            if not self._long_pressed: # Raise event only once per press!
                if current_time - last_press_time > self.long_press_timeout: # Press lasted long enough?
                    get_logger().debug(f'Button {self.pin_id} is long-pressed.')
                    self._long_pressed = True
                    self.raise_event('long press', event_loop, self._long_press_handlers, event_futures)
                else:
                    # Button needs to reconsider the long pressed event later.
                    self._schedule_update(last_press_time + self.long_press_timeout)

        # Maybe raise 'double click' event?
        if (not self._pressed and was_pressed # DOUBLE_CLICK
            and len(self._press_times) >= 2 # Was pressed not long ago.
            and current_time - self._press_times[-2] < self.double_click_timeout): # First of two presses was not too long ago.
            get_logger().debug(f'Button {self.pin_id} is double-clicked.')
            self.raise_event('double click', event_loop, self._double_click_handlers, event_futures)
            # Consume press times not to reuse them in further events.
            self._press_times.clear()
            self._release_times.clear()

        # Maybe raise 'click' event?
        if self._press_times and self._release_times: # CLICK
            last_press: float = self._press_times[-1]
            last_release: float = self._release_times[-1]
            if last_release > last_press: # Was pressed then released. May now be pressed again so checking self.pressed is not enough!
                if current_time - last_press >= self.double_click_timeout:
                    # Last press cannot qualify as a double click anymore.
                    get_logger().debug(f'Button {self.pin_id} is clicked.')
                    self.raise_event('click', event_loop, self._click_handlers, event_futures)
                    # Consume press times not to reuse them in further events.
                    self._press_times.clear()
                    self._release_times.clear()
                else:
                    # Button needs to consider the click event once
                    # last press cannot participate in a double click anymore.
                    self._schedule_update(last_press + self.double_click_timeout)

        return event_futures

    def _schedule_update(self, update_time: float) -> None:
        if update_time == 0.0 or self.scheduled_update_time == 0.0 or self.scheduled_update_time > update_time:
            self.scheduled_update_time = update_time

    def raise_event(self, event_name: str, event_loop: typing.Optional[asyncio.AbstractEventLoop], handlers: EventHandlerList, event_futures: typing.List[concurrent.futures.Future]) -> None:
        if event_loop is None: return
        event_futures += [asyncio.run_coroutine_threadsafe(self._call_event_handler(event_name, handler), event_loop) for handler in handlers]

    async def _call_event_handler(self, event_name: str, handler: EventHandler):
        try:
            handler_result = handler(self)
            if inspect.isawaitable(handler_result):
                get_logger().debug(f'Called event handler asynchronously for "{event_name}" on button {self.name}.')
                awaitable_result = typing.cast(typing.Awaitable, handler_result)
                await awaitable_result
            else:
                get_logger().debug(f'Called event handler synchronously for "{event_name}" on button {self.name}.')

        except BaseException as e:
            get_logger().exception(e)

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
