# NUC980 NuWriter Python Tool
Python/PyUSB host tool for accessing SDRAM, NAND, SPI NOR, SPI NAND, and SD/eMMC
on NUC980 processors. This directory contains the Python host files and bundled
device resources. The implementation follows the Windows NuWriter host and
firmware protocol, with a MA35-style command-line and Python API surface.

## Installation

`nuwriter.py` uses Python/PyUSB directly. Its protocol reference is
`NUC980_NuWriter_Win/NuWriter/NuWriter`: `NucWinUsb.cpp` for USB transfers,
`NuWriterDlg.cpp` for DDR/XUSB and INFO, `xusb.cpp` for media operations,
`Serial.h` for packet layouts, and `PACKDlg.cpp` for pack generation.
`NuWriterFW_BSP` supplies the device-side protocol reference. These sources
are not built, imported, or required at runtime. The bundled DDR settings and
Windows XUSB images are sufficient alongside Python/PyUSB and a USB backend.

```text
NUC980_NuWriter/
	nuwriter.py
	pre-attach-hook.py
	ch341_reset_uart.py
	requirements.txt
	test_nuwriter.py
	README.md
	COPYING
	sys_cfg/*.ini
	xusb/
		xusb.bin
		xusb16.bin
		xusb64.bin
		xusb128.bin
```

