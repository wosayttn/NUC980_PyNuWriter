# NuWriter Desktop GUI

Cross-platform Qt frontend for the existing NuWriter backend. The main layout
follows NuWriter's Choose type, DDR Init, Re-Connect, image list, Parameters,
and operation buttons. The backend is run as a separate Python process.

## Install And Start

From the `NUC980_PyNuWriter` directory, using your Python environment:

```bash
python -m pip install -r gui/requirements.txt
```

```bash
python gui/app.py
```

On Linux/macOS, use `python3` if needed. PySide6 requires a desktop session;
Linux also needs its system libusb and Qt platform libraries. If Qt reports
a missing xcb cursor library on Debian/Ubuntu, install `libxcb-cursor0`.
Windows needs the NUC980 WinUSB driver and 64-bit Python for the bundled DLL.

The GUI and backend use the same Python interpreter. Starting the GUI does
not open serial ports, scan USB targets, reset the board, or write flash.
The main window starts at the top-left of the screen's available area and has
no Help menu. Reinstall the GUI requirements after updating to include `pyte`
for ANSI terminal handling.

## Serial Console

The **Console**, **USB Trace**, and **Op. log** buttons are right-aligned after
**Refresh** in the USB Device row and stay available during backend operations.
Click **Console** to show or hide the console window.
The port list, baud rate, Refresh, and **Open** controls are inside
that window. Select the board's debug UART/VCOM, not the CH341 reset adapter,
then click **Open** to connect. Showing the window does not open a serial port.
Refresh the list after connecting or removing an adapter.

On its first opening without saved geometry, the console matches the main
window's size and opens on its right, aligned at the top. Afterward, hiding or
closing it retains its position and size; reopening restores them without
following main-window moves or resizing. Geometry is also saved in settings
for the next application run. Qt may adjust it if the original screen is no
longer available; Wayland may override window positions.
The terminal has no visible horizontal or vertical scrollbars. Use the
mouse wheel to browse scrollback; new output always returns to the latest text.

The black terminal receives UART output and accepts keyboard input directly.
Defaults are 115200 baud, 8 data bits, no parity, 1 stop bit, and no flow control.
Enter sends CR, arrow keys send terminal sequences, and Ctrl+C sends an interrupt
unless text is selected for copying. Input has no local echo; the target controls
what appears. Pasting multiple lines requires confirmation.

Only one console window/connection is used. Hiding it with **Console** keeps the
connection and output active; showing it again retains the history. The same
button displays **Open** when disconnected and **Close** after a successful
connection. Click **Close** before changing the port or baud rate. Opening
failure, closing, or device removal leaves the button showing **Open**.
Closing the console window,
pressing Esc outside terminal input, or exiting the main window releases the port.
The console remains usable during backend operations.

ANSI foreground/background colors support standard/bright colors, 256 colors,
and RGB. Bold, italic, underline, strikethrough, reverse video, and color reset
are rendered along with `pyte` cursor movement and clearing.

The console has no Save or Clear buttons; text can be selected and copied.
DTR/RTS are requested inactive before opening; some adapters/drivers may still
pulse lines on open, so verify your reset wiring.

## USB Trace

The **USB Trace** button beside **Console** shows or hides the trace window.
Showing it enables recording; hiding or closing it disables recording, backend
trace formatting, and GUI trace processing. This also applies during a running
operation, without restarting the backend or interrupting USB transfers.

The trace window opens to the right of the main window, aligned at the top,
and follows main-window moves and resizing without changing its own size.
It stays on the main window's screen; insufficient space may cause overlap.
On Wayland, the compositor may override the requested position.

Trace records go only to this window. Commands, progress, and errors remain in
Operation Log. The trace window uses colored, fixed-width text on black.
`H->D` means host to device; `D->H` means device to host.
Data values start on the next line, with 16 bytes per line and five leading
spaces. Data lines keep the transaction color; a trailing `...` marks a
truncated preview.

| Transaction | Prefix | Color |
| --- | --- | --- |
| CONTROL OUT | `H->D` | Blue |
| CONTROL IN | `D->H` | Cyan |
| BULK OUT | `H->D` | Amber |
| BULK IN | `D->H` | Green |

Hiding or closing the window retains existing contents but adds no new records.
Only one trace window is used; its button stays available during operations.
The latest 10,000 lines are retained and new output scrolls to the latest entry.
Text can be selected and copied. Trace data may contain image or readback bytes;
review it before sharing.

## Program Flash

1. Prepare USB Boot mode and connect the USB Device port.
2. Select DDR Init for your board. Use Refresh to list USB targets, or leave
   Auto selected when only one target is connected.
3. Click Re-Connect to initialize DDR/XUSB. This runs the pre-attach reset hook.
4. Choose SPI NAND, SPI NOR, NAND, or SD/eMMC. Browse for an image and select
   Data, Environment, Loader, or Pack.
5. Set the image start offset and execution address, then click Program.

DDR Init lists only INI files from the project's relative `sys_cfg` directory.
External DDR file browsing is unavailable. Paths are resolved relative to the
project location, independently of the current working directory.

All addresses and read/erase lengths are bytes; use `0x` for hexadecimal.
Loader images need the selected DDR settings and the correct linked entry
address. Their start offset is 0 for flash or `0x400` for SD/eMMC.

