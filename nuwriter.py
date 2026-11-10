"""NUC980 Windows NuWriter protocol with a MA35-style Python/CLI interface.

Protocol reference: NUC980_NuWriter_Win/NuWriter/NuWriter and NuWriterFW_BSP.
The C++ sources are reference material, not runtime dependencies.
"""

import argparse
import configparser
import importlib
import io
import json
import struct
import subprocess
import sys
import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


USB_VENDOR_ID = 0x0416
__version__ = "0.1.0"
USB_PRODUCT_ID = 0x5963
TRANSFER_SIZE = 4096
ACK = 0x55AA55AA
MEDIA = {"SDRAM": 0, "NAND": 3, "SD": 5, "SPINOR": 7, "SPINAND": 9}
IMAGE_TYPES = {"data": 0, "env": 1, "loader": 2, "pack": 3, "partition": 3}
DEV_DDR_SRAM = 0
DEV_NAND = 1
DEV_EMMC = 2
DEV_SPINOR = 3
DEV_SPINAND = 4
DEV_SD = 7
DEV_UNKNOWN = 0xFF
OPT_NONE = 0
OPT_EXECUTE = 2
OPT_VERIFY = 3
OPT_UNKNOWN = 0xFF
IMG_DATA = 0
IMG_UBOOT = 2
IMG_LINUX = 3
IMG_UNKNOWN = 0xFF
mp_mode = False
INFO_STRUCT = struct.Struct("<9I5B3x4I2H5B3x2IB3x")
INFO_FIELDS = (
    "nand_page_per_block", "nand_page_size", "nand_sector_per_block",
    "nand_block_count", "nand_bad_block_count", "nand_spare_size", "nand_user",
    "spi_id", "spi_user", "spi_quad", "spi_read_status", "spi_write_status",
    "spi_status", "spi_dummy", "emmc_blocks", "emmc_reserved", "spinand_user",
    "spinand_id", "spinand_page_size", "spinand_spare_size", "spinand_quad",
    "spinand_read_status", "spinand_write_status", "spinand_status",
    "spinand_dummy", "spinand_block_count", "spinand_page_per_block", "spinand_die",
)


class NuWriterError(Exception):
    pass


class TransferProgress:
    def __init__(self, label, total):
        self.label = label
        self.total = total
        self.percent = -10

    def __enter__(self):
        self.update(0)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.percent < 100:
            print(flush=True)

    def update(self, completed):
        percent = min(90, completed * 100 // self.total) if self.total else 0
        self.show(percent)

    def complete(self):
        self.show(100)

    def show(self, percent):
        while self.percent + 10 <= percent:
            self.percent += 10
            blocks = self.percent // 10
            bar = "#" * blocks + "-" * (10 - blocks)
            print(f"\r{self.label} [{bar}] {self.percent:3d}%",
                  end="\n" if self.percent == 100 else "", flush=True)


class UsbTransport:
    def __init__(self, device, timeout=10000, trace=False):
        self.device = device
        self.timeout = timeout
        self.trace = trace

    def log(self, message):
        if self.trace:
            print(f"USB {message}", file=sys.stderr, flush=True)

    def write(self, data):
        data = bytes(data)
        if not 0 < len(data) <= 0xFFFF:
            raise NuWriterError("USB transfer length must be between 1 and 65535")
        self.log(f"CONTROL OUT request=0xa0 value=0x0012 index={len(data)} length=0")
        self.device.ctrl_transfer(
            0x40, 0xA0, wValue=0x12, wIndex=len(data),
            data_or_wLength=b"", timeout=self.timeout,
        )
        self.log("CONTROL OUT completed")
        preview = data[:64].hex(" ") + (" ..." if len(data) > 64 else "")
        self.log(f"BULK OUT endpoint=0x02 length={len(data)} data={preview}")
        written = self.device.write(0x02, data, timeout=self.timeout)
        self.log(f"BULK OUT completed length={written}")
        if written != len(data):
            raise NuWriterError(f"Short USB write: {written}/{len(data)}")

    def read(self, size, minimum=None, timeout=None):
        read_timeout = self.timeout if timeout is None else timeout
        self.log(f"BULK IN endpoint=0x81 length={size} timeout={read_timeout} ms")
        data = bytes(self.device.read(0x81, size, timeout=read_timeout))
        preview = data[:64].hex(" ") + (" ..." if len(data) > 64 else "")
        self.log(f"BULK IN completed length={len(data)} data={preview}")
        required = size if minimum is None else minimum
        if not required <= len(data) <= size:
            raise NuWriterError(f"Short USB read: {len(data)}/{size}")
        return data

    def read_word(self, timeout=None):
        data = self.read(4) if timeout is None else self.read(4, timeout=timeout)
        return struct.unpack("<I", data)[0]

    def expect(self, value):
        actual = self.read_word()
        if actual != value:
            raise NuWriterError(f"Unexpected ACK: 0x{actual:08x}, expected 0x{value:08x}")

    def set_type(self, media):
        value = 0x80 + media
        deadline = time.monotonic() + self.timeout / 1000
        while True:
            self.log(f"CONTROL OUT request=0xb0 value=0x{value:04x} index=0 length=0")
            self.device.ctrl_transfer(
                0x40, 0xB0, wValue=value, wIndex=0,
                data_or_wLength=b"", timeout=self.timeout,
            )
            self.log(f"CONTROL IN request=0xb0 value=0x{value:04x} index=0 length=2")
            reply = bytes(self.device.ctrl_transfer(
                0xC0, 0xB0, wValue=value, wIndex=0,
                data_or_wLength=2, timeout=self.timeout,
            ))
            self.log(f"CONTROL IN completed length={len(reply)} data={reply.hex(' ')}")
            if reply and reply[0] == value:
                return
            if time.monotonic() >= deadline:
                last_reply = reply.hex(" ") if reply else "<empty>"
                raise NuWriterError(
                    f"Timed out selecting storage media (type={media}, "
                    f"request=0xB0, wValue=0x{value:04x}, "
                    f"expected ACK byte=0x{value:02x}, last reply={last_reply})"
                )

    def send_chunks(self, data):
        with TransferProgress("Download", len(data)) as progress:
            for offset in range(0, len(data), TRANSFER_SIZE):
                chunk = data[offset:offset + TRANSFER_SIZE]
                self.write(chunk)
                self.expect(len(chunk))
                progress.update(offset + len(chunk))
            progress.complete()


@dataclass
class Image:
    path: Optional[Path]
    kind: int
    execute: int
    offset: int
    parameters: dict = field(default_factory=dict)


@dataclass
class PreparedImage:
    image: Image
    data: bytes
    file_length: int
    init_size: int = 0


class RunConfig:
    def __init__(self, filename, resource_dir=None, settings=None, pack_override=None):
        self.filename = Path(filename) if filename else None
        self.ini = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=("#", ";"))
        if settings is None:
            if self.filename is None:
                raise NuWriterError("A configuration file is required")
            with self.filename.open(encoding="utf-8-sig") as source:
                self.ini.read_file(source)
        else:
            self.ini.read_dict(settings)
        self.resource_dir = Path(resource_dir) if resource_dir else Path(__file__).resolve().parent
        self.initialize = True
        self.compatible = False
        self.byte_range = None
        self.flash_size = None
        self.mode = self.text("RUN", "mode").upper()
        if self.mode not in MEDIA:
            raise NuWriterError(f"Unsupported mode: {self.mode}")
        self.pack = self.yes("RUN", "pack") if pack_override is None else pack_override
        self.all_devices = self.yes("RUN", "all_device")
        self.operation = "download" if self.mode == "SDRAM" else self.text(self.mode, "run").lower()
        allowed = {"program", "program_verify", "read", "erase", "format"}
        if self.mode != "SDRAM" and self.operation not in allowed:
            raise NuWriterError(f"Unsupported operation: {self.operation}")
        if self.operation == "format" and self.mode != "SD":
            raise NuWriterError("Format is only supported in SD mode")
        if self.operation == "erase" and self.mode in {"SD", "SDRAM"}:
            raise NuWriterError("Erase is not supported in this mode")
        if self.pack and self.mode == "SDRAM":
            raise NuWriterError("SDRAM mode does not support pack generation")
        self.images = []
        if self.mode != "SDRAM" and (self.pack or self.operation in {"program", "program_verify"}):
            count = self.number(self.mode, "image_num")
            if not 1 <= count <= 12:
                raise NuWriterError("image_num must be between 1 and 12")
            for index in range(count):
                prefix = f"image{index}_"
                kind = self.text(self.mode, prefix + "type").lower()
                if kind not in IMAGE_TYPES:
                    raise NuWriterError(f"Unsupported image type: {kind}")
                if kind == "partition" and (not self.pack or self.mode != "SD"):
                    raise NuWriterError("Partition images are supported only in SD/eMMC pack generation")
                path_text = self.ini.get(self.mode, prefix + "path", fallback=None) if kind == "partition" else self.text(self.mode, prefix + "path")
                self.images.append(Image(
                    Path(path_text) if path_text else None, IMAGE_TYPES[kind],
                    self.number(self.mode, prefix + "exe_addr", 0),
                    self.number(self.mode, prefix + "start_offset", 0),
                    {"role": "partition"} if kind == "partition" else {},
                ))

    def text(self, section, key, default=None):
        value = self.ini.get(section, key, fallback=default)
        if value is None or not str(value).strip():
            raise NuWriterError(f"Missing [{section}] {key}")
        return str(value).strip()

    def number(self, section, key, default=None):
        text = self.text(section, key, default).rstrip(";").strip()
        try:
            value = int(text, 0)
        except ValueError:
            if not text.isdecimal():
                raise NuWriterError(f"Invalid [{section}] {key}: {text}") from None
            value = int(text, 10)
        if not 0 <= value <= 0xFFFFFFFF:
            raise NuWriterError(f"[{section}] {key} is outside the 32-bit unsigned range")
        return value

    def yes(self, section, key):
        value = self.text(section, key, "no").lower()
        if value not in {"yes", "no"}:
            raise NuWriterError(f"[{section}] {key} must be yes or no")
        return value == "yes"

    def ddr(self):
        path = Path(self.text("DDR", "ddr"))
        return path if path.is_absolute() else self.resource_dir / "sys_cfg" / path

    def xusb(self, name):
        return self.resource_dir / "xusb" / name

    def user_info(self):
        values = dict.fromkeys(INFO_FIELDS, 0)
        values.update(nand_block_count=1024, nand_page_per_block=64, emmc_reserved=1000)
        if self.mode == "NAND":
            values["nand_user"] = int(self.yes(self.mode, "using_user_defined"))
            values["nand_block_count"] = self.number(self.mode, "blockperflash", 1024)
            values["nand_page_per_block"] = self.number(self.mode, "pageperblock", 64)
        if self.mode in {"SPINOR", "SPINAND"}:
            prefix = "spi" if self.mode == "SPINOR" else "spinand"
            values[prefix + "_user"] = int(self.yes(self.mode, "using_user_defined"))
            for suffix, key in (("quad", "quad_read_command"), ("read_status", "read_status_command"),
                                ("write_status", "write_status_command"), ("status", "status_value"),
                                ("dummy", "dummy_bytes")):
                values[prefix + "_" + suffix] = self.number(self.mode, key, 0)
            if self.mode == "SPINAND":
                for field, key, default in (("page_size", "page_size", 2048),
                                            ("spare_size", "spare_area", 64),
                                            ("block_count", "blockperflash", 1024),
                                            ("page_per_block", "pageperflash", 64),
                                            ("die", "multichip", 0)):
                    values["spinand_" + field] = self.number(self.mode, key, default)
        if self.mode == "SD":
            values["emmc_reserved"] = self.number(self.mode, "reserved_size", 1000)
        try:
            return INFO_STRUCT.pack(*(values[field] for field in INFO_FIELDS))
        except struct.error as error:
            raise NuWriterError(f"Storage settings exceed their protocol field widths: {error}") from error


