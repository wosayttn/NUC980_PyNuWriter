import io
import json
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from importlib import import_module
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import nuwriter

export_spec = spec_from_file_location("nuwriter_export_tools", Path(__file__).with_name("export.py"))
if export_spec is None or export_spec.loader is None:
    raise ImportError("Cannot load the internal export tooling")
export = module_from_spec(export_spec)
export_spec.loader.exec_module(export)


class ExportTests(unittest.TestCase):
    def test_macos_export_preserves_app_bundle_and_keeps_cli_outside(self):
        with tempfile.TemporaryDirectory(prefix="nuwriter macOS ! ") as temporary:
            output = Path(temporary).resolve()

            def freeze(directory, name, entry, gui=False):
                if gui:
                    (directory / "nuwriter-gui").mkdir()
                    (directory / "nuwriter-gui" / "unbundled-executable").write_bytes(b"COLLECT output")
                    bundle = directory / "nuwriter-gui.app"
                    (bundle / "Contents" / "MacOS").mkdir(parents=True)
                    (bundle / "Contents" / "MacOS" / "nuwriter-gui").write_bytes(b"GUI executable")
                    (bundle / "Contents" / "Info.plist").write_bytes(b"Bundle metadata")
                else:
                    cli = directory / "nuwriter"
                    cli.mkdir()
                    (cli / "nuwriter").write_bytes(b"CLI executable")
                    framework = cli / "_internal" / "Python.framework"
                    framework.mkdir(parents=True)
                    (framework / "Python").write_bytes(b"CLI framework")

            def copy_licenses(directory, packages):
                (directory / "licenses").mkdir(parents=True, exist_ok=True)

            with patch.object(sys, "platform", "darwin"), \
                 patch.object(export, "freeze", side_effect=freeze), \
                 patch.object(export, "copy_licenses", side_effect=copy_licenses), \
                 patch.object(export.subprocess, "run") as run:
                export.build(output)
            gui = output / "nuwriter-gui"
            bundle = gui / "nuwriter-gui.app"
            self.assertTrue(bundle.is_dir())
            self.assertEqual({path.relative_to(bundle).as_posix() for path in bundle.rglob("*") if path.is_file()},
                             {"Contents/Info.plist", "Contents/MacOS/nuwriter-gui"})
            self.assertEqual((gui / "backend" / "nuwriter" / "nuwriter").read_bytes(), b"CLI executable")
            self.assertTrue((gui / "licenses").is_dir())
            self.assertFalse((gui / "unbundled-executable").exists())
            self.assertEqual((bundle / "Contents" / "Info.plist").read_bytes(), b"Bundle metadata")
            run.assert_called_once_with(["codesign", "--verify", "--deep", "--strict", str(bundle)], check=True)

    def test_macos_archives_extract_app_and_sibling_backend(self):
        with tempfile.TemporaryDirectory(prefix="nuwriter macOS archives ! ") as temporary:
            output = Path(temporary).resolve()
            cli = output / "nuwriter"
            cli.mkdir()
            (cli / "nuwriter").write_bytes(b"CLI executable")
            gui = output / "nuwriter-gui"
            bundle_executable = gui / "nuwriter-gui.app" / "Contents" / "MacOS" / "nuwriter-gui"
            bundle_executable.parent.mkdir(parents=True)
            bundle_executable.write_bytes(b"GUI executable")
            shutil.copytree(cli, gui / "backend" / "nuwriter")
            checked = []

            def smoke(directory, gui=False):
                if gui:
                    self.assertEqual((export.gui_directory(directory) / "nuwriter-gui").read_bytes(), b"GUI executable")
                    self.assertEqual((directory / "backend" / "nuwriter" / "nuwriter").read_bytes(), b"CLI executable")
                else:
                    self.assertEqual((directory / "nuwriter").read_bytes(), b"CLI executable")
                checked.append(gui)

            with patch.object(sys, "platform", "darwin"), \
                 patch.object(export.platform, "machine", return_value="arm64"), \
                 patch.object(export, "smoke", side_effect=smoke):
                export.archive(output)
            self.assertEqual(checked, [False, True])
            self.assertEqual({path.name for path in (output / "artifacts").glob("*.tar.gz")},
                             {"nuwriter-cli-macos-arm64.tar.gz", "nuwriter-gui-macos-arm64.tar.gz"})

    def test_freezer_uses_local_usb_hook_and_platform_resources(self):
        for system in ("win32", "linux", "darwin"):
            for gui in (False, True):
                with self.subTest(system=system, gui=gui), \
                     patch.object(sys, "platform", system), \
                     patch.object(export.subprocess, "run") as run:
                    export.freeze(export.ROOT / "dist", "example", "gui/app.py" if gui else "nuwriter.py", gui=gui)
                command = run.call_args.args[0]
                self.assertIn(str(export.SCRIPTS / "hooks"), command)
                self.assertEqual(f"{export.ROOT / 'driver'}:driver" in command, system == "win32" and not gui)
                self.assertIn("--windowed" if gui else "--console", command)
                self.assertEqual("PySide6.QtVirtualKeyboard" in command, gui)
                self.assertEqual("export_smoke" in command, gui)
                self.assertNotIn("export", command)
                self.assertEqual(run.call_args.kwargs, {"cwd": export.ROOT, "check": True})

    def test_qt_gui_hook_excludes_virtual_keyboard_plugins_on_all_platforms(self):
        binaries = [(name, "PySide6/plugins/platforminputcontexts") for name in
                    ("qtvirtualkeyboardplugin.dll", "libqtvirtualkeyboardplugin.so",
                     "libqtvirtualkeyboardplugin.dylib", "qpdf.dll", "libqpdf.so", "libqpdf.dylib",
                     "libcomposeplatforminputcontextplugin.so", "qwindows.dll")]
        collect = Mock(return_value=(["PySide6.QtCore", "PySide6.QtVirtualKeyboard"], binaries, []))
        modules = {name: SimpleNamespace() for name in
                   ("PyInstaller", "PyInstaller.utils", "PyInstaller.utils.hooks")}
        modules["PyInstaller.utils.hooks.qt"] = SimpleNamespace(add_qt6_dependencies=collect)
        with patch.dict(sys.modules, modules):
            contents = runpy.run_path(str(export.SCRIPTS / "hooks" / "hook-PySide6.QtGui.py"))
        self.assertEqual(contents["binaries"], binaries[-2:])
        self.assertEqual(contents["hiddenimports"], ["PySide6.QtCore"])

    def test_export_rejects_virtual_keyboard_libraries_plugins_and_frameworks(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            export.verify_qt_exclusions(directory)
            for name in ("Qt6VirtualKeyboard.dll", "libQt6VirtualKeyboard.so.6",
                         "QtVirtualKeyboard.framework", "qtvirtualkeyboardplugin.dll"):
                with self.subTest(name=name):
                    path = directory / name
                    path.touch()
                    with self.assertRaisesRegex(RuntimeError, "Qt Virtual Keyboard"):
                        export.verify_qt_exclusions(directory)
                    path.unlink()

    def test_qt_source_inventory_rejects_unreviewed_native_modules(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for name in ("Qt6Core.dll", "libQt6Svg.so.6", "QtWidgets.framework", "libQt6Gui.6.dylib"):
                (directory / name).touch()
            self.assertEqual(export.qt_source_modules(directory), ["qtbase", "qtsvg"])
            (directory / "Qt6VirtualKeyboard.dll").touch()
            with self.assertRaisesRegex(RuntimeError, "license/source review"):
                export.qt_source_modules(directory)

    def test_linux_eglfs_kms_support_uses_the_qtbase_source_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for name in ("libQt6EglFsKmsSupport.so.6", "libQt6EglFsKmsSupport.so.6.12.0", "libQt6Core.so.6",
                         "libQt6EglFSDeviceIntegration.so.6", "libQt6KmsSupport.so.6", "libQt6XcbQpa.so.6",
                         "libQt6DBus.so.6", "libQt6OpenGLWidgets.so.6", "libQt6WaylandClient.so.6",
                         "libQt6WaylandGlobal.so.6", "libQt6EglFsKmsGbmSupport.so.6",
                         "libQt6WlShellIntegration.so.6"):
                (directory / name).touch()
            self.assertEqual(export.qt_source_modules(directory), ["qtbase"])
            (directory / "libQt6UnreviewedSupport.so.6").touch()
            with self.assertRaisesRegex(RuntimeError, "UnreviewedSupport"):
                export.qt_source_modules(directory)

    def test_build_only_preserves_source_rebuild_without_sample_archive_checks(self):
        with patch.object(export, "build") as build, patch.object(export, "archive") as archive:
            self.assertEqual(export.main(["--build-only"]), 0)
        build.assert_called_once_with(ROOT / "dist")
        archive.assert_not_called()

    def test_source_download_checks_digest_and_reuses_cached_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            digest = export.hashlib.sha256(b"upstream source").hexdigest()
            with patch.object(export.urllib.request, "urlopen", return_value=io.BytesIO(b"upstream source")) as fetch:
                record = export.download_source("https://example.test/library.tar.gz", directory, digest)
                self.assertEqual(record["sha256"], digest)
                export.download_source("https://example.test/library.tar.gz", directory, digest)
            self.assertEqual(fetch.call_count, 1)
            with self.assertRaisesRegex(RuntimeError, "SHA-256 mismatch"):
                export.download_source("https://example.test/library.tar.gz", directory, "0" * 64)
            self.assertFalse((directory / "library.tar.gz").exists())

    def test_license_collection_supplies_missing_notices_and_rebuild_source(self):
        installed_distribution = export.metadata.distribution

        def distribution(name):
            if name in ("pyinstaller", "pyinstaller-hooks-contrib"):
                return SimpleNamespace(version="0", files=(), read_text=lambda filename: None)
            return installed_distribution(name)

        def collect_sources(directory, packages):
            records = []
            for name in packages:
                path = directory / "sources" / (name + ".tar.gz")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"corresponding source")
                records.append({"component": name, "file": path.name,
                                "sha256": export.hashlib.sha256(path.read_bytes()).hexdigest()})
            (directory / "sources/manifest.json").write_text(json.dumps(records))

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            packages = export.PACKAGES
            with patch.object(export, "collect_sources", side_effect=collect_sources) as collect, \
                 patch.object(export.metadata, "distribution", side_effect=distribution):
                export.copy_licenses(directory, packages)
            collect.assert_called_once_with(directory, packages)
            self.assertIn("GNU LESSER GENERAL PUBLIC LICENSE", (directory / "licenses/LGPL-3.0.txt").read_text())
            self.assertIn("Redistribution and use", (directory / "licenses/pyserial/LICENSE.txt").read_text())
            self.assertIn("Armstrong", (directory / "licenses/pyfdt/UPSTREAM-NOTICE.txt").read_text())
            self.assertIn("Apache License", (directory / "licenses/pyfdt/APACHE-2.0.txt").read_text())
            source = directory / "sources/application"
            self.assertTrue((source / ".github/scripts/hooks/hook-PySide6.QtGui.py").is_file())
            self.assertTrue((source / ".github/scripts/BUILDING.md").is_file())
            self.assertFalse((source / ".github/scripts/README.md").exists())
            self.assertTrue((source / "gui/app.py").is_file())
            self.assertIn("pyserial==3.5", (source / ".github/scripts/requirements-export.txt").read_text())
            self.assertFalse((source / "export.py").exists())
            self.assertFalse((source / "export-hooks").exists())
            self.assertFalse((source / "gui/screenshot").exists())
            export.verify_licenses(directory)
            (directory / "sources/pyserial.tar.gz").write_bytes(b"corrupt source")
            with self.assertRaisesRegex(RuntimeError, "source is corrupt"):
                export.verify_licenses(directory)
            (directory / "licenses/LGPL-3.0.txt").unlink()
            with self.assertRaisesRegex(RuntimeError, "missing: licenses/LGPL"):
                export.verify_licenses(directory)

    def test_pyte_hook_keeps_lgpl_python_modules_replaceable(self):
        contents = runpy.run_path(str(export.SCRIPTS / "hooks" / "hook-pyte.py"))
        self.assertEqual(contents["module_collection_mode"], {"pyte": "py"})

    def test_usb_hook_only_declares_imports_without_scanning(self):
        contents = runpy.run_path(str(export.SCRIPTS / "hooks" / "hook-usb.py"))
        self.assertIn("usb.backend.libusb1", contents["hiddenimports"])
        self.assertNotIn("binaries", contents)

    def test_frozen_dependency_check_does_not_discover_devices(self):
        with patch.object(sys, "frozen", True, create=True), \
             patch.object(nuwriter.importlib, "import_module") as load, \
             patch.object(nuwriter, "discover_devices") as discover, \
             patch.object(nuwriter, "run_pre_attach_hook") as hook:
            self.assertEqual(nuwriter.main(["--export-smoke-test"]), 0)
        self.assertEqual([call.args[0] for call in load.call_args_list],
                         ["usb.core", "usb.util", "usb.backend.libusb1", "pyfdt.pyfdt", "serial.tools.list_ports"])
        discover.assert_not_called()
        hook.assert_not_called()

    def test_relocated_tool_paths_resolve_from_an_unrelated_directory(self):
        self.assertEqual(export.ROOT, ROOT)
        requirements = export.SCRIPTS / "requirements-export.txt"
        include = requirements.read_text().splitlines()[0].removeprefix("-r ")
        self.assertEqual((requirements.parent / include).resolve(), ROOT / "gui/requirements.txt")
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run([sys.executable, str(export.SCRIPTS / "export.py"), "--help"],
                                    cwd=temporary, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_frozen_gui_loads_the_private_helper_without_the_exporter(self):
        with patch.object(sys, "path", [str(ROOT / "gui")] + sys.path):
            application_module = import_module("app")
        application = Mock()
        helper = Mock()
        helper.smoke_gui.return_value = 0
        with patch.object(application_module, "create_application", return_value=application), \
             patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "argv", ["nuwriter-gui", "--export-smoke-test", "report.json"]), \
             patch.object(application_module, "import_module", return_value=helper) as load:
            self.assertEqual(application_module.main(), 0)
        load.assert_called_once_with("export_smoke")
        helper.smoke_gui.assert_called_once_with(application, application_module.MainWindow, "report.json")

    def test_readmes_do_not_document_export_workflow(self):
        readmes = list(ROOT.glob("README*.md"))
        for name in (".github", "gui", "licenses", "driver", "sample"):
            readmes.extend((ROOT / name).rglob("README*.md"))
        pattern = (r"(?i)Actions\s*>\s*Export|export\.py|requirements-export|test_export|"
                   r"export_smoke|Export workflow|\.github/scripts/")
        for path in readmes:
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                self.assertNotRegex(path.read_text(encoding="utf-8"), pattern)
        self.assertTrue((export.SCRIPTS / "BUILDING.md").is_file())
        self.assertFalse((export.SCRIPTS / "README.md").exists())


if __name__ == "__main__":
    unittest.main()