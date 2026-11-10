#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CH341A (USB-SERIAL 模式) Reset Signal 產生器

重要說明
--------
CH341A 掛在 "USB-SERIAL CH341A" 驅動下時是一顆 USB 轉 UART 晶片。
此模式下 **無法** 用 0xA0/0xA2 這類 vendor 命令去控制 D0~D5 GPIO
(那些命令只在 CH341PAR 並口/I2C/SPI 驅動 + CH341DLL.DLL 下才有效)。
往虛擬 COM port 寫那些位元組，只是把它們當成資料從 TXD 送出去而已。

串口模式下實際可控制的輸出腳位只有:
    RTS  - 由 ser.rts 控制
    DTR  - 由 ser.dtr 控制
    TXD  - 可用 break_condition 拉低

電平極性 (TTL 版 CH341A):
    ser.rts = True   -> RTS 腳位輸出 LOW  (0V)
    ser.rts = False  -> RTS 腳位輸出 HIGH (3.3V)
    DTR 同理。

因此 active-low reset (低電平有效):
    assert   (拉低) -> ser.rts = True
    deassert (放開) -> ser.rts = False

用法
----
    python ch341_reset_uart.py                 # RTS 腳位，1 秒 active-low 脈波
    python ch341_reset_uart.py --pin dtr       # 改用 DTR
    python ch341_reset_uart.py --duration 0.5  # 500ms
    python ch341_reset_uart.py --toggle        # 慢速切換，方便用電表量測
    python ch341_reset_uart.py --list          # 列出 COM port
"""

import argparse
import sys
import time

import serial
import serial.tools.list_ports


DEFAULT_PIN = "rts"
ACTIVE_LOW = True


def find_ch341_port():
    """自動尋找 CH341 對應的 COM port"""
    for port in serial.tools.list_ports.comports():
        desc = (port.description or "").upper()
        hwid = (port.hwid or "").upper()
        if "CH341" in desc or "VID:PID=1A86" in hwid:
            return port.device
    return None


def list_ports():
    """列出所有 COM port"""
    print("偵測到的 COM port:")
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
        print("  (未找到 CH341)")


class CH341Reset:
    """透過 CH341A 串口的 RTS / DTR / TXD 產生 reset 脈波"""

    def __init__(self, port=None, pin=DEFAULT_PIN, active_low=ACTIVE_LOW):
        if pin not in ("rts", "dtr", "txd"):
            raise ValueError(f"不支援的腳位: {pin} (可用: rts / dtr / txd)")
        self.port = port
        self.pin = pin
        self.active_low = active_low
        self.serial = None

    def connect(self):
        port = self.port or find_ch341_port()
        if port is None:
            raise RuntimeError("未找到 CH341 COM port，請確認驅動與 USB 連接")

        self.serial = serial.Serial(
            port=port,
            baudrate=9600,
            timeout=1,
            rtscts=False,
            dsrdtr=False,
        )
        self.port = port
        print(f"已連接: {port}  (控制腳位: {self.pin.upper()})")

        # 進入非 assert 狀態
        self._set_asserted(False)
        time.sleep(0.05)

    def _set_asserted(self, asserted):
        """
        asserted=True  -> reset 有效 (active-low 時腳位為 LOW)
        asserted=False -> reset 釋放
        """
        if self.serial is None:
            raise RuntimeError("尚未連接")

        # pyserial: rts/dtr = True 會讓 TTL 腳位輸出 LOW
        # break_condition = True 會讓 TXD 輸出 LOW
        level_flag = asserted if self.active_low else not asserted

        if self.pin == "rts":
            self.serial.rts = level_flag
        elif self.pin == "dtr":
            self.serial.dtr = level_flag
        else:  # txd
            self.serial.break_condition = level_flag

    def pulse(self, duration=1.0):
        """產生一次 reset 脈波"""
        polarity = "active-low" if self.active_low else "active-high"
        assert_level = "LOW (0V)" if self.active_low else "HIGH (3.3V)"
        release_level = "HIGH (3.3V)" if self.active_low else "LOW (0V)"

        print(f"產生 {duration} 秒 reset 脈波 ({polarity}, {self.pin.upper()})")

        print(f"  assert   -> {self.pin.upper()} = {assert_level}")
        self._set_asserted(True)

        time.sleep(duration)

        print(f"  deassert -> {self.pin.upper()} = {release_level}")
        self._set_asserted(False)
        time.sleep(0.05)

        print("完成")

    def toggle_test(self, period=2.0, count=5):
        """持續切換，方便用三用電表 / 示波器量測"""
        assert_level = "0V" if self.active_low else "3.3V"
        release_level = "3.3V" if self.active_low else "0V"

        print(f"切換測試: {self.pin.upper()} 每 {period} 秒翻轉一次，共 {count} 輪")
        print(f"請把電表接在 {self.pin.upper()} 腳位與 GND 之間")
        for i in range(count):
            self._set_asserted(True)
            print(f"  [{i + 1}/{count}] assert   (應為 {assert_level})")
            time.sleep(period)
            self._set_asserted(False)
            print(f"  [{i + 1}/{count}] deassert (應為 {release_level})")
            time.sleep(period)

    def close(self):
        if self.serial and self.serial.is_open:
            self._set_asserted(False)
            self.serial.close()
            print("已關閉連接")


def main():
    parser = argparse.ArgumentParser(
        description="CH341A (USB-SERIAL) reset signal 產生器"
    )
    parser.add_argument("--port", help="指定 COM port，例如 COM37")
    parser.add_argument(
        "--pin",
        choices=["rts", "dtr", "txd"],
        default=DEFAULT_PIN,
        help="用來輸出 reset 的腳位 (預設 rts)",
    )
    parser.add_argument(
        "--duration", type=float, default=1.0, help="reset 脈波長度，秒 (預設 1.0)"
    )
    parser.add_argument(
        "--active-high",
        action="store_true",
        help="改為 active-high (預設 active-low)",
    )
    parser.add_argument("--list", action="store_true", help="只列出 COM port")
    parser.add_argument(
        "--toggle", action="store_true", help="持續切換模式，方便量測驗證"
    )
    parser.add_argument(
        "--period", type=float, default=2.0, help="toggle 模式每段電位持續秒數 (預設 2.0)"
    )
    parser.add_argument(
        "--count", type=int, default=5, help="toggle 模式輪數 (預設 5)"
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
    except (RuntimeError, ValueError, serial.SerialException) as e:
        print(f"錯誤: {e}")
        print()
        list_ports()
        return 1
    except KeyboardInterrupt:
        print("\n已中止")
        return 130
    finally:
        ctl.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
