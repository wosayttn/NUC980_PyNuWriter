"""Build and verify native standalone CLI/GUI download archives."""

import argparse
import ast
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from importlib import metadata
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parents[1]
PACKAGES = ("pyusb", "pyfdt", "pyserial")
GUI_PACKAGES = ("PySide6", "PySide6_Essentials", "PySide6_Addons", "shiboken6", "pyte", "psutil", "wcwidth")
PACKAGE_LICENSES = {"pyusb": "BSD-3-Clause", "pyfdt": "Apache-2.0", "pyserial": "BSD-3-Clause",
                    "pyte": "LGPL-3.0-only", "psutil": "BSD-3-Clause", "wcwidth": "MIT"}
QT_SOURCE_MODULES = {"Core": "qtbase", "Gui": "qtbase", "Widgets": "qtbase", "Network": "qtbase",
                     "DBus": "qtbase", "EglFSDeviceIntegration": "qtbase", "EglFsKmsSupport": "qtbase",
                     "EglFsKmsGbmSupport": "qtbase", "WlShellIntegration": "qtbase",
                     "KmsSupport": "qtbase", "XcbQpa": "qtbase", "OpenGLWidgets": "qtbase",
                     "WaylandClient": "qtbase", "WaylandGlobal": "qtbase",
                     "OpenGL": "qtbase", "Svg": "qtsvg", "Qml": "qtdeclarative",
                     "QmlMeta": "qtdeclarative", "QmlModels": "qtdeclarative",
                     "QmlWorkerScript": "qtdeclarative", "Quick": "qtdeclarative"}


def executable(directory, name):
    return directory / (name + (".exe" if sys.platform == "win32" else ""))


def gui_directory(directory):
    return directory / "nuwriter-gui.app" / "Contents" / "MacOS" if sys.platform == "darwin" else directory


def verify_qt_exclusions(directory):
    unexpected = [path.relative_to(directory).as_posix() for path in directory.rglob("*")
                  if "virtualkeyboard" in path.name.casefold()]
    if unexpected:
        raise RuntimeError("Excluded Qt Virtual Keyboard files found: " + ", ".join(unexpected))


def qt_source_modules(directory):
    modules = set()
    pattern = re.compile(r"^(?:lib)?Qt6?([A-Za-z0-9]+?)(?:\.dll|\.so(?:\.\d+)*|(?:\.\d+)*\.dylib|\.framework)$")
    for path in directory.rglob("*"):
        match = pattern.fullmatch(path.name)
        if match:
            module = match.group(1)
            if module not in QT_SOURCE_MODULES:
                raise RuntimeError(f"Qt module needs a license/source review before redistribution: {module}")
            modules.add(QT_SOURCE_MODULES[module])
    return sorted(modules)


def download_source(url, directory, expected=None):
    filename = url.rsplit("/", 1)[-1]
    if not filename or filename in (".", "..") or "\\" in filename:
        raise ValueError("Invalid source archive URL")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    if not path.is_file():
        with urllib.request.urlopen(url, timeout=120) as response, \
             tempfile.NamedTemporaryFile(dir=directory, delete=False) as output:
            temporary = Path(output.name)
            try:
                shutil.copyfileobj(response, output)
            except BaseException:
                output.close()
                temporary.unlink(missing_ok=True)
                raise
        temporary.replace(path)
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if expected is not None and digest != expected.lower():
        path.unlink()
        raise RuntimeError(f"Source archive SHA-256 mismatch: {filename}")
    return {"file": filename, "url": url, "sha256": digest}