Requirements: Python 3.9 or newer, PyUSB, pyserial for the CH341 reset hook,
pyfdt for DTB bootargs overrides,
and a libusb-1.0 runtime for USB access. Install `requirements.txt` after updating.
On Windows, install the appropriate USB Device driver and make the libusb
runtime available; PyUSB alone does not supply the native USB backend.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python nuwriter.py --help
python nuwriter.py -a NUC980DK71YC.ini --check
```

On Debian/Ubuntu, run these commands from this directory:

```sh
sudo apt-get install python3 python3-venv libusb-1.0-0
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python nuwriter.py -a NUC980DK71YC.ini --check
python nuwriter.py --list
python nuwriter.py --help
```

Replace example image paths with actual inputs before running. Relative image,
read-output, and pack-output paths resolve from the working directory.
DDR files resolve from `sys_cfg` beside the script, and XUSB images from
the sibling `xusb` directory. Use `--resource-dir /path/to/NUC980_NuWriter` to
select a different resource root containing both `sys_cfg` and `xusb`.
NUC980 XUSB binaries are required; MA35 binaries are not interchangeable.

USB operations require appropriate Linux USB/udev permissions. Listing a device
does not prove that the current user can claim its interface.

### Implemented Operations

| Mode | Operations |
| --- | --- |
| SDRAM | Download, download-and-run, optional DTB download |
| NAND, SPINOR, SPINAND | Program, program_verify, read, erase |
| SD | Program, program_verify, read, FAT32 format |
| Flash/SD pack | Offline generation and programming of the existing NUC980 pack format |

Loader DDR data, 32-byte pack boot headers, environment CRC32, storage information
layout, transfer acknowledgements, and media-specific read units follow the
Windows protocol. Pack generation integrates the standalone
`python/files/nuwriter_pack.py` format: its header length is the serialized
pack size rounded up to 64 KiB. Only this field is rounded; no trailing file
padding is appended. Child payloads retain their exact encoded lengths. Single
loader requests use image number 1 and preserve configured execution/offset
fields; SD loaders retain the Windows 32-byte `0xff` transfer padding.

### MA35-Style Command Interface

The Python port also accepts MA35-style operation flags while keeping the
NUC980 Windows protocol. A compatible external INI can still be supplied as
CONFIG, but no example INI is required or bundled. Prefer direct operations
and JSON pack input. Running without arguments prints help, as in MA35.

```sh
python nuwriter.py -a NUC980DF61YC.ini
python nuwriter.py -w spinor 0x200000 image.bin -o verify
python nuwriter.py -a NUC980DF61YC.ini -w spinor 0x200000 image.bin -o verify
python nuwriter.py -r spinor 0x200000 0x10000 out.bin
python nuwriter.py -e spinor 0x200000 0x10000
python nuwriter.py -e spinor all
python nuwriter.py -w ddr 0x8000 image.bin -o execute
python nuwriter.py -m -a NUC980DF61YC.ini -w spinor 0x200000 image.bin
python nuwriter.py -w nand pack.bin
python nuwriter.py -p pack.json --output pack.bin
python nuwriter.py -v
```

`-a/--attach` takes DDR settings through positional CONFIG or `--ddr`. A bare
bundled filename is resolved in `sys_cfg`; an existing local DDR file
is resolved from the current working directory. Without `-a`, compatible
hardware commands query the already-running NUC980 XUSB firmware and do not
download DDR/XUSB again. Initialize with `-a` first after powering on/resetting
the target. `--ddr` alone supplies loader settings, not initialization.

### Pre-Attach Hook

Before a real CLI/public API attach, the tool checks for `pre-attach-hook.py`
beside `nuwriter.py` and runs it with the same Python interpreter. This happens
after offline validation and before USB discovery/opening, once per invocation
even with `-m`. A missing hook is skipped; a nonzero hook result stops attach.
`--check`, `--list`, offline packing, and operations using an existing XUSB
without initialization do not execute the hook. Low-level `Nuc980Writer.attach`
callers manage their own reset/discovery sequence.

The supplied hook runs `ch341_reset_uart.py --duration 0.2`, using its default
CH341 port auto-detection, RTS pin and active-low pulse, then waits 1 second
for USB re-enumeration after success. Both scripts resolve paths from their
own directory. This is a real hardware reset: connect the CH341 reset signal
appropriately, prepare USB Boot mode, and close other programs using that COM
port. The DEBUG VCOM port is not automatically used as the reset port.

Edit `pre-attach-hook.py` to customize the reset arguments, or rename/remove
it to disable the hook. The flash batch no longer issues a separate CH341
reset, avoiding duplicate pulses. Reinstall `requirements.txt` to include
pyserial when updating an existing environment.

### Kernel And DTB Download To DRAM

`--dtb FILE --dtb-addr ADDRESS` downloads a DTB before the DDR/SRAM image.
With `-o execute`, the Windows firmware passes the DTB address when executing
the image. Both arguments are required together and are DDR/SRAM-only.
Image/DTB transfer ranges must not overlap. The optional `--bootargs TEXT`
uses pyfdt to override `/chosen/bootargs` in the in-memory download copy;
the original DTB file is never rewritten. API callers can use `dtb`,
`dtb_addr`, and `bootargs` keyword settings with `do_img_program`.

```powershell
python nuwriter.py -a NUC980DK71YC.ini -w ddr 0x8000 ..\numaker-iot-nuc980g2\zImage -o execute --dtb ..\numaker-iot-nuc980g2\nuc980-iot-128m-bmc.dtb --dtb-addr 0x1400000 --bootargs "noinitrd ubi.mtd=rofs root=ubi0:rootfs rootfstype=ubifs rw console=ttyS0,115200n8 init=/sbin/init mem=128M lpj=744448" --check
```

Remove `--check` only when ready to download/execute on the board. The board's
`dram_download_openbmc.bat` wraps this workflow and also supports `--check`.
This loads only the kernel/DTB into DRAM: an existing SPI NAND `rofs` UBI
partition containing volume `rootfs` is still required. It is not a full-RAM
OpenBMC image and cannot boot userspace from erased SPI NAND. NuWriter does
not erase/program flash in this workflow; the booted OS may write its rootfs.

Media names are case-insensitive: NAND, SPINAND, SPINOR, SD/EMMC, DDR/SRAM/SDRAM.
DDR/SRAM support writes only; SD/eMMC does not support erase. `-m/--massproduct`
programs targets sequentially and cannot be combined with `--device`, read,
or offline `-p` operations. `-o` and `-t` each take one value.

Compatible START/LENGTH arguments are **bytes**. Read starts must align to a
NAND/SPI NAND block, 64 KiB for SPI NOR, or 512 bytes for SD. Read lengths may
be arbitrary nonzero byte lengths, including a single byte. Erase starts and
lengths must align to complete erase blocks. Ranges are never rounded outward.
Write starts must align to a NAND/SPI NAND block, 4 KiB for SPI NOR, or 512
bytes for SD. Device-dependent alignment/capacity checks happen after querying
storage information, before storage commands. The wire format is limited to
32-bit lengths/addresses; larger requests are rejected.

CLI/API read addresses stay in bytes, but both NAND and SPI NAND read headers
carry block indexes. The host converts byte starts using the reported block
size. Normal SPI NAND reads may skip marked bad blocks or ECC-failing blocks;
a full returned-data blank check does not certify OOB, bad-block markers, or
every physical page. A successful erase progress sequence is not itself a
readback blank check.

```sh
python nuwriter.py -r nand all out.bin
python nuwriter.py -r spinor all out.bin --flash-size 0x800000
python nuwriter.py -w nand 0 loader.bin -t loader --ddr NUC980DK71YC.ini --exec-addr 0x200
python nuwriter.py -a NUC980DK71YC.ini -w spinor 0x200000 image.bin -o verify --check
```

Read-all uses reported NAND/SPI NAND/SD capacity. SPI NOR information lacks a
capacity field, so read-all requires an explicit, correct `--flash-size` in
bytes. `--check` never queries hardware and therefore cannot confirm that
capacity, NAND geometry, or whether XUSB is running.

Flash writes default to raw data. `-t data/linux`, `-t env`, and
`-t loader/uboot` select NUC980 image processing. Loader images must be raw
NUC980 loader binaries, require DDR settings and `--exec-addr`, and start at
0 for flash or 0x400 for SD. `--exec-addr` also sets the metadata execution
address for other single-image flash writes; it does not execute that image.
`-o execute` is DDR/SRAM-only; `-o verify` is
single-image flash-only. Pack verification remains unsupported.

OTP, REG, USBD, MSC (`-s`), conversion (`-c`), TFA/TEE/DDR image types, and
raw/withbad/scrub/unpack options are explicitly rejected. NAND erase retains
the Windows default of preserving marked bad blocks; it does not emulate
MA35 bad-block options. MA35 boot binaries and pack files are not compatible.

### MA35-Style Python API

Import `nuwriter` from this directory. Public IDs match the supported MA35
subset, not the Windows wire media numbers:

| Media | API constant/value | Windows wire type |
| --- | --- | --- |
| DDR/SRAM | `DEV_DDR_SRAM=0` | 0 |
| NAND | `DEV_NAND=1` | 3 |
| eMMC | `DEV_EMMC=2` | 5 |
| SPI NOR | `DEV_SPINOR=3` | 7 |
| SPI NAND | `DEV_SPINAND=4` | 9 |
| SD | `DEV_SD=7` | 5 |

`get_media`, `get_option`, `get_type`, and `switch_mp_mode` are available.
Supported options are `OPT_NONE=0`, `OPT_EXECUTE=2`, and `OPT_VERIFY=3`.
Unsupported names return the corresponding `*_UNKNOWN` value. `get_type`
supports the shared data/U-Boot/Linux IDs; a named `image_type="env"` setting
selects the NUC980-specific environment format without confusing MA35 TFA=1.

| API | Operation |
| --- | --- |
| `do_attach(ddr_file, option=OPT_NONE, **settings)` | Initialize DDR/XUSB and query INFO |
| `do_img_program(media, start, file, option=OPT_NONE, **settings)` | Write one image |
| `do_img_read(media, start, output, length=1, option=OPT_NONE, **settings)` | Read bytes; length 0 means all from start 0 |
| `do_img_erase(media, start, length=0, option=OPT_NONE, **settings)` | Erase range; length 0 means all from start 0 |
| `do_pack_program(media, file, option=OPT_NONE, **settings)` | Program a NUC980 pack |
| `do_pack(config_file, **settings)` | Generate a NUC980 pack offline |

`create_pack_file(images, output_path, media=DEV_SPINAND, ddr_ini=None,
storage=None, resource_dir=None)` also generates packs directly from an image
list. It returns the output `Path`, raises on invalid input/I/O failure, and
uses the same builder as `-p`/`do_pack`. String media names or public `DEV_*`
constants are accepted. No external pack script, USB or reset is invoked.

These functions delegate to the same CLI/configuration/Windows backend and
the `do_*` APIs return its status: 0 on success, nonzero on operational failure. Invalid API
media, unsupported options, unknown settings, and CLI argument errors raise
`NuWriterError` rather than terminating the calling process. Configuration,
input-file and USB failures return nonzero status. Shared keyword settings include
`check`, `ddr`, `initialize`, `device`, `resource_dir`, `timeout`,
`operation_timeout`, `massproduct`, `image_type`, `exec_addr`, and `trace_usb`.
DRAM writes additionally accept `dtb`, `dtb_addr`, and `bootargs`. Pack creation
also accepts `media` and `output`; SPI NOR read-all accepts `flash_size`.
`initialize=True` requires DDR settings. Without initialization, the target
must already be running the bundled Windows XUSB. API reads remain single
target by default even after `switch_mp_mode(True)`.

```python
import nuwriter as nw

