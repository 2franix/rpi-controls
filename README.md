# GPIO controller for Raspberry Pi

[![Python package](https://github.com/2franix/rpi-controls/actions/workflows/python-package.yml/badge.svg)](https://github.com/2franix/rpi-controls/actions/workflows/python-package.yml)

This package provides classes to interact with physical buttons connected to a Raspberry Pi's GPIO. Those classes make it easy to run event-driven code.

## Example for the impatient

The example below shows how to run some code when a button is clicked:

```python
from rpicontrols import Controller, Button, PullType, make_controller

# Initialize the button controller. A single instance can handle as many buttons as needed.
controller: Controller = make_controller()

# Create the button, connected to pin 22.
button: Button = controller.make_button(
	pin_id=22,i  # Id of the GPIO pin the button switch is connected to.
	input=Button.InputType.PRESSED_WHEN_OFF,  # Depends on the physical wiring of the button.
	pull=PullType.UP  # Whether to enable pull-up or pull-down resistor. Use PullType.NONE to disable.
)

# Define a callback to run when button is clicked.
def on_click_callback(button: Button) -> None:
	print(f'Button {button.name} clicked!')

# Subscribe to the click event.
button.add_on_click(on_click_callback)

# Start controller main loop. Use controller.start_in_thread() for the non-blocking version.
controller.run() # Blocks until ctrl+c is hit.
```
