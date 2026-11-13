# NUC980 PyNuWriter

Cross-platform CLI and desktop GUI for NUC980 RAM downloads, NAND/SPI flash
programming, and SD/eMMC programming. See the [desktop GUI guide](gui/README.md)
for interactive use, or follow the CLI examples below.

## Install

The CLI requires Python 3.9+ and libusb-1.0. CI uses Python 3.14; use a Python
version supported by PySide6 for the GUI. Run the following commands from this
repository directory. Keep `sys_cfg`, `xusb`, `driver`, and `sample` beside the
application, and use the same virtual environment for the CLI and GUI.

### Windows

Install x86-64 Python for the bundled x64 libusb DLL. In PowerShell:

```bash
python -m venv .venv
```

```bash
.\.venv\Scripts\Activate.ps1
```

```bash
python -m pip install -r requirements.txt
```

Install the NUC980 WinUSB driver using the [driver guide](driver/README.md).
Select the board's USB Device interface, not its debug VCOM or CH341 adapter.
NuWriter adds the bundled DLL directory to the current process PATH before
USB access; it does not change the permanent PATH. The CH341 driver is needed
only when using that optional reset adapter.

### Linux

Debian/Ubuntu example; other distributions need equivalent packages:

```bash
sudo apt-get update
```

```bash
sudo apt-get install -y python3 python3-venv python3-pip libusb-1.0-0
```

```bash
python3 -m venv .venv
```

```bash
source .venv/bin/activate
```

```bash
python -m pip install -r requirements.txt
```

For the desktop GUI, common Qt prerequisites include:

```bash
sudo apt-get install -y libegl1 libgl1 libxkbcommon0 libxcb-cursor0 fonts-noto-core
```

Grant USB access through device permissions. For an active local desktop
session, place this rule in `/etc/udev/rules.d/70-nuvoton-nuwriter.rules`:

```udev
SUBSYSTEM=="usb", ATTR{idVendor}=="0416", ATTR{idProduct}=="5963", TAG+="uaccess"
```

```bash
sudo udevadm control --reload-rules
```

Reconnect the board. Headless/remote users may need a group-based rule instead.
Serial permissions are separate; Debian/Ubuntu commonly uses the `dialout`
group. Do not replace the CH341 serial driver with a USB programming driver.

### macOS

