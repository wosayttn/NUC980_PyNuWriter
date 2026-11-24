"""Command construction for the NuWriter backend."""

import configparser
import io
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
BACKEND = ROOT / "nuwriter.py"
CHIPS = {"NUC980": "nuc980", "NUC970": "nuc970", "NUC990": "nuc990"}
CHIP_DDR_DEFAULTS = {"nuc980": "NUC980DK71YC.ini", "nuc970": "NUC972DF62Y.ini", "nuc990": "COMING_SOON.ini"}
CHIP_MEDIA = {
    "nuc980": ["SDRAM", "SPI NOR", "NAND", "SD/eMMC", "SPI NAND", "Pack", "Mass Production"],
    "nuc970": ["SDRAM", "SPI NOR", "NAND", "SD/eMMC", "MTP", "Pack", "Mass Production"],
}
CHIP_MEDIA["nuc990"] = list(CHIP_MEDIA["nuc980"])
CHIP_PACK_MEDIA = {
    "nuc980": ["SPI NAND", "SPI NOR", "NAND", "SD/eMMC"],
    "nuc970": ["SPI NOR", "NAND", "SD/eMMC"],
}
CHIP_PACK_MEDIA["nuc990"] = list(CHIP_PACK_MEDIA["nuc980"])
MEDIA = {"SDRAM": "ddr", "NAND": "nand", "SPI NOR": "spinor",
         "SPI NAND": "spinand", "SD/eMMC": "sd", "MTP": "mtp"}
KINDS = {"Data": "data", "Environment": "env", "Loader": "loader", "Pack": "pack"}
MTP_AES_MODES = {"USB": "usb", "eMMC / SD": "emmc", "NAND": "nand", "SPI NOR": "spinor"}
MTP_SHA_MODES = {"USB without SHA": "usb_no_sha", "USB with SHA": "usb_sha"}


def number(text):
    value = int(str(text).strip(), 0)
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("Address/length must be in the unsigned 32-bit range.")
    return value


def input_file(filename):
    path = Path(filename).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"File not found: {filename}")
    return path


def output_file(filename):
    if not str(filename).strip():
        raise ValueError("Select an output file.")
    path = Path(filename).expanduser().resolve()
    if not path.parent.is_dir() or path.is_dir():
        raise ValueError(f"Invalid output path: {filename}")
    return path


@dataclass
class ImageEntry:
    filename: str
    kind: str = "Data"
    offset: str = "0x0"
    execute: str = "0x200"
    aes_key: str = ""


@dataclass
class Target:
    ddr: str
    device: str = ""
    trace: bool = False
    timeout: int = 10000
    operation_timeout: int = 300000
    massproduct: bool = False
    chip: str = "nuc980"

    def normalized_chip(self):
        chip = str(self.chip).strip().lower()
        if chip not in CHIPS.values():
            raise ValueError(f"Unsupported chip: {self.chip}")
        return chip

    def options(self):
        arguments = ["--chip", self.normalized_chip(), "--timeout", str(self.timeout),
                     "--operation-timeout", str(self.operation_timeout)]
        if self.device:
            arguments += ["--device", self.device]
        if self.trace:
            arguments.append("--trace-usb")
        if self.massproduct:
            if self.device:
                raise ValueError("Mass production cannot select one USB device.")
            arguments.append("-m")
        return arguments

    def ddr_file(self):
        return str(input_file(self.ddr))


@dataclass
class Command:
    arguments: list
    cwd: Path = ROOT
    label: str = "NuWriter"

    def invocation(self, check=False):
        if getattr(sys, "frozen", False):
            name = "nuwriter.exe" if sys.platform == "win32" else "nuwriter"
            directory = Path(sys.executable).resolve().parent
            executable = (directory / name if sys.platform == "darwin"
                          else directory / "backend" / "nuwriter" / name)
            prefix = [str(executable)]
        else:
            prefix = [sys.executable, "-u", str(BACKEND)]
        return prefix + self.arguments + (["--check"] if check else [])


def attach(target):
    return Command(["-a", "--ddr", target.ddr_file()] + target.options(), label="Re-Connect")


def _validate_flash_media(target, media):
    chip = target.normalized_chip()
    if media not in CHIP_PACK_MEDIA[chip]:
        raise ValueError(f"{media} is not supported for {chip.upper()}.")


