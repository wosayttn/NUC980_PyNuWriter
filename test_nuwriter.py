import io
import os
import runpy
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import nuwriter


def fixture_config(resource_dir=None):
    image_settings = {
        "run": "program", "image_num": "1", "image0_type": "data", "image0_path": "image.bin",
        "image0_exe_addr": "0", "image0_start_offset": "0", "read_path": "read.bin",
        "read_start_blocks": "0", "read_offset_blocks": "10", "erase_all": "yes",
        "erase_start_blocks": "0", "erase_offset_blocks": "10", "using_user_defined": "no",
    }
    settings = {mode: dict(image_settings) for mode in ("NAND", "SPINAND", "SPINOR", "SD")}
    settings["RUN"] = {"mode": "SPINAND", "pack": "no", "all_device": "no"}
    settings["DDR"] = {"ddr": "NUC980DF61YC.ini"}
    settings["SDRAM"] = {"option": "download", "sdram_path": "image.bin", "exe_addr": "0x8000", "using_dtb": "no"}
    settings["NAND"].update(blockperflash="1024", pageperblock="64")
    settings["SPINOR"].update(quad_read_command="0x6b", read_status_command="0x35",
                              write_status_command="0x31", status_value="2", dummy_bytes="1")
    settings["SPINAND"].update(page_size="2048", spare_area="64", blockperflash="1024",
                               pageperflash="64", multichip="0", quad_read_command="0x6b",
                               read_status_command="0xff", write_status_command="0xff",
                               status_value="0xff", dummy_bytes="1")
    settings["SD"].update(reserved_size="1024;", using_format="yes", partition_num="3",
                          partition1_size="1024", partition2_size="1024", partition3_size="0")
    return nuwriter.RunConfig(None, resource_dir=resource_dir, settings=settings)