def collect_sources(directory, packages):
    qt_modules = qt_source_modules(directory) if "PySide6" in packages else []
    cache = ROOT / "build" / "sources"
    destination = directory / "sources"
    destination.mkdir(parents=True, exist_ok=True)
    records = []
    for name in packages:
        if name.startswith("PySide6") or name == "shiboken6":
            continue
        version = metadata.version(name)
        with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{version}/json", timeout=60) as response:
            release = json.load(response)
        archives = [entry for entry in release["urls"] if entry["packagetype"] == "sdist"]
        if not archives:
            raise RuntimeError(f"Corresponding source release is missing: {name} {version}")
        entry = archives[0]
        record = download_source(entry["url"], cache, entry["digests"]["sha256"])
        record.update(component=name, version=version)
        records.append(record)
    if "PySide6" in packages:
        from PySide6.QtCore import QLibraryInfo, qVersion
        qt_version = qVersion()
        version = metadata.version("PySide6")
        url = (f"https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-{version}-src/"
               f"pyside-setup-everywhere-src-{version}.tar.xz")
        record = download_source(url, cache)
        record.update(component="Qt for Python / Shiboken", version=version)
        records.append(record)
        for module in qt_modules:
            url = (f"https://download.qt.io/official_releases/qt/{'.'.join(qt_version.split('.')[:2])}/"
                   f"{qt_version}/submodules/{module}-everywhere-src-{qt_version}.tar.xz")
            with urllib.request.urlopen(url + ".sha256", timeout=60) as response:
                expected = response.read().decode("ascii").split()[0]
            record = download_source(url, cache, expected)
            record.update(component=module, version=qt_version, build=QLibraryInfo.build())
            records.append(record)
    for record in records:
        shutil.copy2(cache / record["file"], destination / record["file"])
    (destination / "manifest.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    return records


def copy_application_source(directory, packages):
    destination = directory / "sources" / "application"
    destination.mkdir(parents=True, exist_ok=True)
    for path in ROOT.glob("*.py"):
        shutil.copy2(path, destination / path.name)
    for name in ("LICENSE", "README.md", "README.zh-TW.md", "README.zh-CN.md", "requirements.txt"):
        shutil.copy2(ROOT / name, destination / name)
    for name in ("gui", "licenses", "sys_cfg", "xusb", "driver"):
        shutil.copytree(ROOT / name, destination / name,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "screenshot"), dirs_exist_ok=True)
    scripts = destination / ".github" / "scripts"
    shutil.copytree(SCRIPTS, scripts, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"), dirs_exist_ok=True)
    requirements = [f"{name}=={metadata.version(name)}" for name in
                    ("pyinstaller", "pyinstaller-hooks-contrib") + GUI_PACKAGES + PACKAGES]
    (scripts / "requirements-export.txt").write_text("\n".join(requirements) + "\n", encoding="ascii")


def verify_licenses(directory, gui=False):
    required = ["licenses/GPL-3.0.txt", "licenses/LGPL-3.0.txt", "licenses/README.md",
                "licenses/components.json", "licenses/pyserial/LICENSE.txt",
                "licenses/pyfdt/APACHE-2.0.txt", "licenses/pyfdt/UPSTREAM-NOTICE.txt",
                "sources/manifest.json", "sources/application/.github/scripts/export.py"]
    for name in required:
        if not (directory / name).is_file():
            raise RuntimeError(f"Redistribution document/source is missing: {name}")
    records = json.loads((directory / "sources" / "manifest.json").read_text(encoding="utf-8"))
    names = {record["component"] for record in records}
    expected = set(PACKAGES) | ({"pyte", "Qt for Python / Shiboken"} if gui else set())
    if not expected.issubset(names):
        raise RuntimeError("Redistribution source manifest is incomplete")
    for record in records:
        with (directory / "sources" / record["file"]).open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != record["sha256"]:
                raise RuntimeError(f"Redistribution source is corrupt: {record['file']}")
    if gui and not set(qt_source_modules(directory)).issubset(names):
        raise RuntimeError("Bundled Qt libraries do not have corresponding sources")
    if gui and not any(directory.rglob("pyte/__init__.py")):
        raise RuntimeError("The LGPL pyte library must be replaceable external Python source")


def copy_licenses(directory, packages):
    shutil.copy2(ROOT / "LICENSE", directory / "LICENSE")
    for path in (ROOT / "licenses").iterdir():
        if path.is_file():
            target = directory / "licenses" / path.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
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
    if metadata.version("pyserial") != "3.5":
        raise RuntimeError("Review the bundled pyserial license before changing its supported version")
    shutil.copy2(ROOT / "licenses" / "pyserial-LICENSE.txt", directory / "licenses" / "pyserial" / "LICENSE.txt")
    distribution = metadata.distribution("pyfdt")
    entry = next(entry for entry in distribution.files or () if entry.as_posix().endswith("pyfdt/pyfdt.py"))
    notice = ast.get_docstring(ast.parse(Path(distribution.locate_file(entry)).read_text(encoding="utf-8")))
    if not notice or "Apache License" not in notice:
        raise RuntimeError("The pyfdt upstream copyright/license notice could not be verified")
    (directory / "licenses" / "pyfdt" / "UPSTREAM-NOTICE.txt").write_text(notice + "\n", encoding="utf-8")
    shutil.copy2(ROOT / "LICENSE", directory / "licenses" / "pyfdt" / "APACHE-2.0.txt")
    components = [{"name": "Python", "version": platform.python_version(), "license": "PSF-2.0",
                   "architecture": platform.machine()}]
    components += [{"name": name, "version": metadata.version(name),
                   "license": PACKAGE_LICENSES.get(name, "LGPL-3.0-only"), "modified": False}
                  for name in packages]
    (directory / "licenses" / "components.json").write_text(json.dumps(components, indent=2) + "\n", encoding="utf-8")
    collect_sources(directory, packages)
    copy_application_source(directory, packages)
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
        "Project code: LICENSE. Third-party components: licenses/ and driver license/source files.\n"
        "This application uses Qt / PySide6 and pyte under LGPLv3 when the GUI is included.\n"
        "Your LGPL modification and reverse-engineering rights are not restricted.\n"
        "See licenses/README.md for notices, corresponding sources, and rebuilding/replacement steps.\n"
        "Qt Virtual Keyboard and its plugins are excluded from this distribution.\n",
        encoding="ascii",
    )


def freeze(output, name, entry, gui=False):
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--noupx",
               "--name", name, "--distpath", str(output), "--workpath", str(ROOT / "build" / "export"),
               "--specpath", str(ROOT / "build" / "specs"), "--paths", str(ROOT),
               "--additional-hooks-dir", str(SCRIPTS / "hooks")]
    for resource in ("sys_cfg", "xusb"):
        command += ["--add-data", f"{ROOT / resource}:{resource}"]
    if gui:
        command += ["--windowed", "--paths", str(ROOT / "gui"), "--paths", str(SCRIPTS),
                "--hidden-import", "export_smoke",
                    "--exclude-module", "PySide6.QtVirtualKeyboard",
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
    verify_qt_exclusions(gui)
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
    if gui:
        verify_qt_exclusions(directory)
    verify_licenses(directory, gui=gui)
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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--smoke-only", action="store_true", help="Check existing builds without rebuilding or archiving")
    mode.add_argument("--build-only", action="store_true", help="Build applications without sample-based archive checks")
    arguments = parser.parse_args(argv)
    output = ROOT / "dist"
    if arguments.smoke_only:
        smoke(output / "nuwriter")
        smoke(output / "nuwriter-gui", gui=True)
    else:
        build(output)
        if not arguments.build_only:
            archive(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())