def program(target, media, image, verify=False):
    filename = str(input_file(image.filename))
    if media not in MEDIA or media in {"SDRAM", "MTP"} or image.kind not in KINDS:
        raise ValueError("Select flash media and an image type.")
    _validate_flash_media(target, media)
    chip = target.normalized_chip()
    aes_key = image.aes_key.strip() if isinstance(image.aes_key, str) else ""
    if image.kind == "Pack":
        if aes_key:
            raise ValueError("AES encryption key cannot be applied when writing a Pack file.")
        arguments = ["-w", MEDIA[media], filename, "--ddr", target.ddr_file()]
        if verify:
            arguments += ["-o", "verify"]
    else:
        offset = number(image.offset)
        execute = number(image.execute)
        arguments = ["-w", MEDIA[media], hex(offset), filename, "-t", KINDS[image.kind],
                     "--exec-addr", hex(execute)]
        if image.kind == "Loader":
            if offset != (0x400 if media == "SD/eMMC" else 0):
                raise ValueError("Loader offset must be 0 for flash or 0x400 for SD/eMMC.")
            arguments += ["--ddr", target.ddr_file()]
        if aes_key:
            if chip != "nuc970":
                raise ValueError("AES image encryption is supported only for NUC970.")
            if image.kind not in {"Data", "Loader"}:
                raise ValueError("AES image encryption supports only Data and Loader images.")
            arguments += ["--aes-key", str(input_file(aes_key))]
        if verify:
            arguments += ["-o", "verify"]
    return Command(arguments + target.options(), label=f"{media} program")


def mtp_program(target, source_file, option, mode, encrypt_enabled=True, lock=False):
    if target.normalized_chip() != "nuc970":
        raise ValueError("MTP programming is supported only for NUC970.")
    if target.massproduct:
        raise ValueError("MTP programming requires a single target.")
    option_key = str(option).strip().lower()
    if option_key not in {"aes", "sha"}:
        raise ValueError("MTP option must be AES or SHA.")
    mode_value = (MTP_AES_MODES if option_key == "aes" else MTP_SHA_MODES).get(mode, str(mode).strip().lower())
    arguments = ["-w", "mtp", str(input_file(source_file)),
                 "--mtp-option", option_key, "--mtp-mode", mode_value]
    if not encrypt_enabled:
        arguments.append("--mtp-disable-encrypt")
    if lock:
        arguments.append("--mtp-lock")
    return Command(arguments + target.options(), label="MTP program")


def download(target, filename, address, execute=False, dtb="", dtb_address="0x1400000", bootargs=None):
    arguments = ["-w", "ddr", hex(number(address)), str(input_file(filename))]
    if execute:
        arguments += ["-o", "execute"]
    if dtb:
        arguments += ["--dtb", str(input_file(dtb)), "--dtb-addr", hex(number(dtb_address))]
        if bootargs is not None:
            arguments += ["--bootargs", bootargs]
    elif bootargs is not None:
        raise ValueError("Bootargs require a DTB file.")
    return Command(arguments + target.options(), label="SDRAM download")


def read(target, media, filename, start="0x0", length="0x20000", all_flash=False, flash_size=""):
    if target.massproduct:
        raise ValueError("Read operations require a single target.")
    if media not in MEDIA or media in {"SDRAM", "MTP"}:
        raise ValueError(f"Reading {media} is not supported.")
    _validate_flash_media(target, media)
    destination = output_file(filename)
    arguments = ["-r", MEDIA[media]]
    if all_flash:
        arguments += ["all", str(destination)]
        if media == "SPI NOR":
            size = number(flash_size)
            if not size:
                raise ValueError("SPI NOR read-all requires its flash size in bytes.")
            arguments += ["--flash-size", hex(size)]
    else:
        count = number(length)
        if not count:
            raise ValueError("Read length must be greater than zero.")
        arguments += [hex(number(start)), hex(count), str(destination)]
    return Command(arguments + target.options(), label=f"{media} read")


def erase(target, media, start="0x0", length="0x20000", all_flash=True):
    if media not in MEDIA or media in {"SDRAM", "SD/eMMC", "MTP"}:
        raise ValueError("Erase is supported only for NAND, SPI NAND and SPI NOR.")
    _validate_flash_media(target, media)
    arguments = ["-e", MEDIA[media]]
    if all_flash:
        arguments.append("all")
    else:
        count = number(length)
        if not count:
            raise ValueError("Erase length must be greater than zero.")
        arguments += [hex(number(start)), hex(count)]
    return Command(arguments + target.options(), label=f"{media} erase")