Each operation is checked offline before the actual command starts. A failed
check prevents the actual operation from starting. Save JSON writes the
configuration file directly.

## Actions

| Action | Behavior |
| --- | --- |
| Program | Programs the selected row only; existing destination data may be overwritten |
| Program + Verify | Programs one image, then uses backend readback verification |
| Verify | Reads back a Data image and compares it; never programs |
| Read | Saves the selected byte range, or the whole device, to a file |
| Erase | Erases all good blocks or an aligned range after confirmation |
| Format | SD/eMMC only; replaces partition/format data and reinitializes DDR/XUSB |

Standalone Verify supports Data images only. For Loader and Environment,
use Program + Verify. Pack verification is not supported. Read/Verify obey
the backend's read alignment, including 64 KiB for SPI NOR.

SD/eMMC Format sizes are MiB, and the final partition uses remaining capacity.
Formatting and erase destroy data. Interrupted writes or erases cannot be undone;
check or reset the target before reconnecting. Use the title-bar close button
to exit after the current operation has finished.

## SDRAM

Choose SDRAM, select an image and its address, then select Download only or
Download and run. Enable DTB file to supply a DTB and address. Optional bootargs
change only the downloaded DTB copy. RAM execution may start software that
accesses flash; a completed transfer does not certify successful boot.

## Pack

Choose Pack to open/edit a JSON configuration. Add, Modify, and Delete edit
the image table; Save JSON writes the configuration. Loader-specific fields
such as `ddr_ini`, `page_size`, and SPI commands go in Additional JSON parameters.
SD/eMMC partition records use the same JSON fields as the backend.

Output generates a pack without connecting to a board. It uses a temporary
snapshot of the edited configuration and leaves an opened JSON file unchanged.
Relative image/DDR paths resolve from the configuration directory. Save JSON
keeps that directory so relative paths do not change meaning. The snapshot
is removed when the operation finishes or is cancelled.

Choose Mass Production to program a pack to all connected targets sequentially.
Re-Connect in this mode initializes all targets. Device-specific selection,
readback, and pack verification are unavailable in this mode.

## Saved Settings And Input Validation

Closing the application saves `settings.json` in Qt's per-user application
configuration directory (`QStandardPaths.AppConfigLocation`). On Windows this
is normally `%LOCALAPPDATA%/NUC980 PyNuWriter`; on Linux it is normally
`~/.config/NUC980 PyNuWriter` (or the directory selected by `XDG_CONFIG_HOME`).

The JSON stores the selected media/DDR/USB target, image lists and selected
rows, page fields/options, Pack drafts and configuration path, dialog defaults,
Console port/baud, and window sizes. Paths to DDR files remain restricted to
the bundled `sys_cfg` directory. Existing DDR selections migrate from the old
platform settings. Existing logs, connection state, active operations, and
popup visibility are not restored. Startup never connects or programs a target.

Writes are atomic. Invalid JSON loads defaults and is backed up as
`settings.json.<timestamp>.invalid` before a replacement is written. Invalid
individual values are ignored. If saving fails, the application reports the
error and stays open so the settings are not silently lost.

Address and byte-length editors require `0x` followed by 1-8 hexadecimal digits
(`0x0` through `0xffffffff`). Invalid characters are rejected while typing;
incomplete or out-of-range values cannot start an operation. Read/erase lengths
must be nonzero. Numeric partition controls enforce their own ranges. File paths
and bootargs reject control characters; source/output paths are checked before
use. Additional Pack parameters must be a JSON object. Backend preflight still
checks image formats, alignment, and device-specific constraints before access.

## Logs And Tests

When Operation Log is first opened during an application run, it queries the
host OS/kernel, CPU architecture and core
counts, total/available RAM, Python interpreter, Qt platform, display sizes/DPI
scale, and settings-file location. It also lists versions and loaded status for
PySide6, pyte, pyserial, psutil, PyUSB, and pyfdt using package metadata; deferred
backend modules are not imported just to report their versions.
Missing hardware information is marked
unavailable. These queries do not run when the main window starts, and are not
repeated when the log is hidden and shown again. This does not scan USB devices
or open serial ports. The record remains in the log and is not saved in settings.

Click **Op. log** to toggle the nonmodal Operation Log window on or off.
The button stays checked while the window is shown. Only one log window is
used; output continues to accumulate while hidden and is retained when shown
again. The log appears directly below the main window, matches its outer width
including window borders, has
a fixed height of 320, and follows it when moved or resized. Exiting the main
window also hides the log.

The log window has a **NuWriter - Operation Log** title bar for dragging.
It has no minimize, maximize, close, Save, or Clear buttons.
Esc and Alt+F4 do not close it; use **Op. log** to hide it. Console window
controls are unchanged.

Commands are blue and normal backend results are green. Result lines containing
`Error` (case-insensitive) are red. Text can be selected and copied. New output
always scrolls to the latest text.
The main 800x560 window uses the freed
space for the active media page, keeping Flash controls side by side.

An operation cannot start while another is running.

```bash
python -m unittest discover -s gui -p test_gui.py -v
```

Tests use simulated processes and the real backend's offline checks, not
hardware operations. Windows rendering and offline flows have been checked;
Linux/macOS and real-board GUI operations still require platform testing.

The GUI does not implement raw/OOB programming or custom device geometry.
It does not launch the Windows executable or modify the backend source.