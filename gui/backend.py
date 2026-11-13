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
MEDIA = {"SDRAM": "ddr", "NAND": "nand", "SPI NOR": "spinor",
         "SPI NAND": "spinand", "SD/eMMC": "sd"}
KINDS = {"Data": "data", "Environment": "env", "Loader": "loader", "Pack": "pack"}


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


@dataclass
class Target:
    ddr: str
    device: str = ""
    trace: bool = False
    timeout: int = 10000
    operation_timeout: int = 300000
    massproduct: bool = False

    def options(self):
        arguments = ["--timeout", str(self.timeout), "--operation-timeout", str(self.operation_timeout)]
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
            if sys.platform == "darwin":
                directory = directory.parent.parent.parent
            executable = directory / "backend" / "nuwriter" / name
            prefix = [str(executable)]
        else:
            prefix = [sys.executable, "-u", str(BACKEND)]
        return prefix + self.arguments + (["--check"] if check else [])


def attach(target):
    return Command(["-a", "--ddr", target.ddr_file()] + target.options(), label="Re-Connect")


def program(target, media, image, verify=False):
    filename = str(input_file(image.filename))
    if media not in MEDIA or media == "SDRAM" or image.kind not in KINDS:
        raise ValueError("Select flash media and an image type.")
    if image.kind == "Pack":
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
        if verify:
            arguments += ["-o", "verify"]
    return Command(arguments + target.options(), label=f"{media} program")


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
    if media not in MEDIA or media == "SDRAM":
        raise ValueError("Reading SDRAM is not supported.")
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
    if media not in MEDIA or media in {"SDRAM", "SD/eMMC"}:
        raise ValueError("Erase is supported only for NAND, SPI NAND and SPI NOR.")
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
    config.read_dict({"RUN": {"mode": "SD", "pack": "no", "all_device": "no"},
                      "DDR": {"ddr": target.ddr_file()},
                      "SD": {"run": "format", "using_format": "yes", "reserved_size": str(number(reserved)),
                             "partition_num": str(len(sizes))}})
    for index, value in enumerate(sizes[:-1], 1):
        config.set("SD", f"partition{index}_size", str(number(value)))
    output = io.StringIO()
    config.write(output)
    return output.getvalue()


def pack(config, output, media):
    if media not in MEDIA or media == "SDRAM":
        raise ValueError("Select pack media.")
    source = input_file(config)
    return Command(["-p", str(source), "--media", MEDIA[media], "--output", str(output_file(output))],
                   cwd=source.parent, label="Pack output")


def pack_document(document, media):
    result = dict(document)
    result.pop("media", None)
    result["mode"] = MEDIA[media]
    return result


def protect_pack_inputs(document, directory, output, config=None):
    protected = {Path(config).resolve()} if config else set()
    for image in document.get("image", []):
        for key in ("file", "ddr_ini", "ddr"):
            if image.get(key):
                path = Path(image[key])
                protected.add((directory / path).resolve())
                if key != "file":
                    protected.add((ROOT / "sys_cfg" / path).resolve())
    if document.get("ddr"):
        protected.add((directory / document["ddr"]).resolve())
        protected.add((ROOT / "sys_cfg" / document["ddr"]).resolve())
    if Path(output).resolve() in protected:
        raise ValueError("Output cannot overwrite the configuration or its image/DDR inputs.")


def verification_read(target, media, image, destination):
    if image.kind != "Data":
        raise ValueError("Standalone Verify supports Data images. Use Program + Verify for Loader/Environment.")
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