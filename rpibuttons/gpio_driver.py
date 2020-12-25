#!/usr/bin/python3

from __future__ import annotations

class GpioDriver:
    _INSTANCE: GpioDriver

    def __init__(self):
        assert not _INSTANCE, "RpiGpioDriver has already been initialized."
        _INSTANCE = self

    @staticmethod
    def get() -> GpioDriver:
        assert GpioDriver._INSTANCE, "No GPIO driver set."
        return GpioDriver._INSTANCE

    def is_button_pressed(self, pin_id: int) -> bool:
        raise NotImplementedError("Missing function 'is_button_pressed'.")

    def configure_button(self, pin_id: int) -> None:
        raise NotImplementedError("Missing function 'configure_button'.")
