# NUC980 / NUC970 / NUC990 PyNuWriter

[English](README.md) | [简体中文](README.zh-CN.md) | [繁體中文](README.zh-TW.md)

USB programming and RAM download tool for NUC980, NUC970 / N9H30 and NUC990 (including NUC970 MTP/OTP key programming and AES encryption). NUC990 currently uses the NUC980 protocol. For graphical operation, see the [GUI guide](gui/README.md).

## Standalone Downloads

Open the [download page](https://github.com/wosayttn/NUC980_PyNuWriter/releases/latest) and download a CLI or GUI package from **Assets**. GitHub sign-in is not required.
Choose `nuwriter-cli-<platform>` or `nuwriter-gui-<platform>`:

| System | Platform |
| --- | --- |
| Windows x64 | `windows-x64` |
| Linux x64 | `linux-x64` |
| macOS Intel | `macos-x64` |
| macOS Apple Silicon | `macos-arm64` |

Extract the package and keep the entire directory. On Windows/Linux, do not remove `_internal` or `backend`.
**Source code (zip/tar.gz)** is source code, not a standalone CLI/GUI package.
On macOS, `nuwriter-gui.app` includes its CLI backend. Python is not required for these packages.
Windows needs a [programming USB driver](driver/README.md); Linux/macOS need libusb as described below.

Open `nuwriter-gui.exe`, `nuwriter-gui`, or `nuwriter-gui.app` for the GUI.
For CLI use, replace `python nuwriter.py` in the examples with `.\nuwriter.exe` on Windows or `./nuwriter` on Linux/macOS.
Linux packages target Ubuntu 22.04; macOS packages target macOS 15. Older systems are not verified.
Packages are not developer-signed or notarized. Check the source and SHA-256 before opening them.

## Install From Source

Download the [source](https://github.com/wosayttn/NUC980_PyNuWriter) with **Code > Download ZIP** and extract it.
Run the following commands from the directory containing `nuwriter.py`. Python 3.14 is recommended.

### Windows

Install 64-bit [Python](https://www.python.org/downloads/windows/) and configure a [programming USB driver](driver/README.md).
Bind a libusb-compatible driver, such as WinUSB, to the USB Device interface (`0416:5963`), not the debug UART or reset adapter.
The bundled `WinUSB4NuVCOM.exe` installs the onboard UART/VCOM driver, not the programming driver.
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
**Every attach, write, read, erase, or pack command requires an explicit `--chip nuc980`, `--chip nuc970`, or `--chip nuc990` flag** (no auto-detection).
NUC980 DDR settings live in `sys_cfg/nuc980/` (example: `NUC980DK71YC.ini`); NUC970 / N9H30 DDR settings live in `sys_cfg/nuc970/` (example: `NUC972DF62Y.ini`).
NUC990 uses `sys_cfg/nuc990/` and `xusb/nuc990/`. The current DDR setting is `COMING_SOON.ini`; confirm its settings and firmware for your board before hardware operations.

```bash
python nuwriter.py --list
```

```bash
python nuwriter.py --chip nuc980 -a NUC980DK71YC.ini
```

```bash
python nuwriter.py --chip nuc970 -a NUC972DF62Y.ini
```

Validate NUC990 initialization without board access:

```bash
python nuwriter.py --chip nuc990 -a COMING_SOON.ini --check
```

Repeat initialization after resetting or power-cycling. **Initialization may reset the board through a CH341 adapter.** Without that adapter, reset manually into USB Boot mode.
For multiple boards, add `--device BUS:PORT` using a path shown by `--list`.
Before a download, write, erase or pack operation, append `--check` to validate inputs without board access or output writes.

## Program, Read And Erase

Examples use the [sample files](sample/README.md). Confirm offsets and flash settings for your board.
Standalone packages omit samples; copy `sample` from the source ZIP beside the CLI executable.
Program main U-Boot and verify (NUC980 SPI NAND example):

```bash
python nuwriter.py --chip nuc980 -w spinand 0x100000 sample/u-boot-spinand.bin -o verify
```

Read a range or the whole device. Existing output files are overwritten:

```bash
python nuwriter.py --chip nuc980 -r spinand 0x100000 0x20000 readback.bin
```

```bash
python nuwriter.py --chip nuc980 -r spinand all backup.bin
```

**Erase All deletes boot loaders, settings and filesystems. Back up first.** NAND/SPI NAND preserves marked bad blocks.

```bash
python nuwriter.py --chip nuc980 -e spinand all
```

Replace media and `--chip` as needed. NUC980 and NUC990 support `ddr`, `nand`, `spinand`, `spinor`, `sd`/`emmc`; NUC970 supports `ddr`, `nand`, `spinor`, `sd`/`emmc`, and `mtp` (no `spinand`). Addresses and lengths are bytes; use `0x` for hexadecimal.

| Media | Write start | Read start | Erase unit |
| --- | --- | --- | --- |
| `nand`, `spinand` (SPI NAND: NUC980/NUC990) | Flash block | Flash block | Flash block |
| `spinor` | 4 KiB | 64 KiB | 64 KiB |
| `sd`, `emmc` | 512 bytes | 512 bytes | Not supported |

SPI NOR whole-device reads need `--flash-size` with the capacity in bytes.
Reads and verification do not cover OOB or every physical bad block.
Before replacing a UBI image, erase the old rootfs region, including any tail beyond the new image.

### NUC970 AES Encryption And MTP / OTP

`--chip nuc970` additionally supports AES image encryption (`--aes-key key.dat`) and MTP/OTP key programming (`-w mtp`):

```bash
python nuwriter.py --chip nuc970 -w spinor 0x0 loader.bin -t loader --exec-addr 0x200 --ddr NUC972DF62Y.ini --aes-key key_cfg/nuc970/key.dat -o verify
```

```bash
python nuwriter.py --chip nuc970 -w mtp key_cfg/nuc970/key.dat --mtp-option aes --mtp-mode spinor
```

**Warning: adding `--mtp-lock` permanently locks the chip MTP key and cannot be undone.**

## Download To RAM

Download and start main U-Boot; omit `-o execute` to download only:

```bash
python nuwriter.py --chip nuc980 -w ddr 0x00e00000 sample/u-boot-spinand.bin -o execute
```

Linux example using a rootfs already installed on SPI NAND:

```bash
python nuwriter.py --chip nuc980 -w ddr 0x8000 sample/zImage -o execute --dtb sample/nuc980-iot-128m-bmc.dtb --dtb-addr 0x1400000 --bootargs "noinitrd ubi.mtd=3 root=ubi0:rootfs rootfstype=ubifs rw console=ttyS0,115200n8 init=/sbin/init mem=128M"
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
python ../nuwriter.py --chip nuc980 -p config_spinand.json --check
```

```bash
python ../nuwriter.py --chip nuc980 -p config_spinand.json
```

Use `config_sd1.json` instead for SD1. Its CLI media name is `sd`.
Generation overwrites the configuration's output file. Then return to the tool directory:

```bash
cd ..
```

After initialization, program and verify the pack:

```bash
python nuwriter.py --chip nuc980 -w spinand sample/nuwriter-pack-spinand.bin --ddr NUC980DK71YC.ini -o verify
```

```bash
python nuwriter.py --chip nuc980 -w sd sample/nuwriter-pack-sd.bin --ddr NUC980DK71YC.ini -o verify
```

Single-board Pack programming does not automatically erase the whole device.
Loader must be first at `0x0` for flash or `0x400` for SD/eMMC; SPI NOR Pack Verify needs 64 KiB-aligned image offsets.
NUC970 packs use a 16-byte boot header and support `aes_key` on data/loader images as well as `type: "mtp"` items.
Pack verification excludes loader headers/DDR data, SD partition setup, MTP entries, OOB and unused areas.

## Mass Production

Put every board in USB Boot mode, connect them, then initialize and program:

```bash
python nuwriter.py --chip nuc980 -m -a NUC980DK71YC.ini
```

```bash
python nuwriter.py --chip nuc980 -m -w spinand sample/nuwriter-pack-spinand.bin --ddr NUC980DK71YC.ini -o verify
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

Project-owned code: [Apache-2.0](LICENSE). Third-party licenses and replacement rights: [license notices](.github/licenses/README.md).
Keep `licenses/` and `sources/` with standalone packages when redistributing them.