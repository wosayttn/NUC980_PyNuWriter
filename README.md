# NUC980 PyNuWriter

Download to RAM, program/read/erase NAND and SPI flash, and program/read SD/eMMC.

## Install

Requirements: Python 3.9+, a USB Device driver, and libusb-1.0.
Run the following commands from this directory in PowerShell:

```bash
python -m venv .venv
```

```bash
.\.venv\Scripts\Activate.ps1
```

```bash
python -m pip install -r requirements.txt
```

```bash
python nuwriter.py --help
```

On Debian/Ubuntu, install `python3-venv` and `libusb-1.0-0`, create/activate
a virtual environment, then install the same requirements. Set USB access
permissions for your user.

On Windows, the bundled `driver/libusb-1.0.dll` requires 64-bit Python.
Before USB access, the tool automatically adds its absolute `driver` directory
to the current process `PATH`. No permanent environment changes are made.
See [driver/README.md](driver/README.md).

Keep `sys_cfg` and `xusb` beside the script. Examples use NUC980DK71YC;
select the DDR settings and image addresses for your board. Relative image
and output paths resolve from the working directory.

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
python nuwriter.py -w spinand 0x100000 ..\numaker-iot-nuc980g2\u-boot.bin -o verify
```

Read `0x20000` bytes back to a file:

```bash
python nuwriter.py -r spinand 0x100000 0x20000 readback.bin
```

Reading creates or overwrites the output file. Use `-r spinand all backup.bin`
for the whole device. For SPI NOR read-all, also supply its byte capacity with
`--flash-size`, for example `-r spinor all backup.bin --flash-size 0x800000`.

**Erase All deletes flash contents. Back up required data first.**
NAND/SPI NAND erase skips marked bad blocks and retains their markers.

```bash
python nuwriter.py -e spinand all
```

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
python nuwriter.py -w ddr 0x00e00000 ..\numaker-iot-nuc980g2\u-boot.bin -o execute
```

Omit `-o execute` to download without starting the image. For Linux, download
the kernel and DTB together; the following uses an existing SPI NAND rootfs:

```bash
python nuwriter.py -w ddr 0x8000 ..\numaker-iot-nuc980g2\zImage -o execute --dtb ..\numaker-iot-nuc980g2\nuc980-iot-128m-bmc.dtb --dtb-addr 0x1400000 --bootargs "noinitrd ubi.mtd=rofs root=ubi0:rootfs rootfstype=ubifs rw console=ttyS0,115200n8 init=/sbin/init mem=128M lpj=744448"
```

`--bootargs` changes only the downloaded DTB copy. RAM downloads do not program
flash, but the running OS may write it. Downloads and programming show progress
in 10% steps; 100% does not confirm that the downloaded software has booted.

## Make And Program A Pack

Create `pack.json` in this directory. This example contains only main U-Boot,
not a complete bootable system:

```json
{
    "mode": "spinand",
    "output": "pack.bin",
    "image": [
        {"file": "../numaker-iot-nuc980g2/u-boot.bin", "offset": "0x100000", "type": "data"}
    ]
}
```

Check the inputs, then generate the pack without a board:

```bash
python nuwriter.py -p pack.json --check
```

```bash
python nuwriter.py -p pack.json
```

For a complete SPI NAND layout, see the board's
[config.json](../numaker-iot-nuc980g2/config.json). Check its image and DDR
paths before use. Run that configuration from its own directory so relative
paths resolve correctly.

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
python nuwriter.py -w spinand pack.bin --ddr NUC980DK71YC.ini
```

Erase separately if required. Pack programming does not support `-o verify`.

## Checks And Troubleshooting

Append `--check` to validate inputs without reset, board access, or output
writes. It does not check the connected flash's capacity or geometry.

```bash
python nuwriter.py -a NUC980DK71YC.ini --check
```

Use `--device` with a path from `--list` when multiple boards are connected.
For USB errors, append `--trace-usb 2> usb.log`; logs may contain image data.
`--timeout` and `--operation-timeout` are in milliseconds. If erase times out,
do not proceed to programming; wait for the board to stop and reinitialize.

## Tests

GitHub Actions runs backend and offscreen GUI tests with Python 3.14 on
Windows, Ubuntu, and macOS for pushes, pull requests, and manual runs.
Commit both test files together with the workflow. These tests use simulated
devices or offline checks, not connected boards.

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