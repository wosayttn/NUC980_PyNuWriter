# Windows Drivers

[English](README.md) | [简体中文](README.zh-CN.md) | [繁體中文](README.zh-TW.md)

[Main guide](../README.md) | [GUI guide](../gui/README.md) | [Sample guide](../sample/README.md)

## NUC980 USB Driver

Run `WinUSB4NuVCOM.exe` to install the NUC980 USB driver. Select the board's
USB Device interface, not its debug VCOM or a CH341 serial adapter.

## CH341 USB-Serial Driver

Install this driver only if you use a CH341 adapter for serial/reset control.

1. Download `CH341SER.EXE` from WCH: [English](https://www.wch-ic.com/downloads/CH341SER_EXE.html)
  or [Chinese](https://www.wch.cn/downloads/CH341SER_EXE.html). It supports
  32-bit and 64-bit Windows, including Windows 10 and 11.
2. Run the installer, then reconnect the CH341 adapter.
3. In Device Manager, check **Ports (COM & LPT)** for the CH341 serial port.

From the `NUC980_PyNuWriter` directory, list available serial ports:

```bash
python ch341_reset_uart.py --list
```

Use the USB-serial/VCP driver, not CH341PAR. Do not replace the CH341 driver
with WinUSB; NUC980 USB programming and CH341 serial/reset use separate drivers.

## libusb Runtime

`libusb-1.0.dll` is the unmodified libusb 1.0.29 Windows x64 DLL from the
official `VS2022/MS64/dll` build. It requires 64-bit Python and does not
replace the NUC980 WinUSB driver.

On Windows, the tool automatically adds this directory's absolute path to
its process `PATH` before USB access when the DLL is present. It does not
change the permanent user or system `PATH`. If the DLL is missing, the
existing system-library search is used.

Upstream release: https://github.com/libusb/libusb/releases/tag/v1.0.29

DLL SHA-256:

```text
5072054cb3002ae071f382ad5c2c2b0092d9451c537d0c13444c2b6f968f7251
```

## libusb Copyright And License

Copyright remains with the libusb authors and contributors. libusb is licensed
under the GNU Lesser General Public License, version 2.1 or later, and is
provided without warranty. It is not covered by this project's Apache license.

- [License text](LICENSE.libusb.txt): original upstream COPYING file.
- [Authors](AUTHORS.libusb.txt): original upstream contributor list.
- [Corresponding source](libusb-1.0.29.tar.bz2): complete, unmodified official
  source release, including file-specific copyright notices and build scripts.

Keep these files with the DLL when redistributing this directory. The existing
WinUSB installer retains its original license and copyright terms.