import json
import os
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import backend


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="nuwriter gui ! ")
        self.root = Path(self.directory.name).resolve()
        self.image = self.root / "image !.bin"
        self.image.write_bytes(b"data")
        self.ddr = self.root / "DDR.ini"
        self.ddr.write_text("settings", encoding="ascii")
        self.target = backend.Target(str(self.ddr), device="2:3.2")

    def tearDown(self):
        self.directory.cleanup()

    def test_source_invocation_uses_python(self):
        with patch.object(sys, "frozen", False, create=True):
            self.assertEqual(backend.Command(["--version"]).invocation(),
                             [sys.executable, "-u", str(backend.BACKEND), "--version"])

    def test_frozen_resources_use_bundle_root(self):
        with patch.object(sys, "_MEIPASS", str(self.root), create=True):
            module = runpy.run_path(str(Path(backend.__file__)))
        self.assertEqual(module["ROOT"], self.root)

    def test_frozen_invocation_uses_bundled_cli_without_python(self):
        for platform, name in (("win32", "nuwriter.exe"), ("linux", "nuwriter"), ("darwin", "nuwriter")):
            executable = (self.root / "nuwriter-gui.app" / "Contents" / "MacOS" / "nuwriter-gui"
                          if platform == "darwin" else self.root / "nuwriter-gui")
            with self.subTest(platform=platform), \
                 patch.object(sys, "frozen", True, create=True), \
                 patch.object(sys, "platform", platform), \
                 patch.object(sys, "executable", str(executable)):
                expected = self.root / "backend" / "nuwriter" / name
                self.assertEqual(backend.Command(["--version"]).invocation(check=True),
                                 [str(expected), "--version", "--check"])

    def test_program_is_not_an_attach_or_shell_command(self):
        command = backend.program(self.target, "SPI NAND", backend.ImageEntry(str(self.image), offset="0x100000"))
        self.assertEqual(command.arguments[:4], ["-w", "spinand", "0x100000", str(self.image)])
        self.assertNotIn("-a", command.arguments)
        self.assertNotIn("-e", command.arguments)
        self.assertEqual(command.arguments[-2:], ["--device", "2:3.2"])
        self.assertEqual(command.invocation(check=True)[-1], "--check")

    def test_all_flash_media_and_pack_routes(self):
        for media in ("NAND", "SPI NOR", "SPI NAND", "SD/eMMC"):
            with self.subTest(media=media):
                image = backend.ImageEntry(str(self.image), kind="Pack")
                command = backend.program(self.target, media, image)
                self.assertEqual(command.arguments[:3], ["-w", backend.MEDIA[media], str(self.image)])
                verified = backend.program(self.target, media, image, verify=True)
                self.assertIn("-o", verified.arguments)
                self.assertEqual(verified.arguments[verified.arguments.index("-o") + 1], "verify")

    def test_loader_address_and_ddr(self):
        for media, offset in (("SPI NAND", "0"), ("SD/eMMC", "0x400")):
            command = backend.program(self.target, media, backend.ImageEntry(str(self.image), "Loader", offset))
            self.assertIn(str(self.ddr), command.arguments)
        with self.assertRaises(ValueError):
            backend.program(self.target, "SPI NAND", backend.ImageEntry(str(self.image), "Loader", "0x400"))

    def test_download_with_dtb_and_bootargs(self):
        command = backend.download(self.target, self.image, "0x8000", True, str(self.image), bootargs="root=ubi0:rootfs")
        self.assertEqual(command.arguments[:4], ["-w", "ddr", "0x8000", str(self.image)])
        self.assertIn("--dtb", command.arguments)
        self.assertIn("execute", command.arguments)
        with self.assertRaises(ValueError):
            backend.download(self.target, self.image, "0x8000", bootargs="root=/dev/ram0")

    def test_read_erase_and_safety_constraints(self):
        destination = self.root / "out.bin"
        command = backend.read(self.target, "SPI NAND", destination)
        self.assertEqual(command.arguments[:5], ["-r", "spinand", "0x0", "0x20000", str(destination)])
        self.assertEqual(backend.erase(self.target, "SPI NAND").arguments[:3], ["-e", "spinand", "all"])
        with self.assertRaises(ValueError):
            backend.erase(self.target, "SD/eMMC")
        with self.assertRaises(ValueError):
            backend.read(self.target, "SPI NOR", destination, all_flash=True)

    def test_verify_only_reads_and_compares(self):
        output = self.root / "readback.bin"
        image = backend.ImageEntry(str(self.image))
        command = backend.verification_read(self.target, "SPI NAND", image, output)
        self.assertEqual(command.arguments[0], "-r")
        self.assertNotIn("-w", command.arguments)
        output.write_bytes(b"data")
        backend.compare_files(self.image, output)
        output.write_bytes(b"bad")
        with self.assertRaises(ValueError):
            backend.compare_files(self.image, output)

    def test_pack_uses_json_directory_and_absolute_output(self):
        config = self.root / "config.json"
        config.write_text('{"image": []}', encoding="ascii")
        output = self.root / "pack.bin"
        command = backend.pack(config, output, "SPI NAND")
        self.assertEqual(command.cwd, self.root)
        self.assertNotIn("--device", command.arguments)
        self.assertNotIn("-a", command.arguments)

    def test_invalid_inputs(self):
        for value in ("-1", "0x100000000", "bad"):
            with self.assertRaises(ValueError):
                backend.number(value)
        with self.assertRaises(ValueError):
            backend.program(self.target, "NAND", backend.ImageEntry("missing.bin"))

    def test_progress_and_devices(self):
        self.assertEqual(backend.progress_value("SPINAND pack program [#####-----]  50%"), 50)
        self.assertIsNone(backend.progress_value("Error: 50% failed"))
        self.assertEqual(backend.device_paths("2:3.2  VID:PID 0416:5963 (candidate; not a chip identity)\n"), ["2:3.2"])

    def test_mass_production_requires_all_devices_and_rejects_read(self):
        target = backend.Target(str(self.ddr), massproduct=True)
        command = backend.program(target, "SPI NAND", backend.ImageEntry(str(self.image), "Pack"))
        self.assertIn("-m", command.arguments)
        self.assertIn("-m", backend.attach(target).arguments)
        with self.assertRaises(ValueError):
            backend.read(target, "SPI NAND", self.root / "read.bin")
        target.device = "2:3.2"
        with self.assertRaises(ValueError):
            target.options()

    def test_format_configuration_uses_existing_backend_schema(self):
        configuration = backend.format_configuration(self.target, 32, [128, 0])
        self.assertIn("mode = SD", configuration)
        self.assertIn("using_format = yes", configuration)
        self.assertIn("partition1_size = 128", configuration)
        self.assertIn(str(self.ddr), configuration)
        for sizes in ([], [0, 0], [128], [1, 1, 1, 1, 0]):
            with self.assertRaises(ValueError):
                backend.format_configuration(self.target, 32, sizes)

    def test_pack_output_cannot_overwrite_original_config_or_inputs(self):
        document = {"image": [{"file": self.image.name, "ddr_ini": self.ddr.name}], "ddr": self.ddr.name}
        config = self.root / "config.json"
        for path in (self.image, self.ddr, config):
            with self.subTest(path=path), self.assertRaises(ValueError):
                backend.protect_pack_inputs(document, self.root, path, config)
        backend.protect_pack_inputs(document, self.root, self.root / "output.bin", config)
        converted = backend.pack_document({"media": "emmc", "image": []}, "SPI NAND")
        self.assertEqual(converted, {"mode": "spinand", "image": []})


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QPoint, QPointF, QProcess, QRect, QSettings, QTimer, Qt
from PySide6.QtGui import QFontDatabase, QWheelEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton, QScrollArea

import app
import console


class FakeCommand(backend.Command):
    def __init__(self, path, failure=0, failure_in_check=False, block=False):
        super().__init__([], cwd=path.parent, label="Simulated backend")
        self.path = path
        self.failure = failure
        self.failure_in_check = failure_in_check
        self.block = block

    def invocation(self, check=False):
        code = (
            "import json, pathlib, sys\n"
            "path = pathlib.Path(sys.argv[1])\n"
            "with path.open('a', encoding='utf-8') as output:\n"
            "    print(sys.argv[2], file=output)\n"
            "print('SPINAND program [#####-----]  50%', end='\\r', flush=True)\n"
            "print('SPINAND program [##########] 100%', flush=True)\n"
            "print('Payload \\u03a9 completed', flush=True)\n"
        )
        if self.block:
            code += "sys.stdin.read()\n"
        code += "sys.exit(int(sys.argv[3]))\n"
        failed = (check and self.failure_in_check) or (not check and not self.failure_in_check)
        return [sys.executable, "-u", "-c", code, str(self.path), "check" if check else "run", str(self.failure if failed else 0)]


class QtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = app.create_application()
        if os.name == "nt":
            font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeui.ttf"
            if font.is_file():
                QFontDatabase.addApplicationFont(str(font))

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="nuwriter Qt ! ")
        self.root = Path(self.directory.name).resolve()
        self.windows = []
        self.runner = app.BackendRunner()
        serial_guard = patch.object(console.serial, "Serial", side_effect=AssertionError("Real serial access is forbidden in GUI tests"))
        serial_guard.start()
        self.addCleanup(serial_guard.stop)

    def tearDown(self):
        if self.runner.process.state() != QProcess.ProcessState.NotRunning:
            self.runner.process.kill()
            self.runner.process.waitForFinished(3000)
        for window in self.windows:
            window.close()
        self.runner.deleteLater()
        self.application.processEvents()
        self.directory.cleanup()

    def wait_finished(self, spy):
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        self.runner.finished.connect(loop.quit)
        if spy.count() == 0:
            timer.start(10000)
            loop.exec()
            timer.stop()
        self.assertEqual(spy.count(), 1, "Backend process did not finish in time")

    def test_preflight_succeeds_before_running_and_streams_progress(self):
        trace = self.root / "trace.txt"
        done = QSignalSpy(self.runner.finished)
        progress = QSignalSpy(self.runner.progress)
        output = QSignalSpy(self.runner.output)
        self.runner.start(FakeCommand(trace))
        with self.assertRaises(ValueError):
            self.runner.start(FakeCommand(trace))
        self.wait_finished(done)
        self.assertTrue(done.at(0)[0])
        self.assertEqual(trace.read_text().splitlines(), ["check", "run"])
        self.assertIn([50], [progress.at(index) for index in range(progress.count())])
        self.assertTrue(any("Payload \u03a9" in output.at(index)[0] for index in range(output.count())))

    def test_failed_preflight_never_runs_the_operation(self):
        trace = self.root / "trace.txt"
        done = QSignalSpy(self.runner.finished)
        self.runner.start(FakeCommand(trace, failure=17, failure_in_check=True))
        self.wait_finished(done)
        self.assertFalse(done.at(0)[0])
        self.assertEqual(trace.read_text().splitlines(), ["check"])
        self.assertFalse(self.runner.busy)

    def test_failed_operation_is_not_reported_as_success(self):
        done = QSignalSpy(self.runner.finished)
        self.runner.start(FakeCommand(self.root / "trace.txt", failure=9))
        self.wait_finished(done)
        self.assertFalse(done.at(0)[0])
        self.assertIn("9", done.at(0)[1])

    def test_explicit_no_preflight_runs_command_once(self):
        trace = self.root / "trace.txt"
        done = QSignalSpy(self.runner.finished)
        self.runner.start(FakeCommand(trace), preflight=False)
        self.wait_finished(done)
        self.assertTrue(done.at(0)[0])
        self.assertEqual(trace.read_text().splitlines(), ["run"])

    def test_cancellation_clears_the_remaining_queue(self):
        trace = self.root / "trace.txt"
        done = QSignalSpy(self.runner.finished)
        self.runner.process.started.connect(self.runner.stop)
        self.runner.start(FakeCommand(trace, block=True))
        self.wait_finished(done)
        self.assertFalse(done.at(0)[0])
        self.assertFalse(self.runner.busy)
        self.assertFalse(self.runner.queue)
        if trace.exists():
            self.assertNotIn("run", trace.read_text().splitlines())

    def test_failed_start_reports_an_error(self):
        command = FakeCommand(self.root / "trace.txt")
        command.invocation = lambda check=False: [str(self.root / "missing-executable")]
        done = QSignalSpy(self.runner.finished)
        self.runner.start(command)
        self.wait_finished(done)
        self.assertFalse(done.at(0)[0])

    def test_ui_settings_round_trip_restores_pages_dialogs_and_console_without_connections(self):
        ports = [unittest.mock.Mock(device="COM30", description="Debug"),
                 unittest.mock.Mock(device="COM31", description="Second console")]
        with patch.object(console, "available_ports", return_value=ports), \
             patch.object(console.serial, "Serial") as serial, \
             patch.object(app.BackendRunner, "start") as start:
            window = self.window()
            window.show()
            window.resize(920, 640)
            window.ram.filename.setText(str(self.root / "kernel.bin"))
            window.ram.address.setText("0x8000")
            window.ram.dtb_enabled.setChecked(True)
            window.ram.dtb.setText(str(self.root / "board.dtb"))
            window.ram.dtb_address.setText("0x1400000")
            window.ram.bootargs_enabled.setChecked(True)
            window.ram.bootargs.setText("console=ttyS0,115200 root=ubi0:rootfs")
            window.ram.execute.setChecked(True)
            window.media.setCurrentText("SPI NAND")
            window.flash.images.extend([backend.ImageEntry("first.bin", offset="0x100000"),
                                        backend.ImageEntry("second.bin", "Environment", "0x80000")])
            window.flash.refresh()
            window.flash.images_table.selectRow(1)
            window.flash.select_image()
            window.flash.verify_after.setChecked(True)
            window.media.setCurrentText("NAND")
            window.flash.images.append(backend.ImageEntry("nand.bin", offset="0x20000"))
            window.flash.refresh()
            window.media.setCurrentText("SPI NAND")
            window.flash.images_table.selectRow(1)
            window.flash.select_image()
            window.pack.document = {"mode": "spinand", "custom": {"keep": True},
                                    "image": [{"file": "loader.bin", "type": "loader", "offset": "0x0"}]}
            window.pack.config_path = self.root / "pack.json"
            window.pack.media.setCurrentText("SPI NOR")
            window.pack.refresh()
            window.mass.media.setCurrentText("SD/eMMC")
            window.mass.filename.setText(str(self.root / "production.bin"))
            window.devices.addItem("2:3.2", "2:3.2")
            window.devices.setCurrentIndex(1)
            read = app.RangeDialog("SPI NOR", parent=window)
            read.filename.setText(str(self.root / "readback.bin"))
            read.start.setText("0x10000")
            read.length.setText("0x40000")
            read.flash_size.setText("0x1000000")
            read.reject()
            format_dialog = app.FormatDialog(window)
            format_dialog.reserved.setValue(64)
            format_dialog.count.setValue(3)
            format_dialog.sizes[0].setValue(256)
            format_dialog.sizes[1].setValue(512)
            format_dialog.reject()
            editor = app.PackImageDialog(parent=window)
            editor.filename.setText("draft-loader.bin")
            editor.kind.setCurrentText("loader")
            editor.execute.setText("0xe00000")
            editor.parameters.setPlainText('{"custom": 7}')
            editor.reject()
            window.console_button.click()
            window.console_window.ports.setCurrentIndex(window.console_window.ports.findData("COM31"))
            window.console_window.baud.setCurrentText("57600")
            window.trace_button.click()
            window.trace_window.resize(640, 420)
            window.append_output("Do not restore this log")
            self.assertTrue(window.close())
            path = self.root / "settings.json"
            self.assertTrue(path.is_file())
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("trace_enabled", document)
            restored = self.window()
            self.assertEqual(restored.size(), window.size())
            self.assertEqual(restored.media.currentText(), "SPI NAND")
            self.assertEqual(restored.devices.currentData(), "2:3.2")
            self.assertEqual(restored.ram.filename.text(), str(self.root / "kernel.bin"))
            self.assertEqual(restored.ram.address.text(), "0x8000")
            self.assertTrue(restored.ram.dtb_enabled.isChecked())
            self.assertTrue(restored.ram.bootargs_enabled.isChecked())
            self.assertTrue(restored.ram.execute.isChecked())
            self.assertEqual(restored.ram.bootargs.text(), "console=ttyS0,115200 root=ubi0:rootfs")
            self.assertEqual([image.filename for image in restored.flash.images], ["first.bin", "second.bin"])
            self.assertEqual(restored.flash.images_table.currentRow(), 1)
            self.assertEqual(restored.flash.offset.text(), "0x80000")
            self.assertTrue(restored.flash.verify_after.isChecked())
            self.assertEqual(restored.flash.media_images["NAND"][0].filename, "nand.bin")
            self.assertEqual(restored.pack.document, window.pack.document)
            self.assertEqual(restored.pack.config_path, self.root / "pack.json")
            self.assertEqual(restored.pack.media.currentText(), "SPI NOR")
            self.assertEqual(restored.mass.media.currentText(), "SD/eMMC")
            self.assertEqual(restored.mass.filename.text(), str(self.root / "production.bin"))
            self.assertEqual(restored.trace_window.size(), window.trace_window.size())
            self.assertFalse(restored.runner.trace_enabled)
            self.assertFalse(restored.trace_button.isChecked())
            self.assertIsNone(restored.console_window)
            self.assertEqual(restored.log.toPlainText(), "")
            restored.console_button.click()
            self.assertEqual(restored.console_window.ports.currentData(), "COM31")
            self.assertEqual(restored.console_window.baud.currentText(), "57600")
            self.assertFalse(restored.console_window.connection.connected)
            read = app.RangeDialog("SPI NOR", parent=restored)
            self.assertEqual(read.filename.text(), str(self.root / "readback.bin"))
            self.assertEqual(read.start.text(), "0x10000")
            self.assertEqual(read.length.text(), "0x40000")
            self.assertEqual(read.flash_size.text(), "0x1000000")
            read.reject()
            format_dialog = app.FormatDialog(restored)
            self.assertEqual(format_dialog.reserved.value(), 64)
            self.assertEqual(format_dialog.count.value(), 3)
            self.assertEqual([size.value() for size in format_dialog.sizes[:2]], [256, 512])
            format_dialog.reject()
            editor = app.PackImageDialog(parent=restored)
            self.assertEqual(editor.filename.text(), "draft-loader.bin")
            self.assertEqual(editor.kind.currentText(), "loader")
            self.assertEqual(editor.execute.text(), "0xe00000")
            self.assertEqual(json.loads(editor.parameters.toPlainText()), {"custom": 7})
            editor.reject()
            serial.assert_not_called()
            start.assert_not_called()

    def test_ui_settings_keep_hidden_flash_and_pack_selected_rows(self):
        window = self.window()
        window.media.setCurrentText("NAND")
        window.flash.images.extend([backend.ImageEntry("first.bin"), backend.ImageEntry("second.bin", offset="0x20000")])
        window.flash.refresh()
        window.flash.images_table.selectRow(1)
        window.flash.select_image()
        window.pack.document["image"] = [{"file": "one.bin", "type": "data", "offset": "0x0"},
                                          {"file": "two.bin", "type": "data", "offset": "0x20000"}]
        window.pack.refresh()
        window.pack.images_table.selectRow(1)
        window.media.setCurrentText("SDRAM")
        window.close()
        restored = self.window()
        self.assertEqual(restored.media.currentText(), "SDRAM")
        self.assertEqual(restored.flash.current_media, "NAND")
        self.assertEqual(restored.flash.images_table.currentRow(), 1)
        self.assertEqual(restored.flash.filename.text(), "second.bin")
        self.assertEqual(restored.pack.images_table.currentRow(), 1)

    def test_ui_settings_invalid_values_fall_back_without_launching_operations(self):
        settings = app.JsonSettings(self.root / "settings.json")
        settings.setValue("main", {"media": "not a media", "_size": [999999999999, -1]})
        settings.setValue("ram", {"address": "0x100000000", "filename": "bad\x00.bin", "dtb_enabled": "yes"})
        settings.setValue("flash_images", {"NAND": [{"filename": "bad.bin", "kind": ["Unknown"]}]})
        settings.setValue("flash_media", ["invalid type"])
        settings.setValue("pack", {"document": {"image": ["not an object"]}})
        settings.setValue("dialogs", {"format": {"reserved": -1, "count": 99}})
        settings.sync()
        with patch.object(app.BackendRunner, "start") as start:
            window = self.window()
            self.assertEqual(window.media.currentText(), "SDRAM")
            self.assertEqual(window.ram.address.text(), "0x8000")
            self.assertEqual(window.ram.filename.text(), "")
            self.assertFalse(window.ram.dtb_enabled.isChecked())
            self.assertEqual(window.pack.document["image"], [])
            dialog = app.FormatDialog(window)
            self.assertEqual(dialog.reserved.value(), 32)
            self.assertEqual(dialog.count.value(), 2)
            dialog.reject()
            start.assert_not_called()

    def test_ui_settings_write_failure_keeps_window_open(self):
        window = self.window()
        window.show()
        with patch.object(window.settings, "sync", side_effect=OSError("Read-only configuration directory")), \
             patch.object(window, "error") as error:
            self.assertFalse(window.close())
            self.assertTrue(window.isVisible())
            self.assertIn("Could not save settings", error.call_args.args[0])

    def test_first_log_open_queries_host_information_once_without_device_access(self):
        memory = unittest.mock.Mock(total=8 * 1024 ** 3, available=3 * 1024 ** 3)
        with patch.object(app.QSysInfo, "prettyProductName", return_value="Test OS"), \
             patch.object(app.platform, "processor", return_value="Test CPU"), \
             patch.object(app.psutil, "cpu_count", side_effect=lambda logical=True: 8 if logical else 4) as cpu_count, \
             patch.object(app.psutil, "virtual_memory", return_value=memory) as ram, \
             patch.object(app, "host_information", wraps=app.host_information) as information, \
             patch.object(app.BackendRunner, "start") as start, \
             patch.object(console, "available_ports") as ports, \
             patch.object(console.serial, "Serial") as serial:
            window = app.MainWindow(settings_path=self.root / "startup.json")
            self.windows.append(window)
            self.assertEqual(window.log.toPlainText(), "")
            self.assertFalse(window.host_information_logged)
            information.assert_not_called()
            cpu_count.assert_not_called()
            ram.assert_not_called()
            self.assertFalse(window.log_window.isVisible())
            window.show()
            self.application.processEvents()
            information.assert_not_called()
            window.log_button.click()
            output = window.log.toPlainText()
            self.assertIn("OS: Test OS", output)
            self.assertIn("CPU: Test CPU", output)
            self.assertIn("CPU cores: 4 physical, 8 logical", output)
            self.assertIn("RAM: 8.00 GiB total, 3.00 GiB available", output)
            for label in ("Kernel:", "Architecture:", "Python:", "Interpreter:", "Qt:", "Display 1:", "Settings:"):
                self.assertIn(label, output)
            self.assertTrue(window.log_window.isVisible())
            self.assertTrue(window.host_information_logged)
            window.log_button.click()
            window.log_button.click()
            self.application.processEvents()
            self.assertEqual(window.log.toPlainText(), output)
            self.assertEqual(output.count("Host system information"), 1)
            information.assert_called_once()
            self.assertEqual(cpu_count.call_count, 2)
            ram.assert_called_once()
            start.assert_not_called()
            ports.assert_not_called()
            serial.assert_not_called()

    def test_startup_reports_module_versions_without_importing_deferred_modules(self):
        versions = {"PySide6": "6.12.0", "pyte": "0.8.2", "pyserial": "3.5",
                    "psutil": "7.2.2", "pyusb": "1.3.1", "pyfdt": "0.3"}
        before = {name: name in sys.modules for name in ("usb", "pyfdt")}
        with patch.object(app.metadata, "version", side_effect=lambda name: versions[name]):
            output = app.host_information()
        self.assertIn("Python modules:", output)
        for distribution, version in versions.items():
            self.assertIn(f": {version} [", output)
        self.assertIn("pyserial (serial): 3.5 [loaded]", output)
        self.assertEqual({name: name in sys.modules for name in before}, before)
        with patch.object(app.metadata, "version", side_effect=app.metadata.PackageNotFoundError):
            output = app.host_information()
        self.assertIn("PySide6 (PySide6): version unavailable [loaded]", output)
        if not before["usb"]:
            self.assertIn("pyusb (usb): not installed [not loaded]", output)

    def test_startup_host_information_handles_unavailable_hardware_data(self):
        with patch.object(app.psutil, "cpu_count", side_effect=OSError("CPU information unavailable")), \
             patch.object(app.psutil, "virtual_memory", side_effect=NotImplementedError), \
             patch.object(app.platform, "processor", return_value=""):
            output = app.host_information()
            self.assertIn("CPU cores: unavailable", output)
            self.assertIn("RAM: unavailable", output)
            self.assertIn("Architecture:", output)
            self.assertIn("Python:", output)

    def test_json_settings_round_trip_and_corrupt_file_backup(self):
        path = self.root / "config" / "settings.json"
        settings = app.JsonSettings(path)
        settings.setValue("example", {"enabled": True, "address": "0x8000", "filename": "image with spaces.bin"})
        settings.sync()
        restored = app.JsonSettings(path)
        self.assertEqual(restored.value("example"), settings.value("example"))
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["version"], 1)
        path.write_text("{broken", encoding="utf-8")
        damaged = app.JsonSettings(path)
        self.assertTrue(damaged.load_error)
        self.assertEqual(damaged.value("missing", "default"), "default")
        damaged.sync()
        backups = list(path.parent.glob("settings.json.*.invalid"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "{broken")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"version": 1})

    def test_invalid_hex_edits_never_launch_backend(self):
        window = self.window()
        image = self.root / "image.bin"
        image.write_bytes(b"data")
        window.ram.filename.setText(str(image))
        with patch.object(window.runner, "start") as start, patch.object(window, "error") as error:
            for value in ("", "0x", "1234", "-0x1", "0x100000000", "0xxyz"):
                window.ram.address.setText(value)
                window.ram.download()
            self.assertEqual(error.call_count, 6)
            start.assert_not_called()
        field = app.TextLineEdit()
        self.addCleanup(field.close)
        field.setText("image\x00.bin")
        self.assertFalse(field.hasAcceptableInput())
        field.setText("C:/images/image with spaces.bin")
        self.assertTrue(field.hasAcceptableInput())

    def test_range_edits_reject_zero_length_and_invalid_hex(self):
        dialog = app.RangeDialog("SPI NAND")
        self.addCleanup(dialog.close)
        dialog.filename.setText(str(self.root / "readback.bin"))
        with patch.object(app.QMessageBox, "warning") as warning:
            for value in ("0x0", "1234", "0xxyz"):
                dialog.length.setText(value)
                dialog.accept()
                self.assertNotEqual(dialog.result(), app.QDialog.DialogCode.Accepted)
            self.assertEqual(warning.call_count, 3)
        dialog.length.setText("0x20000")
        dialog.accept()
        self.assertEqual(dialog.result(), app.QDialog.DialogCode.Accepted)

    def test_hex_edit_rejects_illegal_characters_and_detects_incomplete_values(self):
        field = app.HexLineEdit()
        self.addCleanup(field.close)
        field.clear()
        QTest.keyClicks(field, "0x1g2!-")
        self.assertEqual(field.text(), "0x12")
        self.assertTrue(field.hasAcceptableInput())
        for value in ("", "0x", "1234", "-0x1", "0x100000000", "0xxyz"):
            with self.subTest(value=value):
                field.setText(value)
                self.assertFalse(field.hasAcceptableInput())
        for value in ("0x0", "0xFFFFFFFF", "0X1234abcd"):
            with self.subTest(value=value):
                field.setText(value)
                self.assertTrue(field.hasAcceptableInput())

    def test_fragmented_progress_and_unicode_is_buffered(self):
        output = QSignalSpy(self.runner.output)
        progress = QSignalSpy(self.runner.progress)
        self.runner.parse("SPI NAND [####")
        self.runner.parse("#-----]  50%\rPayload ")
        self.runner.parse("complete", final=True)
        self.assertEqual(progress.at(0), [50])
        self.assertEqual(output.at(1), ["Payload complete"])

    def test_usb_trace_is_separated_from_output_across_fragmented_lines(self):
        output = QSignalSpy(self.runner.output)
        trace = QSignalSpy(self.runner.trace_output)
        progress = QSignalSpy(self.runner.progress)
        self.runner.set_trace_enabled(True)
        self.runner.parse("USB CONTROL O")
        self.runner.parse("UT request=0xb0 value=0x0089\r\nSPINAND [#####-----]  50%\n")
        self.runner.parse("USB BULK IN completed length=4 data=89 00")
        self.runner.parse(" 00 00", final=True)
        self.assertEqual(trace.count(), 2)
        self.assertEqual(trace.at(0), ["USB CONTROL OUT request=0xb0 value=0x0089"])
        self.assertEqual(trace.at(1), ["USB BULK IN completed length=4 data=89 00 00 00"])
        self.assertEqual(output.count(), 1)
        self.assertEqual(output.at(0), ["SPINAND [#####-----]  50%"])
        self.assertEqual(progress.at(0), [50])

    def test_usb_trace_device_paths_precede_directions_without_changing_colors_or_rows(self):
        window = self.window()
        window.trace_button.click()
        indent = " " * len("[2:4.2.2] <D->H> ")
        records = [
            ("USB (2:4.2.2) CONTROL OUT request=0xb0 value=0x0080 index=0 length=0",
             "[2:4.2.2] <H->D> CONTROL OUT request=0xb0 value=0x0080 index=0 length=0", "#5aa5ff"),
            ("USB (2:4.2.2) CONTROL IN completed length=2 data=80 00",
             "[2:4.2.2] <D->H> CONTROL IN completed length=2\n" + indent + "80 00", "#56dce5"),
            ("USB (2:4.2.3) BULK OUT endpoint=0x02 length=17 data=" + bytes(range(17)).hex(" "),
             "[2:4.2.3] <H->D> BULK OUT endpoint=0x02 length=17\n" + indent + bytes(range(16)).hex(" ") + "\n" + indent + "10", "#f3c969"),
            ("USB (2:4.2.3) BULK IN endpoint=0x81 length=4 timeout=10000 ms",
             "[2:4.2.3] <D->H> BULK IN endpoint=0x81 length=4 timeout=10000 ms", "#74db98"),
        ]
        for raw, expected, color in records:
            window.runner.parse(raw[:12])
            window.runner.parse(raw[12:] + "\n")
        self.assertEqual(window.trace_window.log.toPlainText(), "\n".join(record[1] for record in records))
        block = window.trace_window.log.document().firstBlock()
        for raw, expected, color in records:
            for line in expected.split("\n"):
                self.assertEqual(block.text(), line)
                self.assertEqual(block.begin().fragment().charFormat().foreground().color().name(), color)
                block = block.next()
        self.assertEqual(window.log.toPlainText(), "")
        self.assertEqual(window.collected, [])

    def test_usb_trace_transactions_have_direction_colors_and_keep_literal_text(self):
        window = self.window()
        window.trace_button.click()
        indent = " " * len("<D->H> ")
        records = [
            ("USB CONTROL OUT request=0xb0 value=0x0089", "<H->D> CONTROL OUT request=0xb0 value=0x0089", "#5aa5ff"),
            ("USB CONTROL OUT completed", "<H->D> CONTROL OUT completed", "#5aa5ff"),
            ("USB CONTROL IN completed length=2 data=89 00", "<D->H> CONTROL IN completed length=2\n" + indent + "89 00", "#56dce5"),
            ("USB BULK OUT endpoint=0x02 length=4 data=01 02 03 04", "<H->D> BULK OUT endpoint=0x02 length=4\n" + indent + "01 02 03 04", "#f3c969"),
            ("USB BULK OUT completed length=4", "<H->D> BULK OUT completed length=4", "#f3c969"),
            ("USB BULK IN endpoint=0x81 length=4 timeout=10000 ms", "<D->H> BULK IN endpoint=0x81 length=4 timeout=10000 ms", "#74db98"),
            ("USB BULK IN completed length=4 data=89 00 00 00", "<D->H> BULK IN completed length=4\n" + indent + "89 00 00 00", "#74db98"),
            ("USB diagnostic <literal> & text", "diagnostic <literal> & text", "#e6e6e6"),
        ]
        for raw, expected, color in records:
            window.runner.parse(raw + "\n")
        expected_text = "\n".join(record[1] for record in records)
        popup = window.trace_window
        self.assertEqual(popup.log.toPlainText(), expected_text)
        block = popup.log.document().firstBlock()
        for raw, expected, color in records:
            for line in expected.split("\n"):
                self.assertEqual(block.text(), line)
                self.assertEqual(block.begin().fragment().charFormat().foreground().color().name(), color)
                block = block.next()
        self.assertEqual(window.log.toPlainText(), "")
        self.assertEqual(window.collected, [])
        popup.resize(480, 280)
        self.application.processEvents()
        self.assertEqual(popup.log.toPlainText(), expected_text)
        self.assertTrue(popup.log.isReadOnly())

    def test_usb_trace_ff_preview_matches_requested_format(self):
        window = self.window()
        window.trace_button.click()
        payload = " ".join(["ff"] * 64)
        window.runner.parse("USB (2:4.2.2) BULK IN completed length=4096 data=" + payload + " ...\n")
        indent = " " * len("[2:4.2.2] <D->H> ")
        row = indent + " ".join(["ff"] * 16)
        expected = "[2:4.2.2] <D->H> BULK IN completed length=4096\n" + "\n".join([row] * 4 + [indent + "..."])
        self.assertEqual(window.trace_window.log.toPlainText(), expected)
        self.assertNotIn("data=", expected)
        self.assertEqual(window.log.toPlainText(), "")

    def test_usb_trace_data_rows_have_16_bytes_and_transaction_aligned_indent(self):
        window = self.window()
        window.trace_button.click()
        popup = window.trace_window
        self.assertEqual(popup.log.lineWrapMode(), app.QPlainTextEdit.LineWrapMode.NoWrap)
        for size, truncated in ((0, False), (1, False), (16, False), (17, False), (32, False), (64, True)):
            with self.subTest(size=size, truncated=truncated):
                popup.log.clear()
                payload = bytes(range(size))
                preview = payload.hex(" ") + (" ..." if truncated else "")
                window.runner.parse(f"USB BULK OUT endpoint=0x02 length=4096 data={preview}\n")
                lines = popup.log.toPlainText().split("\n")
                self.assertEqual(lines[0], "<H->D> BULK OUT endpoint=0x02 length=4096")
                indent = " " * len("<H->D> ")
                expected_rows = [indent + payload[offset:offset + 16].hex(" ")
                                 for offset in range(0, size, 16)] or [indent]
                if truncated:
                    expected_rows.append(indent + "...")
                self.assertEqual(lines[1:], expected_rows)
                self.assertEqual(len(lines) - 1, max(1, (size + 15) // 16) + int(truncated))
                block = popup.log.document().firstBlock()
                while block.isValid():
                    if block.text().strip():
                        self.assertEqual(block.begin().fragment().charFormat().foreground().color().name(), "#f3c969")
                    block = block.next()

    def test_usb_trace_payload_and_ellipsis_align_with_all_transaction_names(self):
        window = self.window()
        window.trace_button.click()
        popup = window.trace_window
        for device in ("", "2:4.2.2", "12:10.4.2.12"):
            for transaction in popup.transaction_styles:
                with self.subTest(device=device, transaction=transaction):
                    popup.log.clear()
                    origin = f"({device}) " if device else ""
                    window.runner.parse("USB " + origin + transaction + " length=4096 data=" + bytes(range(17)).hex(" ") + " ...\n")
                    lines = popup.log.toPlainText().splitlines()
                    column = lines[0].index(transaction)
                    for line in lines[1:]:
                        self.assertEqual(len(line) - len(line.lstrip(" ")), column)
                    self.assertEqual(lines[-1], " " * column + "...")

    def test_usb_trace_popup_visibility_controls_recording_and_works_while_busy(self):
        with patch.object(app.BackendRunner, "start") as start:
            window = self.window()
            window.show()
            self.application.processEvents()
            popup = window.trace_window
            self.assertFalse(popup.isVisible())
            self.assertFalse(window.trace_button.isChecked())
            self.assertFalse(window.target().trace)
            self.assertFalse(hasattr(window, "trace"))
            self.assertNotIn("USB trace", [checkbox.text() for checkbox in window.findChildren(app.QCheckBox)])
            self.assertFalse(popup.isModal())
            self.assertEqual(popup.windowTitle(), "USB Trace")
            console_x = window.console_button.mapTo(window, window.console_button.rect().center()).x()
            trace_x = window.trace_button.mapTo(window, window.trace_button.rect().center()).x()
            log_x = window.log_button.mapTo(window, window.log_button.rect().center()).x()
            self.assertLess(console_x, trace_x)
            self.assertLess(trace_x, log_x)
            window.trace_button.click()
            self.assertTrue(popup.isVisible())
            self.assertTrue(window.trace_button.isChecked())
            self.assertTrue(window.target().trace)
            self.assertIn("--trace-usb", window.target().options())
            window.runner.parse("USB BULK IN completed length=4 data=89 00 00 00\n")
            recorded = popup.log.toPlainText()
            window.trace_button.click()
            self.assertFalse(popup.isVisible())
            self.assertFalse(window.trace_button.isChecked())
            self.assertFalse(window.target().trace)
            with patch.object(popup, "append_trace") as append:
                window.runner.parse("USB BULK IN completed length=4 data=hidden\n")
                append.assert_not_called()
            popup.append_trace("USB BULK IN completed length=4 data=also-hidden")
            self.assertEqual(popup.log.toPlainText(), recorded)
            window.set_busy(True)
            self.assertTrue(window.trace_button.isEnabled())
            window.trace_button.click()
            self.assertIn("<D->H> BULK IN completed", popup.log.toPlainText())
            self.assertNotIn("hidden", popup.log.toPlainText())
            self.assertEqual(len(window.findChildren(app.USBTraceWindow)), 1)
            popup.reject()
            self.assertFalse(popup.isVisible())
            self.assertFalse(window.trace_button.isChecked())
            self.assertFalse(window.runner.trace_enabled)
            window.trace_button.click()
            popup.close()
            self.assertFalse(window.trace_button.isChecked())
            self.assertFalse(window.runner.trace_enabled)
            window.set_busy(False)
            window.trace_button.click()
            window.close()
            self.assertFalse(popup.isVisible())
            self.assertFalse(window.trace_button.isChecked())
            self.assertIn("<D->H> BULK IN completed", popup.log.toPlainText())
            start.assert_not_called()

    def test_usb_trace_stays_separate_when_progress_has_no_newline(self):
        window = self.window()
        window.trace_button.click()
        self.runner.set_trace_enabled(True)
        self.runner.trace_output.connect(window.trace_window.append_trace)
        self.runner.output.connect(window.append_output)
        traces = QSignalSpy(self.runner.trace_output)
        progress = QSignalSpy(self.runner.progress)
        percentages = list(range(0, 70, 10))
        progress_lines = [f"SPINAND program [{'#' * (value // 10)}{'-' * (10 - value // 10)}] {value:3d}%"
                          for value in percentages]
        record = "USB CONTROL OUT request=0xa0 value=0x0012 index=4096 length=0"
        code = (
            "import json, sys\n"
            "for line in json.loads(sys.argv[1]):\n"
            "    print('\\r' + line, end='', flush=True)\n"
            "    print(sys.argv[2], file=sys.stderr, flush=True)\n"
            "print('\\rSPINAND program [##########] 100%', flush=True)\n"
            "print('Error: simulated diagnostic', file=sys.stderr, flush=True)\n"
        )
        command = FakeCommand(self.root / "trace.txt")
        command.invocation = lambda check=False: [sys.executable, "-u", "-c", code, json.dumps(progress_lines), record]
        done = QSignalSpy(self.runner.finished)
        self.runner.start(command, preflight=False)
        self.wait_finished(done)
        self.assertTrue(done.at(0)[0], done.at(0)[1])
        self.assertEqual(traces.count(), len(progress_lines))
        self.assertNotIn("USB ", window.log.toPlainText())
        self.assertNotIn("CONTROL OUT", "\n".join(window.collected))
        self.assertIn("Error: simulated diagnostic", window.log.toPlainText())
        for line in progress_lines:
            self.assertIn(line, window.log.toPlainText())
        values = [progress.at(index)[0] for index in range(progress.count())]
        for value in percentages + [100]:
            self.assertIn(value, values)
        self.assertEqual(window.trace_window.log.toPlainText().count("<H->D> CONTROL OUT"), len(progress_lines))

    def test_usb_trace_subprocess_stderr_is_routed_to_its_window(self):
        window = self.window()
        window.trace_button.click()
        self.runner.set_trace_enabled(True)
        self.runner.trace_output.connect(window.trace_window.append_trace)
        self.runner.output.connect(window.append_output)
        command = FakeCommand(self.root / "trace.txt")
        code = ("import sys; "
            "print('USB (2:4.2.2) CONTROL OUT completed', file=sys.stderr, flush=True); "
            "print('USB (2:4.2.2) BULK IN completed length=4 data=89 00 00 00', file=sys.stderr, flush=True); "
                "print('Payload completed', flush=True)")
        command.invocation = lambda check=False: [sys.executable, "-u", "-c", code]
        done = QSignalSpy(self.runner.finished)
        self.runner.start(command, preflight=False)
        self.wait_finished(done)
        self.assertTrue(done.at(0)[0])
        self.assertIn("[2:4.2.2] <H->D> CONTROL OUT completed", window.trace_window.log.toPlainText())
        self.assertIn("[2:4.2.2] <D->H> BULK IN completed", window.trace_window.log.toPlainText())
        self.assertIn("Payload completed", window.log.toPlainText())
        self.assertNotIn("USB ", window.log.toPlainText())
        self.assertNotIn("BULK IN", "\n".join(window.collected))

    def test_usb_trace_switches_live_in_one_running_backend_process(self):
        window = self.window()
        popup = window.trace_window
        popup.visibility_changed.connect(self.runner.set_trace_enabled)
        self.runner.trace_output.connect(popup.append_trace)
        traces = QSignalSpy(self.runner.trace_output)
        phases = []
        process_ids = []
        received_traces = set()
        advanced = set()
        code = (
            "import sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "import nuwriter\n"
            "transport = nuwriter.UsbTransport(None)\n"
            "for stage in sys.stdin:\n"
            "    stage = stage.strip()\n"
            "    if stage == 'quit':\n"
            "        break\n"
            "    transport.log('BULK IN completed stage=%s', stage, data=bytes([137, 0, 0, 0]))\n"
            "    print('STEP ' + stage, flush=True)\n"
            "transport.trace_control.close()\n"
        )
        command = FakeCommand(self.root / "trace.txt")
        command.invocation = lambda check=False: [sys.executable, "-u", "-c", code, str(backend.ROOT)]

        def next_phase(phase):
            if phase not in phases or phase in advanced:
                return
            if phase in ("shown", "shown-again") and phase not in received_traces:
                return
            advanced.add(phase)
            if phase == "hidden":
                window.trace_button.click()
                self.runner.process.write(b"shown\n")
            elif phase == "shown":
                window.trace_button.click()
                self.runner.process.write(b"hidden-again\n")
            elif phase == "hidden-again":
                window.trace_button.click()
                self.runner.process.write(b"shown-again\n")
            elif phase == "shown-again":
                self.runner.process.write(b"quit\n")

        def advance(text):
            if text.startswith("STEP "):
                phase = text.removeprefix("STEP ")
                phases.append(phase)
                process_ids.append(self.runner.process.processId())
                next_phase(phase)

        def received_trace(text):
            phase = text.split("stage=", 1)[1].split()[0]
            received_traces.add(phase)
            next_phase(phase)

        self.runner.output.connect(advance)
        self.runner.trace_output.connect(received_trace)
        self.runner.process.started.connect(lambda: self.runner.process.write(b"hidden\n"))
        done = QSignalSpy(self.runner.finished)
        self.runner.start(command, preflight=False)
        self.wait_finished(done)
        self.assertTrue(done.at(0)[0], done.at(0)[1])
        self.assertEqual(phases, ["hidden", "shown", "hidden-again", "shown-again"])
        self.assertEqual(len(set(process_ids)), 1)
        self.assertGreater(process_ids[0], 0)
        self.assertEqual(traces.count(), 2)
        self.assertIn("stage=shown data=89 00 00 00", traces.at(0)[0])
        self.assertIn("stage=shown-again data=89 00 00 00", traces.at(1)[0])
        self.assertNotIn("hidden", popup.log.toPlainText())
        self.assertEqual(popup.log.document().blockCount(), 4)

    def test_usb_trace_hidden_drops_partial_records_without_affecting_normal_output(self):
        trace = QSignalSpy(self.runner.trace_output)
        output = QSignalSpy(self.runner.output)
        self.runner.set_trace_enabled(True)
        self.runner.parse("USB BULK IN completed data=partial")
        self.runner.set_trace_enabled(False)
        self.runner.parse("\nUSB BULK OUT completed length=4\nOperation completed\n")
        self.assertEqual(trace.count(), 0)
        self.assertEqual(output.count(), 1)
        self.assertEqual(output.at(0), ["Operation completed"])
        self.assertEqual(self.runner.trace_control[0], 0)

    def test_usb_trace_follows_latest_and_bounds_retained_lines(self):
        window = self.window()
        window.trace_button.click()
        popup = window.trace_window
        self.application.processEvents()
        popup.log.setMaximumBlockCount(60)
        for index in range(200):
            window.runner.parse(f"USB BULK IN completed data={index:08x}\n")
        self.application.processEvents()
        scrollbar = popup.log.verticalScrollBar()
        self.assertGreater(scrollbar.maximum(), 0)
        scrollbar.setValue(0)
        window.runner.parse("USB BULK IN completed data=latest\n")
        self.application.processEvents()
        self.assertEqual(scrollbar.value(), scrollbar.maximum())
        self.assertEqual(popup.log.document().blockCount(), 60)
        self.assertNotIn("\n" + " " * len("<D->H> ") + "00000000", popup.log.toPlainText())
        self.assertTrue(popup.log.toPlainText().endswith("<D->H> BULK IN completed\n" + " " * len("<D->H> ") + "latest"))

    def window(self):
        window = app.MainWindow(settings_path=self.root / "settings.json")
        self.windows.append(window)
        window.host_information_logged = True
        window.clear_log()
        window.collected.clear()
        return window

    def test_serial_connection_uses_nonblocking_io_and_inactive_control_lines(self):
        port = unittest.mock.Mock(is_open=False, in_waiting=0)
        connection = console.SerialConnection()
        with patch.object(console.serial, "Serial", return_value=port) as factory:
            connection.open("COM30")
        self.assertFalse(port.dtr)
        self.assertFalse(port.rts)
        self.assertEqual(port.port, "COM30")
        self.assertEqual(factory.call_args.kwargs["timeout"], 0)
        self.assertEqual(factory.call_args.kwargs["write_timeout"], 0)
        self.assertFalse(factory.call_args.kwargs["rtscts"])
        port.is_open = True
        port.write.return_value = 2
        connection.send(b"abc")
        self.assertEqual(connection.pending, b"c")
        port.write.return_value = 1
        connection.poll()
        self.assertEqual(connection.pending, b"")
        received = QSignalSpy(connection.received)
        port.in_waiting = 4
        port.read.return_value = b"boot"
        connection.poll()
        self.assertEqual(received.at(0), [b"boot"])
        connection.close()
        port.close.assert_called_once()
        self.assertFalse(connection.timer.isActive())

    def test_serial_disconnect_and_open_failure_release_the_port(self):
        port = unittest.mock.Mock(is_open=False, in_waiting=0)
        port.open.side_effect = console.serial.SerialException("Access denied")
        connection = console.SerialConnection()
        with patch.object(console.serial, "Serial", return_value=port):
            with self.assertRaises(console.serial.SerialException):
                connection.open("COM30")
        port.close.assert_called_once()
        self.assertFalse(connection.connected)
        port = unittest.mock.Mock(is_open=True)
        connection.port = port
        connection.timer.start()
        type(port).in_waiting = unittest.mock.PropertyMock(side_effect=console.serial.SerialException("Device unplugged"))
        errors = QSignalSpy(connection.error)
        connection.poll()
        self.assertFalse(connection.connected)
        self.assertFalse(connection.timer.isActive())
        self.assertIn("unplugged", errors.at(0)[0])
        port.close.assert_called_once()

    def fake_console_port(self):
        port = unittest.mock.Mock(is_open=False, in_waiting=0)
        port.open.side_effect = lambda: setattr(port, "is_open", True)
        port.close.side_effect = lambda: setattr(port, "is_open", False)
        port.write.side_effect = lambda data: len(data)
        return port

    def test_console_one_button_tracks_success_close_and_device_removal(self):
        window = self.window()
        port = self.fake_console_port()
        with patch.object(console, "available_ports", return_value=[unittest.mock.Mock(device="COM30", description="Debug")]), \
             patch.object(console.serial, "Serial", return_value=port) as factory:
            window.open_console()
            popup = window.console_window
            self.assertEqual(popup.open_button.text(), "Open")
            self.assertEqual([control.text() for control in popup.findChildren(QPushButton)], ["Open"])
            popup.open_button.click()
            popup.connection.timer.stop()
            self.assertTrue(popup.connection.connected)
            self.assertEqual(popup.open_button.text(), "Close")
            self.assertFalse(popup.ports.isEnabled())
            self.assertFalse(popup.baud.isEnabled())
            popup.open_button.click()
            self.assertFalse(popup.connection.connected)
            self.assertEqual(popup.open_button.text(), "Open")
            self.assertTrue(popup.ports.isEnabled())
            self.assertTrue(popup.baud.isEnabled())
            popup.open_button.click()
            popup.connection.timer.stop()
            port.is_open = False
            popup.connection.poll()
            self.assertEqual(popup.open_button.text(), "Open")
            self.assertFalse(popup.connection.connected)
            self.assertFalse(popup.terminal.can_send)
            self.assertFalse(popup.connection.timer.isActive())
            self.assertIn("disconnected", popup.status.text())
            popup.open_button.click()
            popup.connection.timer.stop()
            type(port).in_waiting = unittest.mock.PropertyMock(side_effect=console.serial.SerialException("Device unplugged"))
            popup.connection.poll()
            self.assertEqual(popup.open_button.text(), "Open")
            self.assertFalse(popup.connection.connected)
            self.assertTrue(popup.ports.isEnabled())
            self.assertTrue(popup.baud.isEnabled())
            self.assertEqual(factory.call_count, 3)

    def test_console_port_list_refreshes_inside_console_without_opening(self):
        window = self.window()
        ports = [unittest.mock.Mock(device="COM30", description="Debug VCOM"),
                 unittest.mock.Mock(device="COM17", description="CH341 USB Serial")]
        with patch.object(console.list_ports, "comports", return_value=ports), \
             patch.object(console.serial, "Serial") as serial:
            window.open_console()
            popup = window.console_window
            window.show()
            self.application.processEvents()
            self.assertEqual(popup.ports.count(), 2)
            self.assertEqual(popup.ports.itemData(0), "COM17")
            self.assertEqual(popup.ports.itemData(1), "COM30")
            self.assertEqual(popup.baud.currentText(), "115200")
            self.assertFalse(window.centralWidget().isAncestorOf(popup.ports))
            self.assertFalse(window.centralWidget().isAncestorOf(popup.baud))
            popup.ports.setCurrentIndex(1)
            popup.refresh_ports()
            self.assertEqual(popup.ports.currentData(), "COM30")
            serial.assert_not_called()
        with patch.object(console, "available_ports", return_value=[]):
            popup.refresh_ports()
            self.assertFalse(popup.open_button.isEnabled())
            self.assertEqual(popup.ports.currentData(), "")

    def test_console_open_reuses_window_and_closing_releases_port(self):
        window = self.window()
        port = self.fake_console_port()
        with patch.object(console, "available_ports", return_value=[unittest.mock.Mock(device="COM30", description="Debug VCOM")]), \
             patch.object(console.serial, "Serial", return_value=port) as factory:
            factory.assert_not_called()
            window.open_console()
            popup = window.console_window
            factory.assert_not_called()
            popup.open_button.click()
            popup.connection.timer.stop()
            self.assertTrue(popup.connection.connected)
            self.assertTrue(popup.isVisible())
            window.open_console()
            self.assertFalse(popup.isVisible())
            self.assertTrue(popup.connection.connected)
            self.assertFalse(window.console_button.isChecked())
            window.open_console()
            self.assertTrue(popup.isVisible())
            self.assertTrue(window.console_button.isChecked())
            self.assertIs(window.console_window, popup)
            self.assertEqual(factory.call_count, 1)
            self.assertEqual(len(window.findChildren(console.ConsoleWindow)), 1)
            popup.receive(b"boot output\r\n")
            popup.flush_receive()
            self.assertIn("boot output", popup.terminal.toPlainText())
            popup.reject()
            self.assertFalse(popup.isVisible())
            self.assertFalse(popup.connection.connected)
            self.assertFalse(popup.connection.timer.isActive())
            window.open_console()
            popup.open_button.click()
            popup.connection.timer.stop()
            self.assertIs(window.console_window, popup)
            self.assertIn("boot output", popup.terminal.toPlainText())
            window.close()
            self.assertFalse(popup.isVisible())
            self.assertFalse(popup.connection.connected)

    def test_console_port_change_requires_close_and_works_during_programming(self):
        window = self.window()
        port = self.fake_console_port()
        with patch.object(console, "available_ports", return_value=[unittest.mock.Mock(device="COM30", description="Debug"),
                                                                     unittest.mock.Mock(device="COM31", description="Other")]), \
             patch.object(console.serial, "Serial", return_value=port) as factory:
            window.set_busy(True)
            self.assertTrue(window.console_button.isEnabled())
            window.open_console()
            popup = window.console_window
            self.assertTrue(popup.ports.isEnabled())
            self.assertTrue(popup.open_button.isEnabled())
            popup.open_button.click()
            popup.connection.timer.stop()
            self.assertEqual(popup.open_button.text(), "Close")
            self.assertFalse(popup.ports.isEnabled())
            self.assertFalse(popup.baud.isEnabled())
            self.assertEqual(factory.call_count, 1)
            popup.open_button.click()
            self.assertEqual(popup.open_button.text(), "Open")
            self.assertFalse(popup.connection.connected)
            popup.ports.setCurrentIndex(1)
            popup.baud.setCurrentText("57600")
            popup.receive(b"Old port pending output")
            popup.open_button.click()
            popup.connection.timer.stop()
            self.assertEqual(popup.device, "COM31")
            self.assertEqual(popup.baudrate, 57600)
            self.assertEqual(popup.open_button.text(), "Close")
            self.assertEqual(factory.call_count, 2)
            self.assertFalse(popup.pending_receive)
            self.assertNotIn("Old port pending output", popup.terminal.toPlainText())
            window.set_busy(False)

    def test_console_open_failure_is_reported_without_leaking_port(self):
        window = self.window()
        port = self.fake_console_port()
        port.open.side_effect = console.serial.SerialException("Access denied")
        with patch.object(console, "available_ports", return_value=[unittest.mock.Mock(device="COM30", description="Debug")]), \
             patch.object(console.serial, "Serial", return_value=port):
            window.open_console()
            window.console_window.open_button.click()
            self.assertIn("Access denied", window.log.toPlainText())
            self.assertFalse(window.console_window.connection.connected)
            self.assertFalse(window.console_window.connection.timer.isActive())
            self.assertEqual(window.console_window.open_button.text(), "Open")
            self.assertTrue(window.console_window.ports.isEnabled())
            port.close.assert_called_once()

    def test_console_first_show_uses_right_side_then_stays_independent_of_main(self):
        screen = unittest.mock.Mock()
        screen.availableGeometry.return_value = QRect(0, 0, 3200, 1800)
        for position in (1100, 2400):
            with self.subTest(position=position):
                window = self.window()
                window.show()
                self.application.processEvents()
                with patch.object(console, "available_ports", return_value=[]), \
                     patch.object(window, "screen", return_value=screen):
                    window.move(position, 40)
                    window.console_button.click()
                    self.application.processEvents()
                    popup = window.console_window
                    self.assertEqual(popup.size(), window.size())
                    self.assertEqual(popup.frameGeometry().top(), window.frameGeometry().top())
                    if position == 1100:
                        self.assertEqual(popup.frameGeometry().left(), window.frameGeometry().right() + 1)
                    else:
                        self.assertEqual(popup.frameGeometry().right(), screen.availableGeometry().right())
                    frame, size = popup.frameGeometry(), popup.size()
                    window.resize(920, 600)
                    window.move(1200, 70)
                    self.application.processEvents()
                    self.assertEqual(popup.frameGeometry(), frame)
                    self.assertEqual(popup.size(), size)
                    self.assertFalse(popup.connection.connected)

    def test_console_geometry_survives_hide_close_and_next_app_start(self):
        with patch.object(console, "available_ports", return_value=[]), \
             patch.object(console.serial, "Serial") as serial:
            window = self.window()
            window.show()
            self.application.processEvents()
            window.console_button.click()
            self.application.processEvents()
            popup = window.console_window
            popup.resize(620, 360)
            popup.move(90, 70)
            self.application.processEvents()
            frame, size = popup.frameGeometry(), popup.size()
            window.console_button.click()
            window.move(20, 20)
            window.console_button.click()
            self.application.processEvents()
            self.assertEqual(popup.frameGeometry(), frame)
            self.assertEqual(popup.size(), size)
            popup.close()
            self.assertFalse(window.console_button.isChecked())
            window.console_button.click()
            self.application.processEvents()
            self.assertEqual(popup.frameGeometry(), frame)
            self.assertEqual(popup.size(), size)
            window.close()
            saved = json.loads((self.root / "settings.json").read_text(encoding="utf-8"))
            self.assertTrue(saved["console"]["_geometry"])
            restored = self.window()
            restored.show()
            self.application.processEvents()
            restored.console_button.click()
            self.application.processEvents()
            self.assertEqual(restored.console_window.frameGeometry(), frame)
            self.assertEqual(restored.console_window.size(), size)
            self.assertFalse(restored.console_window.connection.connected)
            serial.assert_not_called()

    def test_console_geometry_invalid_data_uses_saved_size_and_default_position(self):
        settings = app.JsonSettings(self.root / "settings.json")
        settings.setValue("console", {"_geometry": "not hexadecimal", "_size": [600, 320]})
        settings.sync()
        with patch.object(console, "available_ports", return_value=[]):
            window = self.window()
            window.show()
            self.application.processEvents()
            window.console_button.click()
            self.application.processEvents()
            self.assertEqual(window.console_window.width(), 600)
            self.assertEqual(window.console_window.height(), 320)
            self.assertEqual(window.console_window.frameGeometry().top(), window.frameGeometry().top())

    def test_usb_trace_opens_to_right_and_follows_main_on_same_screen(self):
        window = self.window()
        window.show()
        self.application.processEvents()
        popup = window.trace_window
        popup.resize(640, 360)
        size = popup.size()
        screen = unittest.mock.Mock()
        screen.availableGeometry.return_value = QRect(0, 0, 3200, 1800)
        with patch.object(window, "screen", return_value=screen):
            window.move(100, 50)
            window.trace_button.click()
            self.application.processEvents()
            self.assertEqual(popup.frameGeometry().left(), window.frameGeometry().right() + 1)
            self.assertEqual(popup.frameGeometry().top(), window.frameGeometry().top())
            self.assertEqual(popup.size(), size)
            window.resize(920, 600)
            window.move(1200, 70)
            self.application.processEvents()
            self.assertEqual(popup.frameGeometry().left(), window.frameGeometry().right() + 1)
            self.assertEqual(popup.frameGeometry().top(), window.frameGeometry().top())
            self.assertEqual(popup.size(), size)
            window.trace_button.click()
            window.move(2400, 1500)
            window.trace_button.click()
            self.application.processEvents()
            self.assertTrue(screen.availableGeometry().contains(popup.frameGeometry()))
            self.assertEqual(popup.frameGeometry().right(), screen.availableGeometry().right())
            self.assertEqual(popup.frameGeometry().bottom(), screen.availableGeometry().bottom())
            self.assertEqual(popup.size(), size)
            window.trace_button.click()
            popup.move(10, 10)
            window.move(200, 80)
            window.trace_button.click()
            self.application.processEvents()
            self.assertEqual(popup.frameGeometry().left(), window.frameGeometry().right() + 1)
            self.assertEqual(popup.frameGeometry().top(), window.frameGeometry().top())

    def test_console_full_screen_redraw_keeps_first_and_last_rows_visible(self):
        terminal = console.TerminalView()
        self.addCleanup(terminal.close)
        terminal.show()
        for height in (340, 400, 480):
            with self.subTest(height=height):
                terminal.resize(780, height)
                self.application.processEvents()
                rows = terminal.screen.lines
                lines = ["Mem: 56608K used, 64952K free, 388K shrd, 0K buff, 24656K cached",
                         "CPU: 0% usr 1% sys 98% idle",
                         "Load average: 1.07 2.24 1.09",
                         "\x1b[7m  PID PPID USER STAT RSS COMMAND\x1b[0m"]
                lines += [f"{1009 + index} root S process-{index}" for index in range(rows - len(lines))]
                frame = ("\x1b[H\x1b[J" + "\r\n".join(lines)).encode("ascii")
                terminal.clear_terminal()
                for redraw in range(2):
                    terminal.feed(frame)
                    self.application.processEvents()
                    self.assertFalse(terminal.screen.history.top)
                    self.assertTrue(terminal.screen.display[0].startswith("Mem:"))
                    self.assertTrue(terminal.firstVisibleBlock().text().startswith("Mem:"))
                    cursor = console.QTextCursor(terminal.document().firstBlock())
                    self.assertGreaterEqual(terminal.cursorRect(cursor).top(), 0)
                    cursor = console.QTextCursor(terminal.document().lastBlock())
                    self.assertLess(terminal.cursorRect(cursor).bottom(), terminal.viewport().height())

    def test_console_new_output_always_scrolls_to_latest(self):
        terminal = console.TerminalView()
        self.addCleanup(terminal.close)
        terminal.show()
        self.application.processEvents()
        terminal.feed(b"Older output\r\n" * 200)
        scrollbar = terminal.verticalScrollBar()
        self.assertGreater(scrollbar.maximum(), 0)
        scrollbar.setValue(0)
        terminal.feed(b"Latest console output\r\n")
        self.application.processEvents()
        self.assertEqual(scrollbar.value(), scrollbar.maximum())
        self.assertIn("Latest console output", terminal.toPlainText())

    def test_console_terminal_input_and_black_background(self):
        terminal = console.TerminalView()
        terminal.show()
        self.application.processEvents()
        terminal.can_send = True
        sent = QSignalSpy(terminal.input_ready)
        QTest.keyClicks(terminal, "help")
        QTest.keyClick(terminal, Qt.Key.Key_Return)
        QTest.keyClick(terminal, Qt.Key.Key_Up)
        QTest.keyClick(terminal, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual([sent.at(index)[0] for index in range(sent.count())],
                         [b"h", b"e", b"l", b"p", b"\r", b"\x1b[A", b"\x03"])
        self.assertEqual(terminal.toPlainText().strip(), "")
        self.assertEqual(terminal.palette().base().color().name(), "#000000")
        terminal.can_send = False
        QTest.keyClicks(terminal, "ignored")
        self.assertEqual(sent.count(), 7)
        terminal.close()

    def test_console_terminal_ansi_colors_styles_and_reset(self):
        terminal = console.TerminalView()
        self.addCleanup(terminal.close)
        terminal.feed(b"\x1b[31mR\x1b[91mB\x1b[38;5;202mP\x1b[38;2;12;34;56mT"
                      b"\x1b[0m\x1b[1;3;4;9;32;44mS\x1b[0m\x1b[7mI\x1b[0mN")
        fragments = {}
        iterator = terminal.document().firstBlock().begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            for character in fragment.text():
                if character != " ":
                    fragments[character] = fragment.charFormat()
            iterator += 1
        self.assertEqual(fragments["R"].foreground().color().name(), "#cd0000")
        self.assertEqual(fragments["B"].foreground().color().name(), "#ff0000")
        self.assertEqual(fragments["P"].foreground().color().name(), "#ff5f00")
        self.assertEqual(fragments["T"].foreground().color().name(), "#0c2238")
        self.assertEqual(fragments["S"].background().color().name(), "#0000ee")
        self.assertEqual(fragments["S"].fontWeight(), console.QFont.Weight.Bold)
        self.assertTrue(fragments["S"].fontItalic())
        self.assertTrue(fragments["S"].fontUnderline())
        self.assertTrue(fragments["S"].fontStrikeOut())
        self.assertEqual(fragments["I"].foreground().color().name(), "#000000")
        self.assertEqual(fragments["I"].background().color().name(), "#e6e6e6")
        self.assertEqual(fragments["N"].foreground().color().name(), "#e6e6e6")
        self.assertEqual(fragments["N"].background().color().name(), "#000000")
        self.assertFalse(fragments["N"].fontUnderline())
        self.assertNotIn("\x1b", terminal.toPlainText())

    def test_console_terminal_keeps_colors_in_scrollback_and_after_resize(self):
        terminal = console.TerminalView()
        self.addCleanup(terminal.close)
        terminal.resize(640, 320)
        terminal.show()
        self.application.processEvents()
        terminal.feed(b"\x1b[3")
        terminal.feed(b"1mRED\x1b[0m <text> & plain\r\n")
        terminal.feed(b"line\r\n" * (terminal.screen.lines + 5))
        self.assertTrue(terminal.screen.history.top)
        for width, height in ((640, 320), (800, 420)):
            terminal.resize(width, height)
            self.application.processEvents()
            terminal.render()
            first = terminal.document().firstBlock()
            self.assertTrue(first.text().startswith("RED <text> & plain"))
            self.assertEqual(first.begin().fragment().charFormat().foreground().color().name(), "#cd0000")
            self.assertEqual(terminal.verticalScrollBar().value(), terminal.verticalScrollBar().maximum())
        self.assertNotIn("\x1b", terminal.toPlainText())

    def test_console_terminal_ansi_utf8_history_and_resize(self):
        terminal = console.TerminalView()
        terminal.show()
        self.application.processEvents()
        terminal.feed(b"\x1b[2J\x1b[Hstart\r\n\x1b[31mready\x1b[0m\x1b[2D!!\r\n\xce")
        terminal.feed(b"\xa9")
        self.assertIn("start", terminal.toPlainText())
        self.assertIn("rea!!", terminal.toPlainText())
        self.assertIn("\u03a9", terminal.toPlainText())
        self.assertNotIn("\x1b", terminal.toPlainText())
        terminal.feed(b"\r\nline\r\n" * 100)
        self.assertTrue(terminal.screen.history.top)
        self.application.processEvents()
        self.assertEqual(terminal.horizontalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.assertEqual(terminal.verticalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.assertFalse(terminal.horizontalScrollBar().isVisible())
        self.assertFalse(terminal.verticalScrollBar().isVisible())
        self.assertGreater(terminal.verticalScrollBar().maximum(), 0)
        scrollbar = terminal.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        previous = scrollbar.value()
        position = terminal.viewport().rect().center()
        event = QWheelEvent(QPointF(position), QPointF(terminal.viewport().mapToGlobal(position)),
                    QPoint(0, 0), QPoint(0, 120), Qt.MouseButton.NoButton,
                    Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.ScrollUpdate, False)
        self.application.sendEvent(terminal.viewport(), event)
        self.assertLess(scrollbar.value(), previous)
        terminal.verticalScrollBar().setValue(0)
        self.assertEqual(terminal.verticalScrollBar().value(), 0)
        terminal.resize(640, 320)
        self.application.processEvents()
        self.assertIn("line", terminal.toPlainText())
        terminal.clear_terminal()
        self.assertEqual(terminal.toPlainText(), "")
        self.assertFalse(terminal.screen.history.top)
        terminal.close()

    def test_console_multiline_paste_needs_confirmation(self):
        terminal = console.TerminalView()
        terminal.can_send = True
        sent = QSignalSpy(terminal.input_ready)
        self.application.clipboard().setText("first\nsecond")
        with patch.object(console.QMessageBox, "warning", return_value=QMessageBox.StandardButton.No):
            terminal.paste_input()
        self.assertEqual(sent.count(), 0)
        with patch.object(console.QMessageBox, "warning", return_value=QMessageBox.StandardButton.Yes):
            terminal.paste_input()
        self.assertEqual(sent.at(0), [b"first\rsecond"])
        self.application.clipboard().clear()
        terminal.close()

    def test_console_clear_discards_pending_render_and_save_keeps_output(self):
        popup = console.ConsoleWindow()
        self.addCleanup(popup.close)
        popup.receive(b"old output")
        self.assertTrue(popup.render_timer.isActive())
        popup.clear_output()
        self.assertFalse(popup.pending_receive)
        self.assertFalse(popup.render_timer.isActive())
        self.assertEqual(popup.terminal.toPlainText(), "")
        popup.receive(b"new output\r\n")
        destination = self.root / "console.log"
        with patch.object(console.QFileDialog, "getSaveFileName", return_value=(str(destination), "")):
            popup.save_output()
        self.assertIn("new output", destination.read_text(encoding="utf-8"))

    def test_console_settings_are_owned_by_console_and_open_is_explicit(self):
        ports = [unittest.mock.Mock(device="COM30", description="Debug VCOM")]
        port = self.fake_console_port()
        with patch.object(console, "available_ports", return_value=ports), \
             patch.object(console.serial, "Serial", return_value=port) as factory:
            popup = console.ConsoleWindow()
            self.addCleanup(popup.close)
            popup.show()
            self.application.processEvents()
            self.assertTrue(popup.isAncestorOf(popup.ports))
            self.assertTrue(popup.isAncestorOf(popup.baud))
            self.assertEqual(popup.baud.currentText(), "115200")
            factory.assert_not_called()
            popup.open_button.click()
            popup.connection.timer.stop()
            self.assertTrue(popup.connection.connected)
            self.assertEqual(popup.device, "COM30")
            popup.hide()
            self.assertTrue(popup.connection.connected)
            popup.show()
            self.assertEqual(factory.call_count, 1)
            popup.close()
            self.assertFalse(popup.connection.connected)

    def test_log_commands_and_results_have_different_colors_and_keep_plain_text(self):
        window = self.window()
        command = '$ python nuwriter.py --check "image & <test>.bin"'
        result = "Configuration validated\n<result> & output"
        window.runner.command_started.emit(command)
        window.runner.output.emit(result)
        document = window.log.document()
        first = document.firstBlock()
        self.assertEqual(first.begin().fragment().charFormat().foreground().color().name(), "#005fb8")
        second = first.next()
        self.assertEqual(second.begin().fragment().charFormat().foreground().color().name(), "#21643c")
        self.assertEqual(window.log.toPlainText(), command + "\n" + result)
        self.assertEqual(window.collected, [command, result])
        destination = self.root / "operation.log"
        with patch.object(app.QFileDialog, "getSaveFileName", return_value=(str(destination), "")):
            window.save_log()
        self.assertEqual(destination.read_text(encoding="utf-8"), command + "\n" + result)
        window.clear_log()
        self.assertEqual(window.log.toPlainText(), "")
        window.append_output("$ backend result, not a command")
        fragment = document.firstBlock().begin().fragment()
        self.assertEqual(fragment.charFormat().foreground().color().name(), "#21643c")

    def test_log_error_results_are_red_per_line_without_changing_text(self):
        window = self.window()
        command = '$ python nuwriter.py "error-image.bin"'
        result = ("Checking inputs\n"
                  "Error: No CH341 serial port found; check the driver and USB connection\n"
                  "Other output\n"
                  "ERROR: transfer failed\n"
                  "RuntimeError: simulated failure\n"
                  "Completed")
        window.runner.command_started.emit(command)
        window.runner.output.emit(result)
        expected_colors = ["#005fb8", "#21643c", "#c62828", "#21643c", "#c62828", "#c62828", "#21643c"]
        block = window.log.document().firstBlock()
        for color in expected_colors:
            self.assertTrue(block.isValid())
            self.assertEqual(block.begin().fragment().charFormat().foreground().color().name(), color)
            block = block.next()
        self.assertEqual(window.log.toPlainText(), command + "\n" + result)
        self.assertEqual(window.collected, [command, result])
        destination = self.root / "errors.log"
        with patch.object(app.QFileDialog, "getSaveFileName", return_value=(str(destination), "")):
            window.save_log()
        self.assertEqual(destination.read_text(encoding="utf-8"), command + "\n" + result)

    def test_log_new_output_always_scrolls_to_latest(self):
        window = self.window()
        window.show()
        window.log_button.click()
        self.application.processEvents()
        window.append_output("Older output\n" * 200)
        scrollbar = window.log.verticalScrollBar()
        self.assertGreater(scrollbar.maximum(), 0)
        scrollbar.setValue(0)
        window.append_output("Latest operation output")
        self.application.processEvents()
        self.assertEqual(scrollbar.value(), scrollbar.maximum())
        self.assertTrue(window.log.toPlainText().endswith("Latest operation output"))

    def test_log_popup_is_single_instance_and_preserves_hidden_output(self):
        window = self.window()
        window.show()
        self.application.processEvents()
        popup = window.log_window
        self.assertFalse(popup.isVisible())
        self.assertFalse(popup.isModal())
        self.assertFalse(window.centralWidget().isAncestorOf(window.log))
        self.assertTrue(popup.isAncestorOf(window.log))
        self.assertFalse(popup.findChildren(QPushButton))
        window.runner.output.emit("Output while hidden")
        window.log_button.click()
        self.application.processEvents()
        self.assertTrue(popup.isVisible())
        self.assertTrue(window.log_button.isChecked())
        window.log_button.click()
        self.assertFalse(popup.isVisible())
        self.assertFalse(window.log_button.isChecked())
        self.assertIs(window.log_window, popup)
        self.assertEqual(len(window.findChildren(app.OperationLogWindow)), 1)
        window.runner.output.emit("More output while hidden")
        window.log_button.click()
        self.assertEqual(window.log.toPlainText(), "Output while hidden\nMore output while hidden")
        self.assertTrue(popup.isVisible())
        self.assertIs(window.log_window, popup)
        window.close()
        self.assertFalse(popup.isVisible())
        self.assertFalse(window.log_button.isChecked())

    def test_log_popup_has_title_bar_without_window_controls_or_independent_close(self):
        window = self.window()
        window.show()
        window.log_button.click()
        self.application.processEvents()
        popup = window.log_window
        flags = popup.windowFlags()
        self.assertFalse(flags & Qt.WindowType.FramelessWindowHint)
        self.assertTrue(flags & Qt.WindowType.CustomizeWindowHint)
        self.assertTrue(flags & Qt.WindowType.WindowTitleHint)
        self.assertEqual(popup.windowTitle(), "NuWriter - Operation Log")
        self.assertEqual(popup.height(), 320)
        self.assertEqual(popup.minimumHeight(), popup.maximumHeight())
        for flag in (Qt.WindowType.WindowMinimizeButtonHint, Qt.WindowType.WindowMaximizeButtonHint,
                     Qt.WindowType.WindowCloseButtonHint, Qt.WindowType.WindowSystemMenuHint):
            self.assertFalse(flags & flag)
        QTest.keyClick(popup, Qt.Key.Key_Escape)
        self.assertTrue(popup.isVisible())
        popup.reject()
        popup.close()
        self.assertTrue(popup.isVisible())
        self.assertTrue(window.log_button.isChecked())
        self.assertFalse(popup.findChildren(QPushButton))

    def test_log_popup_aligns_below_main_window_and_matches_width(self):
        window = self.window()
        window.move(30, 30)
        window.show()
        self.application.processEvents()
        window.log_button.click()
        self.application.processEvents()
        popup = window.log_window
        for width, height, position in ((800, 560, (30, 30)), (920, 600, (60, 50))):
            with self.subTest(width=width):
                window.resize(width, height)
                window.move(*position)
                self.application.processEvents()
                self.assertEqual(popup.frameGeometry().width(), window.frameGeometry().width())
                self.assertEqual(popup.minimumWidth(), popup.width())
                self.assertEqual(popup.maximumWidth(), popup.width())
                self.assertEqual(popup.height(), 320)
                self.assertEqual(popup.frameGeometry().left(), window.frameGeometry().left())
                self.assertEqual(popup.frameGeometry().top(), window.frameGeometry().bottom() + 1)
        window.log_button.click()
        popup.move(200, 200)
        window.log_button.click()
        self.application.processEvents()
        self.assertEqual(popup.frameGeometry().top(), window.frameGeometry().bottom() + 1)

    def test_log_popup_compensates_different_borders_and_sets_width_before_show(self):
        window = self.window()
        window.show()
        self.application.processEvents()
        popup = window.log_window
        show_popup = popup.show
        frame = app.QRect(30, 30, window.width() + 20, window.height() + 40)

        def popup_frame():
            return app.QRect(0, 0, popup.width() + 8, popup.height() + 30)

        def check_width_before_show():
            self.assertEqual(popup.width(), frame.width() - 8)
            self.assertEqual(popup.minimumWidth(), popup.width())
            self.assertEqual(popup.maximumWidth(), popup.width())
            show_popup()

        with patch.object(window, "frameGeometry", return_value=frame), \
             patch.object(popup, "frameGeometry", side_effect=popup_frame), \
             patch.object(popup, "show", side_effect=check_width_before_show) as show:
            window.log_button.click()
            self.application.processEvents()
            show.assert_called_once()
            self.assertEqual(popup.frameGeometry().width(), frame.width())
            self.assertEqual(popup.height(), 320)

    def test_log_popup_is_available_during_operations_without_action_buttons(self):
        window = self.window()
        window.show()
        window.append_output("Keep this output")
        window.set_busy(True)
        self.assertFalse(window.controls.isEnabled())
        self.assertTrue(window.log_button.isEnabled())
        window.log_button.click()
        self.application.processEvents()
        self.assertTrue(window.log_window.isVisible())
        self.assertFalse(window.log_window.findChildren(QPushButton))
        self.assertEqual(window.log.toPlainText(), "Keep this output")
        window.set_busy(False)
        window.log_button.click()
        self.assertFalse(window.log_window.isVisible())
        self.assertEqual(window.log.toPlainText(), "Keep this output")

    def test_banner_uses_cropped_logo_from_script_directory(self):
        original_directory = Path.cwd()
        try:
            os.chdir(self.root)
            window = self.window()
        finally:
            os.chdir(original_directory)
        brand = window.findChild(QLabel, "brand")
        self.assertEqual(brand.text(), "")
        self.assertFalse(brand.pixmap().isNull())
        self.assertEqual(brand.accessibleName(), "Nuvoton")
        size = brand.pixmap().deviceIndependentSize()
        self.assertLessEqual(size.width(), 224)
        self.assertLessEqual(size.height(), 32)
        self.assertGreater(size.width() / size.height(), 5)
        for width, height in ((1060, 760), (780, 580)):
            window.resize(width, height)
            window.show()
            self.application.processEvents()
            self.assertTrue(brand.isVisible())
            self.assertEqual(brand.size().width(), 224)
            self.assertEqual(brand.size().height(), 32)

    def test_main_window_starts_top_left_without_help_and_console_precedes_log(self):
        window = self.window()
        with patch.object(console, "available_ports") as ports:
            window.show()
            self.application.processEvents()
            self.assertEqual(window.frameGeometry().topLeft(), window.screen().availableGeometry().topLeft())
            self.assertIsNone(window.menuWidget())
            ports.assert_not_called()
        console_x = window.console_button.mapTo(window, window.console_button.rect().center()).x()
        log_x = window.log_button.mapTo(window, window.log_button.rect().center()).x()
        self.assertLess(console_x, log_x)
        self.assertIsNone(window.console_window)
        self.assertFalse(window.runner.busy)

    def test_choose_type_is_25_percent_wider_and_ddr_uses_remaining_space(self):
        window = self.window()
        window.show()
        self.application.processEvents()
        expected = (window.media.sizeHint().width() * 5 + 3) // 4
        previous_ddr_width = None
        for width in (780, 800, 960):
            with self.subTest(width=width):
                window.resize(width, 560)
                self.application.processEvents()
                self.assertEqual(window.width(), width)
                self.assertEqual(window.media.width(), expected)
                self.assertGreater(window.ddr.geometry().left(), window.media.geometry().right())
                self.assertGreater(window.reconnect_button.geometry().left(), window.ddr.geometry().right())
                self.assertTrue(window.controls.rect().contains(window.reconnect_button.geometry().bottomRight()))
                if previous_ddr_width is not None:
                    self.assertEqual(window.ddr.width() - previous_ddr_width, width - previous_width)
                previous_ddr_width = window.ddr.width()
                previous_width = width

    def test_default_window_size_is_800_by_560_for_all_pages(self):
        window = self.window()
        window.show()
        self.application.processEvents()
        self.assertEqual(window.size().width(), 800)
        self.assertEqual(window.size().height(), 560)
        for index in range(window.media.count()):
            with self.subTest(media=window.media.itemText(index)):
                window.media.setCurrentIndex(index)
                self.application.processEvents()
                self.assertEqual(window.size().width(), 800)
                self.assertEqual(window.size().height(), 560)
                self.assertTrue(window.pages.currentWidget().isVisible())
                page = window.pages.currentWidget()
                self.assertGreaterEqual(page.height(), page.minimumSizeHint().height())
                self.assertGreaterEqual(page.width(), page.minimumSizeHint().width())
                self.assertFalse(window.findChildren(QScrollArea))
                if page is window.flash:
                    for control in (window.flash.program_button, window.flash.verify_button,
                                    window.flash.read_button, window.flash.erase_button,
                                    window.flash.format_button):
                        if not control.isVisible():
                            continue
                        position = control.mapTo(page, control.rect().bottomRight())
                        self.assertTrue(page.rect().contains(position), control.text())
        self.assertFalse(window.runner.busy)

    def test_image_type_rows_have_enough_height_and_do_not_touch_next_field(self):
        window = self.window()
        window.show()
        for media in ("SPI NOR", "NAND", "SD/eMMC", "SPI NAND"):
            with self.subTest(media=media):
                window.media.setCurrentText(media)
                self.application.processEvents()
                panel = window.flash
                kinds = panel.kind_layout.parentWidget()
                for radio in panel.kind_buttons.values():
                    self.assertGreaterEqual(radio.height(), radio.sizeHint().height())
                    self.assertTrue(kinds.rect().contains(radio.geometry()))
                top = panel.kind_buttons["Data"].geometry()
                bottom = panel.kind_buttons["Loader"].geometry()
                self.assertGreaterEqual(bottom.top() - top.bottom() - 1, 8)
                kinds_bottom = kinds.mapTo(panel, kinds.rect().bottomLeft()).y()
                execute_top = panel.execute.mapTo(panel, panel.execute.rect().topLeft()).y()
                self.assertGreaterEqual(execute_top - kinds_bottom - 1, 8)

    def test_flash_panel_stays_side_by_side_in_narrow_windows(self):
        window = self.window()
        window.media.setCurrentText("SPI NAND")
        window.show()
        for width, height in ((1060, 760), (780, 580)):
            with self.subTest(width=width):
                window.resize(width, height)
                self.application.processEvents()
                panel = window.flash
                self.assertEqual(panel.layout().direction(), app.QBoxLayout.Direction.LeftToRight)
                parameters = panel.layout().itemAt(1).widget()
                table_right = panel.images_table.mapTo(panel, panel.images_table.rect().topRight()).x()
                self.assertLess(table_right, parameters.geometry().left())
                self.assertGreater(panel.images_table.maximumHeight(), 180)

    def test_popup_buttons_are_right_aligned_after_refresh_and_available_when_busy(self):
        window = self.window()
        window.show()
        self.application.processEvents()
        buttons = (window.refresh_button, window.console_button, window.trace_button, window.log_button)
        for width in (800, 780, 1060):
            with self.subTest(width=width):
                window.resize(width, 560)
                self.application.processEvents()
                self.assertEqual(window.width(), width)
                rectangles = [QRect(control.mapTo(window, QPoint()), control.size()) for control in buttons]
                for index, control in enumerate(buttons):
                    self.assertTrue(control.isVisible())
                    self.assertGreaterEqual(control.width(), control.sizeHint().width())
                    self.assertEqual(rectangles[index].center().y(), rectangles[0].center().y())
                    if index:
                        self.assertGreater(rectangles[index].left(), rectangles[index - 1].right())
                edge = window.centralWidget().mapTo(window, window.centralWidget().rect().topRight()).x()
                margin = window.centralWidget().layout().contentsMargins().right()
                self.assertEqual(rectangles[-1].right(), edge - margin)
        window.set_busy(True)
        self.assertFalse(window.devices.isEnabled())
        self.assertFalse(window.refresh_button.isEnabled())
        for control in buttons[1:]:
            self.assertTrue(control.isEnabled())
        window.set_busy(False)
        self.assertTrue(window.devices.isEnabled())
        self.assertTrue(window.refresh_button.isEnabled())
        window.media.setCurrentText("Mass Production")
        window.set_busy(True)
        window.set_busy(False)
        self.assertFalse(window.devices.isEnabled())
        self.assertTrue(window.refresh_button.isEnabled())

    def test_footer_has_no_stop_or_exit_and_keeps_busy_close_guard(self):
        window = self.window()
        window.show()
        self.application.processEvents()
        labels = [control.text() for control in window.findChildren(QPushButton)]
        self.assertNotIn("Stop", labels)
        self.assertNotIn("EXIT", labels)
        self.assertFalse(hasattr(window, "stop_button"))
        window.runner.busy = True
        try:
            window.set_busy(True)
            self.assertFalse(window.controls.isEnabled())
            self.assertTrue(window.console_button.isEnabled())
            self.assertTrue(window.trace_button.isEnabled())
            self.assertTrue(window.log_button.isEnabled())
            with patch.object(window, "error") as error:
                self.assertFalse(window.close())
                error.assert_called_once_with("An operation is running. Wait for it to finish before closing.")
            self.assertTrue(window.isVisible())
        finally:
            window.runner.busy = False
            window.set_busy(False)
        self.assertTrue(window.controls.isEnabled())
        self.assertTrue(window.close())
        self.assertFalse(window.isVisible())

    def test_window_does_not_launch_backend_and_preserves_media_lists(self):
        with patch.object(app.BackendRunner, "start") as start:
            window = self.window()
            window.show()
            self.application.processEvents()
            self.assertEqual(window.media.count(), 7)
            self.assertEqual(window.media.currentText(), "SDRAM")
            self.assertIs(window.pages.currentWidget(), window.ram)
            self.assertLess(window.devices.mapTo(window, window.devices.rect().center()).y(),
                            window.media.mapTo(window, window.media.rect().center()).y())
            window.media.setCurrentText("SPI NAND")
            window.flash.images.append(backend.ImageEntry("first.bin"))
            window.media.setCurrentText("NAND")
            self.assertFalse(window.flash.images)
            window.media.setCurrentText("SPI NAND")
            self.assertEqual(len(window.flash.images), 1)
            window.media.setCurrentText("Mass Production")
            self.assertTrue(window.target().massproduct)
            self.assertFalse(window.devices.isEnabled())
            start.assert_not_called()

    def test_mass_production_results_show_individual_stage_and_failure_details(self):
        window = self.window()
        events = [
            {"device": "1:2", "stage": "Prepare", "status": "Pending"},
            *[{"device": "1:2", "stage": stage, "status": "Passed"} for stage in ("Erase", "Burn", "Verify", "Result")],
            {"device": "1:3", "stage": "Prepare", "status": "Pending"},
            {"device": "1:3", "stage": "Erase", "status": "Skipped"},
            {"device": "1:3", "stage": "Burn", "status": "Failed", "detail": "USB write timed out"},
            {"device": "1:3", "stage": "Result", "status": "Failed", "detail": "USB write timed out"},
        ]
        for event in events:
            window.runner.parse("MP " + json.dumps(event) + "\n")
        results = window.mass.results
        self.assertEqual(results.rowCount(), 2)
        self.assertEqual([results.item(0, column).text() for column in range(5)], ["1:2", "Passed", "Passed", "Passed", "Passed"])
        self.assertEqual([results.item(1, column).text() for column in range(5)], ["1:3", "Skipped", "Failed", "Not run", "Failed"])
        self.assertEqual(results.item(1, 4).foreground().color().name(), "#c62828")
        self.assertEqual(results.item(1, 4).toolTip(), "USB write timed out")
        self.assertIn("Passed: 1  Failed: 1  Pending: 0", window.mass.summary.text())
        self.assertNotIn("MP {", window.log.toPlainText())
        self.assertIn("Device 1:3 Burn: Failed", window.log.toPlainText())

    def test_mass_production_program_requests_verify_and_confirmation(self):
        window = self.window()
        window.media.setCurrentText("Mass Production")
        pack = self.root / "pack.bin"
        pack.write_bytes(b"simulated pack")
        window.mass.filename.setText(str(pack))
        with patch.object(window.runner, "start") as start, \
             patch.object(app.QMessageBox, "warning", return_value=QMessageBox.StandardButton.Yes) as warning:
            window.mass.program()
        command = start.call_args.args[0]
        self.assertIn("-m", command.arguments)
        self.assertEqual(command.arguments[command.arguments.index("-o") + 1], "verify")
        self.assertIn("Erase All", warning.call_args.args[2])
        self.assertTrue(command.label.endswith("mass production"))
        window.mass.update_result({"device": "1:2", "stage": "Result", "status": "Passed"})
        with patch.object(window.runner, "start") as start, \
             patch.object(app.QMessageBox, "warning", return_value=QMessageBox.StandardButton.No):
            window.mass.program()
        start.assert_not_called()
        self.assertEqual(window.mass.results.rowCount(), 1)

    def test_gui_has_no_check_only_and_requires_hardware_confirmation(self):
        window = self.window()
        self.assertFalse(hasattr(window, "check_only"))
        self.assertNotIn("Check only", [checkbox.text() for checkbox in window.findChildren(app.QCheckBox)])
        command = backend.Command(["-e", "spinand", "all"])
        with patch.object(window.runner, "start") as start, \
             patch.object(app.QMessageBox, "warning", return_value=QMessageBox.StandardButton.Yes) as warning:
            window.submit(command, warning="Erase all?")
        start.assert_called_once_with(command)
        warning.assert_called_once_with(window, command.label, "Erase all?",
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                        QMessageBox.StandardButton.No)
        window.operation_finished(True, "Completed")
        self.assertEqual(window.progress.value(), 100)
        self.assertEqual(window.status.text(), "Passed")
        self.assertEqual(window.status.toolTip(), "Completed")

    def test_rejected_confirmation_does_not_start_backend(self):
        window = self.window()
        with patch.object(window.runner, "start") as start, patch.object(app.QMessageBox, "warning", return_value=QMessageBox.StandardButton.No):
            window.submit(backend.Command(["-e", "spinand", "all"]), warning="Erase all?")
        start.assert_not_called()

    def test_pack_json_round_trip_preserves_extra_fields(self):
        config = self.root / "pack.json"
        document = {"mode": "spinand", "storage": {"page_size": 2048}, "image": [{"file": "image.bin", "type": "data", "offset": "0", "env_size": 4096}]}
        config.write_text(json.dumps(document))
        window = self.window()
        window.pack.load_json(config)
        with patch.object(app.QFileDialog, "getSaveFileName", return_value=(str(config), "")):
            self.assertTrue(window.pack.save_json())
        self.assertEqual(json.loads(config.read_text()), document)

    def test_pack_image_editor_preserves_aliases_and_parameters(self):
        image = {"file": "loader.bin", "type": "uboot", "address": "0x0", "execute_address": "0xe00000",
                 "ddr_ini": "DDR.ini", "page_size": 2048}
        dialog = app.PackImageDialog(image)
        dialog.validate()
        self.assertEqual(dialog.result_image, {"file": "loader.bin", "type": "loader", "offset": "0x0",
                                               "exec_addr": "0xe00000", "ddr_ini": "DDR.ini", "page_size": 2048})
        dialog.close()

    def test_ddr_uses_project_relative_sys_cfg_from_unrelated_directory(self):
        original_directory = Path.cwd()
        try:
            os.chdir(self.root)
            with patch.object(app.QFileDialog, "getOpenFileName") as browse:
                window = self.window()
                expected = sorted(path.name for path in (backend.ROOT / "sys_cfg").glob("*.ini"))
                self.assertEqual([window.ddr.itemText(index) for index in range(window.ddr.count())], expected)
                self.assertFalse(window.ddr.isEditable())
                self.assertFalse(hasattr(window, "select_ddr"))
                self.assertIs(window.ddr.parentWidget(), window.controls)
                for index in range(window.ddr.count()):
                    relative = Path(window.ddr.itemData(index))
                    self.assertFalse(relative.is_absolute())
                    self.assertEqual(relative.parent, Path("sys_cfg"))
                window.ddr.setCurrentIndex((window.ddr.currentIndex() + 1) % window.ddr.count())
                selected = window.ddr.currentText()
                absolute = backend.ROOT / "sys_cfg" / selected
                self.assertEqual(Path(window.target().ddr), absolute)
                self.assertIn(str(absolute), backend.attach(window.target()).arguments)
                window.close()
                restored = self.window()
                self.assertEqual(restored.ddr.currentText(), selected)
                self.assertEqual(Path(restored.target().ddr), absolute)
                browse.assert_not_called()
        finally:
            os.chdir(original_directory)

    def test_ddr_ignores_legacy_external_path_and_clears_it(self):
        external = self.root / "external-ddr.ini"
        external.write_text("external settings")
        settings = app.JsonSettings(self.root / "settings.json")
        settings.setValue("ddr", external.name)
        settings.setValue("ddr_path", str(external))
        settings.sync()
        window = self.window()
        self.assertEqual(window.ddr.currentText(), "NUC980DK71YC.ini")
        self.assertEqual(Path(window.target().ddr), backend.ROOT / "sys_cfg" / "NUC980DK71YC.ini")
        self.assertEqual(window.ddr.findText(external.name), -1)
        window.close()
        self.assertFalse(window.settings.contains("ddr_path"))

    def test_pack_output_uses_snapshot_and_does_not_overwrite_config(self):
        config = self.root / "pack.json"
        document = {"mode": "spinand", "image": [{"file": "original.bin", "type": "data", "offset": "0"}]}
        config.write_text(json.dumps(document))
        window = self.window()
        window.pack.load_json(config)
        window.pack.document["image"][0]["file"] = "edited.bin"
        with patch.object(app.QFileDialog, "getSaveFileName", return_value=(str(self.root / "pack.bin"), "")), patch.object(window.runner, "start") as start:
            window.pack.output()
        self.assertEqual(json.loads(config.read_text()), document)
        snapshot = window.pack_snapshot
        self.assertEqual(json.loads(snapshot.read_text())["image"][0]["file"], "edited.bin")
        self.assertEqual(start.call_args.kwargs, {})
        window.operation_finished(True, "Completed")
        self.assertFalse(snapshot.exists())

    def test_real_backend_check_for_all_media_attach_and_ram(self):
        sample = backend.ROOT / "sample"
        image = sample / "u-boot-spinand.bin"
        self.assertTrue(image.is_file(), "Commit sample images with the integration tests")
        target = backend.Target(str(backend.ROOT / "sys_cfg" / "NUC980DK71YC.ini"))
        kernel = sample / "zImage"
        self.assertEqual(int.from_bytes(kernel.read_bytes()[36:40], "little"), 0x016F2818)
        commands = [backend.attach(target), backend.download(target, image, "0xe00000"),
                backend.download(target, kernel, "0x8000", execute=True,
                         dtb=str(sample / "nuc980-iot-128m-bmc.dtb"),
                         bootargs="noinitrd ubi.mtd=3 root=ubi0:rootfs rootfstype=ubifs rw console=ttyS0,115200n8")]
        for media in ("NAND", "SPI NAND", "SPI NOR", "SD/eMMC"):
            commands.append(backend.program(target, media, backend.ImageEntry(str(image))))
        format_ini = self.root / "format.ini"
        format_ini.write_text(backend.format_configuration(target, 32, [128, 0]))
        commands.append(backend.Command([str(format_ini)], label="Format check"))
        for command in commands:
            with self.subTest(label=command.label):
                done = QSignalSpy(self.runner.finished)
                check_command = backend.Command(command.arguments + ["--check"], cwd=command.cwd, label=command.label)
                self.runner.start(check_command, preflight=False)
                self.wait_finished(done)
                self.assertTrue(done.at(0)[0], done.at(0)[1])

    def test_real_backend_check_for_sample_spinand_and_sd1_templates(self):
        sample = backend.ROOT / "sample"
        target = backend.Target(str(backend.ROOT / "sys_cfg" / "NUC980DK71YC.ini"))
        cases = (("SPI NAND", "config_spinand.json", "nuwriter-pack-spinand.bin", "spinand"),
                 ("SD/eMMC", "config_sd1.json", "nuwriter-pack-sd.bin", "sd"))
        for media, filename, packed, mode in cases:
            with self.subTest(media=media):
                config = sample / filename
                original = config.read_bytes()
                document = json.loads(original)
                self.assertEqual(document["mode"], mode)
                self.assertEqual(document["ddr"], "../sys_cfg/NUC980DK71YC.ini")
                for image in document["image"]:
                    if "file" in image:
                        self.assertTrue((sample / image["file"]).is_file(), image["file"])
                if mode == "sd":
                    loader = document["image"][0]
                    self.assertEqual(loader["offset"], "0x400")
                    self.assertEqual(loader["exec_addr"], "0xe00000")
                    self.assertEqual(document["image"][-1]["partition"], {"count": 1, "reserved_size": 8, "sizes": [0]})
                output = self.root / f"{mode}-pack.bin"
                commands = [backend.pack(config, output, media),
                            backend.program(target, media, backend.ImageEntry(str(sample / packed), "Pack"), verify=True)]
                for command in commands:
                    done = QSignalSpy(self.runner.finished)
                    check_command = backend.Command(command.arguments + ["--check"], cwd=command.cwd, label=command.label)
                    self.runner.start(check_command, preflight=False)
                    self.wait_finished(done)
                    self.assertTrue(done.at(0)[0], done.at(0)[1])
                self.assertFalse(output.exists())
                self.assertEqual(config.read_bytes(), original)

    def test_sample_directory_contains_only_referenced_fixtures(self):
        sample = backend.ROOT / "sample"
        used = {"README.md", "README.zh-CN.md", "README.zh-TW.md", "config_spinand.json", "config_sd1.json", "nuwriter-pack-spinand.bin", "nuwriter-pack-sd.bin", "zImage"}
        for filename in ("config_spinand.json", "config_sd1.json"):
            document = json.loads((sample / filename).read_text(encoding="utf-8"))
            used.update(image["file"] for image in document["image"] if "file" in image)
        self.assertEqual({path.name for path in sample.iterdir() if path.is_file()}, used)


if __name__ == "__main__":
    unittest.main()