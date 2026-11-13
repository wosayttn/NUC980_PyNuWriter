"""Build and verify native standalone CLI/GUI download archives."""

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from importlib import metadata
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PACKAGES = ("pyusb", "pyfdt", "pyserial")
GUI_PACKAGES = ("PySide6", "PySide6_Essentials", "PySide6_Addons", "shiboken6", "pyte", "psutil", "wcwidth")


def executable(directory, name):
    return directory / (name + (".exe" if sys.platform == "win32" else ""))


def gui_directory(directory):
    return directory / "nuwriter-gui.app" / "Contents" / "MacOS" if sys.platform == "darwin" else directory


def copy_licenses(directory, packages):
    shutil.copy2(ROOT / "LICENSE", directory / "LICENSE")
    python_directory = directory / "licenses" / "Python"
    python_directory.mkdir(parents=True, exist_ok=True)
    candidates = (Path(sys.base_prefix) / "LICENSE.txt", Path(os.__file__).resolve().with_name("LICENSE.txt"))
    python_license = next((path for path in candidates if path.is_file()), None)
    if python_license is None:
        raise FileNotFoundError("The build interpreter's Python LICENSE.txt is required for redistribution")
    shutil.copy2(python_license, python_directory / "LICENSE.txt")
    for name in ("pyinstaller", "pyinstaller-hooks-contrib") + packages:
        distribution = metadata.distribution(name)
        destination = directory / "licenses" / name
        destination.mkdir(parents=True, exist_ok=True)
        description = distribution.read_text("METADATA") or distribution.read_text("PKG-INFO") or f"{name} {distribution.version}\n"
        (destination / "METADATA.txt").write_text(description, encoding="utf-8")
        for entry in distribution.files or ():
            if not any(token in entry.name.lower() for token in ("license", "copying", "copyright", "notice", "authors")):
                continue
            source = Path(distribution.locate_file(entry))
            if source.is_file():
                target = destination.joinpath(*(part for part in entry.parts if part not in ("..", ".")))
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    (directory / "README.txt").write_text(
        "NUC980 PyNuWriter standalone export\n\n"
        "Extract the entire archive and keep all files together. Python is bundled.\n"
        "CLI: nuwriter --help (Windows: nuwriter.exe --help).\n"
        "GUI: open nuwriter-gui.exe, nuwriter-gui, or nuwriter-gui.app.\n"
        "Windows: install the NUC980 WinUSB driver; CLI driver files are under _internal/driver\n"
        "(GUI package: backend/nuwriter/_internal/driver).\n"
        "Linux/macOS: install native libusb-1.0; Linux also needs Qt system libraries and USB permissions.\n"
        "Builds are not developer-signed or notarized. See the repository README for platform setup.\n"
        "DDR/XUSB resources are included; large sample images are not.\n"
        "Initialization can reset the board through the optional CH341 adapter.\n"
        "Project code: LICENSE. Third-party components: licenses/ and driver license/source files.\n",
        encoding="ascii",
    )


def freeze(output, name, entry, gui=False):
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--noupx",
               "--name", name, "--distpath", str(output), "--workpath", str(ROOT / "build" / "export"),
               "--specpath", str(ROOT / "build" / "specs"), "--paths", str(ROOT),
               "--additional-hooks-dir", str(ROOT / "export-hooks")]
    for resource in ("sys_cfg", "xusb"):
        command += ["--add-data", f"{ROOT / resource}:{resource}"]
    if gui:
        command += ["--windowed", "--paths", str(ROOT / "gui"), "--hidden-import", "export",
                    "--add-data", f"{ROOT / 'gui' / 'logo.png'}:."]
        packages = GUI_PACKAGES + PACKAGES
    else:
        command += ["--console", "--collect-submodules", "usb", "--hidden-import", "pyfdt.pyfdt",
                    "--hidden-import", "serial.tools.list_ports", "--hidden-import", "ch341_reset_uart",
                    "--add-data", f"{ROOT / 'pre-attach-hook.py'}:."]
        if sys.platform == "win32":
            command += ["--add-data", f"{ROOT / 'driver'}:driver"]
        packages = PACKAGES
    for package in packages:
        command += ["--copy-metadata", package]
    subprocess.run(command + [str(ROOT / entry)], cwd=ROOT, check=True)


def build(output):
    freeze(output, "nuwriter", "nuwriter.py")
    freeze(output, "nuwriter-gui", "gui/app.py", gui=True)
    cli = output / "nuwriter"
    gui = output / "nuwriter-gui"
    if sys.platform == "darwin":
        if gui.is_dir():
            shutil.rmtree(gui)
        gui.mkdir()
        shutil.move(str(output / "nuwriter-gui.app"), str(gui / "nuwriter-gui.app"))
    copy_licenses(cli, PACKAGES)
    copy_licenses(gui, GUI_PACKAGES + PACKAGES)
    shutil.copytree(cli, gui / "backend" / "nuwriter", symlinks=True, dirs_exist_ok=True)
    if sys.platform == "darwin":
        subprocess.run(["codesign", "--verify", "--deep", "--strict", str(gui / "nuwriter-gui.app")], check=True)


