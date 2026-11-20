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
    def test_release_ref_pins_existing_tag_and_retains_artifact_only_mode(self):
        revision = "a" * 40
        with patch.object(export.subprocess, "run") as run, \
             patch.object(export.subprocess, "check_output", return_value=revision + "\n") as resolve:
            self.assertEqual(export.resolve_release_ref("v1.0.0", "refs/heads/main", "b" * 40),
                             {"tag": "v1.0.0", "revision": revision})
        run.assert_called_once_with(["git", "check-ref-format", "refs/tags/v1.0.0"], cwd=ROOT, check=True)
        self.assertIn("refs/tags/v1.0.0^{commit}", resolve.call_args.args[0])
        with patch.object(export.subprocess, "run") as run:
            self.assertEqual(export.resolve_release_ref("", "refs/heads/main", revision),
                             {"tag": "", "revision": revision})
        run.assert_not_called()
        with self.assertRaises(ValueError):
            export.resolve_release_ref("main", "", revision)

    def test_release_ref_uses_push_tag_and_rejects_missing_tag(self):
        with patch.object(export.subprocess, "run"), \
             patch.object(export.subprocess, "check_output", return_value="a" * 40):
            self.assertEqual(export.resolve_release_ref("", "refs/tags/v2.0.0", "b" * 40)["tag"], "v2.0.0")
        with patch.object(export.subprocess, "run"), \
             patch.object(export.subprocess, "check_output", side_effect=subprocess.CalledProcessError(1, "git")):
            with self.assertRaises(subprocess.CalledProcessError):
                export.resolve_release_ref("v9.0.0", "", "a" * 40)

    def test_release_assets_require_all_platforms_and_matching_checksums(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for platform in ("windows-x64", "linux-x64", "macos-x64", "macos-arm64"):
                for kind in ("cli", "gui"):
                    extension = ".zip" if platform == "windows-x64" else ".tar.gz"
                    path = directory / f"nuwriter-{kind}-{platform}{extension}"
                    path.write_bytes(b"verified package")
                    digest = export.hashlib.sha256(path.read_bytes()).hexdigest()
                    path.with_name(path.name + ".sha256").write_text(f"{digest}  {path.name}\n", encoding="ascii")
            export.verify_release_assets(directory)
            missing = directory / "nuwriter-gui-macos-arm64.tar.gz"
            missing.unlink()
            with self.assertRaisesRegex(RuntimeError, "Incomplete release assets"):
                export.verify_release_assets(directory)
            missing.write_bytes(b"corrupt package")
            with self.assertRaisesRegex(RuntimeError, "SHA-256 mismatch"):
                export.verify_release_assets(directory)

    def test_release_modes_emit_outputs_and_reject_a_changed_tag(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "outputs"
            with patch.dict(export.os.environ, {"GITHUB_OUTPUT": str(output)}, clear=True), \
                 patch.object(export, "resolve_release_ref", return_value={"tag": "v1.0.0", "revision": "a" * 40}), \
                 patch.object(export, "build") as build:
                self.assertEqual(export.main(["--resolve-release-ref"]), 0)
            self.assertEqual(output.read_text(), "tag=v1.0.0\nrevision=" + "a" * 40 + "\n")
            build.assert_not_called()
            with patch.dict(export.os.environ, {}, clear=True), \
                 patch.object(export, "verify_release_assets") as verify, \
                 patch.object(export, "resolve_release_ref") as resolve:
                self.assertEqual(export.main(["--verify-release-assets", temporary]), 0)
            verify.assert_called_once_with(Path(temporary))
            resolve.assert_not_called()
            with patch.dict(export.os.environ, {"RELEASE_TAG": "v1.0.0", "EXPECTED_REVISION": "b" * 40}, clear=True), \
                 patch.object(export, "verify_release_assets"), \
                 patch.object(export, "resolve_release_ref", return_value={"tag": "v1.0.0", "revision": "a" * 40}):
                with self.assertRaisesRegex(RuntimeError, "tag changed"):
                    export.main(["--verify-release-assets", temporary])

    def test_macos_export_preserves_the_bundle_with_an_embedded_cli(self):
        with tempfile.TemporaryDirectory(prefix="nuwriter macOS ! ") as temporary:
            output = Path(temporary).resolve()

            def freeze(directory, name, entry, gui=False):
                if gui:
                    (directory / "nuwriter-gui").mkdir()
                    (directory / "nuwriter-gui" / "unbundled-executable").write_bytes(b"COLLECT output")
                    bundle = directory / "nuwriter-gui.app"
                    (bundle / "Contents" / "MacOS").mkdir(parents=True)
                    (bundle / "Contents" / "MacOS" / "nuwriter-gui").write_bytes(b"GUI executable")
                    (bundle / "Contents" / "MacOS" / "nuwriter").write_bytes(b"Embedded CLI executable")
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
                             {"Contents/Info.plist", "Contents/MacOS/nuwriter-gui", "Contents/MacOS/nuwriter"})
            self.assertEqual((bundle / "Contents/MacOS/nuwriter").read_bytes(), b"Embedded CLI executable")
            self.assertFalse((gui / "backend").exists())
            self.assertTrue((gui / "licenses").is_dir())
            self.assertFalse((gui / "unbundled-executable").exists())
            self.assertEqual((bundle / "Contents" / "Info.plist").read_bytes(), b"Bundle metadata")
            run.assert_called_once_with(["codesign", "--verify", "--deep", "--strict", str(bundle)], check=True)

    def test_macos_archives_keep_the_backend_inside_the_extracted_app(self):
        with tempfile.TemporaryDirectory(prefix="nuwriter macOS archives ! ") as temporary:
            output = Path(temporary).resolve()
            cli = output / "nuwriter"
            cli.mkdir()
            (cli / "nuwriter").write_bytes(b"CLI executable")
            gui = output / "nuwriter-gui"
            bundle_executable = gui / "nuwriter-gui.app" / "Contents" / "MacOS" / "nuwriter-gui"
            bundle_executable.parent.mkdir(parents=True)
            bundle_executable.write_bytes(b"GUI executable")
            bundle_executable.with_name("nuwriter").write_bytes(b"Embedded CLI executable")
            checked = []

            def smoke(directory, gui=False):
                if gui:
                    self.assertEqual((export.gui_directory(directory) / "nuwriter-gui").read_bytes(), b"GUI executable")
                    self.assertEqual((export.gui_directory(directory) / "nuwriter").read_bytes(), b"Embedded CLI executable")
                    self.assertFalse((directory / "backend").exists())
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

    def test_macos_spec_shares_dependencies_but_separates_gui_and_cli_entry_points(self):
        analysis = SimpleNamespace(pure=["shared modules"], binaries=["shared binaries"], datas=["shared data"],
                                   scripts=[("pyi_rth", "runtime.py", "PYSOURCE"),
                                            ("app", str(ROOT / "gui/app.py"), "PYSOURCE"),
                                            ("nuwriter", str(ROOT / "nuwriter.py"), "PYSOURCE")])
        analyze = Mock(return_value=analysis)
        python_archive = Mock(return_value="shared Python archive")
        gui_executable = SimpleNamespace(name="nuwriter-gui", dependencies=[])
        cli_executable = SimpleNamespace(name="nuwriter", dependencies=[])
        executables = Mock(side_effect=[gui_executable, cli_executable])
        collect = Mock(return_value="shared collection")
        bundle = Mock()
        modules = {name: SimpleNamespace() for name in ("PyInstaller", "PyInstaller.utils")}
        modules["PyInstaller.utils.hooks"] = SimpleNamespace(
            copy_metadata=lambda name: [(name, "metadata")], collect_submodules=lambda name: ["usb.core"])
        globals_ = {"SPECPATH": str(export.SCRIPTS), "Analysis": analyze, "PYZ": python_archive,
                    "EXE": executables, "COLLECT": collect, "BUNDLE": bundle}
        with patch.dict(sys.modules, modules):
            runpy.run_path(str(export.SCRIPTS / "macos-gui.spec"), init_globals=globals_)
        self.assertEqual(analyze.call_args.args[0], [str(ROOT / "gui/app.py"), str(ROOT / "nuwriter.py")])
        self.assertIn(str(export.SCRIPTS / "hooks"), analyze.call_args.kwargs["hookspath"])
        self.assertIn("PySide6.QtVirtualKeyboard", analyze.call_args.kwargs["excludes"])
        self.assertIn((str(ROOT / "pre-attach-hook.py"), "."), analyze.call_args.kwargs["datas"])
        metadata_names = {source for source, target in analyze.call_args.kwargs["datas"] if target == "metadata"}
        self.assertEqual(metadata_names, set(export.GUI_PACKAGES + export.PACKAGES))
        python_archive.assert_called_once_with(analysis.pure)
        gui, cli = executables.call_args_list
        self.assertEqual(gui.kwargs["name"], "nuwriter-gui")
        self.assertFalse(gui.kwargs["console"])
        self.assertEqual([entry[0] for entry in gui.args[1]], ["pyi_rth", "app"])
        self.assertEqual(cli.kwargs["name"], "nuwriter")
        self.assertTrue(cli.kwargs["console"])
        self.assertEqual([entry[0] for entry in cli.args[1]], ["pyi_rth", "nuwriter"])
        collect.assert_called_once_with(gui_executable, cli_executable, analysis.binaries, analysis.datas,
                                        name="nuwriter-gui", strip=False, upx=False)
        bundle.assert_called_once_with(gui_executable, [("nuwriter", "nuwriter", "EXECUTABLE")],
                           analysis.binaries, analysis.datas, name="nuwriter-gui.app",
                                       bundle_identifier="com.nuvoton.nuwriter")

    def test_macos_smoke_checks_app_only_relocation_and_rejects_a_missing_cli(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(sys, "platform", "darwin"):
            directory = Path(temporary).resolve() / "nuwriter-gui"
            macos = export.gui_directory(directory)
            macos.mkdir(parents=True)
            (macos / "nuwriter-gui").write_bytes(b"GUI executable")
            cli = macos / "nuwriter"
            cli.write_bytes(b"CLI executable")
            checked = []

            def run_checked(command, working, environment):
                executable = Path(command[0])
                self.assertFalse((executable.parents[3] / "backend").exists())
                checked.append(executable)
                Path(command[-1]).write_text(json.dumps({"status": "passed", "backend":
                                                         [str(executable.with_name("nuwriter")), "--check"]}))

            with patch.object(export, "verify_licenses"), \
                 patch.object(export, "run_checked", side_effect=run_checked):
                export.smoke(directory, gui=True)
                self.assertEqual(len(checked), 2)
                self.assertEqual(checked[0], macos / "nuwriter-gui")
                self.assertIn("AppTranslocation", checked[1].parts)
                cli.unlink()
                with self.assertRaisesRegex(RuntimeError, "in-app CLI"):
                    export.smoke(directory, gui=True)

    def test_freezer_uses_local_usb_hook_and_platform_resources(self):
        for system in ("win32", "linux", "darwin"):
            for gui in (False, True):
                with self.subTest(system=system, gui=gui), \
                     patch.object(sys, "platform", system), \
                     patch.object(export.subprocess, "run") as run:
                    export.freeze(export.ROOT / "dist", "example", "gui/app.py" if gui else "nuwriter.py", gui=gui)
                command = run.call_args.args[0]
                if system == "darwin" and gui:
                    self.assertEqual(command[-1], str(export.SCRIPTS / "macos-gui.spec"))
                    self.assertEqual(run.call_args.kwargs, {"cwd": export.ROOT, "check": True})
                    continue
                self.assertIn(str(export.SCRIPTS / "hooks"), command)
                runtime_hook = str(export.SCRIPTS / "hooks" / "rthook_linux_gio.py")
                self.assertEqual(runtime_hook in command, system == "linux")
                if runtime_hook in command:
                    self.assertEqual(command[command.index(runtime_hook) - 1], "--runtime-hook")
                native_dll = f"{export.ROOT / 'driver' / 'libusb-1.0.dll'}:driver"
                self.assertEqual(native_dll in command, system == "win32" and not gui)
                if native_dll in command:
                    self.assertEqual(command[command.index(native_dll) - 1], "--add-binary")
                self.assertIn("--windowed" if gui else "--console", command)
                self.assertEqual("PySide6.QtVirtualKeyboard" in command, gui)
                self.assertEqual("export_smoke" in command, gui)
                self.assertNotIn("export", command)
                self.assertEqual(run.call_args.kwargs, {"cwd": export.ROOT, "check": True})

    def test_linux_runtime_hook_isolates_inherited_system_gio_modules(self):
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(sys, "platform", "linux"), \
             patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "_MEIPASS", temporary, create=True), \
             patch.dict(export.os.environ, {"GIO_MODULE_DIR": "/usr/lib/gio/modules",
                                           "GIO_EXTRA_MODULES": "/usr/lib/gvfs",
                                           "GIO_USE_VFS": "gvfs", "GSETTINGS_BACKEND": "dconf"}):
            runpy.run_path(str(export.SCRIPTS / "hooks/rthook_linux_gio.py"))
            self.assertEqual(export.os.environ["GIO_MODULE_DIR"], str(Path(temporary) / "nuwriter-gio-modules"))
            self.assertNotIn("GIO_EXTRA_MODULES", export.os.environ)
            self.assertEqual(export.os.environ["GIO_USE_VFS"], "local")
            self.assertEqual(export.os.environ["GSETTINGS_BACKEND"], "memory")

    def test_gio_runtime_hook_leaves_other_platforms_and_source_runs_unchanged(self):
        for system, frozen in (("win32", True), ("darwin", True), ("linux", False)):
            with self.subTest(system=system, frozen=frozen), \
                 patch.object(sys, "platform", system), \
                 patch.object(sys, "frozen", frozen, create=True), \
                 patch.dict(export.os.environ, {"GIO_MODULE_DIR": "original", "GIO_EXTRA_MODULES": "extra"}):
                original = dict(export.os.environ)
                runpy.run_path(str(export.SCRIPTS / "hooks/rthook_linux_gio.py"))
                self.assertEqual(dict(export.os.environ), original)

    def test_native_module_errors_fail_export_even_when_the_process_exits_successfully(self):
        for error in ("libdconfsettings.so: undefined symbol: g_assertion_message_cmpint",
                      "Failed to load module: /usr/lib/gio/modules/libgvfsdbus.so"):
            with self.subTest(error=error), patch.object(export.subprocess, "run", return_value=
                    SimpleNamespace(returncode=0, stdout="", stderr=error)):
                with self.assertRaisesRegex(RuntimeError, "Native library/module loading failed"):
                    export.run_checked(["nuwriter-gui", "--export-smoke-test"], ROOT, {})

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
            readme = (directory / "README.txt").read_text()
            self.assertIn("programming USB 0416:5963", readme)
            self.assertIn("WinUSB4NuVCOM.exe is for the board's USB-to-UART/VCOM interface, not programming USB.", readme)
            source = directory / "sources/application"
            self.assertTrue((source / ".github/licenses/GPL-3.0.txt").is_file())
            self.assertTrue((source / ".github/licenses/README.md").is_file())
            self.assertFalse((source / "licenses").exists())
            self.assertTrue((source / ".github/scripts/hooks/hook-PySide6.QtGui.py").is_file())
            self.assertTrue((source / ".github/scripts/hooks/rthook_linux_gio.py").is_file())
            self.assertTrue((source / ".github/scripts/BUILDING.md").is_file())
            self.assertTrue((source / ".github/scripts/macos-gui.spec").is_file())
            self.assertFalse((source / ".github/scripts/README.md").exists())
            self.assertTrue((source / ".github/scripts/test_nuwriter.py").is_file())
            self.assertTrue((source / ".github/scripts/test_gui.py").is_file())
            self.assertFalse((source / "test_nuwriter.py").exists())
            self.assertFalse((source / "gui/test_gui.py").exists())
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
             patch.object(nuwriter, "validate_libusb_library") as validate, \
             patch.object(nuwriter, "discover_devices") as discover, \
             patch.object(nuwriter, "run_pre_attach_hook") as hook:
            self.assertEqual(nuwriter.main(["--export-smoke-test"]), 0)
        self.assertEqual([call.args[0] for call in load.call_args_list],
                         ["usb.core", "usb.util", "usb.backend.libusb1", "pyfdt.pyfdt",
                          "serial.tools.list_ports"])
        discover.assert_not_called()
        hook.assert_not_called()
        validate.assert_called_once_with()

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

    def test_maintenance_tests_are_kept_in_the_internal_scripts_directory(self):
        for name in ("test_nuwriter.py", "test_gui.py", "test_export.py"):
            with self.subTest(name=name):
                self.assertTrue((export.SCRIPTS / name).is_file())
        self.assertFalse((ROOT / "test_nuwriter.py").exists())
        self.assertFalse((ROOT / "gui/test_gui.py").exists())

    def test_license_inputs_are_internal_packaging_resources(self):
        self.assertEqual(export.LICENSE_INPUTS, ROOT / ".github/licenses")
        self.assertFalse((ROOT / "licenses").exists())
        for name in ("GPL-3.0.txt", "LGPL-3.0.txt", "pyserial-LICENSE.txt", "README.md"):
            with self.subTest(name=name):
                self.assertTrue((export.LICENSE_INPUTS / name).is_file())

    def test_nuc970_and_nuc980_resources_are_packaged_for_export(self):
        with patch.object(sys, "platform", "win32"), patch.object(export.subprocess, "run") as run:
            export.freeze(export.ROOT / "dist", "nuwriter", "nuwriter.py", gui=False)
        command = run.call_args.args[0]
        self.assertIn(f"{export.ROOT / 'key_cfg'}:key_cfg", command)
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(export.metadata, "version", side_effect=lambda name: f"0.0-{name}"):
            directory = Path(temporary)
            export.copy_application_source(directory, export.PACKAGES)
            source = directory / "sources" / "application"
            self.assertTrue((source / "nuwriter.py").is_file())
            self.assertTrue((source / "key_cfg" / "nuc970" / "key.dat").is_file())
            self.assertTrue((source / "sys_cfg" / "nuc980" / "NUC980DK71YC.ini").is_file())
            self.assertTrue((source / "xusb" / "nuc980" / "xusb128.bin").is_file())
            self.assertTrue((source / "sys_cfg" / "nuc970" / "NUC972DF62Y.ini").is_file())
            self.assertTrue((source / "xusb" / "nuc970" / "xusb32.bin").is_file())


if __name__ == "__main__":
    unittest.main()