def load_ddr(path):
    data = bytearray()
    xusb_name = None
    names = {4: "xusb16.bin", 5: "xusb.bin", 6: "xusb64.bin", 7: "xusb128.bin"}
    with Path(path).open(encoding="utf-8-sig") as source:
        for line_number, line in enumerate(source, 1):
            line = line.strip()
            if not line or line.startswith(("#", ";")):
                continue
            try:
                address_text, value_text = line.split("=", 1)
                address, value = int(address_text, 0), int(value_text, 0)
                pair = struct.pack("<II", address, value)
            except (ValueError, struct.error) as error:
                raise NuWriterError(f"Invalid DDR setting at {path}:{line_number}") from error
            if address == 0xB0002010:
                xusb_name = names.get(value & 7)
            if address != 0xB0000000:
                data.extend(pair)
    if not data or len(data) > TRANSFER_SIZE:
        raise NuWriterError("DDR settings must contain between 1 and 4096 bytes")
    if xusb_name is None:
        raise NuWriterError("DDR settings do not select a supported XUSB image")
    return bytes(data), xusb_name


def ddr_input_path(config, filename=None):
    path = config.ddr() if filename is None else Path(filename)
    if filename is not None and not path.is_absolute() and not path.is_file():
        path = config.resource_dir / "sys_cfg" / path
    return path