def run_checked(command, directory, environment):
    result = subprocess.run([str(value) for value in command], cwd=directory, env=environment,
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    if result.returncode:
        raise RuntimeError(f"Export check failed ({result.returncode}): {command}\n{result.stdout}\n{result.stderr}")
    print(result.stdout.strip(), flush=True)
    return result


def smoke(directory, gui=False):
    environment = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    for name in ("PYTHONHOME", "PYTHONPATH", "NUWRITER_TRACE_CONTROL"):
        environment.pop(name, None)
    if sys.platform == "win32":
        windows = Path(os.environ.get("SYSTEMROOT", "C:/Windows"))
        environment["PATH"] = os.pathsep.join((str(windows / "System32"), str(windows)))
    else:
        environment["PATH"] = "/usr/bin:/bin"
    with tempfile.TemporaryDirectory(prefix="nuwriter offline ! ") as temporary:
        working = Path(temporary).resolve()
        if gui:
            report = working / "gui.json"
            run_checked([executable(gui_directory(directory), "nuwriter-gui"), "--export-smoke-test", report], working, environment)
            data = json.loads(report.read_text(encoding="utf-8"))
            if data.get("status") != "passed":
                raise RuntimeError(f"GUI export smoke test failed: {data}")
            print(data, flush=True)
            return
        cli = executable(directory, "nuwriter")
        for arguments in (["--help"], ["--version"], ["--export-smoke-test"],
                          ["--reset-ch341", "--help"], ["-a", "NUC980DK71YC.ini", "--check"],
                          ["-w", "ddr", "0x8000", str(ROOT / "sample" / "zImage"), "-o", "execute",
                           "--dtb", str(ROOT / "sample" / "nuc980-iot-128m-bmc.dtb"), "--dtb-addr", "0x1400000",
                           "--bootargs", "console=ttyS0,115200n8", "--check"]):
            run_checked([cli] + arguments, working, environment)


def smoke_gui(application, window_class, report):
    from unittest.mock import patch
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QPixmap
    import backend
    import console

    def forbidden(*arguments, **keywords):
        raise AssertionError("Hardware access is forbidden during export smoke tests")

    with tempfile.TemporaryDirectory(prefix="nuwriter GUI ! ") as temporary, \
         patch.object(console, "available_ports", return_value=[]), \
         patch.object(console.serial, "Serial", side_effect=forbidden), \
         patch.object(window_class, "refresh_devices", side_effect=forbidden):
        window = window_class(settings_path=Path(temporary) / "settings.json")
        window.show()
        application.processEvents()
        if window.ddr.count() == 0 or QPixmap(str(Path(sys._MEIPASS) / "logo.png")).isNull():
            raise RuntimeError("Bundled DDR settings or GUI logo are missing")
        window.open_log()
        window.open_console()

        def finish(success, message):
            Path(report).write_text(json.dumps({"status": "passed" if success else "failed", "message": message,
                                               "ddr_settings": window.ddr.count(), "backend": window.runner.current.invocation()}),
                                    encoding="utf-8")
            window.close()
            application.exit(0 if success else 1)

        def expired():
            window.runner.process.kill()
            application.exit(1)

        window.runner.finished.connect(finish)
        QTimer.singleShot(20000, expired)
        QTimer.singleShot(0, lambda: window.runner.start(
            backend.Command(["-a", "NUC980DK71YC.ini", "--check"], cwd=Path(temporary)), preflight=False))
        return application.exec()


def archive(output):
    system = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    machine = platform.machine().lower()
    architecture = {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64"}.get(machine, machine)
    artifacts = output / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    for kind, name in (("cli", "nuwriter"), ("gui", "nuwriter-gui")):
        filename = artifacts / f"nuwriter-{kind}-{system}-{architecture}"
        package = Path(shutil.make_archive(str(filename), "zip" if sys.platform == "win32" else "gztar",
                                           root_dir=output, base_dir=name))
        with package.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        package.with_name(package.name + ".sha256").write_text(f"{digest}  {package.name}\n", encoding="ascii")
        with tempfile.TemporaryDirectory(prefix="nuwriter extracted ! ") as temporary:
            shutil.unpack_archive(package, temporary)
            smoke(Path(temporary).resolve() / name, gui=kind == "gui")
        print(f"Verified artifact: {package}", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke-only", action="store_true", help="Check existing builds without rebuilding or archiving")
    arguments = parser.parse_args(argv)
    output = ROOT / "dist"
    if arguments.smoke_only:
        smoke(output / "nuwriter")
        smoke(output / "nuwriter-gui", gui=True)
    else:
        build(output)
        archive(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())