def format_configuration(target, reserved, sizes):
    if not 1 <= len(sizes) <= 4 or sizes[-1] != 0:
        raise ValueError("Select 1-4 partitions; the last partition uses remaining capacity.")
    if any(number(value) == 0 for value in sizes[:-1]):
        raise ValueError("Fixed partition sizes must be greater than zero.")
    config = configparser.ConfigParser()
    config.read_dict({"RUN": {"chip": target.normalized_chip(), "mode": "SD", "pack": "no", "all_device": "no"},
                      "DDR": {"ddr": target.ddr_file()},
                      "SD": {"run": "format", "using_format": "yes", "reserved_size": str(number(reserved)),
                             "partition_num": str(len(sizes))}})
    for index, value in enumerate(sizes[:-1], 1):
        config.set("SD", f"partition{index}_size", str(number(value)))
    output = io.StringIO()
    config.write(output)
    return output.getvalue()


def pack(config, output, media, chip="nuc980"):
    normalized_chip = str(chip).strip().lower()
    if normalized_chip not in CHIPS.values():
        raise ValueError(f"Unsupported chip: {chip}")
    if media not in CHIP_PACK_MEDIA[normalized_chip]:
        raise ValueError("Select pack media.")
    source = input_file(config)
    return Command(["--chip", normalized_chip, "-p", str(source), "--media", MEDIA[media], "--output", str(output_file(output))],
                   cwd=source.parent, label="Pack output")


def pack_document(document, media, chip=None):
    result = dict(document)
    result.pop("media", None)
    result["mode"] = MEDIA[media]
    if chip is not None and "chip" in result:
        result["chip"] = str(chip).strip().lower()
    return result


def protect_pack_inputs(document, directory, output, config=None):
    protected = {Path(config).resolve()} if config else set()
    for image in document.get("image", []):
        for key in ("file", "key_file", "ddr_ini", "ddr", "aes_key"):
            if image.get(key):
                path = Path(image[key])
                protected.add((directory / path).resolve())
                if key in {"ddr_ini", "ddr"}:
                    protected.add((ROOT / "sys_cfg" / path).resolve())
                    protected.add((ROOT / "sys_cfg" / "nuc980" / path).resolve())
                    protected.add((ROOT / "sys_cfg" / "nuc970" / path).resolve())
                    protected.add((ROOT / "sys_cfg" / "nuc990" / path).resolve())
                elif key in {"aes_key", "key_file"} or image.get("type") == "mtp":
                    protected.add((ROOT / "key_cfg" / path).resolve())
                    protected.add((ROOT / "key_cfg" / "nuc970" / path).resolve())
    if document.get("ddr"):
        protected.add((directory / document["ddr"]).resolve())
        protected.add((ROOT / "sys_cfg" / document["ddr"]).resolve())
        protected.add((ROOT / "sys_cfg" / "nuc980" / document["ddr"]).resolve())
        protected.add((ROOT / "sys_cfg" / "nuc970" / document["ddr"]).resolve())
        protected.add((ROOT / "sys_cfg" / "nuc990" / document["ddr"]).resolve())
    if Path(output).resolve() in protected:
        raise ValueError("Output cannot overwrite the configuration or its image/DDR inputs.")


def verification_read(target, media, image, destination):
    if image.kind != "Data":
        raise ValueError("Standalone Verify supports Data images. Use Program + Verify for Loader/Environment.")
    if isinstance(image.aes_key, str) and image.aes_key.strip():
        raise ValueError("Standalone Verify compares plaintext files. Use Program + Verify for AES-encrypted images.")
    source = input_file(image.filename)
    return read(target, media, destination, image.offset, hex(source.stat().st_size))


def compare_files(expected, actual):
    position = 0
    with Path(expected).open("rb") as source, Path(actual).open("rb") as result:
        while True:
            original = source.read(65536)
            received = result.read(65536)
            if original != received:
                raise ValueError(f"Verification mismatch near offset 0x{position:x}.")
            if not original:
                return
            position += len(original)


def progress_value(text) -> Optional[int]:
    match = re.search(r"\[[#-]{10}\]\s*(\d{1,3})%", text)
    return min(100, int(match.group(1))) if match else None


def device_paths(text):
    return re.findall(r"(?m)^(\d+:[\d.]+)\s+VID:PID 0416:5963", text)