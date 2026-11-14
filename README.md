# NUC980 PyNuWriter

[English](README.md) | [简体中文](README.zh-CN.md) | [繁體中文](README.zh-TW.md)

USB programming and RAM download tool for NUC980. For graphical operation, see the [GUI guide](gui/README.md).

## Standalone Downloads

Open the [download page](https://github.com/wosayttn/NUC980_PyNuWriter/actions), select a completed item, then download a CLI or GUI package from **Artifacts** (GitHub sign-in required).
Choose `nuwriter-cli-<platform>` or `nuwriter-gui-<platform>`:

| System | Platform |
| --- | --- |
| Windows x64 | `windows-x64` |
| Linux x64 | `linux-x64` |
| macOS Intel | `macos-x64` |
| macOS Apple Silicon | `macos-arm64` |

Extract both archive layers. Keep the entire directory, including `_internal` and `backend`.
On macOS, keep `nuwriter-gui.app` and `backend` together. Python is not required for these packages.
Windows needs the [NUC980 WinUSB driver](driver/README.md); Linux/macOS need libusb as described below.

Open `nuwriter-gui.exe`, `nuwriter-gui`, or `nuwriter-gui.app` for the GUI.
For CLI use, replace `python nuwriter.py` in the examples with `.\nuwriter.exe` on Windows or `./nuwriter` on Linux/macOS.
Linux packages target Ubuntu 22.04; macOS packages target macOS 15. Older systems are not verified.
Packages are not developer-signed or notarized. Check the source and SHA-256 before opening them.

## Install From Source

Download the [source](https://github.com/wosayttn/NUC980_PyNuWriter) with **Code > Download ZIP** and extract it.
Run the following commands from the directory containing `nuwriter.py`. Python 3.14 is recommended.

### Windows

Install 64-bit [Python](https://www.python.org/downloads/windows/) and the [NUC980 WinUSB driver](driver/README.md).
Install WinUSB on the board's USB Device interface, not its debug UART or reset adapter.
Install the CH341 driver only if using that adapter. In PowerShell:

```bash
python -m venv .venv
```

```bash
.\.venv\Scripts\Activate.ps1
```

### Linux

Debian/Ubuntu packages, including the GUI prerequisites:

```bash
sudo apt-get update
```

```bash
sudo apt-get install -y python3 python3-venv python3-pip libusb-1.0-0 libegl1 libgl1 libxkbcommon0 libxcb-cursor0 libdbus-1-3 fonts-noto-core
```

For local desktop USB access, create `/etc/udev/rules.d/70-nuvoton-nuwriter.rules` containing:

```udev
SUBSYSTEM=="usb", ATTR{idVendor}=="0416", ATTR{idProduct}=="5963", TAG+="uaccess"
```

```bash
sudo udevadm control --reload-rules
```

Reconnect the board. Remote/headless users need suitable USB group permissions.
Serial access may also require membership in `dialout`.

```bash
python3 -m venv .venv
```

```bash
source .venv/bin/activate
```

### macOS

Install [Homebrew](https://brew.sh/), then Python and libusb of the same architecture:

```bash
brew install python@3.14 libusb
```

```bash
"$(brew --prefix python@3.14)/bin/python3.14" -m venv .venv
```

```bash
source .venv/bin/activate
```

### Python Packages

In the activated environment on any OS, install the CLI dependencies:

```bash
python -m pip install -r requirements.txt
```

For the GUI, also install its dependencies and start it:

```bash
python -m pip install -r gui/requirements.txt
```

```bash
python gui/app.py
```

## Connect

Put the board in USB Boot mode and connect its USB Device port to the PC.
The examples use NUC980DK71YC; select the DDR setting in `sys_cfg` that matches your board.

```bash
python nuwriter.py --list
```

```bash
python nuwriter.py -a NUC980DK71YC.ini
```

Repeat initialization after resetting or power-cycling. **Initialization may reset the board through a CH341 adapter.** Without that adapter, reset manually into USB Boot mode.
For multiple boards, add `--device BUS:PORT` using a path shown by `--list`.
Before a download, write, erase or pack operation, append `--check` to validate inputs without board access or output writes.

## Program, Read And Erase

Examples use the [sample files](sample/README.md). Confirm offsets and flash settings for your board.
Standalone packages omit samples; copy `sample` from the source ZIP beside the CLI executable.
Program main U-Boot and verify:

```bash
python nuwriter.py -w spinand 0x100000 sample/u-boot-spinand.bin -o verify
```

Read a range or the whole device. Existing output files are overwritten:

```bash
python nuwriter.py -r spinand 0x100000 0x20000 readback.bin
```

```bash
python nuwriter.py -r spinand all backup.bin
```

**Erase All deletes boot loaders, settings and filesystems. Back up first.** NAND/SPI NAND preserves marked bad blocks.

```bash
python nuwriter.py -e spinand all
```

Replace `spinand` with the required media. Addresses and lengths are bytes; use `0x` for hexadecimal.

| Media | Write start | Read start | Erase unit |
| --- | --- | --- | --- |
| `nand`, `spinand` | Flash block | Flash block | Flash block |
| `spinor` | 4 KiB | 64 KiB | 64 KiB |
| `sd`, `emmc` | 512 bytes | 512 bytes | Not supported |

SPI NOR whole-device reads need `--flash-size` with the capacity in bytes.
Reads and verification do not cover OOB or every physical bad block.
Before replacing a UBI image, erase the old rootfs region, including any tail beyond the new image.

## Download To RAM

Download and start main U-Boot; omit `-o execute` to download only:

```bash
python nuwriter.py -w ddr 0x00e00000 sample/u-boot-spinand.bin -o execute
```

Linux example using a rootfs already installed on SPI NAND:

```bash
python nuwriter.py -w ddr 0x8000 sample/zImage -o execute --dtb sample/nuc980-iot-128m-bmc.dtb --dtb-addr 0x1400000 --bootargs "noinitrd ubi.mtd=3 root=ubi0:rootfs rootfstype=ubifs rw console=ttyS0,115200n8 init=/sbin/init mem=128M"
```

Use matching kernel, DTB and rootfs files. For this command, use raw `zImage`, not U-Boot-wrapped `uImage`.
RAM downloading does not program flash, but software started on the board may write it.

## Create And Program A Pack

The sample configurations use relative paths. For standalone CLI use, also copy the source ZIP's `sys_cfg` beside the executable.
Replace `python ../nuwriter.py` below with `..\nuwriter.exe` on Windows or `../nuwriter` on Linux/macOS. Run from `sample`:

```bash
cd sample
```

```bash
python ../nuwriter.py -p config_spinand.json --check
```

```bash
python ../nuwriter.py -p config_spinand.json
```

Use `config_sd1.json` instead for SD1. Its CLI media name is `sd`.
Generation overwrites the configuration's output file. Then return to the tool directory:

```bash
cd ..
```

After initialization, program and verify the pack:

```bash
python nuwriter.py -w spinand sample/nuwriter-pack-spinand.bin --ddr NUC980DK71YC.ini -o verify
```

```bash
python nuwriter.py -w sd sample/nuwriter-pack-sd.bin --ddr NUC980DK71YC.ini -o verify
```

Single-board Pack programming does not automatically erase the whole device.
Loader must be first at `0x0` for flash or `0x400` for SD/eMMC; SPI NOR Pack Verify needs 64 KiB-aligned image offsets.
Pack verification excludes loader headers/DDR data, SD partition setup, OOB and unused areas.

## Mass Production

Put every board in USB Boot mode, connect them, then initialize and program:

```bash
python nuwriter.py -m -a NUC980DK71YC.ini
```

```bash
python nuwriter.py -m -w spinand sample/nuwriter-pack-spinand.bin --ddr NUC980DK71YC.ini -o verify
```

**This erases all good blocks before programming NAND/SPI NAND.** SPI NOR and SD/eMMC skip the separate whole-device erase.
Boards run sequentially; failures are not retried and later boards continue. Any failure returns a nonzero exit status.
Omitting `-o verify` also disables the automatic Erase All step.

## Troubleshooting

- Confirm the DDR setting, USB Boot mode, USB Device port and driver if initialization fails.
- After a timeout, wait for the operation to stop, check or reset the board, then reconnect.
- Add `--trace-usb` to capture USB diagnostics. The data may contain image contents.
- Use `--timeout` for USB/reconnect waits and `--operation-timeout` for operations; both are milliseconds.
- If macOS cannot find libusb, set its path before starting:

```bash
export DYLD_FALLBACK_LIBRARY_PATH="$(brew --prefix libusb)/lib:${DYLD_FALLBACK_LIBRARY_PATH:-$HOME/lib:/usr/local/lib:/usr/lib}"
```

## License

Project-owned code: [Apache-2.0](LICENSE). Third-party licenses and replacement rights: [license notices](licenses/README.md).
Keep `licenses/` and `sources/` with standalone packages when redistributing them.