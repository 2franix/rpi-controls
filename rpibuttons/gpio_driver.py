#!/usr/bin/python3

from __future__ import annotations

class GpioDriver:
    def input(self, pin_id: int) -> bool:
        raise NotImplementedError("Missing function 'input'.")

    def configure_button(self, pin_id: int) -> None:
        raise NotImplementedError("Missing function 'configure_button'.")