class PreAttachHookTests(unittest.TestCase):
    def test_external_hook_uses_current_python_and_script_directory(self):
        with tempfile.TemporaryDirectory(prefix="nuwriter hook ") as directory:
            root = Path(directory)
            hook = root / "pre-attach-hook.py"
            hook.write_text("raise SystemExit(0)\n", encoding="ascii")
            with patch.object(nuwriter, "__file__", str(root / "nuwriter.py")), \
                 patch.object(nuwriter.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
                nuwriter.run_pre_attach_hook()
            run.assert_called_once_with([sys.executable, str(hook)], cwd=str(root), check=False)

    def test_failed_external_hook_reports_its_exit_code(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pre-attach-hook.py").write_text("raise SystemExit(17)\n", encoding="ascii")
            with patch.object(nuwriter, "__file__", str(root / "nuwriter.py")), \
                 patch.object(nuwriter.subprocess, "run", return_value=SimpleNamespace(returncode=17)):
                with self.assertRaisesRegex(nuwriter.NuWriterError, "hook failed with exit code 17"):
                    nuwriter.run_pre_attach_hook()

    def test_missing_hook_is_optional(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(nuwriter, "__file__", str(Path(directory) / "nuwriter.py")), \
                 patch.object(nuwriter.subprocess, "run") as run:
                nuwriter.run_pre_attach_hook()
            run.assert_not_called()

    def test_reset_hook_calls_ch341_and_waits_only_after_success(self):
        hook = Path(__file__).with_name("pre-attach-hook.py")
        module = runpy.run_path(str(hook))
        for code in (0, 17):
            with self.subTest(code=code), \
                 patch.object(nuwriter.subprocess, "run", return_value=SimpleNamespace(returncode=code)) as run, \
                 patch.object(nuwriter.time, "sleep") as sleep:
                self.assertEqual(module["main"](), code)
                run.assert_called_once()
                command = run.call_args.args[0]
                self.assertEqual(command[:3], [sys.executable, str(hook.resolve().with_name("ch341_reset_uart.py")), "--duration"])
                self.assertGreater(float(command[3]), 0)
                self.assertEqual(run.call_args.kwargs, {"check": False})
                if code == 0:
                    sleep.assert_called_once_with(1.0)
                else:
                    sleep.assert_not_called()

    def test_attach_runs_hook_once_before_usb_scan_for_all_targets(self):
        events = []
        devices = [SimpleNamespace(bus=1, port_numbers=(port,), address=port) for port in (2, 3)]
        config = SimpleNamespace(pack=False, initialize=True, all_devices=True, mode="SDRAM", operation="attach")
        writer = Mock()
        writer.attach.return_value = {"nand_page_size": 0, "spinand_page_size": 0, "emmc_blocks": 0}
        def discover():
            events.append("scan")
            return devices
        with patch.object(nuwriter, "config_from_arguments", return_value=config), \
             patch.object(nuwriter, "preflight", return_value=[]), \
             patch.object(nuwriter, "run_pre_attach_hook", side_effect=lambda: events.append("hook")) as hook, \
             patch.object(nuwriter, "discover_devices", side_effect=discover), \
             patch.object(nuwriter, "UsbSession", return_value=Mock()) as session_class, \
             patch.object(nuwriter, "Nuc980Writer", return_value=writer):
            session_class.device_identity.side_effect = lambda device: (device.bus, device.port_numbers)
            self.assertEqual(nuwriter.main(["-m", "-a", "NUC980DK71YC.ini"]), 0)
        self.assertEqual(events, ["hook", "scan"])
        hook.assert_called_once()
        self.assertEqual(writer.attach.call_count, 2)

    def test_failed_hook_stops_before_usb_discovery(self):
        with patch.object(nuwriter, "run_pre_attach_hook", side_effect=nuwriter.NuWriterError("hook failed")), \
             patch.object(nuwriter, "discover_devices") as discover:
            self.assertEqual(nuwriter.main(["-a", "NUC980DK71YC.ini"]), 1)
            discover.assert_not_called()

    def test_offline_checks_and_existing_xusb_queries_do_not_run_hook(self):
        with patch.object(nuwriter, "run_pre_attach_hook") as hook, \
             patch.object(nuwriter, "discover_devices", return_value=[]) as discover:
            self.assertEqual(nuwriter.main(["-a", "NUC980DK71YC.ini", "--check"]), 0)
            discover.assert_not_called()
            self.assertEqual(nuwriter.main(["-r", "spinand", "0", "1", "unused.bin"]), 1)
            hook.assert_not_called()


class TransportTests(unittest.TestCase):
    def test_chunk_progress_updates_in_ten_percent_steps(self):
        device = Mock()
        lengths = [4096, 4096, 4096, 1]
        device.write.side_effect = lengths
        device.read.side_effect = [struct.pack("<I", length) for length in lengths]
        output = io.StringIO()
        with patch.object(nuwriter.sys, "stdout", output):
            nuwriter.UsbTransport(device).send_chunks(bytes(sum(lengths)))
        frames = [frame for frame in output.getvalue().split("\r") if "%" in frame]
        percentages = [int(frame.rsplit(None, 1)[-1].rstrip("%")) for frame in frames]
        self.assertEqual(percentages, list(range(0, 101, 10)))
        self.assertIn("Download [##########] 100%", output.getvalue())
        self.assertTrue(output.getvalue().endswith("\n"))
        self.assertEqual(device.write.call_count, len(lengths))
        self.assertEqual(device.read.call_count, len(lengths))

    def test_chunk_progress_does_not_complete_after_a_failed_ack(self):
        device = Mock()
        device.write.return_value = 4096
        device.read.side_effect = [struct.pack("<I", 4096), OSError("acknowledgement failed")]
        output = io.StringIO()
        with patch.object(nuwriter.sys, "stdout", output):
            with self.assertRaises(OSError):
                nuwriter.UsbTransport(device).send_chunks(bytes(8192))
        self.assertIn("50%", output.getvalue())
        self.assertNotIn("60%", output.getvalue())
        self.assertNotIn("100%", output.getvalue())
        self.assertTrue(output.getvalue().endswith("\n"))

    def test_trace_records_header_transfer_and_reply_without_changing_usb_calls(self):
        device = Mock()
        device.write.return_value = 56
        device.read.return_value = struct.pack("<I", 0x89)
        device.ctrl_transfer.side_effect = [0, b"\x89\x00", 0]
        transport = nuwriter.UsbTransport(device, trace=True)
        header = nuwriter.storage_header(2, kind=0, execute=1024, number=0xFFFFFFFF)
        output = io.StringIO()
        with patch.object(nuwriter.sys, "stderr", output):
            transport.set_type(9)
            transport.write(header)
            self.assertEqual(transport.read_word(), 0x89)
        text = output.getvalue()
        self.assertIn("value=0x0089", text)
        self.assertIn("index=56", text)
        self.assertIn("BULK OUT endpoint=0x02 length=56", text)
        self.assertIn(header.hex(" "), text)
        self.assertIn("BULK IN completed length=4 data=89 00 00 00", text)
        self.assertEqual(device.ctrl_transfer.call_count, 3)
        device.write.assert_called_once_with(0x02, header, timeout=10000)

    def test_trace_shows_pending_read_when_device_does_not_acknowledge(self):
        device = Mock()
        device.read.side_effect = OSError(10060, "Operation timed out")
        output = io.StringIO()
        with patch.object(nuwriter.sys, "stderr", output):
            with self.assertRaises(OSError):
                nuwriter.UsbTransport(device, trace=True).read_word(timeout=300000)
        self.assertIn("BULK IN endpoint=0x81 length=4 timeout=300000 ms", output.getvalue())
        self.assertNotIn("BULK IN completed", output.getvalue())

    def test_usb_trace_is_disabled_by_default(self):
        device = Mock()
        device.read.return_value = bytes(4)
        output = io.StringIO()
        with patch.object(nuwriter.sys, "stderr", output):
            nuwriter.UsbTransport(device).read_word()
        self.assertEqual(output.getvalue(), "")

    def test_write_uses_nuc980_endpoint_and_length_request(self):
        device = Mock()
        device.write.return_value = 3
        nuwriter.UsbTransport(device).write(b"abc")
        device.ctrl_transfer.assert_called_once_with(
            0x40, 0xA0, wValue=0x12, wIndex=3,
            data_or_wLength=b"", timeout=10000,
        )
        device.write.assert_called_once_with(0x02, b"abc", timeout=10000)

    def test_short_transfers_are_errors(self):
        device = Mock()
        device.write.return_value = 2
        transport = nuwriter.UsbTransport(device)
        with self.assertRaises(nuwriter.NuWriterError):
            transport.write(b"abc")
        device.read.return_value = b"abc"
        with self.assertRaises(nuwriter.NuWriterError):
            transport.read(4)

    def test_media_selection_uses_bidirectional_handshake(self):
        device = Mock()
        device.ctrl_transfer.side_effect = [0, struct.pack("<I", 0x87)]
        nuwriter.UsbTransport(device).set_type(7)
        self.assertEqual(device.ctrl_transfer.call_args_list[0].args, (0x40, 0xB0))
        self.assertEqual(device.ctrl_transfer.call_args_list[1].args, (0xC0, 0xB0))
        self.assertEqual(device.ctrl_transfer.call_args_list[1].kwargs["wValue"], 0x87)
        self.assertEqual(device.ctrl_transfer.call_args_list[1].kwargs["data_or_wLength"], 2)

    def test_media_selection_has_a_deadline(self):
        device = Mock()
        device.ctrl_transfer.side_effect = [0, bytes(4)]
        with patch.object(nuwriter.time, "monotonic", side_effect=[0, 11]):
            with self.assertRaisesRegex(nuwriter.NuWriterError, "Timed out"):
                nuwriter.UsbTransport(device).set_type(7)

    def test_media_selection_accepts_short_ack_like_c(self):
        for reply in (b"\x8a", b"\x8a\x00", b"\x8a\x00\x00", b"\x8a\xff\xff\xff"):
            with self.subTest(reply=reply):
                device = Mock()
                device.ctrl_transfer.side_effect = [0, reply]
                nuwriter.UsbTransport(device).set_type(10)
                self.assertEqual(device.ctrl_transfer.call_count, 2)

    def test_wrong_or_empty_ack_reports_last_reply(self):
        for reply in (b"", b"\x8b", bytes(4)):
            with self.subTest(reply=reply):
                device = Mock()
                device.ctrl_transfer.side_effect = [0, reply]
                with patch.object(nuwriter.time, "monotonic", side_effect=[0, 11]):
                    with self.assertRaises(nuwriter.NuWriterError) as raised:
                        nuwriter.UsbTransport(device).set_type(10)
                self.assertIn("wValue=0x008a", str(raised.exception))
                expected = reply.hex(" ") if reply else "<empty>"
                self.assertIn(f"last reply={expected}", str(raised.exception))

    def test_chunks_use_little_endian_length_ack(self):
        device = Mock()
        device.write.side_effect = [4096, 1]
        device.read.side_effect = [struct.pack("<I", 4096), struct.pack("<I", 1)]
        nuwriter.UsbTransport(device).send_chunks(bytes(4097))
        self.assertEqual(device.write.call_args_list[1].args, (0x02, bytes(1)))


class TransferProgressTests(unittest.TestCase):
    def assert_progress(self, output, label):
        frames = [frame for frame in output.getvalue().split("\r") if label in frame]
        percentages = [int(frame.rsplit(None, 1)[-1].rstrip("%")) for frame in frames]
        self.assertEqual(percentages, list(range(0, 101, 10)))
        self.assertTrue(output.getvalue().endswith("\n"))

    def test_sdram_progress_for_tiny_full_partial_and_multiple_chunks(self):
        for length in (1, 4096, 4097, 40961):
            with self.subTest(length=length):
                transport = Mock()
                transport.read_word.return_value = 0x80
                output = io.StringIO()
                with patch.object(nuwriter.sys, "stdout", output):
                    writer = nuwriter.Nuc980Writer(fixture_config(), transport)
                    writer.download(bytes(length), 0x8000, True, 0)
                self.assert_progress(output, "SDRAM download 0x00008000")
                self.assertEqual(transport.expect.call_count, (length + 4095) // 4096)
                self.assertEqual(transport.write.call_args_list[-1].args, (bytes((length - 1) % 4096 + 1),))

    def test_each_sdram_download_starts_a_new_progress_bar(self):
        transport = Mock()
        transport.read_word.return_value = 0x80
        output = io.StringIO()
        with patch.object(nuwriter.sys, "stdout", output):
            writer = nuwriter.Nuc980Writer(fixture_config(), transport)
            writer.download(b"dtb", 0x1400000, False, 0)
            writer.download(b"kernel", 0x8000, True, 0x81400000)
        self.assert_progress(output, "SDRAM download 0x01400000")
        self.assert_progress(output, "SDRAM download 0x00008000")

    def test_program_progress_waits_for_completion_for_each_media_and_image_kind(self):
        for mode in ("NAND", "SPINAND", "SPINOR", "SD"):
            for kind in (0, 2):
                with self.subTest(mode=mode, kind=kind):
                    config = fixture_config()
                    config.mode = mode
                    output = io.StringIO()
                    snapshots = []
                    transport = Mock()
                    def acknowledge():
                        snapshots.append(output.getvalue())
                        return 100
                    transport.read_word.side_effect = acknowledge
                    data = bytes(65537)
                    prepared = nuwriter.PreparedImage(nuwriter.Image(Path("image.bin"), kind, 0x200, 0), data, len(data))
                    with patch.object(nuwriter.sys, "stdout", output):
                        nuwriter.Nuc980Writer(config, transport).program(prepared)
                    self.assert_progress(output, f"{mode} program")
                    self.assertTrue(all("100%" not in text for text in snapshots))
                    self.assertEqual(transport.expect.call_count, 17)

    def test_pack_progress_covers_all_children_without_restarting(self):
        first = struct.pack("<4I", 65536, 0, 0, 0xFFFFFFFF) + bytes(65536)
        second = struct.pack("<4I", 4097, 0x20000, 0, 0xFFFFFFFF) + bytes(4097)
        data = struct.pack("<4I", 5, 65536 + 4097, 2, 0xFFFFFFFF) + first + second
        prepared = nuwriter.PreparedImage(nuwriter.Image(Path("pack.bin"), 3, 0, 0), data, len(data))
        for mode in ("NAND", "SPINAND", "SPINOR", "SD"):
            with self.subTest(mode=mode):
                config = fixture_config()
                config.mode = mode
                transport = Mock()
                output = io.StringIO()
                snapshots = []
                def acknowledge():
                    snapshots.append(output.getvalue())
                    return 100
                transport.read_word.side_effect = acknowledge
                with patch.object(nuwriter.sys, "stdout", output):
                    nuwriter.Nuc980Writer(config, transport).program_pack(prepared)
                self.assert_progress(output, f"{mode} pack program")
                self.assertTrue(all("100%" not in text for text in snapshots))
                self.assertEqual(transport.write.call_count, 22)

    def test_progress_does_not_complete_after_transfer_or_final_status_errors(self):
        data = b"payload"
        single = nuwriter.PreparedImage(nuwriter.Image(Path("image.bin"), 0, 0, 0), data, len(data))
        pack = struct.pack("<4I", 5, len(data), 1, 0xFFFFFFFF) + struct.pack("<4I", len(data), 0, 0, 0xFFFFFFFF) + data
        packed = nuwriter.PreparedImage(nuwriter.Image(Path("pack.bin"), 3, 0, 0), pack, len(pack))
        for operation in ("download", "program", "program_pack"):
            with self.subTest(operation=operation):
                transport = Mock()
                if operation == "download":
                    transport.read_word.return_value = 0x80
                    transport.expect.side_effect = OSError("data acknowledgement failed")
                else:
                    replies = [0] if operation == "program" else [0, 0, 0, len(data)]
                    transport.read_word.side_effect = replies + [OSError("completion failed")]
                output = io.StringIO()
                writer = nuwriter.Nuc980Writer(fixture_config(), transport)
                with patch.object(nuwriter.sys, "stdout", output):
                    with self.assertRaises((OSError, nuwriter.NuWriterError)):
                        if operation == "download":
                            writer.download(data, 0x8000, False, 0)
                        elif operation == "program":
                            writer.program(single)
                        else:
                            writer.program_pack(packed)
                self.assertNotIn("100%", output.getvalue())
                self.assertTrue(output.getvalue().endswith("\n"))

    def test_program_verify_progress_does_not_complete_after_verification_failure(self):
        config = fixture_config()
        config.operation = "program_verify"
        transport = Mock()
        prepared = nuwriter.PreparedImage(nuwriter.Image(Path("image.bin"), 0, 0, 0), b"data", 4)
        writer = nuwriter.Nuc980Writer(config, transport)
        output = io.StringIO()
        with patch.object(nuwriter.sys, "stdout", output), \
             patch.object(writer, "verify_data", side_effect=nuwriter.NuWriterError("Verification failed")):
            with self.assertRaisesRegex(nuwriter.NuWriterError, "Verification failed"):
                writer.program(prepared)
        self.assertIn("90%", output.getvalue())
        self.assertNotIn("100%", output.getvalue())


class InitializationTests(unittest.TestCase):
    def test_default_resources_use_sibling_sys_cfg_and_xusb(self):
        config = fixture_config()
        root = Path(nuwriter.__file__).resolve().parent
        self.assertEqual(config.resource_dir, root)
        self.assertEqual(config.ddr().parent, root / "sys_cfg")
        self.assertEqual(config.xusb("xusb64.bin"), root / "xusb" / "xusb64.bin")

    def test_custom_resource_root_changes_both_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = fixture_config(resource_dir=root)
            self.assertEqual(config.ddr().parent, root / "sys_cfg")
            self.assertEqual(config.xusb("xusb128.bin"), root / "xusb" / "xusb128.bin")

    def test_info_layout_matches_c_alignment(self):
        config = fixture_config()
        data = config.user_info()
        self.assertEqual(len(data), 84)
        self.assertEqual(struct.unpack_from("<H", data, 60)[0], 2048)
        self.assertEqual(struct.unpack_from("<I", data, 72)[0], 1024)
        self.assertEqual(data[80], 0)

    def test_ddr_preserves_duplicate_delay_entries(self):
        config = fixture_config()
        data, name = nuwriter.load_ddr(config.ddr())
        self.assertEqual(name, "xusb64.bin")
        self.assertNotIn(struct.pack("<I", 0xB0000000), data)
        self.assertGreater(data.count(struct.pack("<II", 0x55AA55AA, 1)), 1)

    def test_reserved_size_accepts_existing_trailing_semicolon(self):
        config = fixture_config()
        self.assertEqual(config.number("SD", "reserved_size"), 1024)

    def test_attach_downloads_xusb_without_its_file_header(self):
        config = fixture_config()
        transport = Mock()
        transport.read_word.return_value = 8
        transport.read.return_value = bytes(84)
        image = struct.pack("<4I", 0xA55A4257, 0x8000, 3, 1) + b"usb"
        with patch.object(nuwriter, "load_ddr", return_value=(bytes(8), "xusb.bin")):
            with patch.object(Path, "read_bytes", autospec=True, return_value=image) as read_image:
                nuwriter.Nuc980Writer(config, transport).attach()
        read_image.assert_called_once_with(config.resource_dir / "xusb" / "xusb.bin")
        self.assertEqual(transport.write.call_args_list[0].args, (struct.pack("<II", 8, 16),))
        self.assertEqual(transport.write.call_args_list[2].args, (struct.pack("<II", 3, 0x8000),))
        transport.send_chunks.assert_called_once_with(b"usb")
        transport.set_type.assert_called_once_with(10)

    def test_attach_skips_download_if_xusb_is_already_running(self):
        config = fixture_config()
        transport = Mock()
        transport.read_word.return_value = 4097
        transport.read.return_value = bytes(84)
        with patch.object(nuwriter, "load_ddr", return_value=(bytes(8), "xusb.bin")):
            nuwriter.Nuc980Writer(config, transport).attach()
        transport.send_chunks.assert_not_called()
        transport.expect.assert_called_once_with(0x90)

    def test_windows_nand_info_normalizes_last_block_indexes(self):
        config = fixture_config()
        config.mode = "NAND"
        for last_index in (1023, 2047, 4095, 8191):
            with self.subTest(last_index=last_index):
                values = dict.fromkeys(nuwriter.INFO_FIELDS, 0)
                values["nand_block_count"] = last_index
                transport = Mock()
                transport.read.return_value = nuwriter.INFO_STRUCT.pack(*(values[key] for key in nuwriter.INFO_FIELDS))
                info = nuwriter.Nuc980Writer(config, transport).get_info()
                self.assertEqual(info["nand_block_count"], last_index + 1)

    def test_windows_nand_user_geometry_overrides_auto_information(self):
        config = fixture_config()
        config.mode = "NAND"
        config.ini.set("NAND", "using_user_defined", "yes")
        config.ini.set("NAND", "blockperflash", "512")
        config.ini.set("NAND", "pageperblock", "32")
        transport = Mock()
        transport.read.return_value = bytes(84)
        info = nuwriter.Nuc980Writer(config, transport).get_info()
        self.assertEqual((info["nand_block_count"], info["nand_page_per_block"]), (512, 32))


class FlashTests(unittest.TestCase):
    def config(self):
        return fixture_config()

    def test_nand_header_is_56_bytes(self):
        header = nuwriter.storage_header(0, 12, 2, 0x200, 0x1000, 16)
        self.assertEqual(len(header), 56)
        self.assertEqual(struct.unpack_from("<4I", header, 28), (2, 0x200, 0x1000, 0))
        self.assertEqual(struct.unpack_from("<I", header, 52)[0], 16)

    def test_environment_crc_and_line_endings(self):
        data = nuwriter.environment_image(b"foo=bar\r\nsecond=value", 0x10000)
        self.assertEqual(len(data), 0x10000)
        self.assertEqual(data[4:26], b"foo=bar\x00second=value\x00\x00")
        self.assertEqual(struct.unpack_from("<I", data)[0], nuwriter.zlib.crc32(data[4:]))
        with self.assertRaises(nuwriter.NuWriterError):
            nuwriter.environment_image(b"toolong", 8)

    def test_spinand_environment_is_128_kib(self):
        image = nuwriter.Image(Path("env.txt"), 1, 0, 0x80000)
        with patch.object(Path, "read_bytes", return_value=b"foo=bar\n"):
            prepared = nuwriter.prepare_image(self.config(), image)
        self.assertEqual(len(prepared.data), 0x20000)

    def test_loader_keeps_original_file_length_in_request(self):
        transport = Mock()
        config = self.config()
        image = nuwriter.Image(Path("loader.bin"), 2, 0x200, 0x1000)
        with patch.object(Path, "read_bytes", return_value=b"loader"):
            prepared = nuwriter.prepare_image(config, image)
        nuwriter.Nuc980Writer(config, transport).program(prepared)
        header = transport.write.call_args_list[0].args[0]
        self.assertEqual(struct.unpack_from("<I", header, 4)[0], 6)
        self.assertEqual(struct.unpack_from("<I", header, 8)[0], 1)
        self.assertEqual(struct.unpack_from("<I", header, 36)[0], 0x1000)
        self.assertEqual(prepared.data[prepared.init_size:], b"loader")
        self.assertEqual(prepared.init_size % 16, 0)

    def test_verify_mismatch_sends_failure_ack_and_raises(self):
        transport = Mock()
        transport.read.return_value = b"bad" + bytes(4093)
        writer = nuwriter.Nuc980Writer(self.config(), transport)
        with self.assertRaisesRegex(nuwriter.NuWriterError, "Verification failed"):
            writer.verify_data(b"good")
        transport.write.assert_called_once_with(bytes(4))

    def test_verify_final_packet_is_padded_to_4096(self):
        transport = Mock()
        transport.read.return_value = b"ok" + bytes(4094)
        nuwriter.Nuc980Writer(self.config(), transport).verify_data(b"ok")
        transport.read.assert_called_once_with(4096, minimum=2)
        transport.write.assert_called_once_with(struct.pack("<I", 4096))


class MediaTests(unittest.TestCase):
    def config(self, mode, operation="program"):
        config = fixture_config()
        config.mode, config.operation = mode, operation
        return config

    def test_mmc_header_matches_c_100_byte_layout(self):
        header = nuwriter.mmc_header(6, reserved=2048, partition_count=2, sizes=(10, 20, 0, 0))
        self.assertEqual(len(header), 100)
        self.assertEqual(struct.unpack_from("<I", header, 44)[0], 2048)
        self.assertEqual(struct.unpack_from("<9I", header, 64), (2, 10, 20, 0, 0, 0, 0, 0, 0))

    def test_spinor_consumes_extra_status_at_64_kib_boundary(self):
        transport = Mock()
        image = nuwriter.Image(Path("data.bin"), 0, 0, 0)
        prepared = nuwriter.PreparedImage(image, bytes(0x10000), 0x10000)
        nuwriter.Nuc980Writer(self.config("SPINOR"), transport).program(prepared)
        self.assertEqual(transport.expect.call_count, 16)
        self.assertEqual(transport.read_word.call_count, 2)

    def test_sd_loader_padding_is_not_verified(self):
        config = self.config("SD", "program_verify")
        image = nuwriter.Image(Path("loader.bin"), 2, 0x200, 0x400)
        with patch.object(Path, "read_bytes", return_value=b"loader"):
            prepared = nuwriter.prepare_image(config, image)
        self.assertEqual(prepared.data[-32:], b"\xff" * 32)
        transport = Mock()
        transport.read.return_value = b"loader" + bytes(4090)
        nuwriter.Nuc980Writer(config, transport).program(prepared)
        header = transport.write.call_args_list[0].args[0]
        self.assertEqual(struct.unpack_from("<I", header, 8)[0], 1)
        self.assertEqual(struct.unpack_from("<I", header, 36)[0], 0x400)
        transport.read.assert_called_once_with(4096, minimum=6)

    def test_windows_image_headers_keep_configured_execution_address_and_offset(self):
        for mode in ("NAND", "SPINAND", "SPINOR", "SD"):
            for kind in (0, 1, 2):
                with self.subTest(mode=mode, kind=kind):
                    transport = Mock()
                    image = nuwriter.Image(Path("image.bin"), kind, 0x8000, 0x40000)
                    prepared = nuwriter.PreparedImage(image, b"abc", 3)
                    writer = nuwriter.Nuc980Writer(self.config(mode), transport)
                    writer.wait_progress = Mock()
                    writer.program(prepared)
                    header = transport.write.call_args_list[0].args[0]
                    self.assertEqual(struct.unpack_from("<I", header, 8)[0], 1 if kind == 2 else 0)
                    self.assertEqual(struct.unpack_from("<I", header, 32)[0], 0x8000)
                    self.assertEqual(struct.unpack_from("<I", header, 36)[0], 0x40000)

    def test_sd_read_uses_sectors_and_trims_final_packet(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self.config("SD", "read")
            path = Path(directory) / "read.bin"
            config.ini.set("SD", "read_path", str(path))
            config.ini.set("SD", "read_start_blocks", "2")
            config.ini.set("SD", "read_offset_blocks", "1")
            transport = Mock()
            transport.read.return_value = b"a" * 4096
            nuwriter.Nuc980Writer(config, transport).read_flash()
            self.assertEqual(path.read_bytes(), b"a" * 512)
            header = transport.write.call_args_list[0].args[0]
            self.assertEqual(struct.unpack_from("<I", header, 4)[0], 512)
            self.assertEqual(struct.unpack_from("<I", header, 36)[0], 1024)

    def test_spinand_erase_consumes_block_count_and_final_index(self):
        transport = Mock()
        transport.read_word.side_effect = [0x89, 3, 0, 1, 2]
        writer = nuwriter.Nuc980Writer(self.config("SPINAND", "erase"), transport)
        writer.info = {"spinand_block_count": 3}
        writer.erase()
        self.assertEqual(transport.read_word.call_count, 5)

    def test_device_progress_errors_are_not_success(self):
        transport = Mock()
        transport.read_word.return_value = 0x10064
        with self.assertRaises(nuwriter.NuWriterError):
            nuwriter.Nuc980Writer(self.config("NAND"), transport).wait_progress()

    def test_device_progress_has_whole_operation_timeout(self):
        transport = Mock()
        writer = nuwriter.Nuc980Writer(self.config("NAND"), transport, operation_timeout=1000)
        with patch.object(nuwriter.time, "monotonic", side_effect=[0, 2]):
            with self.assertRaisesRegex(nuwriter.NuWriterError, "Timed out"):
                writer.wait_progress()

    def test_windows_sdram_execute_reads_final_partial_ack(self):
        transport = Mock()
        transport.read_word.return_value = 0x80
        writer = nuwriter.Nuc980Writer(self.config("SDRAM"), transport)
        writer.download(b"abc", 0x8000, True, 0)
        transport.expect.assert_called_once_with(3)
        header = transport.write.call_args_list[0].args[0]
        self.assertEqual(struct.unpack("<4I", header), (0, 3, 0x80008000, 0))

    def test_sdram_download_only_reads_final_ack(self):
        transport = Mock()
        transport.read_word.return_value = 0x80
        nuwriter.Nuc980Writer(self.config("SDRAM"), transport).download(b"abc", 0x8000, False, 0)
        transport.expect.assert_called_once_with(3)

    def test_sd_format_rejects_overcommitted_partitions(self):
        config = self.config("SD", "format")
        transport = Mock()
        writer = nuwriter.Nuc980Writer(config, transport)
        writer.info = {"emmc_blocks": 2048 * 1024}
        with self.assertRaises(nuwriter.NuWriterError):
            writer.format_sd()
        transport.write.assert_not_called()

    def test_flash_read_units_match_each_media(self):
        for mode, block_size, expected_offset in (("NAND", 4096, 2),
                                                   ("SPINAND", 4096, 2),
                                                   ("SPINOR", 0x10000, 0x20000)):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                config = self.config(mode, "read")
                path = Path(directory) / "read.bin"
                config.ini.set(mode, "read_path", str(path))
                config.ini.set(mode, "read_start_blocks", "2")
                config.ini.set(mode, "read_offset_blocks", "1")
                transport = Mock()
                transport.read.return_value = bytes(4096)
                writer = nuwriter.Nuc980Writer(config, transport)
                writer.info = {"nand_page_size": 2048, "nand_page_per_block": 2,
                               "spinand_page_size": 2048, "spinand_page_per_block": 2}
                writer.read_flash()
                header = transport.write.call_args_list[0].args[0]
                self.assertEqual(struct.unpack_from("<I", header, 4)[0], block_size)
                self.assertEqual(struct.unpack_from("<I", header, 36)[0], expected_offset)
                self.assertEqual(path.stat().st_size, block_size)

    def test_sd_format_assigns_remaining_capacity_to_last_partition(self):
        config = self.config("SD", "format")
        transport = Mock()
        transport.read_word.side_effect = [0, 100]
        writer = nuwriter.Nuc980Writer(config, transport)
        writer.info = {"emmc_blocks": 2048 * 8192}
        writer.format_sd()
        header = transport.write.call_args.args[0]
        self.assertEqual(struct.unpack_from("<I", header, 44)[0], 1024 * 2048)
        self.assertEqual(struct.unpack_from("<5I", header, 64), (3, 1024, 1024, 5120, 0))

    def test_sdram_execute_reads_ack_for_a_full_final_packet(self):
        transport = Mock()
        transport.read_word.return_value = 0x80
        nuwriter.Nuc980Writer(self.config("SDRAM"), transport).download(bytes(4096), 0x8000, True, 0)
        transport.expect.assert_called_once_with(4096)

    def test_windows_read_tail_sizes_depend_on_media(self):
        for mode, read_size in (("NAND", 2048), ("SPINAND", 4096), ("SD", 4096)):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                config = self.config(mode, "read")
                config.ini.set(mode, "read_path", str(Path(directory) / "read.bin"))
                config.ini.set(mode, "read_start_blocks", "0")
                config.ini.set(mode, "read_offset_blocks", "1")
                transport = Mock()
                transport.read.return_value = bytes(read_size)
                writer = nuwriter.Nuc980Writer(config, transport)
                writer.info = {"nand_page_size": 2048, "nand_page_per_block": 1,
                               "spinand_page_size": 2048, "spinand_page_per_block": 1}
                writer.read_flash()
                payload = 512 if mode == "SD" else 2048
                transport.read.assert_called_once_with(read_size, minimum=payload)
                self.assertEqual((Path(directory) / "read.bin").stat().st_size, payload)

    def test_windows_spinand_read_uses_distinct_nonzero_block_indexes(self):
        for block in (1, 4, 8, 64, 512, 1023):
            with self.subTest(block=block), tempfile.TemporaryDirectory() as directory:
                config = self.config("SPINAND", "read")
                config.byte_range = (block * 0x20000, 2048)
                config.ini.set("SPINAND", "read_path", str(Path(directory) / "read.bin"))
                transport = Mock()
                transport.read.return_value = bytes(4096)
                writer = nuwriter.Nuc980Writer(config, transport)
                writer.info = {"spinand_page_size": 2048, "spinand_page_per_block": 64}
                writer.read_flash()
                header = transport.write.call_args_list[0].args[0]
                self.assertEqual(struct.unpack_from("<I", header, 36)[0], block)
                self.assertEqual(struct.unpack_from("<I", header, 4)[0], 2048)

    def test_windows_dtb_parameter_is_set_only_when_running(self):
        for execute in (False, True):
            with self.subTest(execute=execute):
                writer = nuwriter.Nuc980Writer(self.config("SDRAM"), Mock())
                writer.download = Mock()
                writer.download_sdram((b"kernel", 0x8000, execute, b"dtb", 0x100000))
                self.assertEqual(writer.download.call_args_list[0].args, (b"dtb", 0x100000, False, 0))
                self.assertEqual(writer.download.call_args_list[1].args,
                                 (b"kernel", 0x8000, execute, 0x80100000 if execute else 0))

    def test_windows_nand_erase_all_preserves_bad_block_markers(self):
        transport = Mock()
        transport.read_word.side_effect = [0, 100]
        writer = nuwriter.Nuc980Writer(self.config("NAND", "erase"), transport)
        writer.info = {"nand_block_count": 1024}
        writer.erase()
        header = transport.write.call_args.args[0]
        self.assertEqual(struct.unpack_from("<I", header, 8)[0], 0xFFFFFFFF)
        self.assertEqual(struct.unpack_from("<3I", header, 28), (0, 1024, 0))


class SdramDiagnosticTests(unittest.TestCase):
    def writer(self, transport):
        config = fixture_config()
        config.mode = "SDRAM"
        return nuwriter.Nuc980Writer(config, transport)

    def test_sdram_wrong_header_ack_stops_before_payload(self):
        transport = Mock()
        transport.read_word.return_value = 0x90
        with self.assertRaisesRegex(nuwriter.NuWriterError, "header acknowledgement.*Unexpected SDRAM ACK"):
            self.writer(transport).download(b"data", 0x1400000, False, 0)
        self.assertEqual(transport.write.call_count, 1)

    def test_sdram_timeouts_identify_each_transfer_stage(self):
        for stage in ("media selection", "16-byte header transmission", "header acknowledgement",
                      "data transmission", "data acknowledgement"):
            with self.subTest(stage=stage):
                transport = Mock()
                transport.read_word.return_value = 0x80
                error = OSError(10060, "Operation timed out")
                if stage == "media selection":
                    transport.set_type.side_effect = error
                elif stage == "16-byte header transmission":
                    transport.write.side_effect = error
                elif stage == "header acknowledgement":
                    transport.read_word.side_effect = error
                elif stage == "data transmission":
                    transport.write.side_effect = [None, error]
                else:
                    transport.expect.side_effect = error
                with self.assertRaises(nuwriter.NuWriterError) as raised:
                    self.writer(transport).download(b"data", 0x1400000, False, 0)
                self.assertIn("0x01400000", str(raised.exception))
                self.assertIn(stage, str(raised.exception))
                self.assertIn("10060", str(raised.exception))


class PackTests(unittest.TestCase):
    def config(self, mode="SPINAND"):
        config = fixture_config()
        config.mode = mode
        return config

    def test_pack_data_and_loader_match_legacy_headers(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.bin"
            source.write_bytes(b"abc")
            config = self.config()
            images = [nuwriter.Image(source, kind, 0x200, 0x1000) for kind in (0, 2)]
            prepared = [nuwriter.prepare_image(config, image) for image in images]
            data = nuwriter.build_pack(config, prepared)
            self.assertEqual(struct.unpack_from("<4I", data), (5, 0x10000, 2, 0xFFFFFFFF))
            children = nuwriter.parse_pack(data)
            self.assertEqual(children[0][1], b"abc")
            loader = children[1][1]
            self.assertEqual(loader[:16], struct.pack("<4sIII", b" TVN", 0x200, 3, 0xFFFFFFFF))
            self.assertEqual(struct.unpack_from("<HH5B", loader, 16), (2048, 64, 0x6B, 0xFF, 0xFF, 0xFF, 1))
            self.assertEqual(loader[32:36], b"\x55\xaa\x55\xaa")
            self.assertEqual(loader[-3:], b"abc")

    def test_sd_pack_includes_48_byte_partition_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.bin"
            path.write_bytes(b"a")
            config = self.config("SD")
            image = nuwriter.Image(path, 0, 0, 0x1000)
            data = nuwriter.build_pack(config, [nuwriter.prepare_image(config, image)])
            children = nuwriter.parse_pack(data)
            self.assertEqual(len(children), 2)
            self.assertEqual(children[1][2], 3)
            self.assertEqual(len(children[1][1]), 48)
            self.assertEqual(struct.unpack_from("<4I", children[1][1]), (0, 3, 1024, 0xFFFFFFFF))
            self.assertEqual(struct.unpack_from("<I", data, 4)[0], 0x10000)

    def test_truncated_and_trailing_pack_data_are_rejected(self):
        data = struct.pack("<4I", 5, 1, 1, 0xFFFFFFFF) + struct.pack("<4I", 1, 0, 0, 0xFFFFFFFF) + b"a"
        self.assertEqual(len(nuwriter.parse_pack(data)), 1)
        for invalid in (data[:-1], data + b"a", bytes(16)):
            with self.assertRaises(nuwriter.NuWriterError):
                nuwriter.parse_pack(invalid)

    def test_pack_verify_is_rejected_before_usb_writes(self):
        config = self.config()
        config.operation = "program_verify"
        transport = Mock()
        image = nuwriter.Image(Path("pack.bin"), 3, 0, 0)
        prepared = nuwriter.PreparedImage(image, bytes(16), 16)
        with self.assertRaisesRegex(nuwriter.NuWriterError, "program_verify"):
            nuwriter.Nuc980Writer(config, transport).program_pack(prepared)
        transport.write.assert_not_called()

    def test_nand_pack_has_child_header_and_completion_ack(self):
        config = self.config("NAND")
        data = struct.pack("<4I", 5, 3, 1, 0xFFFFFFFF) + struct.pack("<4I", 3, 0, 0, 0xFFFFFFFF) + b"abc"
        transport = Mock()
        prepared = nuwriter.PreparedImage(nuwriter.Image(Path("pack.bin"), 3, 0, 0), data, len(data))
        nuwriter.Nuc980Writer(config, transport).program_pack(prepared)
        self.assertEqual(transport.read_word.call_count, 5)
        self.assertEqual(transport.write.call_args_list[-1].args, (b"abc",))

    def test_windows_spinand_pack_consumes_each_child_header_and_completion(self):
        config = self.config("SPINAND")
        first = struct.pack("<4I", 3, 0, 0, 0xFFFFFFFF) + b"abc"
        second = struct.pack("<4I", 2, 0x20000, 0, 0xFFFFFFFF) + b"de"
        data = struct.pack("<4I", 5, 5, 2, 0xFFFFFFFF) + first + second
        transport = Mock()
        prepared = nuwriter.PreparedImage(nuwriter.Image(Path("pack.bin"), 3, 0, 0), data, len(data))
        nuwriter.Nuc980Writer(config, transport).program_pack(prepared)
        self.assertEqual(transport.read_word.call_count, 8)
        operations = [entry[0] for entry in transport.method_calls if entry[0] != "set_type"]
        self.assertEqual(operations, ["write", "read_word", "write", "read_word",
                                     "write", "read_word", "write", "read_word", "read_word",
                                     "write", "read_word", "write", "read_word", "read_word"])
        self.assertEqual(transport.write.call_args_list[-1].args, (b"de",))

    def test_windows_spinor_pack_reads_completion_for_a_4096_byte_tail(self):
        config = self.config("SPINOR")
        data = struct.pack("<4I", 5, 4096, 1, 0xFFFFFFFF) + struct.pack("<4I", 4096, 0, 0, 0xFFFFFFFF) + bytes(4096)
        transport = Mock()
        transport.read_word.side_effect = [0x87, 0, 4096, 100]
        prepared = nuwriter.PreparedImage(nuwriter.Image(Path("pack.bin"), 3, 0, 0), data, len(data))
        nuwriter.Nuc980Writer(config, transport).program_pack(prepared)
        self.assertEqual(transport.read_word.call_count, 4)

    def test_windows_pack_loader_ddr_is_checked_before_programming(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "loader.bin"
            source.write_bytes(b"loader")
            config = self.config()
            config.ini.set("DDR", "ddr", "NUC980DK71YC.ini")
            prepared = nuwriter.prepare_image(config, nuwriter.Image(source, 2, 0x200, 0))
            data = nuwriter.build_pack(config, [prepared])
            self.assertEqual(len(nuwriter.validate_pack(config, data)), 1)
            config.ini.set("DDR", "ddr", "NUC980DF61YC.ini")
            transport = Mock()
            image = nuwriter.PreparedImage(nuwriter.Image(Path("pack.bin"), 3, 0, 0), data, len(data))
            with self.assertRaisesRegex(nuwriter.NuWriterError, "DDR data does not match"):
                nuwriter.Nuc980Writer(config, transport).program_pack(image)
            transport.write.assert_not_called()

    def test_windows_pack_rejects_truncated_loader_ddr(self):
        payload = b" TVN" + bytes(28) + struct.pack("<II", 0xAA55AA55, 100)
        data = struct.pack("<4I", 5, len(payload), 1, 0xFFFFFFFF) + struct.pack("<4I", len(payload), 0, 2, 0xFFFFFFFF) + payload
        with self.assertRaisesRegex(nuwriter.NuWriterError, "truncated loader DDR"):
            nuwriter.validate_pack(self.config(), data)


class IntegratedPackTests(unittest.TestCase):
    def test_cli_json_generates_data_environment_and_partition_for_all_media(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, env = root / "data.bin", root / "env.txt"
            source.write_bytes(b"data")
            env.write_bytes(b"key=value\n")
            for media in ("spinand", "spinor", "nand", "sd", "emmc"):
                with self.subTest(media=media):
                    output, config = root / (media + ".bin"), root / (media + ".json")
                    images = [{"file": str(source), "offset": "0x100000", "type": 3},
                              {"file": str(env), "offset": "0x80000", "type": "env"}]
                    if media in {"sd", "emmc"}:
                        images.append({"type": "partition", "partition": {"count": 1, "reserved_size": 32, "sizes": [0]}})
                    config.write_text(nuwriter.json.dumps({"mode": media, "output": str(output), "image": images}), encoding="utf-8")
                    with patch.object(nuwriter, "run_pre_attach_hook") as hook, patch.object(nuwriter, "discover_devices") as discover:
                        self.assertEqual(nuwriter.main(["-p", str(config), "--check"]), 0)
                        self.assertFalse(output.exists())
                        self.assertEqual(nuwriter.main(["-p", str(config)]), 0)
                        hook.assert_not_called()
                        discover.assert_not_called()
                    self.assertEqual([child[2] for child in nuwriter.parse_pack(output.read_bytes())], [0, 1, 3] if media in {"sd", "emmc"} else [0, 1])

    def test_pack_api_accepts_paths_and_does_not_overwrite_ddr_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            loader, ddr = root / "loader.bin", root / "ddr.ini"
            loader.write_bytes(b"loader")
            original = Path(nuwriter.__file__).parent / "sys_cfg" / "NUC980DK71YC.ini"
            ddr.write_bytes(original.read_bytes())
            images = [{"file": loader, "type": "loader", "offset": 0, "ddr_ini": ddr}]
            with self.assertRaisesRegex(nuwriter.NuWriterError, "cannot overwrite"):
                nuwriter.create_pack_file(images, ddr, media="nand")
            self.assertEqual(ddr.read_bytes(), original.read_bytes())
            output = nuwriter.create_pack_file(images, root / "pack.bin", media="nand")
            self.assertEqual(nuwriter.parse_pack(output.read_bytes())[0][2], 2)

    def test_conflicting_loader_aliases_are_not_silently_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "loader.bin"
            source.write_bytes(b"loader")
            for values in ({"offset": 0, "address": 0x1000},
                           {"exec_addr": 0x200, "execute_address": 0x8000},
                           {"read_status_cmd": 15, "read_status_command": 255}):
                with self.subTest(values=values):
                    image = {"file": source, "type": "loader", "ddr_ini": "NUC980DK71YC.ini", **values}
                    with self.assertRaisesRegex(nuwriter.NuWriterError, "conflict"):
                        nuwriter.create_pack_file([image], root / "pack.bin", media="nand")

    def test_create_pack_file_supports_loader_env_data_for_all_media(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            loader, env, data = root / "loader.bin", root / "env.txt", root / "data.bin"
            loader.write_bytes(b"loader")
            env.write_bytes(b"key=value\r\n")
            data.write_bytes(b"data")
            images = [{"file": str(loader), "offset": "0", "type": 2, "ddr_ini": "NUC980DK71YC.ini",
                       "quad_read_cmd": 107, "read_status_cmd": 15, "write_status_cmd": 31,
                       "status_value": 24, "dummy_byte": 1, "page_size": 2048, "spare_area": 64},
                      {"file": str(env), "offset": "0x80000", "type": "env"},
                      {"file": str(data), "offset": "0x100000", "type": 3}]
            for media in ("spinand", "spinor", "nand", "sd", "emmc"):
                with self.subTest(media=media):
                    output = nuwriter.create_pack_file(images, root / (media + ".bin"), media=media)
                    blob = output.read_bytes()
                    children = nuwriter.parse_pack(blob)
                    self.assertEqual([child[2] for child in children], [2, 1, 0])
                    self.assertEqual(children[0][1][:4], b" TVN")
                    self.assertEqual(len(children[1][1]), 0x20000 if media == "spinand" else 0x10000)
                    self.assertEqual(children[2][1], b"data")
                    self.assertEqual(struct.unpack_from("<I", blob, 4)[0], ((len(blob) + 0xFFFF) // 0x10000) * 0x10000)

    def test_sd_partition_json_and_raw_record_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = {"count": 2, "reserved_size": 32, "sizes": [128, 0]}
            output = nuwriter.create_pack_file([{"type": "partition", "partition": settings}], root / "sd.bin", media="emmc")
            header, payload, kind = nuwriter.parse_pack(output.read_bytes())[0]
            self.assertEqual((len(payload), kind), (48, 3))
            self.assertEqual(struct.unpack_from("<4I", payload), (0, 2, 32, 0xFFFFFFFF))
            self.assertEqual(struct.unpack_from("<I", header, 4)[0], 0xFFFFFFFF)
            record = root / "partition.bin"
            record.write_bytes(payload)
            raw_output = nuwriter.create_pack_file([{"type": "partition", "file": str(record)}], root / "raw.bin", media="sd")
            self.assertEqual(nuwriter.parse_pack(raw_output.read_bytes())[0][1], payload)

    def test_partition_is_rejected_for_flash_and_invalid_geometry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = {"type": "partition", "partition": {"count": 2, "reserved_size": 32, "sizes": [128, 0]}}
            for media in ("spinand", "spinor", "nand"):
                with self.subTest(media=media), self.assertRaises(nuwriter.NuWriterError):
                    nuwriter.create_pack_file([image], root / "bad.bin", media=media)
            with self.assertRaises(nuwriter.NuWriterError):
                nuwriter.partition_payload({"count": 2, "reserved_size": 32, "sizes": [0, 0]})

    def test_loader_image_parameters_override_global_storage_and_ddr(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "loader.bin"
            path.write_bytes(b"loader")
            config = fixture_config()
            config.pack = True
            parameters = {"ddr_ini": "NUC980DK71YC.ini", "page_size": 4096, "spare_area": 128,
                          "quad_read_cmd": 0x6B, "read_status_cmd": 0x0F, "write_status_cmd": 0x1F,
                          "status_value": 0x18, "dummy_byte": 1}
            image = nuwriter.Image(path, 2, 0x200, 0, parameters)
            prepared = nuwriter.prepare_image(config, image)
            header = nuwriter.loader_header(config, prepared)
            self.assertEqual(struct.unpack_from("<HH5B", header, 16), (4096, 128, 0x6B, 0x0F, 0x1F, 0x18, 1))
            expected = nuwriter.formatted_ddr(config, "NUC980DK71YC.ini")
            self.assertEqual(prepared.data[:prepared.init_size], expected)

    def test_ma35_json_tags_accept_generator_loader_parameters(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            loader = root / "loader.bin"
            loader.write_bytes(b"loader")
            output = root / "pack.bin"
            config = root / "pack.json"
            config.write_text(nuwriter.json.dumps({"mode": "spinand", "output": str(output), "image": [{
                "file": str(loader), "offset": "0", "type": 2, "execute_address": "0x200",
                "ddr_ini": "NUC980DK71YC.ini", "page_size": 2048, "spare_area": 64,
                "quad_read_cmd": 107, "read_status_cmd": 15, "write_status_cmd": 31,
                "status_value": 24, "dummy_byte": 1}]}), encoding="utf-8")
            self.assertEqual(nuwriter.main(["-p", str(config)]), 0)
            child = nuwriter.parse_pack(output.read_bytes())[0]
            self.assertEqual(child[2], 2)
            self.assertEqual(struct.unpack_from("<HH5B", child[1], 16), (2048, 64, 107, 15, 31, 24, 1))

    def test_environment_defaults_and_growth_for_all_media(self):
        for mode, block_size in (("SPINAND", 0x20000), ("SPINOR", 0x10000),
                                 ("NAND", 0x10000), ("SD", 0x10000)):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                config = fixture_config()
                config.mode, config.pack = mode, True
                path = Path(directory) / "env.txt"
                image = nuwriter.Image(path, 1, 0, 0)
                path.write_bytes(b"key=value\r\n")
                prepared = nuwriter.prepare_image(config, image)
                self.assertEqual(len(prepared.data), block_size)
                self.assertEqual(struct.unpack_from("<I", prepared.data)[0], nuwriter.zlib.crc32(prepared.data[4:]))
                path.write_bytes(b"key=" + b"v" * block_size)
                prepared = nuwriter.prepare_image(config, image)
                self.assertEqual(len(prepared.data), block_size * 2)

    def test_environment_explicit_payload_size_and_alignment(self):
        with tempfile.TemporaryDirectory() as directory:
            config = fixture_config()
            config.pack = True
            path = Path(directory) / "env.txt"
            path.write_bytes(b"key=value\n")
            image = nuwriter.Image(path, 1, 0, 0, {"env_size": 0x40000 - 4})
            self.assertEqual(len(nuwriter.prepare_image(config, image).data), 0x40000)
            image.parameters["env_size"] = 123
            with self.assertRaisesRegex(nuwriter.NuWriterError, "align"):
                nuwriter.prepare_image(config, image)

    def test_loader_header_field_widths_are_validated(self):
        config = fixture_config()
        image = nuwriter.Image(Path("loader.bin"), 2, 0x200, 0, {"page_size": 0x10000})
        prepared = nuwriter.PreparedImage(image, b"loader", 6)
        with self.assertRaisesRegex(nuwriter.NuWriterError, "protocol field widths"):
            nuwriter.loader_header(config, prepared)
        with self.assertRaisesRegex(nuwriter.NuWriterError, "Image file is required"):
            nuwriter.prepare_image(config, nuwriter.Image(None, 0, 0, 0))


class CliTests(unittest.TestCase):
    def pack_config(self, directory):
        path = Path(directory) / "data.bin"
        path.write_bytes(b"abc")
        ini = Path(directory) / "run.ini"
        output = Path(directory) / "pack.bin"
        ini.write_text(
            f"[RUN]\nmode=SPINOR\npack=yes\npack_path={output}\n"
            f"[SPINOR]\nrun=program\nimage_num=1\nimage0_type=data\nimage0_path={path}\n",
            encoding="utf-8",
        )
        return ini, output

    def test_check_does_not_import_usb_or_write_pack(self):
        with tempfile.TemporaryDirectory() as directory:
            ini, output = self.pack_config(directory)
            with patch.object(nuwriter.importlib, "import_module", side_effect=AssertionError("USB imported")):
                self.assertEqual(nuwriter.main([str(ini), "--check"]), 0)
            self.assertFalse(output.exists())

    def test_offline_pack_runs_without_usb(self):
        with tempfile.TemporaryDirectory() as directory:
            ini, output = self.pack_config(directory)
            with patch.object(nuwriter.importlib, "import_module", side_effect=AssertionError("USB imported")):
                self.assertEqual(nuwriter.main([str(ini)]), 0)
            self.assertEqual(nuwriter.parse_pack(output.read_bytes())[0][1], b"abc")

    def test_missing_input_returns_error_before_discovery(self):
        with tempfile.TemporaryDirectory() as directory:
            ini, output = self.pack_config(directory)
            (Path(directory) / "data.bin").unlink()
            with patch.object(nuwriter, "discover_devices") as discover:
                self.assertEqual(nuwriter.main([str(ini)]), 1)
            discover.assert_not_called()

    def test_pack_output_cannot_overwrite_input(self):
        with tempfile.TemporaryDirectory() as directory:
            ini, output = self.pack_config(directory)
            config = nuwriter.RunConfig(ini)
            config.ini.set("RUN", "pack_path", str(Path(directory) / "data.bin"))
            with patch.object(nuwriter, "RunConfig", return_value=config):
                self.assertEqual(nuwriter.main([str(ini)]), 1)
            self.assertEqual((Path(directory) / "data.bin").read_bytes(), b"abc")

    def test_multiple_devices_require_explicit_selection(self):
        devices = [SimpleNamespace(bus=1, port_numbers=(port,), address=port) for port in (3, 2)]
        with self.assertRaisesRegex(nuwriter.NuWriterError, "Multiple"):
            nuwriter.select_devices(devices)
        self.assertEqual(nuwriter.select_devices(devices, selection="1:2"), [devices[1]])
        self.assertEqual(nuwriter.select_devices(devices, all_devices=True), [devices[1], devices[0]])

    def test_partial_bulk_read_is_allowed_only_with_minimum(self):
        device = Mock()
        device.read.return_value = b"abc"
        transport = nuwriter.UsbTransport(device)
        self.assertEqual(transport.read(4096, minimum=3), b"abc")
        with self.assertRaises(nuwriter.NuWriterError):
            transport.read(4096, minimum=4)

    def test_failed_operation_returns_nonzero_and_closes_usb(self):
        with tempfile.TemporaryDirectory() as directory:
            ini, output = self.pack_config(directory)
            config = nuwriter.RunConfig(ini)
            config.pack = False
            config.ini.add_section("DDR")
            config.ini.set("DDR", "ddr", "NUC980DF61YC.ini")
            device = SimpleNamespace(bus=1, port_numbers=(2,), address=3)
            session, writer = Mock(), Mock()
            writer.attach.return_value = {"nand_page_size": 0, "spinand_page_size": 0, "emmc_blocks": 0}
            writer.run.side_effect = nuwriter.NuWriterError("Simulated transfer failure")
            session_class = Mock(return_value=session)
            session_class.device_identity.side_effect = lambda target: (target.bus, target.port_numbers)
            with patch.multiple(nuwriter, RunConfig=Mock(return_value=config),
                                run_pre_attach_hook=Mock(), discover_devices=Mock(return_value=[device]),
                                UsbSession=session_class, Nuc980Writer=Mock(return_value=writer)):
                self.assertEqual(nuwriter.main([str(ini)]), 1)
            session.close.assert_called_once()


class CompatibleCliTests(unittest.TestCase):
    def configured_command(self, arguments):
        configurations = []
        with patch.object(nuwriter, "preflight", side_effect=lambda config: configurations.append(config) or []):
            self.assertEqual(nuwriter.main(arguments + ["--check"]), 0)
        return configurations[0]

    def test_attach_check_uses_ddr_settings_not_run_ini(self):
        with patch.object(nuwriter, "discover_devices") as discover:
            self.assertEqual(nuwriter.main(["-a", "NUC980DF61YC.ini", "--check"]), 0)
        discover.assert_not_called()

    def test_attach_does_not_program_images(self):
        config = fixture_config()
        config.operation = "attach"
        transport = Mock()
        nuwriter.Nuc980Writer(config, transport).run([])
        transport.write.assert_not_called()

    def test_write_and_verify_map_to_native_image(self):
        config = self.configured_command(["-a", "NUC980DF61YC.ini", "-w", "spinor", "0x200000", "image.bin", "-o", "verify"])
        self.assertEqual((config.mode, config.operation), ("SPINOR", "program_verify"))
        self.assertTrue(config.initialize)
        self.assertEqual(config.images, [nuwriter.Image(Path("image.bin"), 0, 0, 0x200000)])

    def test_separate_write_uses_existing_xusb_without_ddr_initialization(self):
        config = self.configured_command(["-w", "spinor", "0x200000", "image.bin"])
        self.assertFalse(config.initialize)
        self.assertEqual(config.operation, "program")

    def test_sdram_execute_and_emmc_alias(self):
        config = self.configured_command(["-w", "ddr", "0x8000", "image.bin", "-o", "execute"])
        self.assertEqual(config.mode, "SDRAM")
        self.assertEqual(config.text("SDRAM", "option"), "run")
        config = self.configured_command(["-w", "emmc", "0x200000", "image.bin"])
        self.assertEqual(config.mode, "SD")

    def test_read_and_erase_ranges_are_bytes_not_native_blocks(self):
        for flag, operation in (("-r", "read"), ("-e", "erase")):
            with self.subTest(operation=operation):
                arguments = [flag, "nand", "0x20000", "0x40000"]
                if flag == "-r":
                    arguments.append("out.bin")
                config = self.configured_command(arguments)
                self.assertEqual(config.byte_range, (0x20000, 0x40000))
                writer = nuwriter.Nuc980Writer(config, Mock())
                writer.info = {"nand_page_size": 2048, "nand_page_per_block": 64, "nand_block_count": 1024}
                writer.resolve_byte_range()
                prefix = "read" if operation == "read" else "erase"
                self.assertEqual(config.number("NAND", prefix + "_start_blocks"), 1)
                self.assertEqual(config.number("NAND", prefix + "_offset_blocks"), 2)

    def test_unaligned_byte_range_is_rejected_without_transfer(self):
        config = self.configured_command(["-e", "spinor", "1", "0x10000"])
        transport = Mock()
        with self.assertRaisesRegex(nuwriter.NuWriterError, "aligned"):
            nuwriter.Nuc980Writer(config, transport).run([])
        transport.write.assert_not_called()

    def test_read_all_uses_reported_nand_capacity(self):
        config = self.configured_command(["-r", "nand", "all", "out.bin"])
        writer = nuwriter.Nuc980Writer(config, Mock())
        writer.info = {"nand_page_size": 2048, "nand_page_per_block": 64, "nand_block_count": 8}
        writer.resolve_byte_range()
        self.assertEqual(config.number("NAND", "read_offset_blocks"), 8)

    def test_unsupported_commands_fail_before_device_discovery(self):
        commands = (["-w", "otp", "otp.json"], ["-r", "reg", "0xB0000000"],
                    ["-e", "sd", "all"], ["-w", "spinor", "0", "image.bin", "-o", "scrub"],
                    ["-c", "config.json"], ["-s", "sd", "0x1000"])
        for arguments in commands:
            with self.subTest(arguments=arguments), patch.object(nuwriter, "discover_devices") as discover:
                self.assertEqual(nuwriter.main(arguments), 1)
                discover.assert_not_called()


class CompatibleSafetyTests(unittest.TestCase):
    def test_invalid_ranges_are_rejected_by_check_before_usb(self):
        commands = (["-r", "spinor", "all", "out.bin"],
                    ["-r", "spinor", "all", "out.bin", "--flash-size", "1"],
                    ["-e", "spinor", "1", "0x10000"],
                    ["-r", "sd", "1", "512", "out.bin"],
                    ["-r", "nand", "0xFFFFFFF0", "0x10000", "out.bin"])
        for arguments in commands:
            with self.subTest(arguments=arguments), patch.object(nuwriter, "discover_devices") as discover:
                self.assertEqual(nuwriter.main(arguments + ["--check"]), 1)
                discover.assert_not_called()

    def test_spi_nor_read_all_accepts_explicit_aligned_capacity(self):
        self.assertEqual(nuwriter.main(["-r", "spinor", "all", "out.bin", "--flash-size", "0x800000", "--check"]), 0)

    def test_windows_cli_read_accepts_single_byte_lengths(self):
        for mode, read_size in (("NAND", 1), ("SPINOR", 1), ("SD", 4096), ("SPINAND", 4096)):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "read.bin"
                config = fixture_config()
                config.mode, config.operation, config.compatible = mode, "read", True
                config.byte_range = (0, 1)
                config.ini.set(mode, "read_path", str(path))
                transport = Mock()
                transport.read.return_value = b"a" + bytes(read_size - 1)
                writer = nuwriter.Nuc980Writer(config, transport)
                writer.info = {"nand_page_size": 2048, "nand_page_per_block": 64, "nand_block_count": 1024,
                               "spinand_page_size": 2048, "spinand_page_per_block": 64, "spinand_block_count": 1024,
                               "emmc_blocks": 2048}
                writer.run([])
                transport.read.assert_called_once_with(read_size, minimum=1)
                self.assertEqual(path.read_bytes(), b"a")
                self.assertEqual(struct.unpack_from("<I", transport.write.call_args_list[0].args[0], 4)[0], 1)

    def test_query_info_does_not_download_ddr(self):
        config = fixture_config()
        transport = Mock()
        transport.read.return_value = bytes(84)
        nuwriter.Nuc980Writer(config, transport).get_info()
        transport.write.assert_called_once_with(config.user_info())
        transport.send_chunks.assert_not_called()

    def test_cli_read_generates_native_offsets_for_each_media(self):
        capture = CompatibleCliTests().configured_command
        for media, unit, native_offset in (("nand", 4096, 1), ("spinand", 4096, 1),
                                            ("spinor", 65536, 65536), ("sd", 512, 512)):
            with self.subTest(media=media), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "out.bin"
                config = capture(["-r", media, str(unit), str(unit), str(path)])
                transport = Mock()
                transport.read.return_value = bytes(4096)
                writer = nuwriter.Nuc980Writer(config, transport)
                writer.info = {"nand_page_size": 2048, "nand_page_per_block": 2, "nand_block_count": 8,
                               "spinand_page_size": 2048, "spinand_page_per_block": 2, "spinand_block_count": 8,
                               "emmc_blocks": 8}
                writer.run([])
                header = transport.write.call_args_list[0].args[0]
                self.assertEqual(struct.unpack_from("<I", header, 4)[0], unit)
                self.assertEqual(struct.unpack_from("<I", header, 36)[0], native_offset)
                self.assertEqual(path.stat().st_size, unit)

    def test_pack_member_alignment_is_validated_before_programming(self):
        config = fixture_config()
        config.compatible = True
        config.mode = "SPINOR"
        data = struct.pack("<4I", 5, 1, 1, 0xFFFFFFFF) + struct.pack("<4I", 1, 1, 0, 0xFFFFFFFF) + b"a"
        image = nuwriter.PreparedImage(nuwriter.Image(Path("pack.bin"), 3, 0, 0), data, len(data))
        transport = Mock()
        with self.assertRaisesRegex(nuwriter.NuWriterError, "aligned"):
            nuwriter.Nuc980Writer(config, transport).run([image])
        transport.write.assert_not_called()

    def test_massproduct_queries_existing_xusb_and_closes_each_target(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "image.bin"
            path.write_bytes(b"abc")
            devices = [SimpleNamespace(bus=1, port_numbers=(port,), address=port) for port in (3, 2)]
            sessions, writers = [Mock(), Mock()], [Mock(), Mock()]
            order = []
            for index, writer in enumerate(writers):
                writer.get_info.return_value = {"nand_page_size": 0, "spinand_page_size": 0, "emmc_blocks": 0}
                writer.run.side_effect = lambda prepared, target=index: order.append(target)
            with patch.object(nuwriter, "discover_devices", return_value=devices), \
                 patch.object(nuwriter, "UsbSession", side_effect=sessions) as session_class, \
                 patch.object(nuwriter, "Nuc980Writer", side_effect=writers):
                session_class.device_identity.side_effect = lambda target: (target.bus, target.port_numbers)
                self.assertEqual(nuwriter.main(["-m", "-w", "spinor", "0", str(path)]), 0)
            self.assertEqual(order, [0, 1])
            for session, writer in zip(sessions, writers):
                session.close.assert_called_once()
                writer.get_info.assert_called_once()
                writer.attach.assert_not_called()

    def test_invalid_write_options_and_massproduct_read_are_rejected(self):
        commands = (["-w", "spinor", "0", "image.bin", "-o", "execute"],
                    ["-w", "ddr", "0", "image.bin", "-o", "verify"],
                    ["-w", "nand", "0", "loader.bin", "-t", "loader"],
                    ["-m", "-r", "sd", "0", "512", "out.bin"],
                    ["-e", "nand", "all", "-o", "withbad"])
        for arguments in commands:
            with self.subTest(arguments=arguments), patch.object(nuwriter, "discover_devices") as discover:
                self.assertEqual(nuwriter.main(arguments + ["--check"]), 1)
                discover.assert_not_called()


class PublicApiTests(unittest.TestCase):
    def test_ma35_public_ids_are_not_windows_wire_ids(self):
        self.assertEqual(nuwriter.get_media("spinand"), 4)
        self.assertEqual(nuwriter.MEDIA["SPINAND"], 9)
        self.assertEqual(nuwriter.get_media("emmc"), 2)
        self.assertEqual(nuwriter.get_media("sd"), 7)
        self.assertEqual(nuwriter.get_media("reg"), nuwriter.DEV_UNKNOWN)
        self.assertEqual(nuwriter.get_option("verify"), 3)
        self.assertEqual(nuwriter.get_type("uboot"), 2)
        self.assertEqual(nuwriter.get_type("tfa"), nuwriter.IMG_UNKNOWN)

    def test_program_api_routes_verify_to_existing_cli(self):
        with patch.object(nuwriter, "main", return_value=17) as main:
            self.assertEqual(nuwriter.do_img_program(nuwriter.DEV_SPINAND, 0x200000, "image.bin", nuwriter.OPT_VERIFY), 17)
        main.assert_called_once_with(["-w", "spinand", "0x200000", "image.bin", "-o", "verify"])

    def test_attach_and_pack_api_share_cli_settings(self):
        with patch.object(nuwriter, "main", return_value=0) as main:
            self.assertEqual(nuwriter.do_attach("NUC980DK71YC.ini", check=True), 0)
            self.assertEqual(main.call_args.args[0], ["-a", "NUC980DK71YC.ini", "--check"])
            nuwriter.do_pack_program(nuwriter.DEV_SPINAND, "pack.bin", ddr="NUC980DK71YC.ini")
            self.assertEqual(main.call_args.args[0], ["-w", "spinand", "pack.bin", "--ddr", "NUC980DK71YC.ini"])
            nuwriter.do_pack("pack.json", media=nuwriter.DEV_SPINAND, output="pack.bin")
            self.assertEqual(main.call_args.args[0], ["-p", "pack.json", "--media", "spinand", "--output", "pack.bin"])

    def test_read_default_is_one_byte_and_zero_length_means_all(self):
        with patch.object(nuwriter, "main", return_value=0) as main:
            nuwriter.do_img_read(nuwriter.DEV_NAND, 0, "out.bin")
            self.assertEqual(main.call_args.args[0], ["-r", "nand", "0x0", "0x1", "out.bin"])
            nuwriter.do_img_read("spinand", 0, "out.bin", length=0)
            self.assertEqual(main.call_args.args[0], ["-r", "spinand", "all", "out.bin"])

    def test_erase_all_and_range_use_byte_arguments(self):
        with patch.object(nuwriter, "main", return_value=0) as main:
            nuwriter.do_img_erase(nuwriter.DEV_SPINAND, 0)
            self.assertEqual(main.call_args.args[0], ["-e", "spinand", "all"])
            nuwriter.do_img_erase(nuwriter.DEV_SPINAND, 0x20000, 0x40000)
            self.assertEqual(main.call_args.args[0], ["-e", "spinand", "0x20000", "0x40000"])

    def test_loader_api_passes_windows_settings_and_initialization(self):
        with patch.object(nuwriter, "main", return_value=0) as main:
            nuwriter.do_img_program(nuwriter.DEV_SPINAND, 0, "loader.bin", image_type=nuwriter.IMG_UBOOT,
                                   exec_addr=0x200, ddr="NUC980DK71YC.ini", initialize=True)
        self.assertEqual(main.call_args.args[0], ["-w", "spinand", "0x0", "loader.bin", "-a",
                                                "--ddr", "NUC980DK71YC.ini", "--exec-addr", "512", "--type", "uboot"])

    def test_invalid_api_requests_do_not_reach_hardware_entry(self):
        with patch.object(nuwriter, "main") as main:
            for operation in (lambda: nuwriter.do_img_program("reg", 0, "image.bin"),
                              lambda: nuwriter.do_img_erase("spinand", 1, 0),
                              lambda: nuwriter.do_img_read("spinand", 1, "out.bin", length=0),
                              lambda: nuwriter.do_img_program("spinand", 0, "image.bin", option="scrub"),
                              lambda: nuwriter.do_img_program("spinand", 0, "image.bin", image_type=1)):
                with self.assertRaises(nuwriter.NuWriterError):
                    operation()
            main.assert_not_called()

    def test_massproduct_switch_keeps_api_reads_single_target(self):
        with patch.object(nuwriter, "mp_mode", False), patch.object(nuwriter, "main", return_value=0) as main:
            nuwriter.switch_mp_mode(True)
            nuwriter.do_img_program("spinand", 0, "image.bin")
            self.assertIn("-m", main.call_args.args[0])
            nuwriter.do_img_read("spinand", 0, "out.bin")
            self.assertNotIn("-m", main.call_args.args[0])

    def test_no_arguments_prints_help_like_ma35_without_usb(self):
        with patch.object(nuwriter, "discover_devices") as discover:
            self.assertEqual(nuwriter.main([]), 0)
            discover.assert_not_called()

    def test_api_argument_errors_do_not_exit_the_calling_process(self):
        with patch.object(nuwriter, "discover_devices") as discover:
            with self.assertRaisesRegex(nuwriter.NuWriterError, "Invalid API arguments"):
                nuwriter.do_img_read(nuwriter.DEV_SD, 0, "out.bin", timeout=0, check=True)
            discover.assert_not_called()

    def test_api_passes_usb_trace_without_changing_operation(self):
        with patch.object(nuwriter, "main", return_value=0) as main:
            nuwriter.do_img_read("spinand", 0, "probe.bin", check=True, trace_usb=True)
        main.assert_called_once_with(["-r", "spinand", "0x0", "0x1", "probe.bin", "--check", "--trace-usb"])


class DramDownloadTests(unittest.TestCase):
    def test_cli_prepares_kernel_and_dtb_before_usb_access(self):
        with tempfile.TemporaryDirectory() as directory:
            kernel, dtb = Path(directory) / "zImage", Path(directory) / "board.dtb"
            kernel.write_bytes(b"kernel")
            dtb.write_bytes(b"device tree")
            original = nuwriter.preflight
            captured = []
            def prepare(config):
                result = original(config)
                captured.append(result)
                return result
            with patch.object(nuwriter, "preflight", side_effect=prepare), \
                 patch.object(nuwriter, "discover_devices") as discover:
                result = nuwriter.main(["-a", "NUC980DK71YC.ini", "-w", "ddr", "0x8000", str(kernel),
                                        "-o", "execute", "--dtb", str(dtb), "--dtb-addr", "0x1400000", "--check"])
            self.assertEqual(result, 0)
            self.assertEqual(captured, [(b"kernel", 0x8000, True, b"device tree", 0x1400000)])
            discover.assert_not_called()

    def test_dtb_options_are_paired_and_ddr_only(self):
        cases = (["-w", "ddr", "0x8000", "zImage", "--dtb", "board.dtb"],
                 ["-w", "ddr", "0x8000", "zImage", "--dtb-addr", "0x1400000"],
                 ["-w", "spinand", "0", "image.bin", "--dtb", "board.dtb", "--dtb-addr", "0x1400000"],
                 ["-a", "NUC980DK71YC.ini", "--dtb", "board.dtb", "--dtb-addr", "0x1400000"])
        with patch.object(nuwriter, "discover_devices") as discover:
            for arguments in cases:
                with self.subTest(arguments=arguments):
                    self.assertEqual(nuwriter.main(arguments + ["--check"]), 1)
            discover.assert_not_called()

    def test_dram_and_dtb_ranges_cannot_overlap(self):
        with tempfile.TemporaryDirectory() as directory:
            kernel, dtb = Path(directory) / "kernel", Path(directory) / "board.dtb"
            kernel.write_bytes(bytes(64))
            dtb.write_bytes(bytes(32))
            with patch.object(nuwriter, "discover_devices") as discover:
                result = nuwriter.main(["-w", "ddr", "0x8000", str(kernel), "--dtb", str(dtb),
                                        "--dtb-addr", "0x8020", "--check"])
            self.assertEqual(result, 1)
            discover.assert_not_called()

    def test_api_passes_dtb_settings_to_the_existing_cli(self):
        with patch.object(nuwriter, "main", return_value=0) as main:
            nuwriter.do_img_program(nuwriter.DEV_DDR_SRAM, 0x8000, "zImage", nuwriter.OPT_EXECUTE,
                                   dtb="board.dtb", dtb_addr=0x1400000, check=True)
        main.assert_called_once_with(["-w", "ddr", "0x8000", "zImage", "-o", "execute", "--check",
                                      "--dtb", "board.dtb", "--dtb-addr", str(0x1400000)])

    def test_bootargs_override_changes_downloaded_copy_not_source_dtb(self):
        from pyfdt.pyfdt import FdtBlobParse
        source = Path(__file__).resolve().parent.parent / "numaker-iot-nuc980g2" / "nuc980-iot-128m-bmc.dtb"
        original = source.read_bytes()
        bootargs = "noinitrd ubi.mtd=rofs root=ubi0:rootfs rootfstype=ubifs console=ttyS0,115200n8"
        patched = nuwriter.dtb_with_bootargs(original, bootargs)
        tree = FdtBlobParse(io.BytesIO(patched)).to_fdt()
        self.assertEqual(tree.resolve_path("/chosen/bootargs").strings, [bootargs])
        self.assertEqual(tree.resolve_path("/apb/spi@b0060000/flash@0/partition@3/label").strings, ["rofs"])
        self.assertEqual(source.read_bytes(), original)

    def test_bootargs_without_dtb_or_invalid_dtb_fails_offline(self):
        with patch.object(nuwriter, "discover_devices") as discover:
            self.assertEqual(nuwriter.main(["-w", "ddr", "0x8000", "zImage", "--bootargs", "root=ubi0:rootfs", "--check"]), 1)
            discover.assert_not_called()
        with self.assertRaisesRegex(nuwriter.NuWriterError, "Cannot update DTB"):
            nuwriter.dtb_with_bootargs(b"not a DTB", "root=ubi0:rootfs")

    def test_listing_or_version_cannot_ignore_dram_options(self):
        for arguments in (["--list", "--bootargs", "root=ubi0:rootfs"],
                          ["--list", "--bootargs", ""],
                          ["--version", "--dtb", "board.dtb", "--dtb-addr", "0x1400000"]):
            with self.subTest(arguments=arguments), patch.object(nuwriter, "discover_devices") as discover:
                with self.assertRaises(SystemExit) as raised:
                    nuwriter.main(arguments)
                self.assertEqual(raised.exception.code, 2)
                discover.assert_not_called()


class CompatiblePackTests(unittest.TestCase):
    def test_pack_switch_overrides_ini_run_operation_without_usb(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "data.bin"
            image.write_bytes(b"abc")
            ini = Path(directory) / "config.ini"
            output = Path(directory) / "pack.bin"
            for mode, operation in (("SPINOR", "read"), ("SD", "format")):
                with self.subTest(mode=mode):
                    ini.write_text(f"[RUN]\nmode={mode}\npack=no\n[{mode}]\nrun={operation}\nimage_num=1\nimage0_type=data\nimage0_path={image}\n", encoding="utf-8")
                    with patch.object(nuwriter, "discover_devices") as discover:
                        self.assertEqual(nuwriter.main(["-p", str(ini), "--output", str(output)]), 0)
                    discover.assert_not_called()
                    self.assertEqual(nuwriter.parse_pack(output.read_bytes())[0][1], b"abc")

    def test_json_image_list_produces_nuc980_not_ma35_pack(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "image.bin"
            image.write_bytes(b"abc")
            config = Path(directory) / "config.json"
            output = Path(directory) / "pack.bin"
            config.write_text(nuwriter.json.dumps({"image": [{"file": str(image), "offset": "0x200000", "type": 3}]}), encoding="utf-8")
            with patch.object(nuwriter.importlib, "import_module", side_effect=AssertionError("USB imported")):
                self.assertEqual(nuwriter.main(["-p", str(config), "--media", "spinor", "--output", str(output), "--check"]), 0)
                self.assertFalse(output.exists())
                self.assertEqual(nuwriter.main(["-p", str(config), "--media", "spinor", "--output", str(output)]), 0)
            data = output.read_bytes()
            self.assertEqual(struct.unpack_from("<I", data)[0], 5)
            header, payload, kind = nuwriter.parse_pack(data)[0]
            self.assertEqual((struct.unpack_from("<I", header, 4)[0], payload, kind), (0x200000, b"abc", 0))

    def test_json_does_not_reinterpret_tfa_type_as_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(nuwriter.json.dumps({"mode": "SPINOR", "image": [{"file": "image.bin", "type": 1}]}), encoding="utf-8")
            with patch.object(nuwriter, "discover_devices") as discover:
                self.assertEqual(nuwriter.main(["-p", str(path), "--check"]), 1)
            discover.assert_not_called()

    def test_json_loader_requires_explicit_boot_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(nuwriter.json.dumps({"mode": "SPINOR", "image": [{"file": "loader.bin", "type": 2}]}), encoding="utf-8")
            self.assertEqual(nuwriter.main(["-p", str(path), "--check"]), 1)

    def test_json_loader_encodes_explicit_spinand_boot_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "loader.bin"
            image.write_bytes(b"abc")
            path, output = Path(directory) / "pack.json", Path(directory) / "pack.bin"
            document = {"mode": "SPINAND", "ddr": "NUC980DF61YC.ini", "output": str(output),
                        "storage": {"page_size": 2048, "spare_area": 64, "quad_read_command": 107,
                                    "read_status_command": 255, "write_status_command": 255,
                                    "status_value": 255, "dummy_bytes": 1},
                        "image": [{"file": str(image), "offset": "0", "type": 2, "exec_addr": "0x200"}]}
            path.write_text(nuwriter.json.dumps(document), encoding="utf-8")
            self.assertEqual(nuwriter.main(["-p", str(path)]), 0)
            header, payload, kind = nuwriter.parse_pack(output.read_bytes())[0]
            self.assertEqual(kind, 2)
            self.assertEqual(struct.unpack_from("<HH5B", payload, 16), (2048, 64, 107, 255, 255, 255, 1))


class EraseTimeoutTests(unittest.TestCase):
    def writer(self, transport, operation_timeout=300000):
        config = fixture_config()
        config.mode = "SPINAND"
        config.ini.set("SPINAND", "erase_all", "no")
        config.ini.set("SPINAND", "erase_start_blocks", "0")
        config.ini.set("SPINAND", "erase_offset_blocks", "1024")
        return nuwriter.Nuc980Writer(config, transport, operation_timeout=operation_timeout)

    def test_erase_ack_and_progress_use_operation_timeout(self):
        transport = Mock()
        transport.read_word.side_effect = [0x89, 1024, 0, 100]
        with patch.object(nuwriter.time, "monotonic", return_value=0):
            self.writer(transport).erase()
        self.assertEqual([call.kwargs["timeout"] for call in transport.read_word.call_args_list], [300000] * 4)
        header = transport.write.call_args.args[0]
        self.assertEqual(struct.unpack_from("<3I", header, 28), (1, 1024, 0))
        self.assertEqual(struct.unpack_from("<I", header, 8)[0], 0xFFFFFFFF)

    def test_remaining_budget_does_not_restart_for_each_word(self):
        transport = Mock()
        writer = self.writer(transport)
        with patch.object(nuwriter.time, "monotonic", side_effect=[1, 3]):
            writer.read_erase_word("test acknowledgement", 10)
            writer.read_erase_word("test progress", 10)
        self.assertEqual([call.kwargs["timeout"] for call in transport.read_word.call_args_list], [9000, 7000])

    def test_expired_budget_does_not_issue_another_usb_read(self):
        transport = Mock()
        with patch.object(nuwriter.time, "monotonic", return_value=11):
            with self.assertRaisesRegex(nuwriter.NuWriterError, "Timed out waiting for test progress"):
                self.writer(transport).read_erase_word("test progress", 10)
        transport.read_word.assert_not_called()

    def test_timeout_identifies_ack_block_count_or_progress(self):
        cases = (([OSError(10060, "Operation timed out")], "command acknowledgement"),
                 ([0x89, OSError(10060, "Operation timed out")], "block count"),
                 ([0x89, 1024, 0, OSError(10060, "Operation timed out")], "progress (last status=0)"))
        for replies, stage in cases:
            with self.subTest(stage=stage):
                transport = Mock()
                transport.read_word.side_effect = replies
                with patch.object(nuwriter.time, "monotonic", return_value=0):
                    with self.assertRaises(nuwriter.NuWriterError) as raised:
                        self.writer(transport).erase()
                self.assertIn(stage, str(raised.exception))
                self.assertIn("10060", str(raised.exception))

    def test_media_selection_timeout_has_erase_context(self):
        transport = Mock()
        transport.set_type.side_effect = OSError(10060, "Operation timed out")
        with self.assertRaisesRegex(nuwriter.NuWriterError, "SPINAND erase media selection"):
            self.writer(transport).erase()
        transport.write.assert_not_called()

    def test_transport_read_override_keeps_default_timeout_unchanged(self):
        device = Mock()
        device.read.return_value = bytes(4)
        transport = nuwriter.UsbTransport(device, timeout=10000)
        transport.read_word(timeout=300000)
        transport.read_word()
        self.assertEqual([call.kwargs["timeout"] for call in device.read.call_args_list], [300000, 10000])
        self.assertEqual(transport.timeout, 10000)


class WindowsEraseProtocolTests(unittest.TestCase):
    def writer(self, transport, erase_all):
        config = fixture_config()
        config.mode = "SPINAND"
        config.ini.set("SPINAND", "erase_all", "yes" if erase_all else "no")
        config.ini.set("SPINAND", "erase_start_blocks", "0")
        config.ini.set("SPINAND", "erase_offset_blocks", "1024")
        writer = nuwriter.Nuc980Writer(config, transport)
        writer.info = {"spinand_block_count": 1024, "spinand_page_size": 2048,
                       "spinand_page_per_block": 64, "spinand_die": 0}
        return writer

    def test_range_finishes_at_100_percent_without_another_read(self):
        transport = Mock()
        transport.read_word.side_effect = [0x89, 1024, 0, 50, 100]
        self.writer(transport, False).erase()
        self.assertEqual(transport.read_word.call_count, 5)
        header = transport.write.call_args.args[0]
        self.assertEqual(struct.unpack_from("<I", header, 8)[0], 0xFFFFFFFF)
        self.assertEqual(struct.unpack_from("<3I", header, 28), (1, 1024, 0))

    def test_all_uses_block_indexes_not_100_percent(self):
        transport = Mock()
        transport.read_word.side_effect = [0x89, 1024, 0, 100, 1023]
        self.writer(transport, True).erase()
        self.assertEqual(transport.read_word.call_count, 5)
        header = transport.write.call_args.args[0]
        self.assertEqual(struct.unpack_from("<I", header, 8)[0], 0xFFFFFFFF)
        self.assertEqual(struct.unpack_from("<3I", header, 28), (0, 1024, 0))

    def test_bad_ack_is_rejected_before_reading_block_count(self):
        transport = Mock()
        transport.read_word.return_value = 0x8A
        with self.assertRaisesRegex(nuwriter.NuWriterError, "Unexpected SPI NAND erase ACK"):
            self.writer(transport, True).erase()
        self.assertEqual(transport.read_word.call_count, 1)

    def test_wrong_block_count_is_rejected_before_progress(self):
        transport = Mock()
        transport.read_word.side_effect = [0x89, 512]
        with self.assertRaisesRegex(nuwriter.NuWriterError, "block-count mismatch"):
            self.writer(transport, True).erase()
        self.assertEqual(transport.read_word.call_count, 2)

    def test_firmware_error_sentinel_is_not_completion(self):
        for erase_all in (True, False):
            with self.subTest(erase_all=erase_all):
                transport = Mock()
                transport.read_word.side_effect = [0x89, 1024, 0xFFFF]
                with self.assertRaises(nuwriter.NuWriterError):
                    self.writer(transport, erase_all).erase()

    def test_multi_die_uses_combined_block_count(self):
        transport = Mock()
        transport.read_word.side_effect = [0x89, 2048, 0, 2047]
        writer = self.writer(transport, True)
        writer.info["spinand_die"] = 1
        self.assertEqual(writer.capacity(), 0x10000000)
        writer.erase()
        header = transport.write.call_args.args[0]
        self.assertEqual(struct.unpack_from("<I", header, 32)[0], 2048)


@unittest.skipUnless(os.name == "nt", "Windows batch scripts require cmd.exe")
class BatchScriptTests(unittest.TestCase):
    pack_scripts = (
        ("pack_spinand.bat", "spinand", "nuwriter-pack-spinand.bin"),
        ("pack_spinor.bat", "spinor", "nuwriter-pack-spinor.bin"),
        ("pack_nand.bat", "nand", "nuwriter-pack-nand.bin"),
        ("pack_sd_emmc.bat", "sd", "nuwriter-pack-sd-emmc.bin"),
    )

    def run_batch(self, fail_stage=None, missing_pack=False, missing_python=False, fail_code=17,
                  script_name="erase_flash_spinand.bat", check_only=False, missing_dtb=False,
                  mode=None, missing_boot_image=False, wrong_boot_address=False, trace_usb=False,
                  pack_arguments=None, missing_pack_config=False):
        with tempfile.TemporaryDirectory(prefix="nuwriter batch ! ") as directory:
            root = Path(directory)
            board = root / "numaker-iot-nuc980g2"
            tool = root / "NUC980_NuWriter"
            board.mkdir()
            (tool / "sys_cfg").mkdir(parents=True)
            source = Path(__file__).resolve().parent.parent / "numaker-iot-nuc980g2" / script_name
            batch = board / source.name
            batch.write_bytes(source.read_bytes())
            (tool / "sys_cfg" / "NUC980DK71YC.ini").write_text("test settings", encoding="ascii")
            if not missing_pack:
                (board / "nuwriter-pack.bin").write_bytes(b"test pack")
            kernel = bytearray(48)
            struct.pack_into("<I", kernel, 36, 0x016F2818)
            (board / "zImage").write_bytes(kernel)
            if not missing_dtb:
                (board / "nuc980-iot-128m-bmc.dtb").write_bytes(b"simulated DTB")
            for name, base in (("u-boot.bin", 0x00E00000), ("u-boot-spl.bin", 0x200)):
                if missing_boot_image and name == ("u-boot-spl.bin" if mode == "with-spl" else "u-boot.bin"):
                    continue
                image = bytearray(96)
                struct.pack_into("<I", image, 0, 0xEA000001)
                vector = 0x100000 if wrong_boot_address else base + 64
                struct.pack_into("<7I", image, 32, *([vector] * 7))
                (board / name).write_bytes(image)
            (tool / "ch341_reset_uart.py").write_text("raise SystemExit(0)\n", encoding="ascii")
            (tool / "nuwriter.py").write_text(
                "import json, os, sys\n"
                "arguments = sys.argv[1:]\n"
                "stage = 'check' if '--check' in arguments else 'pack' if '-p' in arguments else 'attach' if '-a' in arguments else 'erase' if '-e' in arguments else 'download' if 'ddr' in arguments else 'flash'\n"
                "code = int(os.environ['BATCH_FAIL_CODE']) if stage == os.environ.get('BATCH_FAIL_STAGE') else 0\n"
                "pack_output = arguments[arguments.index('--output') + 1] if '-p' in arguments else None\n"
                "if stage == 'pack' and code == 0:\n"
                "    with open(pack_output, 'wb') as output:\n"
                "        output.write(b'test generated pack')\n"
                "with open(os.environ['BATCH_TRACE'], 'a', encoding='utf-8') as output:\n"
                "    print(json.dumps({'stage': stage, 'arguments': arguments, 'cwd': os.getcwd(), 'output_exists': bool(pack_output and os.path.isfile(pack_output))}), file=output)\n"
                "sys.exit(code)\n",
                encoding="ascii",
            )
            trace = root / "trace.jsonl"
            working = root / "unrelated working directory"
            working.mkdir()
            if pack_arguments is not None:
                configuration = working / "pack config !"
                configuration.mkdir()
                (configuration / "payload.bin").write_bytes(b"test payload")
                if not missing_pack_config:
                    (configuration / "input.json").write_text(
                        '{"image": [{"file": "payload.bin", "offset": "0", "type": 0}]}',
                        encoding="ascii",
                    )
            environment = os.environ.copy()
            environment["PYTHON"] = str(root / "missing-python.exe") if missing_python else sys.executable
            environment["BATCH_TRACE"] = str(trace)
            environment["BATCH_FAIL_STAGE"] = fail_stage or ""
            environment["BATCH_FAIL_CODE"] = str(fail_code)
            arguments = ([mode] if mode is not None else []) + (["--check"] if check_only else [])
            arguments += (["--trace-usb"] if trace_usb else [])
            arguments += pack_arguments if pack_arguments is not None else []
            command = subprocess.list2cmdline([str(batch)] + arguments)
            shell = subprocess.list2cmdline([environment.get("COMSPEC", "cmd.exe")])
            result = subprocess.run(
                f'{shell} /d /s /c "{command}"',
                cwd=working, env=environment, capture_output=True, text=True, timeout=15,
            )
            records = [nuwriter.json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()] if trace.exists() else []
            return result, records

    def test_pack_batches_check_then_generate_from_the_json_directory(self):
        for script, media, output_name in self.pack_scripts:
            with self.subTest(script=script):
                result, records = self.run_batch(script_name=script, pack_arguments=["pack config !\\input.json"])
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual([record["stage"] for record in records], ["check", "pack"])
                arguments = records[1]["arguments"]
                self.assertEqual(arguments[0], "-p")
                self.assertEqual(Path(arguments[1]).name, "input.json")
                self.assertTrue(Path(arguments[1]).is_absolute())
                self.assertEqual(arguments[2:4], ["--media", media])
                self.assertEqual(arguments[4], "--output")
                self.assertEqual(Path(arguments[5]).name, output_name)
                self.assertEqual(Path(arguments[5]).parent.name, "numaker-iot-nuc980g2")
                self.assertEqual(records[0]["arguments"], arguments + ["--check"])
                self.assertEqual([record["cwd"] for record in records], [str(Path(arguments[1]).parent)] * 2)
                self.assertFalse(records[0]["output_exists"])
                self.assertTrue(records[1]["output_exists"])

    def test_pack_batches_check_only_do_not_generate(self):
        for script, _, _ in self.pack_scripts:
            with self.subTest(script=script):
                result, records = self.run_batch(
                    script_name=script, pack_arguments=["pack config !\\input.json", "--check"],
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual([record["stage"] for record in records], ["check"])
                self.assertFalse(records[0]["output_exists"])

    def test_pack_batches_resolve_output_override_from_the_calling_directory(self):
        for script, _, _ in self.pack_scripts:
            for check_only in (False, True):
                with self.subTest(script=script, check_only=check_only):
                    arguments = ["pack config !\\input.json", "custom pack !.bin"]
                    result, records = self.run_batch(
                        script_name=script, pack_arguments=arguments + (["--check"] if check_only else []),
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    output = Path(records[0]["arguments"][5])
                    self.assertEqual(output.name, "custom pack !.bin")
                    self.assertEqual(output.parent.name, "unrelated working directory")
                    self.assertEqual([record["stage"] for record in records], ["check"] if check_only else ["check", "pack"])
                    self.assertEqual(records[-1]["output_exists"], not check_only)

    def test_pack_batches_stop_at_failure_and_preserve_nonzero_exit_codes(self):
        for stage in ("check", "pack"):
            for code in (17, -1):
                with self.subTest(stage=stage, code=code):
                    result, records = self.run_batch(
                        script_name="pack_spinand.bat", pack_arguments=["pack config !\\input.json"],
                        fail_stage=stage, fail_code=code,
                    )
                    self.assertEqual(result.returncode & 0xFFFFFFFF, code & 0xFFFFFFFF, result.stdout + result.stderr)
                    self.assertEqual([record["stage"] for record in records], ["check"] if stage == "check" else ["check", "pack"])
                    self.assertFalse(any(record["output_exists"] for record in records))
                    self.assertIn("Remaining steps skipped", result.stderr)

    def test_pack_batch_missing_inputs_stop_before_generation(self):
        for settings in ({"missing_pack_config": True}, {"missing_python": True}):
            with self.subTest(settings=settings):
                result, records = self.run_batch(
                    script_name="pack_spinand.bat", pack_arguments=["pack config !\\input.json"], **settings,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(records, [])

    def test_pack_batch_rejects_invalid_arguments(self):
        for arguments in ([], ["--check"], ["pack config !\\input.json", "--check", "extra"],
                          ["pack config !\\input.json", "output.bin", "--wrong"],
                          ["pack config !\\input.json", "output.bin", "--check", "extra"]):
            with self.subTest(arguments=arguments):
                result, records = self.run_batch(script_name="pack_spinand.bat", pack_arguments=arguments)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(records, [])
                self.assertIn("Usage:", result.stderr)

    def test_batch_checks_initializes_erases_then_programs_from_any_directory(self):
        result, records = self.run_batch()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([record["stage"] for record in records], ["check", "attach", "erase", "flash"])
        self.assertEqual(records[2]["arguments"], ["-e", "spinand", "all"])
        self.assertEqual(records[3]["arguments"][:2], ["-w", "spinand"])
        self.assertEqual(Path(records[1]["arguments"][1]).name, "NUC980DK71YC.ini")
        pack = records[3]["arguments"][2]
        self.assertTrue(Path(pack).is_absolute())
        self.assertEqual(Path(pack).name, "nuwriter-pack.bin")
        ddr = records[1]["arguments"][1]
        self.assertEqual(records[0]["arguments"], ["-w", "spinand", pack, "--ddr", ddr, "--check"])
        self.assertEqual(records[3]["arguments"], ["-w", "spinand", pack, "--ddr", ddr])

    def test_batch_aborts_at_each_failure_and_preserves_exit_code(self):
        stages = ["check", "attach", "erase", "flash"]
        for index, stage in enumerate(stages):
            with self.subTest(stage=stage):
                result, records = self.run_batch(fail_stage=stage)
                self.assertEqual(result.returncode, 17, result.stdout + result.stderr)
                self.assertEqual([record["stage"] for record in records], stages[:index + 1])
                self.assertIn("Remaining steps skipped", result.stderr)

    def test_batch_missing_pack_stops_before_initialization(self):
        result, records = self.run_batch(missing_pack=True)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(records, [])
        self.assertIn("Missing pack image", result.stderr)

    def test_batch_missing_python_stops_before_initialization(self):
        result, records = self.run_batch(missing_python=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(records, [])

    def test_batch_negative_exit_code_does_not_continue_to_programming(self):
        result, records = self.run_batch(fail_stage="erase", fail_code=-1)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([record["stage"] for record in records], ["check", "attach", "erase"])
        self.assertIn("Remaining steps skipped", result.stderr)

    def test_dram_batch_only_checks_initializes_then_executes_dram(self):
        result, records = self.run_batch(script_name="dram_download_openbmc.bat")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([record["stage"] for record in records], ["check", "attach", "download"])
        arguments = records[-1]["arguments"]
        self.assertEqual(arguments[:3], ["-w", "ddr", "0x8000"])
        self.assertEqual(Path(arguments[3]).name, "zImage")
        self.assertEqual(arguments[arguments.index("--dtb-addr") + 1], "0x1400000")
        self.assertEqual(Path(arguments[arguments.index("--dtb") + 1]).name, "nuc980-iot-128m-bmc.dtb")
        self.assertIn("ubi.mtd=rofs", arguments[arguments.index("--bootargs") + 1])
        self.assertIn("root=ubi0:rootfs", arguments[arguments.index("--bootargs") + 1])
        self.assertNotIn("-e", arguments)
        self.assertNotIn("spinand", arguments)

    def test_dram_batch_check_only_never_initializes(self):
        result, records = self.run_batch(script_name="dram_download_openbmc.bat", check_only=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([record["stage"] for record in records], ["check"])

    def test_dram_batch_trace_reaches_attach_and_download(self):
        result, records = self.run_batch(script_name="dram_download_openbmc.bat", trace_usb=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([record["stage"] for record in records], ["check", "attach", "download"])
        self.assertNotIn("--trace-usb", records[0]["arguments"])
        self.assertIn("--trace-usb", records[1]["arguments"])
        self.assertIn("--trace-usb", records[2]["arguments"])

    def test_dram_batch_stops_at_each_failed_stage(self):
        stages = ["check", "attach", "download"]
        for index, stage in enumerate(stages):
            with self.subTest(stage=stage):
                result, records = self.run_batch(script_name="dram_download_openbmc.bat", fail_stage=stage)
                self.assertEqual(result.returncode, 17, result.stdout + result.stderr)
                self.assertEqual([record["stage"] for record in records], stages[:index + 1])

    def test_dram_batch_missing_dtb_stops_before_board_access(self):
        result, records = self.run_batch(script_name="dram_download_openbmc.bat", missing_dtb=True)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(records, [])

    def test_uboot_batch_selects_correct_image_and_dram_address(self):
        for mode, name, address in (("without-spl", "u-boot.bin", "0x00e00000"),
                                     ("with-spl", "u-boot-spl.bin", "0x200")):
            with self.subTest(mode=mode):
                result, records = self.run_batch(script_name="dram_download_uboot.bat", mode=mode)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual([record["stage"] for record in records], ["check", "attach", "download"])
                arguments = records[-1]["arguments"]
                self.assertEqual(arguments[:3], ["-w", "ddr", address])
                self.assertEqual(Path(arguments[3]).name, name)
                self.assertEqual(arguments[-2:], ["-o", "execute"])
                self.assertFalse(any("-e" in record["arguments"] or "spinand" in record["arguments"] for record in records))
                if mode == "with-spl":
                    self.assertIn("main U-Boot from SPI NAND", result.stdout)

    def test_uboot_batch_check_only_never_initializes(self):
        for mode in ("without-spl", "with-spl"):
            with self.subTest(mode=mode):
                result, records = self.run_batch(script_name="dram_download_uboot.bat", mode=mode, check_only=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual([record["stage"] for record in records], ["check"])

    def test_uboot_batch_stops_at_each_failure(self):
        stages = ["check", "attach", "download"]
        for mode in ("without-spl", "with-spl"):
            for index, stage in enumerate(stages):
                with self.subTest(mode=mode, stage=stage):
                    result, records = self.run_batch(script_name="dram_download_uboot.bat", mode=mode, fail_stage=stage)
                    self.assertEqual(result.returncode, 17, result.stdout + result.stderr)
                    self.assertEqual([record["stage"] for record in records], stages[:index + 1])

    def test_uboot_batch_rejects_missing_image_or_wrong_entry_before_usb(self):
        for mode in ("without-spl", "with-spl"):
            for settings in ({"missing_boot_image": True}, {"wrong_boot_address": True}):
                with self.subTest(mode=mode, settings=settings):
                    result, records = self.run_batch(script_name="dram_download_uboot.bat", mode=mode, **settings)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertEqual(records, [])

    def test_uboot_batch_requires_an_explicit_supported_mode(self):
        for mode in (None, "other"):
            with self.subTest(mode=mode):
                result, records = self.run_batch(script_name="dram_download_uboot.bat", mode=mode)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(records, [])


class SessionTests(unittest.TestCase):
    def device(self, endpoints=(0x02, 0x81), address=3):
        device = Mock(bus=1, port_numbers=(2, 3), address=address)
        device.is_kernel_driver_active.return_value = False
        device.get_active_configuration.return_value = {
            (0, 0): [SimpleNamespace(bEndpointAddress=endpoint) for endpoint in endpoints],
        }
        return device

    def modules(self):
        core = Mock(USBError=OSError)
        util = Mock()
        return core, util

    def test_windows_session_keeps_existing_usb_configuration(self):
        device = self.device()
        core, util = self.modules()
        with patch.object(nuwriter.importlib, "import_module", side_effect=[core, util]):
            session = nuwriter.UsbSession(device, 10000)
            session.close()
        device.set_configuration.assert_not_called()
        util.claim_interface.assert_called_once_with(device, 0)

    def test_unconfigured_device_is_configured_once(self):
        device = self.device()
        configuration = device.get_active_configuration.return_value
        device.get_active_configuration.side_effect = [OSError("Configuration not set"), configuration]
        core, util = self.modules()
        with patch.object(nuwriter.importlib, "import_module", side_effect=[core, util]):
            session = nuwriter.UsbSession(device, 10000)
            session.close()
        device.set_configuration.assert_called_once()

    def test_busy_device_is_not_reconfigured(self):
        device = self.device()
        device.get_active_configuration.side_effect = OSError(16, "Resource busy")
        core, util = self.modules()
        with patch.object(nuwriter.importlib, "import_module", side_effect=[core, util]):
            with self.assertRaises(OSError):
                nuwriter.UsbSession(device, 10000)
        device.set_configuration.assert_not_called()
        util.dispose_resources.assert_called_once_with(device)

    def test_wrong_platform_endpoints_are_rejected_and_released(self):
        device = self.device((0x01, 0x81))
        core, util = self.modules()
        with patch.object(nuwriter.importlib, "import_module", side_effect=[core, util]):
            with self.assertRaisesRegex(nuwriter.NuWriterError, "endpoints"):
                nuwriter.UsbSession(device, 10000)
        device.write.assert_not_called()
        util.dispose_resources.assert_called_once_with(device)

    def test_reconnect_tracks_port_not_changed_device_address(self):
        first, replacement = self.device(address=3), self.device(address=7)
        core, util = self.modules()
        core.find.return_value = [replacement]
        with patch.object(nuwriter.importlib, "import_module", side_effect=[core, util]):
            session = nuwriter.UsbSession(first, 10000, trace=True)
            with patch.object(nuwriter.time, "sleep"):
                transport = session.reconnect()
            self.assertIs(transport.device, replacement)
            self.assertTrue(transport.trace)
            session.close()
        self.assertEqual(util.dispose_resources.call_count, 2)


if __name__ == "__main__":
    unittest.main()