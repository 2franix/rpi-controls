#!/usr/bin/python3

import RPi.GPIO as GPIO
import time
import threading
import subprocess
import signal
import os

status = 'off'
stopped = False
buttonPressedRisingEdgeTimestamp = None # Timestamp of the last button pressed event.