status = nw.do_pack_program(
	nw.DEV_SPINAND,
	"../numaker-iot-nuc980g2/nuwriter-pack.bin",
	ddr="NUC980DK71YC.ini",
	check=True,
)
if status != 0:
	raise RuntimeError("Pack validation failed")
```

The example is offline. Removing `check=True` programs flash and requires a
successfully initialized target. Pack readback verification is not supported.

### Windows Firmware And SPI NAND Erase

The four bundled `xusb/*.bin` images are synchronized with
`../NUC980_NuWriter_Win/NuWriter/NuWriter/Release`. Their original contents
are preserved in `xusb-before-windows-sync/`. The INFO and storage header
layouts are implemented directly by this Python host. Initialization, INFO,
NAND/SPI NOR/SPI NAND/SD/SDRAM transfers, erase, format and pack operations use
the Windows contracts; GUI-only and unsupported security features are not copied.

After changing firmware files, confirm the board is no longer busy, then
power-cycle it into USB Boot before initializing. `-a` skips the XUSB download
when a device reports that XUSB is already running; replacing host files alone
does not replace firmware already loaded in board RAM.

SPI NAND erase follows the Windows firmware protocol:

| Command | imageNo | Mode | Progress completion |
| --- | --- | --- | --- |
| `-e spinand all` | `0xFFFFFFFF` | `type=0` | Last block index |
| `-e spinand START LENGTH` | `0xFFFFFFFF` | `type=1` | Percentage `100` |

Erase requests validate ACK `0x89` and the returned block count before reading
progress. Erase All sends the reported total block count, including both dies
when applicable. It still performs `0xD8` block erases across the device while
skipping marked bad blocks and preserving their markers; it is not a separate
SPI NAND chip-erase opcode. Erasing bad blocks with `0xFFFFFFFE` is not enabled
in this firmware and is not requested by this host.

Prefer `all` for whole-device erase. The supplied Windows firmware range branch
has a known bad-block loop issue that can prevent completion. The board batch
therefore uses Erase All, not a full-capacity range request. This port retains
bounded waits and does not copy the Windows Fast GUI's read-error assignment
bug. A timeout is a failure, not successful completion.

### JSON Pack Input

`-p`/`do_pack` integrate the standalone generator in this program, without
launching or importing it at runtime. JSON uses the same core MA35 pack tags:
`image` is an array, and each normal image has `file`, `offset`, and `type`.
Numeric values accept JSON integers or strings with `0x` for hexadecimal.
Output is the NUC980 16-byte pack/child-header format, not the MA35 format.

| Target `mode` / `--media` | Supported children | Default environment size including CRC |
| --- | --- | --- |
| `spinand` | loader, env, data/Linux | 128 KiB |
| `spinor` | loader, env, data/Linux | 64 KiB |
| `nand` | loader, env, data/Linux | 64 KiB |
| `sd` / `emmc` | loader, env, data/Linux, partition | 64 KiB |

Specify `mode` (or its `media` alias) in JSON, or use `--media`; conflicting
values are rejected. Relative input/output paths resolve from the working
directory, as in MA35. Output defaults to `pack.bin`; `output` or `--output`
can choose another path. Configuration, source images and DDR files cannot
be overwritten by the pack output. `--check` validates/encodes but writes no
output and never executes the reset hook or accesses USB.

```json
{
	"mode": "spinand",
	"output": "pack.bin",
	"image": [
		{
			"file": "../numaker-iot-nuc980g2/u-boot-spl.bin",
			"offset": "0x0",
			"type": 2,
			"exec_addr": "0x200",
			"ddr_ini": "NUC980DK71YC.ini",
			"page_size": "0x800",
			"spare_area": "0x40",
			"quad_read_cmd": "0x6b",
			"read_status_cmd": "0x0f",
			"write_status_cmd": "0x1f",
			"status_value": "0x18",
			"dummy_byte": "0x1"
		},
		{"file": "../python/files/uboot-env.txt", "offset": "0x80000", "type": "env"},
		{"file": "../numaker-iot-nuc980g2/u-boot.bin", "offset": "0x100000", "type": 0}
	]
}
```

```sh
python nuwriter.py -p pack.json --check
python nuwriter.py -p pack.json
python nuwriter.py -p pack.json --media spinand --output nuwriter-pack.bin
```

JSON uses MA35 numeric type meanings: 0 (data) and 3 (Linux) become NUC980
data; 2 (U-Boot) becomes a NUC980 loader. Type 1 (TFA) is rejected, not treated
as NUC980 environment data. Use named `env`/`environment` for environment
images and named `partition` for SD/eMMC records. Named `data/linux/loader/uboot`
types are also accepted. TFA/DDR/TEE and nested packs are rejected.

Loader extensions are the standalone generator's parameters:

| Per-image field | Meaning / alias |
| --- | --- |
| `offset` | Byte burn address; legacy `address` is accepted |
| `exec_addr` | Loader entry matching the linked image; alias `execute_address`, default `0x200` for typical SPL |
| `ddr_ini` / `ddr` | Per-image DDR file; overrides root `ddr` or CLI `--ddr` |
| `page_size`, `spare_area` | SPI NAND geometry; 16-bit fields |
| `quad_read_cmd`, `read_status_cmd`, `write_status_cmd` | 8-bit command fields |
| `status_value`, `dummy_byte` | 8-bit configuration fields |
| `env_size` | Environment payload bytes, excluding the 4-byte CRC |

DDR input is required for loader images; it is never silently omitted when a
file is missing. SPI loader images require explicit command fields (and page/
spare fields for SPI NAND), either per-image or in global `storage`. Existing
native storage keys such as `quad_read_command`, `read_status_command`,
`write_status_command`, and `dummy_bytes` remain supported. Per-image values
override global settings; conflicting aliases within an image are rejected.
Use parameters appropriate for the actual board/chip, not another media's
example. DDR data is padded to 16 bytes, after the 32-byte loader boot header.

Environment input is text: CRLF/LF entries become NUL-separated U-Boot values,
followed by zero fill and CRC32. The CRC-inclusive size must be a multiple of
the table's default block size. `env_size` can increase it; if input does not
fit, the encoder grows to the next full block rather than truncating it.

SD/eMMC can add a generated partition child alongside normal images:

```json
{
	"mode": "emmc",
	"image": [
		{"file": "u-boot.bin", "offset": "0x400", "type": 2, "exec_addr": "0x00e00000", "ddr_ini": "NUC980DK71YC.ini"},
		{"type": "partition", "partition": {"count": 2, "reserved_size": 32, "sizes": [128, 0]}}
	]
}
```

Partition reserved/sizes are MiB; the sizes array must match count (1-4).
Only the final size may be zero for remaining capacity. The record is 48 bytes
with corresponding 512-byte sector counts, and its child offset is
`0xFFFFFFFF`. Instead of the object, `file` can name an existing valid 48-byte
record. Partition types are rejected on NAND/SPI NOR/SPI NAND. Do not combine
an explicit partition image with `storage.using_format=true`; the compatible
global-storage partition form remains available.

Compatible external INI input remains optional. Existing Windows packs are
still accepted by the parser. Supplying `--ddr` to pack programming checks
embedded loader registers against the selected DDR file; board flashing batch
does this before erase and during programming. This integration was verified
offline against the original generator; it does not certify a new layout on
physical flash.

### Device Selection And Validation

```sh
python nuwriter.py -a NUC980DK71YC.ini --check
python nuwriter.py --list
python nuwriter.py -a NUC980DK71YC.ini --device 1:2.3
python nuwriter.py -e spinand all --timeout 10000 --operation-timeout 300000
python -m unittest discover -s . -p test_nuwriter.py -v
```

`--check` validates configuration and input files without USB access or output
writes, including when `pack=yes`. It cannot validate actual flash geometry,
device compatibility, or hardware behavior. Offline pack generation requires
no USB backend. Existing example image paths may refer to files not included
in this repository.

`--list` shows physical USB paths. VID/PID `0416:5963` is shared with MA35 and
is not a chip identity. Only connect intended NUC980 targets; the Python port
also checks for NUC980 endpoints before sending its protocol. Multiple
candidates require `--device` or `[RUN] all_device=yes` (at most 8 devices).
Devices are programmed sequentially and tracked by physical port after XUSB
re-enumeration. `--device` cannot be combined with `all_device=yes`.

Timeouts are milliseconds. `--timeout` applies to USB transfers and reconnect;
`--operation-timeout` bounds device progress waits during erase, format, and
SPI NOR loader/pack programming. Failures return a nonzero process exit code.

For erase operations, the command acknowledgement, SPI NAND block-count reply,
and progress reads share one `--operation-timeout` budget (default 300000 ms).
Those reads use the remaining budget rather than the default 10000 ms USB
transfer timeout. Media selection and command transmission still use
`--timeout`. Erase errors identify the failed stage and include the last
progress status when available. A host timeout does not prove the device has
stopped erasing; data may already be partially erased. Do not program after a
failed erase, and confirm the board is no longer busy before retrying.

### USB Command Diagnostics

`--trace-usb` writes host control requests, bulk transfer start/completion,
and reply bytes to stderr. Up to 64 bytes per transfer are shown, enough for
the 56-byte NAND/SPI NAND command header. API callers can use `trace_usb=True`.
Tracing does not retry transfers, reset DMA, alter payloads, or treat a timeout
as success. Logs may contain image/data bytes; review them before sharing.
This is host-side API tracing, not a physical USB bus capture.

SDRAM downloads identify the DTB and main image separately and report media
selection, 16-byte header transmission, header ACK, data transfer, or data ACK
as the failing stage. The header ACK must be `0x80`; every data packet must
receive its length ACK, including the final execute packet. A timeout is not
silently treated as a successful jump to Linux.

The UART `pSN->SPINand_PageSize`/`SpareArea` messages are printed before the
SPI NAND command receive loop. The later action/erase messages are debug-only,
so their absence alone does not identify a failed command or prove no erase
occurred. INFO success does not prove a flash command completed.

For a non-destructive receive/ACK test, first confirm the device is no longer
busy and power-cycle into USB Boot. From this directory in PowerShell:

```powershell
python nuwriter.py -a NUC980DK71YC.ini --trace-usb 2> attach-usb.log
python nuwriter.py -r spinand 0 1 spinand-probe.bin --trace-usb 2> read-usb.log
```

Run the read only after initialization succeeds. It reads flash but does not
erase or program it; the output file is created/overwritten on the PC. Provide
the normal console result and both trace logs when reporting a failure.
If the last event is `BULK OUT completed length=56` followed by a pending
4-byte `BULK IN`, the host submitted the header but has not received its ACK.
If `89 00 00 00` arrives, the SPI NAND command was acknowledged; subsequent
data/count/progress events identify the next failing boundary.

Pack inputs with `program_verify` are explicitly rejected: use individual
images for verified programming.
A pack input must be the sole image. SD reads/programs do not require FAT32
formatting; the format operation requires `using_format=yes` and checks that
partitions fit the reported capacity. Environment input must be text.

The port has automated simulated-USB/API/batch and offline tests using
independent in-memory settings, not a bundled sample INI. Real NUC980 hardware
validation is still required before production use. It is not yet wired
into the MA35 Python entry point; `Nuc980Writer` provides the NUC980 operations
for that subsequent integration.

**Copyright (C) 2018 Nuvoton Technology Corp. All rights reserved**


