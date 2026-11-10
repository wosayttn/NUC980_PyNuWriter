#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CH341A (USB-SERIAL mode) reset signal generator.

Important
---------
With the "USB-SERIAL CH341A" driver, the CH341A operates as a USB-to-UART
adapter. Vendor commands such as 0xA0/0xA2 cannot control D0-D5 GPIO pins
in this mode. They require the CH341PAR parallel/I2C/SPI driver and
CH341DLL.DLL. Writing these bytes to a serial port only sends them over TXD.

Available serial-mode control outputs:
    RTS  - controlled by ser.rts
    DTR  - controlled by ser.dtr
    TXD  - driven low with break_condition

Signal polarity (TTL CH341A):
    ser.rts = True   -> RTS LOW  (0V)
    ser.rts = False  -> RTS HIGH (3.3V)
    The same applies to DTR.

For active-low reset:
    assert   -> ser.rts = True
    deassert -> ser.rts = False

Usage
-----
    python ch341_reset_uart.py                 # 1-second active-low RTS pulse
    python ch341_reset_uart.py --pin dtr       # Use DTR instead
    python ch341_reset_uart.py --duration 0.5  # 500 ms pulse
    python ch341_reset_uart.py --toggle        # Toggle for signal measurement
    python ch341_reset_uart.py --list          # List serial ports
"""

import argparse
import sys
import time

import serial
import serial.tools.list_ports


DEFAULT_PIN = "rts"
ACTIVE_LOW = True
CH341_NOT_FOUND = 3


def find_ch341_port():
    """Find the CH341 serial port automatically."""
    for port in serial.tools.list_ports.comports():
        desc = (port.description or "").upper()
        hwid = (port.hwid or "").upper()
        if "CH341" in desc or "VID:PID=1A86" in hwid:
            return port.device
    return None


def list_ports():
    """List all serial ports."""
    print("Detected serial ports:")
    found = False
    for port in serial.tools.list_ports.comports():
        desc = (port.description or "").upper()
        hwid = (port.hwid or "").upper()
        mark = ""
        if "CH341" in desc or "VID:PID=1A86" in hwid:
            mark = "   <-- CH341"
            found = True
        print(f"  {port.device}: {port.description}{mark}")
    if not found:
        print("  (No CH341 found)")


class CH341NotFoundError(RuntimeError):
    pass


class CH341Reset:
    """Generate reset pulses using CH341A RTS, DTR, or TXD."""

    def __init__(self, port=None, pin=DEFAULT_PIN, active_low=ACTIVE_LOW):
        if pin not in ("rts", "dtr", "txd"):
            raise ValueError(f"Unsupported pin: {pin} (choose rts / dtr / txd)")
        self.port = port
        self.pin = pin
        self.active_low = active_low
        self.serial = None

    def connect(self):
        port = self.port or find_ch341_port()
        if port is None:
            raise CH341NotFoundError("No CH341 serial port found; manual reset is required")

        self.serial = serial.Serial(
            port=port,
            baudrate=9600,
            timeout=1,
            rtscts=False,
            dsrdtr=False,
        )
        self.port = port
        print(f"Connected: {port}  (control pin: {self.pin.upper()})")

        # Start with reset deasserted.
        self._set_asserted(False)
        time.sleep(0.05)

    def _set_asserted(self, asserted):
        """
        asserted=True  -> assert reset (LOW for active-low reset)
        asserted=False -> release reset
        """
        if self.serial is None:
            raise RuntimeError("Not connected")

        # pyserial: rts/dtr = True drives the TTL pin LOW.
        # break_condition = True drives TXD LOW.
        level_flag = asserted if self.active_low else not asserted

        if self.pin == "rts":
            self.serial.rts = level_flag
        elif self.pin == "dtr":
            self.serial.dtr = level_flag
        else:  # txd
            self.serial.break_condition = level_flag

    def pulse(self, duration=1.0):
        """Generate one reset pulse."""
        polarity = "active-low" if self.active_low else "active-high"
        assert_level = "LOW (0V)" if self.active_low else "HIGH (3.3V)"
        release_level = "HIGH (3.3V)" if self.active_low else "LOW (0V)"

        print(f"Generating a {duration}-second reset pulse ({polarity}, {self.pin.upper()})")

        print(f"  assert   -> {self.pin.upper()} = {assert_level}")
        self._set_asserted(True)

        time.sleep(duration)

        print(f"  deassert -> {self.pin.upper()} = {release_level}")
        self._set_asserted(False)
        time.sleep(0.05)

        print("Done")

    def toggle_test(self, period=2.0, count=5):
        """Toggle the output for multimeter or oscilloscope measurements."""
        assert_level = "0V" if self.active_low else "3.3V"
        release_level = "3.3V" if self.active_low else "0V"

        print(f"Toggle test: {self.pin.upper()} changes every {period} seconds, {count} cycles")
        print(f"Connect a multimeter between {self.pin.upper()} and GND")
        for i in range(count):
            self._set_asserted(True)
            print(f"  [{i + 1}/{count}] assert   (expected {assert_level})")
            time.sleep(period)
            self._set_asserted(False)
            print(f"  [{i + 1}/{count}] deassert (expected {release_level})")
            time.sleep(period)

    def close(self):
        if self.serial and self.serial.is_open:
            self._set_asserted(False)
            self.serial.close()
            print("Connection closed")


def main():
    parser = argparse.ArgumentParser(
        description="CH341A (USB-SERIAL) reset signal generator"
    )
    parser.add_argument("--port", help="Serial port, for example COM37 or /dev/ttyUSB0")
    parser.add_argument(
        "--pin",
        choices=["rts", "dtr", "txd"],
        default=DEFAULT_PIN,
        help="Reset output pin (default: rts)",
    )
    parser.add_argument(
        "--duration", type=float, default=1.0, help="Reset pulse duration in seconds (default: 1.0)"
    )
    parser.add_argument(
        "--active-high",
        action="store_true",
        help="Use active-high reset (default: active-low)",
    )
    parser.add_argument("--list", action="store_true", help="List serial ports only")
    parser.add_argument(
        "--toggle", action="store_true", help="Toggle the output for signal measurements"
    )
    parser.add_argument(
        "--period", type=float, default=2.0, help="Hold time per toggle level in seconds (default: 2.0)"
    )
    parser.add_argument(
        "--count", type=int, default=5, help="Number of toggle cycles (default: 5)"
    )
    args = parser.parse_args()

    if args.list:
        list_ports()
        return 0

    ctl = CH341Reset(
        port=args.port,
        pin=args.pin,
        active_low=not args.active_high,
    )

    try:
        ctl.connect()
        if args.toggle:
            ctl.toggle_test(period=args.period, count=args.count)
        else:
            ctl.pulse(args.duration)
    except CH341NotFoundError as error:
        print(f"Warning: {error}")
        return CH341_NOT_FOUND
    except (RuntimeError, ValueError, serial.SerialException) as e:
        print(f"Error: {e}")
        print()
        list_ports()
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted")
        return 130
    finally:
        ctl.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
