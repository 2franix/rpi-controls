# GPIO controller for Raspberry Pi

[![CI](https://github.com/2franix/rpi-controls/actions/workflows/python-package.yml/badge.svg)](https://github.com/2franix/rpi-controls/actions/workflows/python-package.yml)
[![TestPyPI](https://github.com/2franix/rpi-controls/actions/workflows/python-publish-testpypi.yml/badge.svg)](https://github.com/2franix/rpi-controls/actions/workflows/python-publish-testpypi.yml)
[![PyPI](https://github.com/2franix/rpi-controls/actions/workflows/python-publish-pypi.yml/badge.svg)](https://github.com/2franix/rpi-controls/actions/workflows/python-publish-pypi.yml)

This package provides classes to interact with physical buttons connected to a Raspberry Pi's GPIO. Those classes make it easy to run event-driven callbacks.

# Brief example

The example below illustrates the implementation of a callback to execute asynchronously when clicking a button:
```python
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
```

Asynchronous callbacks are optional and synchronous ones work just fine. Check out the full documentation [here](https://rpi-controls.readthedocs.io) for all the details.