Using [Homebrew](https://brew.sh/), install Python and libusb:

```bash
brew install python@3.14 libusb
```

```bash
"$(brew --prefix python@3.14)/bin/python3.14" -m venv .venv
```

```bash
source .venv/bin/activate
```

```bash
python -m pip install -r requirements.txt
```

Python and libusb must use the same architecture (arm64 or x86_64). Linux/macOS
use their system libusb, not the Windows DLL or WinUSB installer.

## Desktop GUI

In the activated virtual environment:

```bash
python -m pip install -r gui/requirements.txt
```

```bash
python gui/app.py
```

The [GUI guide](gui/README.md) covers Console, USB Trace, Operation Log,
saved settings, and Mass Production. A desktop session is required. Starting
the GUI does not connect, reset, or program a board.

## Sample Files

Examples use the supplied [sample files](sample/README.md) and NUC980DK71YC DDR
settings. Confirm the board, DDR, flash geometry, and boot medium before use;
the sample layouts are not universal defaults.

| Template | Backend mode | Root filesystem |
| --- | --- | --- |
| [SPI NAND](sample/config_spinand.json) | `spinand` | UBI at 0x800000 |
| [SD1](sample/config_sd1.json) | `sd` | ext4 at 0x800000 |

SD1 is the board workflow name, not a separate CLI mode. The SD1 template uses
8 MiB of reserved space and a partition taking the remaining card capacity.
Its partition record differs from the prebuilt SD pack's raw MBR. Use `zImage`
for raw-kernel RAM execution; the flash-pack templates use `uImage`, which
includes a U-Boot header. Offline checks do not certify successful boot.

## Connect

1. Select USB Boot mode and power on the board.
2. Connect its USB Device port to the PC, not the VCOM/debug port.
3. List devices and initialize DDR/XUSB:

```bash
python nuwriter.py --list
```

```bash
python nuwriter.py -a NUC980DK71YC.ini
```

Initialize again after resetting or power-cycling. Subsequent commands below
use the running XUSB. `--ddr` supplies DDR settings; it does not initialize.

**Automatic reset:** if `pre-attach-hook.py` is present, `-a` runs it before
connecting. The supplied hook resets through CH341 when detected. Without a
CH341 adapter, it prints a notice and skips automatic reset; manually reset
the board into USB Boot mode before connecting. Errors opening or controlling
a detected adapter still stop the operation. Offline checks and packing do not
reset. The standalone reset helper returns exit code 3 when no CH341 is found.

## Program And Read Flash

Program main U-Boot at byte offset `0x100000` and verify the data:

```bash
python nuwriter.py -w spinand 0x100000 sample/u-boot-spinand.bin -o verify
```

Read `0x20000` bytes back to a file:

```bash
python nuwriter.py -r spinand 0x100000 0x20000 readback.bin
```

This programs main U-Boot only, not SPL, environment, kernel, or rootfs.
Reading creates or overwrites the output file. To read the whole device:

```bash
python nuwriter.py -r spinand all backup.bin
```

SPI NOR read-all additionally requires its byte capacity with `--flash-size`.
Normal reads do not include OOB/bad-block markers and are not physical-chip
backups of every byte.

**Erase All deletes flash contents. Back up required data first.**
NAND/SPI NAND erase skips marked bad blocks and retains their markers.

```bash
python nuwriter.py -e spinand all
```

Before replacing a UBI image, remove old UBI blocks from the whole rootfs
region. Programming a shorter image does not clear untouched tail blocks.
Erase All also removes boot loaders and writable filesystems; back up first.

Replace `spinand` with the required media. Addresses and lengths are in bytes;
hexadecimal values use `0x`.

| Media | Write start alignment | Read start alignment | Erase |
| --- | --- | --- | --- |
| `nand`, `spinand` | Flash block | Flash block | Whole blocks |
| `spinor` | 4 KiB | 64 KiB | 64 KiB units |
| `sd`, `emmc` | 512 bytes | 512 bytes | Not supported |

## Download To RAM

Load the board's main U-Boot at its linked address and execute it:

```bash
python nuwriter.py -w ddr 0x00e00000 sample/u-boot-spinand.bin -o execute
```

Omit `-o execute` to download without starting the image. For Linux, download
the kernel and DTB together; the following uses an existing SPI NAND rootfs:

```bash
python nuwriter.py -w ddr 0x8000 sample/zImage -o execute --dtb sample/nuc980-iot-128m-bmc.dtb --dtb-addr 0x1400000 --bootargs "noinitrd ubi.mtd=3 root=ubi0:rootfs rootfstype=ubifs rw console=ttyS0,115200n8 init=/sbin/init mem=128M"
```

Use the matching kernel, DTB, and installed rootfs. The sample `uImage` has a
U-Boot header and must not be executed directly as a raw kernel; use `zImage`
for this RAM workflow. `--bootargs` changes only the downloaded DTB copy.
RAM downloads do not program
flash, but the running OS may write it. Downloads and programming show progress
in 10% steps; 100% does not confirm that the downloaded software has booted.

## Make And Program A Pack

Use the [SPI NAND](sample/config_spinand.json) or [SD1](sample/config_sd1.json)
template. CLI image paths resolve from the current working directory, so run
these configurations from `sample`; the GUI handles this directory automatically.

```bash
cd sample
```

```bash
python ../nuwriter.py -p config_spinand.json --check
```

```bash
python ../nuwriter.py -p config_sd1.json --check
```

Offline checks do not reset, access a board, or write outputs. To generate
packs, omit `--check`. These commands overwrite the named sample pack files:

```bash
python ../nuwriter.py -p config_spinand.json
```

```bash
python ../nuwriter.py -p config_sd1.json
```

```bash
cd ..
```

JSON `mode` accepts `nand`, `spinand`, `spinor`, `sd`, or `emmc`.

| Image `type` | Use |
| --- | --- |
| `data`, `linux` | Store the file unchanged |
| `loader` | Boot loader; requires DDR settings and the correct entry address |
| `env` | U-Boot environment text |
| `partition` | SD/eMMC partition settings |

SPI loaders also require flash command parameters; SPI NAND needs page and
spare sizes. Use values for your flash chip, not another media's settings.

After initialization, program the generated pack:

```bash
python nuwriter.py -w spinand sample/nuwriter-pack-spinand.bin --ddr NUC980DK71YC.ini
```

For a single board, erase separately if required and add `-o verify` to compare
packed image data after programming:

```bash
python nuwriter.py -w spinand sample/nuwriter-pack-spinand.bin --ddr NUC980DK71YC.ini -o verify
```

```bash
python nuwriter.py -w sd sample/nuwriter-pack-sd.bin --ddr NUC980DK71YC.ini -o verify
```

Single-board Pack programming does not add Erase All. Pack Verify compares
image data, excluding loader header/DDR bytes and SD partition instructions.
Loader must be first at offset 0 (flash) or 0x400 (SD/eMMC). SPI NOR Pack Verify
requires 64 KiB-aligned offsets. This is not verification of unused/OOB regions.

## Mass Production

Reset every target into USB Boot mode, then initialize all connected boards:

```bash
python nuwriter.py -m -a NUC980DK71YC.ini
```

Run the complete sequential workflow:

```bash
python nuwriter.py -m -w spinand sample/nuwriter-pack-spinand.bin --ddr NUC980DK71YC.ini -o verify
```

**This performs Erase All before Burn/Verify on NAND/SPI NAND**, deleting existing
boot, environment and filesystem data while preserving marked bad blocks.
SPI NOR and SD/eMMC skip the separate erase. Each board reports its stages and
result; failures do not retry and do not stop later boards. Any failure returns
a nonzero exit status. Without `-o verify`, existing `-m` programming remains
sequential and does not add Erase All. This implementation is not parallel;
the GUI displays individual stages and results.

## Checks And Troubleshooting

Append `--check` to validate inputs without reset, board access, or output
writes. It does not check the connected flash's capacity or geometry.

```bash
python nuwriter.py -a NUC980DK71YC.ini --check
```

Use `--device` with a path from `--list` when multiple boards are connected.
For USB diagnostics, append `--trace-usb`; records include device paths and may
contain image bytes. The GUI USB Trace window records only while shown.
`--timeout` and `--operation-timeout` are in milliseconds. If erase times out,
do not proceed to programming; wait for the board to stop and reinitialize.

If macOS cannot locate Homebrew libusb, set its search path in the current
terminal before starting the CLI/GUI:

```bash
export DYLD_FALLBACK_LIBRARY_PATH="$(brew --prefix libusb)/lib:${DYLD_FALLBACK_LIBRARY_PATH:-$HOME/lib:/usr/local/lib:/usr/lib}"
```

## Tests

GitHub Actions runs backend and offscreen GUI tests with Python 3.14 on
Windows, Ubuntu, and macOS for pushes, pull requests, and manual runs.
Commit the tests and sample fixtures with the workflow. Tests use simulated
devices or real sample-image offline checks, not connected boards. Install
the GUI requirements before running both suites.

```bash
python -m unittest discover -s . -p test_nuwriter.py -v
```

```bash
python -m unittest discover -s gui -p test_gui.py -v
```

Windows batch integration tests require the sibling `numaker-iot-nuc980g2`
directory and are skipped when it is absent from a standalone checkout.
Native desktop rendering and real-board operations still need manual testing.

## License

Project-owned Python source code and documentation are licensed under the
[Apache License, Version 2.0](LICENSE).

Bundled libusb uses LGPL-2.1-or-later; see [driver/README.md](driver/README.md).
Third-party software, the WinUSB installer, XUSB firmware, and DDR configuration
files retain their original licenses and copyrights; they are not relicensed.