def formatted_ddr(config, filename=None):
    path = ddr_input_path(config, filename)
    data, name = load_ddr(path)
    result = struct.pack("<II", 0xAA55AA55, len(data) // 8) + data
    return result + bytes((-len(result)) % 16)


def environment_image(source, size):
    if b"\x00" in source:
        raise NuWriterError("Environment input must be text, not a binary environment image")
    body = source.replace(b"\r\n", b"\n").replace(b"\n", b"\x00")
    if not body.endswith(b"\x00"):
        body += b"\x00"
    if len(body) >= size - 4:
        raise NuWriterError("Environment does not fit in its storage region")
    body += bytes(size - 4 - len(body))
    return struct.pack("<I", zlib.crc32(body)) + body


def partition_payload(settings):
    if not isinstance(settings, dict) or set(settings) - {"count", "reserved_size", "sizes", "filesystem"}:
        raise NuWriterError("Partition settings must contain count, reserved_size, sizes, and optional filesystem")
    count = cli_number(settings.get("count"), "partition count")
    reserved = cli_number(settings.get("reserved_size"), "partition reserved size")
    sizes = settings.get("sizes")
    if not 1 <= count <= 4 or not isinstance(sizes, list) or len(sizes) != count:
        raise NuWriterError("Partition sizes must be an array matching count (1 to 4)")
    sizes = [cli_number(value, "partition size") for value in sizes]
    if any(size == 0 for size in sizes[:-1]):
        raise NuWriterError("Only the final partition may use size 0 for remaining capacity")
    sizes += [0] * (4 - len(sizes))
    fields = [cli_number(settings.get("filesystem", 0), "partition filesystem"), count, reserved, 0xFFFFFFFF]
    for size in sizes:
        fields.extend((size, size * 2048))
    try:
        return struct.pack("<12I", *fields)
    except struct.error as error:
        raise NuWriterError(f"Partition sizes exceed the 32-bit record: {error}") from error


def validate_partition_payload(data):
    if len(data) != 48:
        raise NuWriterError("SD/eMMC partition record must contain exactly 48 bytes")
    fields = struct.unpack("<12I", data)
    if not 1 <= fields[1] <= 4 or fields[3] != 0xFFFFFFFF:
        raise NuWriterError("Invalid SD/eMMC partition record header")
    for index in range(4):
        if fields[5 + index * 2] != fields[4 + index * 2] * 2048:
            raise NuWriterError("Partition MB and sector sizes disagree")
    return data


def prepare_image(config, image):
    if image.parameters.get("role") == "partition":
        if not config.pack or config.mode != "SD":
            raise NuWriterError("Partition records require SD/eMMC pack mode")
        settings = image.parameters.get("partition")
        if settings is not None:
            if image.path is not None:
                raise NuWriterError("Specify partition settings or a record file, not both")
            data = partition_payload(settings)
        elif image.path is not None:
            data = validate_partition_payload(image.path.read_bytes())
        else:
            raise NuWriterError("Partition image requires settings or a 48-byte record file")
        return PreparedImage(image, data, len(data))
    if image.path is None:
        raise NuWriterError("Image file is required")
    source = image.path.read_bytes()
    if not source or len(source) > 0xFFFFFFFF:
        raise NuWriterError(f"Invalid image length: {image.path}")
    if image.kind == IMAGE_TYPES["pack"]:
        return PreparedImage(image, source, len(source))
    if image.kind == IMAGE_TYPES["env"]:
        block_size = 0x20000 if config.mode == "SPINAND" else 0x10000
        size = block_size
        if config.pack:
            payload_size = cli_number(image.parameters.get("env_size", block_size - 4), "environment payload size")
            size = payload_size + 4
            if size % block_size:
                raise NuWriterError(f"Environment size including CRC must align to {block_size} bytes")
            needed = len(source.replace(b"\r\n", b"\n").replace(b"\n", b"\x00").rstrip(b"\x00")) + 6
            size = max(size, ((needed + block_size - 1) // block_size) * block_size)
            if size > 0xFFFFFFFF:
                raise NuWriterError("Environment image exceeds the 32-bit pack format")
        data = environment_image(source, size)
        return PreparedImage(image, data, len(data))
    if image.kind == IMAGE_TYPES["loader"]:
        ddr = formatted_ddr(config, image.parameters.get("ddr_ini"))
        padding = b"\xff" * 32 if config.mode == "SD" else b""
        return PreparedImage(image, ddr + source + padding, len(source), len(ddr))
    return PreparedImage(image, source, len(source))


def storage_header(action, file_length=0, kind=0, execute=0, offset=0, init_size=0, number=0):
    try:
        return struct.pack("<3I16s4I8sI", action, file_length, number, bytes(16),
                           kind, execute, offset, 0, bytes(8), init_size)
    except struct.error as error:
        raise NuWriterError(f"Storage request exceeds its protocol field widths: {error}") from error


def mmc_header(action, file_length=0, kind=0, execute=0, offset=0, init_size=0,
               number=0, reserved=0, partition_count=0, sizes=(0, 0, 0, 0)):
    base = storage_header(action, file_length, kind, execute, offset, init_size, number)
    try:
        partitions = struct.pack("<B3x9I", 0, partition_count, *sizes, 0, 0, 0, 0)
        return base[:44] + struct.pack("<I", reserved) + base[44:] + partitions
    except struct.error as error:
        raise NuWriterError(f"SD partition settings exceed their protocol field widths: {error}") from error


def partition_settings(config):
    if not config.yes("SD", "using_format"):
        return 0, (0, 0, 0, 0)
    count = config.number("SD", "partition_num")
    if not 1 <= count <= 4:
        raise NuWriterError("partition_num must be between 1 and 4")
    sizes = tuple(config.number("SD", f"partition{index}_size", 0) for index in range(1, 4)) + (0,)
    return count, sizes


def dtb_with_bootargs(data, bootargs):
    if not bootargs.strip() or "\x00" in bootargs:
        raise NuWriterError("DTB bootargs must be nonempty text without NUL characters")
    try:
        fdt_module = importlib.import_module("pyfdt.pyfdt")
    except ModuleNotFoundError as error:
        raise NuWriterError("Bootargs override requires pyfdt; install requirements.txt") from error
    try:
        tree = fdt_module.FdtBlobParse(io.BytesIO(data)).to_fdt()
        chosen = tree.resolve_path("/chosen")
        if chosen is None:
            chosen = fdt_module.FdtNode("chosen")
            tree.resolve_path("/").append(chosen)
        if tree.resolve_path("/chosen/bootargs") is not None:
            chosen.remove("bootargs")
        chosen.append(fdt_module.FdtPropertyStrings("bootargs", [bootargs]))
        return tree.to_dtb()
    except Exception as error:
        raise NuWriterError(f"Cannot update DTB bootargs: {error}") from error


def prepare_sdram(config):
    option = config.text("SDRAM", "option", "download").lower()
    if option not in {"download", "run"}:
        raise NuWriterError("[SDRAM] option must be download or run")
    data = Path(config.text("SDRAM", "sdram_path")).read_bytes()
    address = config.number("SDRAM", "exe_addr")
    dtb_address, dtb_data = 0, b""
    if config.yes("SDRAM", "using_dtb"):
        dtb_address = config.number("SDRAM", "dtb_addr")
        dtb_data = Path(config.text("SDRAM", "dtb_path")).read_bytes()
        if not dtb_data or not dtb_address:
            raise NuWriterError("DTB image and address must be nonzero")
    if config.ini.has_option("SDRAM", "bootargs"):
        if not dtb_data:
            raise NuWriterError("Bootargs override requires a DTB")
        dtb_data = dtb_with_bootargs(dtb_data, config.text("SDRAM", "bootargs"))
    if not data or address >= 0x80000000 or dtb_address >= 0x80000000:
        raise NuWriterError("SDRAM image must be nonempty and addresses must not set the autorun bit")
    if max(len(data), len(dtb_data)) > 0xFFFFFFFF:
        raise NuWriterError("SDRAM image length exceeds its protocol field width")
    if address + len(data) > 0x80000000 or dtb_address + len(dtb_data) > 0x80000000:
        raise NuWriterError("SDRAM image range must not cross the autorun address bit")
    if dtb_data and address < dtb_address + len(dtb_data) and dtb_address < address + len(data):
        raise NuWriterError("SDRAM image and DTB download ranges overlap")
    return data, address, option == "run", dtb_data, dtb_address


def loader_header(config, prepared):
    values = dict(zip(INFO_FIELDS, INFO_STRUCT.unpack(config.user_info())))
    parameters = prepared.image.parameters
    prefix = "spinand" if config.mode == "SPINAND" else "spi"
    page = parameters.get("page_size", values["spinand_page_size"] if prefix == "spinand" else 2048)
    spare = parameters.get("spare_area", values["spinand_spare_size"] if prefix == "spinand" else 64)
    commands = [parameters.get(parameter, values[prefix + "_" + key]) for parameter, key in
                (("quad_read_cmd", "quad"), ("read_status_cmd", "read_status"),
                 ("write_status_cmd", "write_status"), ("status_value", "status"), ("dummy_byte", "dummy"))]
    try:
        return struct.pack("<4sIIIHH5B3sI", b" TVN", prepared.image.execute,
                           prepared.file_length, 0xFFFFFFFF, page, spare,
                           *commands, b"\xff" * 3, 0xFFFFFFFF)
    except struct.error as error:
        raise NuWriterError(f"Loader parameters exceed their protocol field widths: {error}") from error


def build_pack(config, prepared_images):
    if any(prepared.image.kind == 3 and prepared.image.parameters.get("role") != "partition" for prepared in prepared_images):
        raise NuWriterError("Nested pack images are not supported")
    children = []
    for prepared in prepared_images:
        payload = prepared.data
        if prepared.image.kind == 2:
            if config.mode == "SD":
                payload = payload[:-32]
            payload = loader_header(config, prepared) + payload
        try:
            child_header = struct.pack("<4I", len(payload), prepared.image.offset,
                                       prepared.image.kind, 0xFFFFFFFF)
        except struct.error as error:
            raise NuWriterError(f"Pack child exceeds the 32-bit format: {error}") from error
        children.append(child_header + payload)
    if config.mode == "SD":
        count, sizes = partition_settings(config)
        if count:
            if any(prepared.image.parameters.get("role") == "partition" for prepared in prepared_images):
                raise NuWriterError("Do not combine explicit partition images with storage.using_format")
            reserved = config.number("SD", "reserved_size", 1000)
            fields = [0, count, reserved, 0xFFFFFFFF]
            for size in sizes:
                fields.extend((size, size * 2048))
            payload = struct.pack("<12I", *fields)
            children.append(struct.pack("<4I", 48, 0xFFFFFFFF, 3, 0xFFFFFFFF) + payload)
    total = ((16 + sum(len(child) for child in children) + 0xFFFF) // 0x10000) * 0x10000
    if total > 0xFFFFFFFF:
        raise NuWriterError("Pack source size exceeds the 32-bit format")
    return struct.pack("<4I", 5, total, len(children), 0xFFFFFFFF) + b"".join(children)


def parse_pack(data):
    if len(data) < 16:
        raise NuWriterError("Pack header is truncated")
    action, allocation_length, count, reserved = struct.unpack_from("<4I", data)
    if action != 5 or not 0 < count <= (len(data) - 16) // 16:
        raise NuWriterError("Invalid NUC980 pack header")
    children = []
    position = 16
    for index in range(count):
        if position + 16 > len(data):
            raise NuWriterError(f"Pack child {index} header is truncated")
        header = data[position:position + 16]
        length, offset, kind, reserved = struct.unpack("<4I", header)
        position += 16
        if not length or position + length > len(data) or kind not in {0, 1, 2, 3, 4}:
            raise NuWriterError(f"Pack child {index} is invalid or truncated")
        children.append((header, data[position:position + length], kind))
        position += length
    if position != len(data):
        raise NuWriterError("Unexpected trailing data in NUC980 pack image")
    return children


def validate_pack(config, data):
    if config.operation == "program_verify":
        raise NuWriterError("Pack program_verify is unsupported; program individual images to verify")
    children = parse_pack(data)
    expected_ddr = None
    if config.ini.has_option("DDR", "ddr"):
        expected_ddr, name = load_ddr(config.ddr())
    for header, payload, kind in children:
        if kind == 3 and (config.mode != "SD" or len(payload) != 48):
            raise NuWriterError("Partition pack records require SD mode and a 48-byte payload")
        if kind == IMAGE_TYPES["loader"]:
            if len(payload) < 40 or payload[:4] != b" TVN":
                raise NuWriterError("Invalid Windows NuWriter loader header in pack")
            signature, count = struct.unpack_from("<II", payload, 32)
            ddr_end = 40 + count * 8
            if signature != 0xAA55AA55 or not count or ddr_end > len(payload):
                raise NuWriterError("Invalid or truncated loader DDR data in pack")
            if expected_ddr is not None and payload[40:ddr_end] != expected_ddr:
                raise NuWriterError("Pack DDR data does not match the selected DDR settings")
    return children


def load_xusb(path):
    image = Path(path).read_bytes()
    if len(image) <= 16:
        raise NuWriterError(f"XUSB image is truncated: {path}")
    signature, address, length, version = struct.unpack_from("<4I", image)
    if signature != 0xA55A4257 or address == 0xFFFFFFFF:
        raise NuWriterError(f"Invalid NUC980 XUSB image header: {path}")
    return address, image[16:]


def preflight(config):
    config.user_info()
    if config.compatible and config.byte_range is not None:
        start, length = config.byte_range
        unit = {"SPINOR": 0x10000, "SD": 512}.get(config.mode)
        if length is None and config.mode == "SPINOR":
            if not config.flash_size:
                raise NuWriterError("SPI NOR read-all requires --flash-size BYTES")
            length = config.flash_size
        if length is not None:
            if start + length > 0x100000000:
                raise NuWriterError("Range exceeds the NUC980 32-bit protocol")
            align_length = config.operation == "erase" or config.byte_range[1] is None
            if unit and (start % unit or (align_length and length % unit)):
                raise NuWriterError(f"{config.mode} start and length must be aligned to {unit} bytes")
    if config.compatible and config.mode in {"SPINOR", "SD"}:
        unit = 4096 if config.mode == "SPINOR" else 512
        if any(image.kind != 3 and image.offset % unit for image in config.images):
            raise NuWriterError(f"Write start must be aligned to {unit} bytes")
    if config.operation == "attach":
        prepared = []
    elif config.mode == "SDRAM":
        prepared = prepare_sdram(config)
    else:
        prepared = [prepare_image(config, image) for image in config.images]
        packed = [image for image in prepared if image.image.kind == 3 and image.image.parameters.get("role") != "partition"]
        if packed:
            if config.pack or len(prepared) != 1:
                raise NuWriterError("A pack input must be the only image and cannot be nested")
            validate_pack(config, packed[0].data)
    if config.mode == "SD" and (config.pack or config.operation == "format"):
        count, sizes = partition_settings(config)
        if config.operation == "format" and not count:
            raise NuWriterError("SD formatting requires using_format=yes")
    if not config.pack and config.initialize:
        data, name = load_ddr(config.ddr())
        load_xusb(config.xusb(name))
    if not config.pack:
        if config.operation == "read":
            config.text(config.mode, "read_path")
            if config.byte_range is None:
                config.number(config.mode, "read_start_blocks")
                if not config.number(config.mode, "read_offset_blocks"):
                    raise NuWriterError("Read block count must be nonzero")
        if config.operation == "erase" and config.byte_range is None and not config.yes(config.mode, "erase_all"):
            config.number(config.mode, "erase_start_blocks")
            if not config.number(config.mode, "erase_offset_blocks"):
                raise NuWriterError("Erase block count must be nonzero")
    return prepared


def run_pre_attach_hook():
    hook = Path(__file__).resolve().with_name("pre-attach-hook.py")
    if not hook.is_file():
        return
    print(f"Running pre-attach hook: {hook}", flush=True)
    result = subprocess.run([sys.executable, str(hook)], cwd=str(hook.parent), check=False)
    if result.returncode != 0:
        raise NuWriterError(f"Pre-attach hook failed with exit code {result.returncode}")


def discover_devices():
    try:
        core = importlib.import_module("usb.core")
    except ModuleNotFoundError as error:
        raise NuWriterError("PyUSB is required for USB operations; install requirements.txt") from error
    return list(core.find(idVendor=USB_VENDOR_ID, idProduct=USB_PRODUCT_ID, find_all=True))


def device_path(device):
    bus, ports = UsbSession.device_identity(device)
    return f"{bus}:" + ".".join(str(port) for port in ports)


def select_devices(devices, all_devices=False, selection=None):
    if all_devices and selection:
        raise NuWriterError("--device cannot be combined with all_device=yes")
    devices = sorted(devices, key=UsbSession.device_identity)
    if selection:
        devices = [device for device in devices if device_path(device) == selection]
    if not devices:
        raise NuWriterError("Device not found")
    if not all_devices and len(devices) != 1:
        raise NuWriterError("Multiple devices found; use --device BUS:PORT or all_device=yes")
    if all_devices and len(devices) > 8:
        raise NuWriterError("At most 8 devices are supported in one operation")
    return devices if all_devices else devices[:1]


class UsbSession:
    def __init__(self, device, timeout, trace=False):
        self.core = importlib.import_module("usb.core")
        self.util = importlib.import_module("usb.util")
        self.timeout = timeout
        self.trace = trace
        self.identity = self.device_identity(device)
        self.device = None
        self.detached = False
        self.transport = self.open(device)

    @staticmethod
    def device_identity(device):
        ports = tuple(device.port_numbers or ())
        return device.bus, ports if ports else (0, device.address)

    def open(self, device):
        self.device = device
        try:
            try:
                if device.is_kernel_driver_active(0):
                    device.detach_kernel_driver(0)
                    self.detached = True
            except NotImplementedError:
                pass
            try:
                configuration = device.get_active_configuration()
            except self.core.USBError as error:
                if error.errno is not None:
                    raise
                device.set_configuration()
                configuration = device.get_active_configuration()
            interface = configuration[(0, 0)]
            endpoints = {endpoint.bEndpointAddress for endpoint in interface}
            if not {0x02, 0x81}.issubset(endpoints):
                raise NuWriterError("USB endpoints do not match NUC980; refusing to send its protocol")
            self.util.claim_interface(device, 0)
        except Exception:
            self.close()
            raise
        self.transport = UsbTransport(device, self.timeout, trace=self.trace)
        return self.transport

    def close(self):
        if self.device is None:
            return
        try:
            try:
                self.util.release_interface(self.device, 0)
                if self.detached:
                    self.device.attach_kernel_driver(0)
            except (self.core.USBError, NotImplementedError):
                pass
        finally:
            try:
                self.util.dispose_resources(self.device)
            except self.core.USBError:
                pass
            finally:
                self.device = None
                self.detached = False

    def reconnect(self):
        self.close()
        deadline = time.monotonic() + self.timeout / 1000
        time.sleep(1)
        while time.monotonic() < deadline:
            devices = self.core.find(idVendor=USB_VENDOR_ID, idProduct=USB_PRODUCT_ID, find_all=True)
            for device in devices:
                if self.device_identity(device) == self.identity:
                    return self.open(device)
            time.sleep(0.1)
        raise NuWriterError("Timed out waiting for XUSB to reconnect at the same USB port")


class Nuc980Writer:
    def __init__(self, config, transport, reconnect=None, operation_timeout=300000):
        self.config = config
        self.transport = transport
        self.reconnect = reconnect
        self.operation_timeout = operation_timeout
        self.info = {}

    def attach(self):
        data, xusb_name = load_ddr(self.config.ddr())
        self.transport.write(struct.pack("<II", len(data), 16))
        self.transport.write(data)
        state = self.transport.read_word()
        if state != TRANSFER_SIZE + 1:
            self.transport.expect(ACK)
            address, payload = load_xusb(self.config.xusb(xusb_name))
            self.transport.write(struct.pack("<II", len(payload), address))
            self.transport.send_chunks(payload)
            if self.reconnect:
                self.transport = self.reconnect()
        return self.get_info()

    def get_info(self):
        self.transport.set_type(10)
        self.transport.write(self.config.user_info())
        self.info = dict(zip(INFO_FIELDS, INFO_STRUCT.unpack(self.transport.read(INFO_STRUCT.size))))
        self.transport.expect(0x90)
        if self.config.mode == "NAND":
            if self.config.yes("NAND", "using_user_defined"):
                self.info["nand_block_count"] = self.config.number("NAND", "blockperflash")
                self.info["nand_page_per_block"] = self.config.number("NAND", "pageperblock")
            elif self.info["nand_block_count"] in {1023, 2047, 4095, 8191}:
                self.info["nand_block_count"] += 1
        return self.info

    def block_size(self):
        if self.config.mode in {"NAND", "SPINAND"}:
            prefix = "nand" if self.config.mode == "NAND" else "spinand"
            size = self.info.get(prefix + "_page_size", 0) * self.info.get(prefix + "_page_per_block", 0)
        else:
            size = 512 if self.config.mode == "SD" else 0x10000
        if not size:
            raise NuWriterError("Device did not report a usable flash block size")
        return size

    def capacity(self):
        mode = self.config.mode
        if mode == "SD":
            return self.info.get("emmc_blocks", 0) * 512
        if mode in {"NAND", "SPINAND"}:
            prefix = "nand" if mode == "NAND" else "spinand"
            blocks = self.info.get(prefix + "_block_count", 0)
            if mode == "SPINAND" and self.info.get("spinand_die", 0) == 1:
                blocks *= 2
            return blocks * self.block_size()
        return self.config.flash_size or 0

    def resolve_byte_range(self):
        start, length = self.config.byte_range
        unit = self.block_size()
        capacity = self.capacity()
        if length is None:
            if not capacity:
                raise NuWriterError("Read-all needs reported capacity; for SPI NOR supply --flash-size BYTES")
            length = capacity
        if not 0 < length <= 0xFFFFFFFF or start + length > 0x100000000:
            raise NuWriterError("Range exceeds the NUC980 32-bit protocol")
        if start % unit or (self.config.operation == "erase" and length % unit):
            raise NuWriterError(f"{self.config.mode} {self.config.operation} start and length must be aligned to {unit} bytes")
        if capacity and start + length > capacity:
            raise NuWriterError("Requested range exceeds reported/configured storage capacity")
        section = self.config.mode
        if self.config.operation == "read":
            self.config.byte_range = (start, length)
            self.config.ini.set(section, "read_start_blocks", str(start // unit))
            if length % unit == 0:
                self.config.ini.set(section, "read_offset_blocks", str(length // unit))
        else:
            self.config.ini.set(section, "erase_all", "no")
            self.config.ini.set(section, "erase_start_blocks", str(start // unit))
            self.config.ini.set(section, "erase_offset_blocks", str(length // unit))

    def validate_write(self, prepared):
        unit = 4096 if self.config.mode == "SPINOR" else self.block_size()
        capacity = self.capacity()
        if prepared.image.kind == 3:
            ranges = []
            for header, payload, kind in parse_pack(prepared.data):
                if kind != 3:
                    length, offset, image_type, reserved = struct.unpack("<4I", header)
                    ranges.append((offset, length))
        else:
            ranges = [(prepared.image.offset, len(prepared.data))]
        for offset, length in ranges:
            if offset % unit:
                raise NuWriterError(f"Write start must be aligned to {unit} bytes")
            if offset + length > 0x100000000:
                raise NuWriterError("Write exceeds the NUC980 32-bit address range")
            if capacity and offset + length > capacity:
                raise NuWriterError("Write exceeds reported storage capacity")

    def command(self, header):
        self.transport.set_type(MEDIA[self.config.mode])
        self.transport.write(header)
        self.transport.read_word()

    def header(self, action, **values):
        if self.config.mode == "SD":
            return mmc_header(action, **values)
        return storage_header(action, **values)

    def program(self, prepared):
        image = prepared.image
        execute = image.execute
        offset = image.offset
        number = 1 if image.kind == IMAGE_TYPES["loader"] else 0
        values = dict(file_length=prepared.file_length, kind=image.kind, execute=execute,
                      offset=offset, init_size=prepared.init_size, number=number)
        self.command(self.header(0, **values))
        with TransferProgress(f"{self.config.mode} program", len(prepared.data)) as progress:
            for position in range(0, len(prepared.data), TRANSFER_SIZE):
                chunk = prepared.data[position:position + TRANSFER_SIZE]
                self.transport.write(chunk)
                self.transport.expect(len(chunk))
                if self.config.mode == "SPINOR" and image.kind != 2 and (position + len(chunk)) % 0x10000 == 0:
                    self.transport.read_word()
                progress.update(position + len(chunk))
            if self.config.mode == "SPINOR":
                if image.kind == 2:
                    self.wait_progress()
                elif len(prepared.data) % 0x10000:
                    self.transport.read_word()
            else:
                self.transport.read_word()
            if self.config.operation == "program_verify":
                self.command(self.header(3, **values))
                expected = prepared.data[prepared.init_size:]
                if image.kind == 2 and self.config.mode == "SD":
                    expected = expected[:-32]
                self.verify_data(expected)
            progress.complete()

    def verify_data(self, expected):
        for offset in range(0, len(expected), TRANSFER_SIZE):
            length = min(TRANSFER_SIZE, len(expected) - offset)
            actual = self.transport.read(TRANSFER_SIZE, minimum=length)
            matches = actual[:length] == expected[offset:offset + length]
            self.transport.write(struct.pack("<I", TRANSFER_SIZE if matches else 0))
            if not matches:
                raise NuWriterError(f"Verification failed at image offset 0x{offset:x}")

    def read_flash(self):
        config = self.config
        block_size = self.block_size()
        if config.byte_range is None:
            start = config.number(config.mode, "read_start_blocks")
            length = config.number(config.mode, "read_offset_blocks") * block_size
            byte_start = start * block_size
        else:
            byte_start, length = config.byte_range
            if length is None:
                length = self.capacity()
        if not length:
            raise NuWriterError("Read length must be nonzero")
        offset = byte_start // block_size if config.mode in {"NAND", "SPINAND"} else byte_start
        header = self.header(4, file_length=length, offset=offset)
        path = Path(config.text(config.mode, "read_path"))
        with path.open("wb") as output:
            self.command(header)
            remaining = length
            while remaining:
                count = min(remaining, TRANSFER_SIZE)
                read_size = count if config.mode in {"NAND", "SPINOR"} else TRANSFER_SIZE
                data = self.transport.read(read_size, minimum=count)
                output.write(data[:count])
                self.transport.write(struct.pack("<I", TRANSFER_SIZE))
                remaining -= count

    def read_erase_word(self, stage, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise NuWriterError(f"Timed out waiting for {stage}")
        timeout = max(1, int(remaining * 1000))
        try:
            return self.transport.read_word(timeout=timeout)
        except (OSError, NuWriterError) as error:
            raise NuWriterError(f"{stage} failed while waiting up to {timeout} ms: {error}") from error

    def wait_progress(self, block_count=None, deadline=None):
        if block_count is not None and not block_count:
            raise NuWriterError("Device reported zero erase blocks")
        operation_deadline = time.monotonic() + self.operation_timeout / 1000 if deadline is None else deadline
        last_status = None
        while time.monotonic() < operation_deadline:
            if deadline is None:
                status = self.transport.read_word()
            else:
                stage = f"{self.config.mode} erase progress (last status={last_status})"
                status = self.read_erase_word(stage, operation_deadline)
            last_status = status
            if block_count is not None:
                if status >= block_count:
                    raise NuWriterError(f"Invalid erase block status: {status}/{block_count}")
                if status == block_count - 1:
                    return
            else:
                if status >> 16 or status > 100:
                    raise NuWriterError(f"Device operation failed: 0x{status:08x}")
                if status == 100:
                    return
        raise NuWriterError(f"Timed out waiting for device operation to finish (last status={last_status})")

    def erase(self):
        config = self.config
        erase_all = config.yes(config.mode, "erase_all")
        start = 0 if erase_all else config.number(config.mode, "erase_start_blocks")
        count = 0xFFFFFFFF if erase_all else config.number(config.mode, "erase_offset_blocks")
        if config.mode in {"NAND", "SPINAND"} and erase_all:
            prefix = "nand" if config.mode == "NAND" else "spinand"
            count = self.info.get(prefix + "_block_count", 0)
            if config.mode == "SPINAND" and self.info.get("spinand_die", 0) == 1:
                count *= 2
        if not count:
            raise NuWriterError("Erase block count must be nonzero")
        number = 0xFFFFFFFF if config.mode in {"NAND", "SPINAND"} or erase_all else 0
        header = self.header(2, kind=0 if erase_all else 1, execute=count, offset=start, number=number)
        deadline = time.monotonic() + self.operation_timeout / 1000
        stage = "media selection"
        try:
            self.transport.set_type(MEDIA[config.mode])
            stage = "command transmission"
            self.transport.write(header)
        except (OSError, NuWriterError) as error:
            raise NuWriterError(f"{config.mode} erase {stage} failed: {error}") from error
        print(f"{config.mode} erase request sent: start block={start}, count={count}, timeout={self.operation_timeout} ms")
        acknowledgement = self.read_erase_word(f"{config.mode} erase command acknowledgement", deadline)
        if config.mode == "SPINAND" and acknowledgement != 0x89:
            raise NuWriterError(f"Unexpected SPI NAND erase ACK: 0x{acknowledgement:08x}, expected 0x00000089")
        blocks = self.read_erase_word("SPINAND erase block count", deadline) if config.mode == "SPINAND" else None
        if blocks is not None:
            if blocks != count:
                raise NuWriterError(f"SPI NAND erase block-count mismatch: received {blocks}, expected {count}")
            print(f"SPINAND erase block count: {blocks}; waiting for progress")
        self.wait_progress(blocks if erase_all else None, deadline=deadline)

    def format_sd(self):
        count, sizes = partition_settings(self.config)
        if not count:
            raise NuWriterError("SD formatting requires using_format=yes")
        reserved = self.config.number("SD", "reserved_size", 1000)
        capacity = self.info["emmc_blocks"] // 2048
        sizes = list(sizes)
        sizes[count - 1] = capacity - reserved - sum(sizes[:count - 1])
        if sizes[count - 1] <= 0 or any(size <= 0 for size in sizes[:count]):
            raise NuWriterError("SD partitions and reserved space do not fit the reported capacity")
        self.command(mmc_header(6, reserved=reserved * 2048, partition_count=count, sizes=sizes))
        self.wait_progress()

    def download_sdram(self, prepared):
        data, address, execute, dtb_data, dtb_address = prepared
        if dtb_data:
            print(f"Downloading DTB: {len(dtb_data)} bytes at 0x{dtb_address:08x}", flush=True)
            self.download(dtb_data, dtb_address, False, 0)
            print("DTB download complete", flush=True)
        dtb_parameter = dtb_address | 0x80000000 if dtb_data and execute else 0
        print(f"Downloading SDRAM image: {len(data)} bytes at 0x{address:08x}, execute={execute}", flush=True)
        self.download(data, address, execute, dtb_parameter)

    def download(self, data, address, execute, dtb_address):
        header = struct.pack("<4I", 0, len(data), address | (0x80000000 if execute else 0), dtb_address)
        stage = "media selection"
        try:
            self.transport.set_type(MEDIA["SDRAM"])
            stage = "16-byte header transmission"
            self.transport.write(header)
            stage = "header acknowledgement"
            acknowledgement = self.transport.read_word()
            if acknowledgement != 0x80:
                raise NuWriterError(f"Unexpected SDRAM ACK: 0x{acknowledgement:08x}, expected 0x00000080")
            with TransferProgress(f"SDRAM download 0x{address:08x}", len(data)) as progress:
                for position in range(0, len(data), TRANSFER_SIZE):
                    chunk = data[position:position + TRANSFER_SIZE]
                    stage = f"data transmission at offset 0x{position:x} ({len(chunk)} bytes)"
                    self.transport.write(chunk)
                    stage = f"data acknowledgement at offset 0x{position:x} ({len(chunk)} bytes)"
                    self.transport.expect(len(chunk))
                    progress.update(position + len(chunk))
                progress.complete()
        except (OSError, NuWriterError) as error:
            raise NuWriterError(f"SDRAM download at 0x{address:08x}: {stage} failed: {error}") from error

    def program_pack(self, prepared):
        data = prepared.data
        children = validate_pack(self.config, data)
        self.command(self.header(5, file_length=len(data), kind=3))
        self.transport.write(data[:16])
        self.transport.read_word()
        total = sum(len(payload) for header, payload, kind in children)
        completed = 0
        with TransferProgress(f"{self.config.mode} pack program", total) as progress:
            for header, payload, kind in children:
                self.transport.write(header)
                if self.config.mode in {"NAND", "SD", "SPINAND"}:
                    self.transport.read_word()
                for position in range(0, len(payload), TRANSFER_SIZE):
                    chunk = payload[position:position + TRANSFER_SIZE]
                    self.transport.write(chunk)
                    self.transport.read_word()
                    if self.config.mode == "SPINOR" and len(chunk) == TRANSFER_SIZE and (position + len(chunk)) % 0x10000 == 0:
                        self.transport.read_word()
                    completed += len(chunk)
                    progress.update(completed)
                if self.config.mode in {"NAND", "SD", "SPINAND"}:
                    self.transport.read_word()
                elif self.config.mode == "SPINOR" and len(payload) % 0x10000:
                    self.wait_progress()
            progress.complete()

    def run(self, prepared):
        if self.config.operation == "attach":
            return
        if self.config.byte_range is not None:
            self.resolve_byte_range()
        if self.config.compatible and self.config.mode != "SDRAM":
            for image in prepared:
                self.validate_write(image)
        if self.config.mode == "SDRAM":
            self.download_sdram(prepared)
        elif self.config.operation == "read":
            self.read_flash()
        elif self.config.operation == "erase":
            self.erase()
        elif self.config.operation == "format":
            self.format_sd()
        else:
            for index, image in enumerate(prepared):
                print(f"Image {index}: {image.image.path}")
                if image.image.kind == 3:
                    self.program_pack(image)
                else:
                    self.program(image)
                print(f"Image {index}: passed")


def cli_number(value, label):
    try:
        number = value if type(value) is int else int(value, 0)
    except (TypeError, ValueError) as error:
        raise NuWriterError(f"Invalid {label}: {value}") from error
    if not 0 <= number <= 0xFFFFFFFF:
        raise NuWriterError(f"{label} is outside the NUC980 32-bit unsigned range")
    return number


def pack_config_from_arguments(args, document=None):
    if not args.config and document is None:
        raise NuWriterError("--pack requires a NUC980 INI or JSON configuration")
    if args.attach or args.massproduct or args.device or args.option or args.type or args.exec_addr or args.flash_size:
        raise NuWriterError("Pack generation is offline; attach/device/write options are not supported")
    path = Path(args.config) if args.config else None
    if document is None and path.suffix.lower() != ".json":
        if args.ddr:
            raise NuWriterError("For INI pack generation, specify DDR settings inside the INI")
        config = RunConfig(path, args.resource_dir, pack_override=True)
        config.operation = "program"
        selected_mode = args.media.upper() if args.media else config.mode
        selected_mode = "SD" if selected_mode == "EMMC" else selected_mode
        if selected_mode != config.mode:
            raise NuWriterError("--media conflicts with the INI mode")
        if args.output:
            config.ini.set("RUN", "pack_path", str(args.output))
        return config
    if document is None:
        with path.open(encoding="utf-8-sig") as source:
            document = json.load(source)
    if not isinstance(document, dict) or not isinstance(document.get("image"), list):
        raise NuWriterError("Pack JSON must be an object containing an image array")
    selected_mode = args.media or document.get("mode", document.get("media"))
    if not isinstance(selected_mode, str):
        raise NuWriterError("Pack JSON requires mode or --media (NAND/SPINAND/SPINOR/SD/EMMC)")
    mode = selected_mode.upper()
    mode = "SD" if mode == "EMMC" else mode
    if mode not in {"NAND", "SPINAND", "SPINOR", "SD"}:
        raise NuWriterError(f"Unsupported pack media: {mode}")
    declared_mode = document.get("mode")
    if declared_mode is not None:
        if not isinstance(declared_mode, str):
            raise NuWriterError("Pack JSON mode must be a string")
        declared_mode = declared_mode.upper()
        declared_mode = "SD" if declared_mode == "EMMC" else declared_mode
        if declared_mode != mode:
            raise NuWriterError("--media conflicts with the JSON mode")
    if "media" in document:
        declared_media = document["media"]
        if not isinstance(declared_media, str):
            raise NuWriterError("Pack JSON media must be a string")
        declared_media = declared_media.upper()
        declared_media = "SD" if declared_media == "EMMC" else declared_media
        if declared_media != mode:
            raise NuWriterError("Pack JSON media/mode or --media conflict")
    output = args.output or document.get("output", "pack.bin")
    if not isinstance(output, (str, Path)) or not str(output).strip():
        raise NuWriterError("Pack output must be a filename")
    storage = document.get("storage", {})
    if not isinstance(storage, dict):
        raise NuWriterError("Pack JSON storage must be an object")
    allowed_storage = {"using_user_defined", "blockperflash", "pageperblock", "page_size", "spare_area",
                       "quad_read_command", "read_status_command", "write_status_command", "status_value",
                       "dummy_bytes", "pageperflash", "multichip", "reserved_size", "using_format",
                       "partition_num", "partition1_size", "partition2_size", "partition3_size"}
    if not set(storage).issubset(allowed_storage):
        raise NuWriterError("Pack JSON contains unsupported storage settings")
    values = {}
    for key, value in storage.items():
        if type(value) is bool:
            values[key] = "yes" if value else "no"
        elif type(value) in {str, int}:
            values[key] = str(value)
        else:
            raise NuWriterError(f"Invalid storage setting: {key}")
    values.update(run="program", image_num=str(len(document["image"])))
    settings = {"RUN": {"mode": mode, "pack": "yes", "pack_path": str(output)}, mode: values}
    ddr_name = args.ddr or document.get("ddr")
    if ddr_name is not None:
        if not isinstance(ddr_name, str) or not ddr_name.strip():
            raise NuWriterError("Pack DDR settings must be a filename")
        ddr = Path(ddr_name)
        settings["DDR"] = {"ddr": str(ddr.resolve()) if ddr.is_file() else str(ddr)}
    named_types = {"data": "data", "linux": "data", "env": "env", "environment": "env",
                   "loader": "loader", "uboot": "loader", "partition": "partition"}
    numbered_types = {0: "data", 2: "loader", 3: "data"}
    image_parameters = []
    loader_fields = {"page_size": "page_size", "spare_area": "spare_area",
                     "quad_read_cmd": "quad_read_command", "read_status_cmd": "read_status_command",
                     "write_status_cmd": "write_status_command", "status_value": "status_value",
                     "dummy_byte": "dummy_bytes"}
    for index, image in enumerate(document["image"]):
        if not isinstance(image, dict):
            raise NuWriterError(f"Pack image {index} must be an object")
        image_type = image.get("type", 0)
        if isinstance(image_type, str):
            kind = named_types.get(image_type.lower())
        elif type(image_type) is int:
            kind = numbered_types.get(image_type)
        else:
            kind = None
        if kind is None:
            raise NuWriterError(f"Unsupported MA35 image type {image_type}; TFA/DDR/TEE are not NUC980 images")
        filename = image.get("file")
        if kind != "partition" and (not isinstance(filename, str) or not filename.strip()):
            raise NuWriterError(f"Pack image {index} requires a file")
        if filename is not None and (not isinstance(filename, str) or not filename.strip()):
            raise NuWriterError(f"Invalid pack image {index} filename")
        if kind == "partition" and mode != "SD":
            raise NuWriterError("Partition records are supported only for SD/eMMC packs")
        if "offset" in image and "address" in image and cli_number(image["offset"], "offset") != cli_number(image["address"], "address"):
            raise NuWriterError(f"Image {index} offset/address conflict")
        default_offset = "0xffffffff" if kind == "partition" else "0"
        offset = cli_number(image.get("offset", image.get("address", default_offset)), f"image {index} offset")
        if kind == "partition" and offset != 0xFFFFFFFF:
            raise NuWriterError("Partition record offset must be 0xffffffff")
        if "exec_addr" in image and "execute_address" in image and cli_number(image["exec_addr"], "exec_addr") != cli_number(image["execute_address"], "execute_address"):
            raise NuWriterError(f"Image {index} execution-address aliases conflict")
        execute = cli_number(image.get("exec_addr", image.get("execute_address", "0x200" if kind == "loader" else "0")), f"image {index} execution address")
        parameters = {}
        if kind == "partition":
            parameters["role"] = "partition"
            if "partition" in image:
                parameters["partition"] = image["partition"]
        if "env_size" in image:
            if kind != "env":
                raise NuWriterError("env_size is supported only for environment images")
            parameters["env_size"] = cli_number(image["env_size"], f"image {index} environment size")
        if kind == "loader":
            image_ddr = image.get("ddr", image.get("ddr_ini", ddr_name))
            if not isinstance(image_ddr, str) or not image_ddr.strip():
                raise NuWriterError("JSON loader images require DDR settings")
            if "ddr" in image and "ddr_ini" in image and image["ddr"] != image["ddr_ini"]:
                raise NuWriterError(f"Image {index} DDR aliases conflict")
            parameters["ddr_ini"] = image_ddr
            for parameter, native_key in loader_fields.items():
                if parameter != native_key and parameter in image and native_key in image:
                    if cli_number(image[parameter], parameter) != cli_number(image[native_key], native_key):
                        raise NuWriterError(f"Image {index} {parameter}/{native_key} conflict")
                if parameter in image:
                    value = image[parameter]
                elif native_key in image:
                    value = image[native_key]
                elif native_key in storage:
                    value = storage[native_key]
                else:
                    value = 2048 if parameter == "page_size" else 64 if parameter == "spare_area" else 0xFF
                parameters[parameter] = cli_number(value, f"image {index} {parameter}")
            if mode in {"SPINOR", "SPINAND"}:
                required = {"quad_read_command", "read_status_command", "write_status_command", "status_value", "dummy_bytes"}
                if mode == "SPINAND":
                    required |= {"page_size", "spare_area"}
                supplied = set(storage) | set(image) | {native for parameter, native in loader_fields.items() if parameter in image}
                if not required.issubset(supplied):
                    raise NuWriterError("JSON SPI loader images require explicit storage command/page settings")
        image_parameters.append(parameters)
        prefix = f"image{index}_"
        values.update({prefix + "type": kind,
                       prefix + "start_offset": str(offset), prefix + "exe_addr": str(execute)})
        if filename is not None:
            values[prefix + "path"] = filename
    config = RunConfig(path, args.resource_dir, settings=settings)
    for image, parameters in zip(config.images, image_parameters):
        image.parameters = parameters
    return config


def pack_output_path(config):
    output = Path(config.text("RUN", "pack_path"))
    inputs = {image.path.resolve() for image in config.images if image.path is not None}
    if config.filename is not None:
        inputs.add(config.filename.resolve())
    if config.ini.has_option("DDR", "ddr"):
        inputs.add(config.ddr().resolve())
    for image in config.images:
        if "ddr_ini" in image.parameters:
            inputs.add(ddr_input_path(config, image.parameters["ddr_ini"]).resolve())
    if output.resolve() in inputs:
        raise NuWriterError("Pack output cannot overwrite its configuration or source images/DDR settings")
    return output


def create_pack_file(images, output_path, media=DEV_SPINAND, ddr_ini=None, storage=None, resource_dir=None):
    args = argparse.Namespace(config=None, attach=False, massproduct=False, device=None, option=None,
                              type=None, exec_addr=None, flash_size=None, media=_api_media_name(media),
                              output=Path(output_path), ddr=str(ddr_ini) if ddr_ini is not None else None, resource_dir=resource_dir)
    normalized = []
    if not isinstance(images, list):
        raise NuWriterError("Pack images must be a list")
    for image in images:
        if not isinstance(image, dict):
            raise NuWriterError("Pack images must contain objects")
        image = dict(image)
        for key in ("file", "ddr", "ddr_ini"):
            if isinstance(image.get(key), Path):
                image[key] = str(image[key])
        normalized.append(image)
    document = {"image": normalized, "storage": {} if storage is None else storage}
    config = pack_config_from_arguments(args, document=document)
    output = pack_output_path(config)
    output.write_bytes(build_pack(config, preflight(config)))
    return output


def config_from_arguments(args):
    if (args.dtb is None) != (args.dtb_addr is None):
        raise NuWriterError("--dtb and --dtb-addr must be supplied together")
    if args.dtb is not None and not args.write:
        raise NuWriterError("DTB options require a DDR/SRAM write")
    if args.bootargs is not None and args.dtb is None:
        raise NuWriterError("--bootargs requires --dtb and --dtb-addr")
    if args.convert or args.storage:
        raise NuWriterError("MA35 convert/MSC operations are not supported by the NUC980 backend")
    if args.pack:
        return pack_config_from_arguments(args)
    if args.media or args.output:
        raise NuWriterError("--media and --output are supported only for pack generation")
    if not any((args.attach, args.write, args.read, args.erase)):
        if args.option or args.type or args.ddr or args.exec_addr or args.flash_size:
            raise NuWriterError("These options require a compatible attach/read/write/erase command")
        config = RunConfig(args.config, args.resource_dir)
        if args.massproduct:
            if config.pack or config.operation == "read":
                raise NuWriterError("--massproduct supports hardware operations other than reads")
            config.all_devices = True
        return config
    arguments = args.write or args.read or args.erase
    aliases = {"DDR": "SDRAM", "SRAM": "SDRAM", "EMMC": "SD"}
    media = arguments[0].upper() if arguments else "SDRAM"
    mode = aliases.get(media, media)
    if mode not in MEDIA:
        raise NuWriterError(f"Unsupported NUC980 media: {media}; OTP/REG/USBD are not supported")
    if args.dtb is not None and mode != "SDRAM":
        raise NuWriterError("DTB options are supported only for DDR/SRAM writes")
    option = args.option[0].lower() if args.option else None
    if option not in {None, "verify", "execute"}:
        raise NuWriterError(f"Unsupported NUC980 option: {option}")
    if option and not args.write:
        raise NuWriterError("verify/execute options require --write")
    if args.type and not args.write:
        raise NuWriterError("--type requires a single-image flash write")
    if args.exec_addr and not args.write:
        raise NuWriterError("--exec-addr requires a single-image flash write")
    if args.ddr and args.config:
        raise NuWriterError("Specify DDR settings either as CONFIG or --ddr, not both")
    ddr_name = args.ddr or args.config
    if args.attach and not ddr_name:
        raise NuWriterError("--attach requires NUC980 DDR settings as CONFIG or --ddr")
    settings = {"RUN": {"mode": mode, "all_device": "yes" if args.massproduct else "no"}, mode: {}}
    if ddr_name:
        ddr = Path(ddr_name)
        settings["DDR"] = {"ddr": str(ddr.resolve()) if ddr.is_file() else str(ddr)}
    values = settings[mode]
    byte_range = None
    operation = "attach"
    if args.write:
        if len(arguments) not in {2, 3}:
            raise NuWriterError("Use -w MEDIA START FILE or -w MEDIA PACK_FILE")
        if mode == "SDRAM":
            if len(arguments) != 3 or option == "verify" or args.type or args.exec_addr:
                raise NuWriterError("Use -w ddr START FILE [-o execute]; SRAM/DDR readback verification is unsupported")
            values.update(sdram_path=arguments[2], exe_addr=str(cli_number(arguments[1], "write start")),
                          option="run" if option == "execute" else "download")
            if args.dtb is not None:
                values.update(using_dtb="yes", dtb_path=str(args.dtb),
                              dtb_addr=str(cli_number(args.dtb_addr, "DTB address")))
            if args.bootargs is not None:
                values["bootargs"] = args.bootargs
            operation = "download"
        else:
            if option == "execute":
                raise NuWriterError("execute is supported only for DDR/SRAM writes")
            operation = "program_verify" if option == "verify" else "program"
            if len(arguments) == 2:
                if args.type or args.exec_addr:
                    raise NuWriterError("Pack writes do not support --type or --exec-addr")
                kind, start, execute, filename = "pack", 0, 0, arguments[1]
            else:
                types = {"data": "data", "linux": "data", "env": "env", "loader": "loader", "uboot": "loader"}
                requested_type = args.type[0].lower() if args.type else "data"
                if requested_type not in types:
                    raise NuWriterError(f"Unsupported NUC980 image type: {requested_type}")
                kind = types[requested_type]
                start = cli_number(arguments[1], "write start")
                execute = cli_number(args.exec_addr, "loader execution address") if args.exec_addr else 0
                if kind == "loader":
                    if args.exec_addr is None or not ddr_name:
                        raise NuWriterError("Loader writes require --exec-addr and DDR settings (CONFIG or --ddr)")
                    if start != (0x400 if mode == "SD" else 0):
                        raise NuWriterError("Loader start must be 0x400 for SD/eMMC, or 0 for flash")
                filename = arguments[2]
            values.update(run=operation, image_num="1", image0_type=kind, image0_path=filename,
                          image0_start_offset=str(start), image0_exe_addr=str(execute))
    elif args.read:
        if mode == "SDRAM" or len(arguments) not in {3, 4}:
            raise NuWriterError("Use -r MEDIA START LENGTH FILE or -r MEDIA all FILE; DDR/SRAM reads are unsupported")
        if args.massproduct:
            raise NuWriterError("Read operations require one target; --massproduct is unsupported for reads")
        if len(arguments) == 3 and arguments[1].lower() == "all":
            byte_range, filename = (0, None), arguments[2]
        elif len(arguments) == 4:
            byte_range = (cli_number(arguments[1], "read start"), cli_number(arguments[2], "read length"))
            if not byte_range[1]:
                raise NuWriterError("Read length must be nonzero")
            filename = arguments[3]
        else:
            raise NuWriterError("Use -r MEDIA all FILE")
        operation = "read"
        values.update(run=operation, read_path=filename, read_start_blocks="0", read_offset_blocks="1")
    elif args.erase:
        if mode in {"SD", "SDRAM"} or len(arguments) not in {2, 3}:
            raise NuWriterError("Erase supports only NAND/SPINAND/SPINOR: -e MEDIA all or -e MEDIA START LENGTH")
        operation = "erase"
        if len(arguments) == 2 and arguments[1].lower() == "all":
            values.update(run=operation, erase_all="yes")
        elif len(arguments) == 3:
            byte_range = (cli_number(arguments[1], "erase start"), cli_number(arguments[2], "erase length"))
            if not byte_range[1]:
                raise NuWriterError("Erase length must be nonzero")
            values.update(run=operation, erase_all="no", erase_start_blocks="0", erase_offset_blocks="1")
        else:
            raise NuWriterError("Use -e MEDIA all")
    if args.flash_size and not (args.read and byte_range[1] is None and mode == "SPINOR"):
        raise NuWriterError("--flash-size is supported only for -r spinor all FILE")
    config = RunConfig(ddr_name, args.resource_dir, settings=settings)
    config.initialize = args.attach
    config.compatible = True
    config.operation = operation
    config.byte_range = byte_range
    config.flash_size = cli_number(args.flash_size, "SPI NOR capacity") if args.flash_size else None
    return config


def get_media(media):
    return {"DDR": DEV_DDR_SRAM, "SRAM": DEV_DDR_SRAM, "SDRAM": DEV_DDR_SRAM,
            "NAND": DEV_NAND, "EMMC": DEV_EMMC, "SD": DEV_SD,
            "SPINOR": DEV_SPINOR, "SPINAND": DEV_SPINAND}.get(str(media).upper(), DEV_UNKNOWN)


def get_option(option):
    if option is None:
        return OPT_NONE
    if type(option) is int:
        return option if option in {OPT_NONE, OPT_VERIFY, OPT_EXECUTE} else OPT_UNKNOWN
    return {"NONE": OPT_NONE, "VERIFY": OPT_VERIFY, "EXECUTE": OPT_EXECUTE}.get(str(option).upper(), OPT_UNKNOWN)


def get_type(image_type):
    return {"DATA": IMG_DATA, "UBOOT": IMG_UBOOT, "LOADER": IMG_UBOOT,
            "LINUX": IMG_LINUX}.get(str(image_type).upper(), IMG_UNKNOWN)


def switch_mp_mode(flag):
    global mp_mode
    mp_mode = bool(flag)


def _api_media_name(media):
    value = get_media(media) if isinstance(media, str) else media
    names = {DEV_DDR_SRAM: "ddr", DEV_NAND: "nand", DEV_EMMC: "emmc",
             DEV_SD: "sd", DEV_SPINOR: "spinor", DEV_SPINAND: "spinand"}
    if type(value) is not int or value not in names:
        raise NuWriterError(f"Unsupported NUC980 API media: {media}")
    return names[value]


def _api_option_arguments(option, write=False):
    value = get_option(option)
    if value == OPT_NONE:
        return []
    if write and value in {OPT_VERIFY, OPT_EXECUTE}:
        return ["-o", "verify" if value == OPT_VERIFY else "execute"]
    raise NuWriterError(f"Unsupported option for this NUC980 API operation: {option}")


def _run_api(arguments, **settings):
    arguments = list(arguments)
    flags = {"ddr": "--ddr", "device": "--device", "resource_dir": "--resource-dir",
             "exec_addr": "--exec-addr", "image_type": "--type", "media": "--media",
             "output": "--output", "flash_size": "--flash-size", "timeout": "--timeout",
             "operation_timeout": "--operation-timeout", "dtb": "--dtb", "dtb_addr": "--dtb-addr",
             "bootargs": "--bootargs"}
    allowed = set(flags) | {"initialize", "check", "massproduct", "trace_usb"}
    if set(settings) - allowed:
        raise NuWriterError(f"Unknown API settings: {', '.join(sorted(set(settings) - allowed))}")
    if settings.get("initialize") and "-a" not in arguments:
        arguments.append("-a")
    if settings.get("check"):
        arguments.append("--check")
    if settings.get("trace_usb"):
        arguments.append("--trace-usb")
    default_massproduct = mp_mode if arguments[0] not in {"-r", "-p"} else False
    if settings.get("massproduct", default_massproduct):
        arguments.append("-m")
    for key, flag in flags.items():
        value = settings.get(key)
        if value is None:
            continue
        if key == "media":
            value = _api_media_name(value)
        if key == "image_type" and type(value) is int:
            types = {IMG_DATA: "data", IMG_UBOOT: "uboot", IMG_LINUX: "linux"}
            if value not in types:
                raise NuWriterError(f"Unsupported MA35 API image type: {value}")
            value = types[value]
        arguments.extend((flag, str(value)))
    try:
        return main(arguments)
    except SystemExit as error:
        if error.code == 0:
            return 0
        raise NuWriterError(f"Invalid API arguments (CLI exit code {error.code})") from error


def do_attach(ini_file_name, option=OPT_NONE, **settings):
    return _run_api(["-a", str(ini_file_name)] + _api_option_arguments(option), **settings)


def do_img_program(media, start, image_file_name, option=OPT_NONE, **settings):
    arguments = ["-w", _api_media_name(media), hex(cli_number(start, "write start")), str(image_file_name)]
    return _run_api(arguments + _api_option_arguments(option, write=True), **settings)


def do_img_read(media, start, out_file_name, length=1, option=OPT_NONE, **settings):
    start, length = cli_number(start, "read start"), cli_number(length, "read length")
    if length == 0 and start != 0:
        raise NuWriterError("Read-all requires start=0")
    arguments = ["-r", _api_media_name(media)]
    arguments += [hex(start), hex(length), str(out_file_name)] if length else ["all", str(out_file_name)]
    return _run_api(arguments + _api_option_arguments(option), **settings)


def do_img_erase(media, start, length=0, option=OPT_NONE, **settings):
    start, length = cli_number(start, "erase start"), cli_number(length, "erase length")
    if length == 0 and start != 0:
        raise NuWriterError("Erase-all requires start=0")
    arguments = ["-e", _api_media_name(media)]
    arguments += [hex(start), hex(length)] if length else ["all"]
    return _run_api(arguments + _api_option_arguments(option), **settings)


def do_pack_program(media, pack_file_name, option=OPT_NONE, **settings):
    return _run_api(["-w", _api_media_name(media), str(pack_file_name)] + _api_option_arguments(option), **settings)


def do_pack(cfg_file, **settings):
    return _run_api(["-p", str(cfg_file)], **settings)


def main(argv=None):
    parser = argparse.ArgumentParser(description="NUC980 NuWriter Python command tool")
    parser.add_argument("config", nargs="?", help="Pack/configuration file, or DDR settings with --attach")
    parser.add_argument("-a", "--attach", action="store_true", help="Initialize NUC980 DDR and load XUSB")
    parser.add_argument("-m", "--massproduct", action="store_true", help="Operate on all connected targets sequentially")
    parser.add_argument("-o", "--option", nargs=1, help="Single-image write option: verify or execute")
    parser.add_argument("-t", "--type", nargs=1, help="Flash image type: data, linux, env, loader, uboot")
    parser.add_argument("--ddr", help="NUC980 DDR settings, required with --attach and for loader images")
    parser.add_argument("--dtb", type=Path, help="DTB file to download before a DDR/SRAM image")
    parser.add_argument("--dtb-addr", help="DTB address in DRAM; required with --dtb")
    parser.add_argument("--bootargs", help="Override /chosen/bootargs in the downloaded DTB copy only")
    parser.add_argument("--exec-addr", help="Flash image execution address (required for loader/uboot)")
    parser.add_argument("--flash-size", help="SPI NOR byte capacity, required with --read spinor all")
    operations = parser.add_mutually_exclusive_group()
    operations.add_argument("-w", "--write", nargs="+", help="MEDIA START FILE, or MEDIA PACK_FILE")
    operations.add_argument("-r", "--read", nargs="+", help="MEDIA START LENGTH FILE, or MEDIA all FILE (bytes)")
    operations.add_argument("-e", "--erase", nargs="+", help="MEDIA START LENGTH, or MEDIA all (bytes)")
    operations.add_argument("-p", "--pack", action="store_true", help="Generate a NUC980 pack from CONFIG (INI or JSON)")
    operations.add_argument("-c", "--convert", action="store_true", help="Unsupported MA35 operation")
    operations.add_argument("-s", "--storage", nargs="+", help="Unsupported MA35 MSC operation")
    operations.add_argument("-v", "--version", action="store_true", help="Show Python port version")
    parser.add_argument("--media", help="Pack media (required for JSON without mode)")
    parser.add_argument("--output", type=Path, help="Pack output filename")
    parser.add_argument("--resource-dir", type=Path, help="Resource root containing sys_cfg/ and xusb/ (default: beside this script)")
    parser.add_argument("--device", help="Select a physical USB path from --list, such as 1:2.3")
    parser.add_argument("--timeout", type=int, default=10000, help="USB/reconnect timeout in milliseconds")
    parser.add_argument("--operation-timeout", type=int, default=300000, help="Erase/program/format progress timeout in milliseconds")
    parser.add_argument("--trace-usb", action="store_true", help="Trace USB requests, transfer headers and replies to stderr")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check", action="store_true", help="Validate configuration and input files without USB or output writes")
    modes.add_argument("--list", action="store_true", help="List candidate USB devices without programming them")
    arguments = sys.argv[1:] if argv is None else list(argv)
    if not arguments:
        parser.print_help()
        return 0
    args = parser.parse_args(arguments)
    if args.timeout <= 0 or args.operation_timeout <= 0:
        parser.error("Timeouts must be positive")
    if args.version:
        if (args.attach or args.config or args.option or args.type or args.massproduct or args.check or args.list
            or args.dtb or args.dtb_addr or args.bootargs is not None):
            parser.error("--version cannot be combined with operation options")
        print(f"NUC980 NuWriter Python {__version__}")
        return 0
    if args.list and any((args.attach, args.write, args.read, args.erase, args.pack, args.convert,
                          args.storage, args.config, args.option, args.type, args.massproduct,
                          args.ddr, args.exec_addr, args.flash_size, args.media, args.output,
                          args.dtb, args.dtb_addr, args.bootargs is not None)):
        parser.error("--list cannot be combined with operation options")
    if not args.list and not any((args.config, args.ddr, args.write, args.read, args.erase, args.pack, args.convert, args.storage)):
        parser.error("A configuration file is required unless --list is used")
    try:
        if args.list:
            devices = discover_devices()
            for device in sorted(devices, key=UsbSession.device_identity):
                print(f"{device_path(device)}  VID:PID 0416:5963 (candidate; not a chip identity)")
            if not devices:
                print("No candidate USB devices found")
            return 0
        config = config_from_arguments(args)
        if config.all_devices and args.device:
            raise NuWriterError("--device cannot be combined with all_device=yes")
        prepared = preflight(config)
        if config.pack:
            data = build_pack(config, prepared)
            output = pack_output_path(config)
            if not args.check:
                output.write_bytes(data)
                print(f"Pack written: {output} ({len(data)} bytes)")
        if args.check:
            print(f"Configuration and inputs validated: {config.mode}/{config.operation}; no USB or output writes")
            return 0
        if config.pack:
            return 0
        if config.initialize:
            run_pre_attach_hook()
        devices = select_devices(discover_devices(), config.all_devices, args.device)
        for device in devices:
            print(f"Device {device_path(device)}: {config.mode}/{config.operation}")
            session = UsbSession(device, args.timeout, trace=args.trace_usb)
            try:
                writer = Nuc980Writer(config, session.transport, session.reconnect, args.operation_timeout)
                info = writer.attach() if config.initialize else writer.get_info()
                print(f"NAND page size: {info['nand_page_size']}; SPI NAND page size: {info['spinand_page_size']}; SD sectors: {info['emmc_blocks']}")
                writer.run(prepared)
                print("Passed")
            finally:
                session.close()
        return 0
    except (NuWriterError, OSError, ValueError, ImportError, struct.error) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())