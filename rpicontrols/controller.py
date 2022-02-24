#!/usr/bin/python3

from __future__ import annotations  # PEP 563
import logging
import time
import threading
import signal
import asyncio
import concurrent.futures
import inspect
import enum
import typing

from . import gpio_driver


def get_logger():
    return logging.getLogger(__name__)


class Controller:
    """Represents the object managing all buttons.
    It monitors the state of the GPIO and calls event callbacks on buttons when appropriate.
    """

    class Status(enum.Enum):
        """Defines the various steps in a controller lifecycle."""

        READY = "ready"
        """Controller is waiting for being started, either with :meth:`Controller.run` or :meth:`Controller.start_in_thread`"""

        RUNNING = "running"
        """Controller has been started and is monitoring GPIO. This is the active state of the controller, during which button
        events can be raised."""

        STOPPING = "stopping"
        """Controller is being shut down. No new events will be raised at this point because GPIO is no longer monitored,
        but ongoing callbacks may still need to finish."""

        STOPPED = "stopped"
        """Controller is at full stop and all event callbacks have returned. Controller cannot be started again."""

    def __init__(self, driver: gpio_driver.GpioDriver):
        """Initializes a new instance of the engine controlling the GPIO.

        :param driver: object abstracting access to the GPIO.
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
        self._scheduled_updates_thread: threading.Thread = threading.Thread(target=self._scheduled_updates_thread_main, daemon=True)
        # Condition that notifies the thread when something is scheduled.
        self._scheduled_updates_condition: threading.Condition = threading.Condition()

        self._running_event_handlers: typing.List[concurrent.futures.Future] = []

    @property
    def status(self) -> Controller.Status:
        """Gets the current status of this controller."""
        return self._status

    @property
    def buttons(self) -> typing.Iterable[Button]:
        """Gets the collection of buttons that have been registered using :meth:`make_button`."""
        return self._buttons

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
                    get_logger().debug("Thread for scheduled updates going to sleep.")
                    self._scheduled_updates_condition.wait()
                    get_logger().debug("Thread for scheduled updates wakes up.")

    def make_button(
        self, input_pin_id: int, input: Button.InputType, pull: gpio_driver.PullType, name: typing.Optional[str] = None, bounce_time: int = 0
    ) -> Button:
        """Creates a new button connected to pins of the GPIO.

        :param input_pin_id: id of the *input* pin the button is connected to. Its meaning depends on the selected GPIO driver.
            The default driver is :class:`rpicontrols.rpi_gpio_driver.RpiGpioDriver` which uses :data:`RPi.GPIO.BOARD` unless otherwise specified.
        :param input: value describing the button physical behavior with respect to the electrical wiring. It helps the controller
            tell when the button is considered pressed or released, depending on the state of the GPIO.
        :param pull: whether built-in pull-up or pull-down should be used for this button. Those are resistors integrated in the
            Raspberry Pi's circuits that can be used to make sure GPIO pins are always at a predictable potential. The appropriate
            value is dependent on how the physical button or switch has been wired to the GPIO.
            See `Wikipedia <https://en.wikipedia.org/wiki/Pull-up_resistor>`_ for more information.
        :param name: optional name, used for documentation and logging purposes. If unset, a default unique name will be assigned.
        :param bounce_time: timespan after a GPIO rising or falling edge during which new edges should be ignored. This is meant
            to avoid unwanted edge detections due to the transient instability of switches when they change state. The appropriate
            value depends on the actual physical switch or button in use.
        """
        button = Button(input_pin_id, input, name)

        self.driver.configure_button(input_pin_id, pull, bounce_time)
        get_logger().debug(f"New button configured for pin {input_pin_id}")

        # Do an initial update to initialize the internal state of the button.
        # No event loop is passed, so that it does not attempt to raise any
        # event.
        self._update_button(button, raise_events=False)
        self._buttons.append(button)
        return button

    def delete_button(self, button: Button) -> None:
        """Removes the button from the controller. The controller will
        stop monitoring this button events and will not update its
        status anymore. Call this method to save resources if this
        button is not useful anymore.
        It is not required to delete all buttons before deleting
        this controller.
        """
        if button not in self._buttons:
            raise ValueError(f"Button {button.name} is not registered in this controller.")
        self.driver.unconfigure_button(button.pin_id)
        self._buttons.remove(button)

    def stop(self, wait: bool = False) -> None:
        """Stops this controller.

        Attempting to stop a controller that is already stopped does nothing. Otherwise, calling this method on a controller
        that is in a status different from :data:`Controller.Status.RUNNING` raises an exception.

        :param wait: whether to block until the controller has actually stopped. If False, the method returns quicker but
            there is no guarantee that the controller has actually reached the :data:`Status.STOPPED` status.
        """
        get_logger().info("Stopping controller...")
        with self._status_lock:
            # Already stopped?
            if self.status == Controller.Status.STOPPED:
                get_logger().info("Controller is already stopped.")
                return
            # Otherwise, stopping only makes sense while controller is running.
            if self.status != Controller.Status.RUNNING:
                message: str = f"Controller status is {self.status} and cannot be stopped."
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
        get_logger().debug("All event handlers are now complete.")

        # Request the event loop to stop (so will end its thread).
        # https://stackoverflow.com/a/51647591
        self._event_loop.call_soon_threadsafe(self._event_loop.stop)

        while wait and self._status != Controller.Status.STOPPED:
            time.sleep(0.01)

    def _get_button(self, pin_id: int) -> typing.Optional[Button]:
        buttons = [b for b in self._buttons if b.pin_id == pin_id]
        if not buttons:
            return None
        if len(buttons) > 1:
            raise Exception(f"Several buttons correspond to pin {pin_id}.")
        return buttons[0]

    def _on_gpio_edge(self, pin_id: int, edge: gpio_driver.EdgeType) -> None:
        get_logger().debug(f"edge start: {edge} on pin {pin_id}")
        with self._status_lock:
            # Maybe raise new events. Make sure the controller cannot stop in
            # the meantime.
            button: typing.Optional[Button] = self._get_button(pin_id)
            if not button:
                get_logger().info(f"Ignoring edge for GPIO pin {pin_id} because no button is registered for it.")
                return
            with self._scheduled_updates_condition:
                self._update_button(button, edge == gpio_driver.EdgeType.RISING)
                if button.scheduled_update_time != 0:
                    self._scheduled_updates_condition.notify()
        get_logger().debug(f"edge end: {edge} on pin {pin_id}")

    def _update_button(self, button: Button, pin_input: typing.Optional[bool] = None, raise_events: bool = True) -> None:
        if self._status != Controller.Status.RUNNING:
            return
        actual_pin_input: bool = pin_input if pin_input is not None else self.driver.input(button.pin_id)
        event_futures: typing.List[concurrent.futures.Future] = button.update(self._event_loop if raise_events else None, actual_pin_input)
        self._running_event_handlers += event_futures

    def start_in_thread(self) -> None:
        """Runs the engine controlling the GPIO in its own thread."""
        thread = threading.Thread(target=self.run)
        thread.start()
        while self._status == Controller.Status.READY:
            time.sleep(0.01)

    def run(self) -> None:
        """Runs the engine controlling the GPIO.

        This method blocks until the controller is stopped. See also :meth:`start_in_thread` for
        a non-blocking version of this start method.
        """
        get_logger().info("Starting the controller...")
        with self._status_lock:
            # Already running or stopping.
            if self._status != Controller.Status.READY:
                message: str = f'Controller is currently "{self.status}" and cannot be started.'
                get_logger().error(message)
                raise Exception(message)
            self._scheduled_updates_thread.start()
            self.driver.set_edge_callback(self._on_gpio_edge)
            self._status = Controller.Status.RUNNING

        get_logger().debug("Async event loop for event handlers started.")
        self._event_loop.run_forever()
        get_logger().debug("Async event loop for event handlers is now stopped.")

        with self._status_lock:
            self._status = Controller.Status.STOPPED
            get_logger().info("Controller is now stopped")

    def stop_on_signals(self, signals: typing.Iterable[signal.Signals] = [signal.SIGINT, signal.SIGTERM]):
        """Registers a handler to stop this controller when specific signals are caught.

        :param signals: list of signals that should stop this controller.
        """
        for sig in signals:
            signal.signal(sig, self._signal_handler)

    def _signal_handler(self, signal, frame) -> None:
        get_logger().debug(f"Signal caught: {signal} on frame={frame}.")
        self.stop(wait=False)


class Button:
    """Represents a button connected to the GPIO.

    This object holds the current state of the button and the event handlers to be called when
    events are raised.
    """

    class InputType(enum.Enum):
        """Defines the various physical behaviors of a button with respect to the wiring of its corresponding GPIO pins."""

        PRESSED_WHEN_ON = 1
        """The button is detected as pressed when its GPIO input pin is on."""

        PRESSED_WHEN_OFF = 2
        """The button is detected as pressed when its GPIO input pin is off."""

    SyncEventHandler = typing.Callable[["Button"], None]
    """Represents the type for synchronous event handlers."""
    AsyncEventHandler = typing.Callable[["Button"], typing.Coroutine[typing.Any, typing.Any, typing.Any]]
    """Represents the type for asynchronous event handlers."""
    EventHandler = typing.Union[SyncEventHandler, AsyncEventHandler]
    """Represents the type for all kinds of event handlers (synchronous or asynchronous)."""
    EventHandlerList = typing.List[EventHandler]
    """Represents the type for lists of event handlers (synchronous or asynchronous)."""

    def __init__(self, input_pin_id: int, input_type: Button.InputType, name: typing.Optional[str] = None):
        self._pin_id: int = input_pin_id
        self._name: str = name or f"button for pin {input_pin_id}"
        self._input_type: Button.InputType = input_type
        self._pressed: bool = False
        self._long_pressed: bool = False
        self._press_handlers: Button.EventHandlerList = []
        self._release_handlers: Button.EventHandlerList = []
        self._long_press_handlers: Button.EventHandlerList = []
        self._click_handlers: Button.EventHandlerList = []
        self._double_click_handlers: Button.EventHandlerList = []
        #: Period of time in seconds that defines the double click speed. For a double click to be detected,
        #: two clicks must occur so that the number of elapsed seconds between the first press and the second release
        #: is at most equal to this timeout.
        #: This timeout has an indirect impact on the detection of the click events: since no click event is raised
        #: when a double click occurs, the controller must wait for this double click timeout to expire once
        #: a first click has been detected before the actual click event can be raised.
        self.double_click_timeout: float = 0.5
        #: Number of consecutive seconds the button must be pressed for the *long pressed* event
        #: to be raised.
        self.long_press_timeout: float = 0.5
        # Timestamps of previous presses and releases.
        self._press_times: typing.List[float] = []
        self._release_times: typing.List[float] = []
        self.scheduled_update_time: float = 0.0

    @property
    def pin_id(self) -> int:
        """Id of the input pin the button is connected to. See :meth:`Controller.make_button` for more info on its meaning."""
        return self._pin_id

    @property
    def name(self) -> str:
        """Informational name of this button. This name is used mainly for logging purposes."""
        return self._name

    @property
    def input_type(self) -> InputType:
        """Returns a value indicating the physical status of the button with respect to GPIO status."""
        return self._input_type

    @property
    def pressed(self) -> bool:
        """Returns a value indicating whether the button is currently pressed."""
        return self._pressed

    @property
    def long_pressed(self) -> bool:
        """Returns a value indicating whether the button is currently pressed and has been so for
        least a period of time at least equal to :attr:`long_press_timeout`."""
        return self._long_pressed

    def update(self, event_loop: typing.Optional[asyncio.AbstractEventLoop], pin_input: bool) -> typing.List[concurrent.futures.Future]:
        was_pressed: bool = self._pressed
        new_pressed: bool = pin_input if self._input_type == Button.InputType.PRESSED_WHEN_ON else not pin_input
        self._pressed = new_pressed
        if not self._pressed:
            self._long_pressed = False
        current_time: float = time.time()

        # Mark button as updated.
        if self.scheduled_update_time < current_time:
            self._schedule_update(0.0)

        def log_state(new_state: str):
            get_logger().debug(f"Button {self.name} [{self.pin_id}] is {new_state}.")

        event_futures: typing.List[concurrent.futures.Future] = []
        if self._pressed and not was_pressed:  # PRESS
            # Record time of this new press.
            log_state("pressed")
            self._press_times.append(current_time)
            self._raise_event("press", event_loop, self._press_handlers, event_futures)
        elif not self._pressed and was_pressed:  # RELEASE
            log_state("released")
            self._release_times.append(current_time)
            self._raise_event("release", event_loop, self._release_handlers, event_futures)

        # Maybe raise 'long press' event?
        if self._pressed:  # LONG_PRESS
            last_press_time: float = self._press_times[-1]
            if not self._long_pressed:  # Raise event only once per press!
                if current_time - last_press_time > self.long_press_timeout:  # Press lasted long enough?
                    log_state("long-pressed")
                    self._long_pressed = True
                    self._raise_event("long press", event_loop, self._long_press_handlers, event_futures)
                else:
                    # Button needs to reconsider the long pressed event later.
                    self._schedule_update(last_press_time + self.long_press_timeout)

        # Maybe raise 'double click' event?
        just_released: bool = not self._pressed and was_pressed
        clicked_twice: bool = len(self._press_times) >= 2  # Was pressed at least twice recently.
        # First of two presses was not too long ago?
        first_press_recent: bool = clicked_twice and current_time - self._press_times[-2] < self.double_click_timeout

        if just_released and clicked_twice and first_press_recent:  # DOUBLE_CLICK
            log_state("double-clicked")
            self._raise_event("double click", event_loop, self._double_click_handlers, event_futures)
            # Consume press times not to reuse them in further events.
            self._press_times.clear()
            self._release_times.clear()

        # Maybe raise 'click' event?
        if self._press_times and self._release_times:  # CLICK
            last_press: float = self._press_times[-1]
            last_release: float = self._release_times[-1]
            if last_release > last_press:  # Was pressed then released. May now be pressed again so checking self.pressed is not enough!
                if current_time - last_press >= self.double_click_timeout:
                    # Last press cannot qualify as a double click anymore.
                    log_state("clicked")
                    self._raise_event("click", event_loop, self._click_handlers, event_futures)
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

    def _raise_event(
        self,
        event_name: str,
        event_loop: typing.Optional[asyncio.AbstractEventLoop],
        handlers: EventHandlerList,
        event_futures: typing.List[concurrent.futures.Future],
    ) -> None:
        if event_loop is None:
            return
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
        """Adds a handler of the *press* event. This handler will be called whenever the button is pressed."""
        self._press_handlers.append(func)

    def remove_on_press(self, func: EventHandler) -> None:
        """Removes a handler of the *press* event."""
        self._press_handlers.remove(func)

    def add_on_long_press(self, func: EventHandler) -> None:
        """Adds a handler of the *long press* event. This handler will be called whenever the button has
        been kept in its pressed state for a period of time equal to :attr:`long_press_timeout` seconds."""
        self._long_press_handlers.append(func)

    def remove_on_long_press(self, func: EventHandler) -> None:
        """Removes a handler of the *long press* event."""
        self._long_press_handlers.remove(func)

    def add_on_release(self, func: EventHandler) -> None:
        """Adds a handler of the *release* event. This handler will be called whenever the button is released
        after having been pressed."""
        self._release_handlers.append(func)

    def remove_on_release(self, func: EventHandler) -> None:
        """Removes a handler of the *release* event."""
        self._release_handlers.remove(func)

    def add_on_click(self, func: EventHandler) -> None:
        """Adds a handler of the *click* event. This handler will be called whenever the button is pressed
        and released once. If a second click happens before :attr:`double_click_timeout` expires, this event is
        not raised. The *double click* event is raised instead."""
        self._click_handlers.append(func)

    def remove_on_click(self, func: EventHandler) -> None:
        """Removes a handler of the *click* event."""
        self._click_handlers.remove(func)

    def add_on_double_click(self, func: EventHandler) -> None:
        """Adds a handler of the *double click* event. This handler will be called whenever the button is pressed
        and released twice within a period of time at most equal to :attr:`double_click_timeout`.
        """
        self._double_click_handlers.append(func)

    def remove_on_double_click(self, func: EventHandler) -> None:
        """Removes a handler of the *double click* event."""
        self._double_click_handlers.remove(func)
