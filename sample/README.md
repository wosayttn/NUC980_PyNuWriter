# Sample images and configurations

[English](README.md) | [简体中文](README.zh-CN.md) | [繁體中文](README.zh-TW.md)

[Main guide](../README.md) | [GUI guide](../gui/README.md) | [Driver guide](../driver/README.md)

GUI integration tests use these real NUC980 images with `--check`; no board
access or pack-output writes are performed. Synthetic files remain in tests
that exercise invalid inputs, subprocess failures, and command construction.

| Configuration | Target | Root filesystem |
| --- | --- | --- |
| [config_spinand.json](config_spinand.json) | SPI NAND | UBI at 0x800000 |
| [config_sd1.json](config_sd1.json) | Board SD1, backend mode sd | ext4 at 0x800000 |

Paths are relative to this directory. Both configurations use
`../sys_cfg/NUC980DK71YC.ini`. The SD1 template reserves 8 MiB before the first
partition and uses the remaining capacity for it; the card must be large
enough for the ext4 image. The host uses `sd`, not a separate `sd1` CLI mode.

The source images, U-Boot environments, and offsets are based on the supplied
SPI NAND and SD packs. The SD1 template generates a backend partition record
rather than copying the supplied pack's raw MBR. Offline validation is not a
real-board boot test; verify the board, boot mode, and media before programming.

`zImage` is the raw ARM Linux kernel used by RAM-download integration tests.
`uImage` includes a U-Boot image header and remains the kernel input in the
flash-pack templates. Do not execute `uImage` directly as a raw kernel.

Run from the `sample` directory. The GUI uses the JSON directory as the
working directory automatically:

```bash
python ../nuwriter.py -p config_spinand.json --check
```

```bash
python ../nuwriter.py -p config_sd1.json --check
```

Generate packs only when intended; these commands write the output files:

```bash
python ../nuwriter.py -p config_spinand.json
```

```bash
python ../nuwriter.py -p config_sd1.json
```

Prebuilt SPI NAND and SD pack fixtures are retained for pack-program checks.
Duplicate image aliases, unused UBIFS/WIC images, build metadata, and unused
configuration files are not retained.