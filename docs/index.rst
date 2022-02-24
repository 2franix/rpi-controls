.. rpi-controls documentation master file, created by
   sphinx-quickstart on Sun Sep 19 11:41:42 2021.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

rpi-controls - RPi's GPIO buttons
=================================

The rpicontrols package simplifies interactions with physical buttons connected to
GPIO pins on a Raspberry Pi.

It abstracts away the complexity of monitoring the state of GPIO pins to detect events
such as presses, clicks, double clicks... User code can subscribe to those high-level
events the same way it would with most UI frameworks.

.. tabs::

    .. code-tab:: python Asynchronous

        from rpicontrols import Controller, Button, PullType, make_controller

        # Initialize the button controller. A single instance can handle as many buttons as needed.
        controller: Controller = make_controller()

        # Create the button, connected to pin 22.
        button: Button = controller.make_button(
            input_pin_id=22,  # Id of the GPIO pin the button switch is connected to.
            input=Button.InputType.PRESSED_WHEN_OFF,  # Depends on the physical wiring of the button.
            pull=PullType.UP  # Whether to enable pull-up or pull-down resistor. Use PullType.NONE to disable.
        )

        # Define a callback to run when button is clicked.
        async def on_click_callback(button: Button) -> None:
            print(f'Button {button.name} clicked!')

            # Run some IO-bound task without blocking.
            # Other event handlers may run while waiting.
            await asyncio.sleep(2)

        # Subscribe to the click event.
        button.add_on_click(on_click_callback)

        # Start controller main loop. Use controller.start_in_thread() for the non-blocking version.
        controller.run()

    .. code-tab:: python Synchronous

        from rpicontrols import Controller, Button, PullType, make_controller

        # Initialize the button controller. A single instance can handle as many buttons as needed.
        controller: Controller = make_controller()

        # Create the button, connected to pin 22.
        button: Button = controller.make_button(
            input_pin_id=22,  # Id of the GPIO pin the button switch is connected to.
            input=Button.InputType.PRESSED_WHEN_OFF,  # Depends on the physical wiring of the button.
            pull=PullType.UP  # Whether to enable pull-up or pull-down resistor. Use PullType.NONE to disable.
        )

        # Define a callback to run when button is clicked.
        def on_click_callback(button: Button) -> None:
            print(f'Button {button.name} clicked!')

        # Subscribe to the click event.
        button.add_on_click(on_click_callback)

        # Start controller main loop. Use controller.start_in_thread() for the non-blocking version.
        controller.run()

As shown in the example above, event handlers can be either synchronous or asynchronous functions.

Synchronous handlers can only run one at a time. One handler must finish its execution for another to be executed,
so long-running synchronous handlers are discouraged.

On the contrary, asynchronous handlers can run concurrently, in the sense that one handler can run while another is awaiting an
IO-bound task.

In all cases, event handlers are all run on the same thread.

.. module:: rpicontrols

Summary
~~~~~~~

.. autosummary::
    make_controller
    Controller
    Controller.Status
    Button


Functions
~~~~~~~~~

.. autofunction::
     make_controller

Controller Object
~~~~~~~~~~~~~~~~~

.. autoclass:: Controller
    :members:

Button Objects
~~~~~~~~~~~~~~

.. autoclass:: Button
    :members:

GPIO Drivers
~~~~~~~~~~~~

.. module:: rpicontrols.rpi_gpio_driver

.. class:: RpiGpioDriver(mode: int = RPi.GPIO.BOARD)

    Implementation of the GPIO driver interface based on `RPi.GPIO <https://pypi.org/project/RPi.GPIO/>`_.
    This is the default driver for button controllers.

    :param mode: value describing the meaning of GPIO pin numbers. Refer to RPi.GPIO documentation for more information.
