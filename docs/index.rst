.. rpi-controls documentation master file, created by
   sphinx-quickstart on Sun Sep 19 11:41:42 2021.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

rpi-controls - RPi's GPIO buttons
=================================

The rpicontrols package simplifies interactions with physical buttons connected to
GPIO pins on a Raspberry Pi.

.. code:: python

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

Py Module
~~~~~~~~~

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
