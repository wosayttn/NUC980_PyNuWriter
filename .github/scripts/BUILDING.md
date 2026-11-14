# Internal Export Tooling

These scripts are for CI and maintainers, not normal NuWriter end-user
operations. The export workflow invokes them from the repository root.

- `export.py`: native CLI/GUI builds, license/source collection, checksums and
  verification of extracted archives.
- `export_smoke.py`: private hardware-free GUI verification helper. Only this
  helper, not the exporter, is embedded in the GUI executable.
- `hooks/`: local PyInstaller hooks for USB safety, Qt exclusions and replaceable
  pyte source.
- `requirements-export.txt`: version-pinned build dependencies.
- `test_nuwriter.py`: backend and protocol regression tests.
- `test_gui.py`: GUI command, layout and offline integration tests.
- `test_export.py`: export regression tests.

## Build And Test

Use an activated Python 3.14 environment on the target OS. Run from the repository
root; resource paths are resolved from the script location, not the current
working directory.

```bash
python -m pip install -r .github/scripts/requirements-export.txt
```

```bash
python -m unittest discover -s .github/scripts -p test_nuwriter.py -v
```

```bash
python -m unittest discover -s .github/scripts -p test_gui.py -v
```

```bash
python -m unittest discover -s .github/scripts -p test_export.py -v
```

Run GUI tests with `QT_QPA_PLATFORM=offscreen` in headless environments. Tests
use simulated devices/processes and real sample-image offline checks, not
connected boards. Commit sample fixtures with the tests. Offline checks do
not write pack outputs. Windows batch integration tests require the sibling
`numaker-iot-nuc980g2` directory and are skipped if it is absent. Native desktop
rendering and real-board operations still need platform-specific manual testing.

```bash
python .github/scripts/export.py
```

Archives and SHA-256 checksums are written to `dist/artifacts`. Full export needs
the sample files for offline input validation. It does not scan/open USB or serial
devices, reset boards, program/erase flash, or publish GitHub Releases.
Linux/macOS require their system Qt and libusb dependencies; use the workflow
runner setup. Build each platform natively; cross-compilation is not supported.

To check an existing build:

```bash
python .github/scripts/export.py --smoke-only
```

To rebuild the applications from the bundled corresponding application source
without requiring the large sample images:

```bash
python .github/scripts/export.py --build-only
```

Source snapshots preserve this `.github/scripts` layout and contain a generated,
version-pinned requirements file. Keep the license/source archives with any
redistributed application. See the repository's `licenses/README.md` for the
library replacement and redistribution rights.

## Rebuild With Modified Libraries

1. Copy `sources/application/` to a writable working directory. Install the
   Python version/architecture shown in the distribution's component inventory.
2. Create and activate a virtual environment. In that working directory, run
   `python -m pip install -r .github/scripts/requirements-export.txt`.
3. Extract the desired library's source archive from `sources/`. Make the
   intended changes and build/install that library into the environment.
   For pyte, run `python -m pip install /path/to/modified-pyte`.
4. Qt's source archive includes CMake configuration and platform build
   instructions. Build shared libraries, not static libraries. Build matching
   PySide6/Shiboken bindings using the included Qt for Python source and its
   build scripts when their interfaces or Python bindings are changed.
   Preserve the original license texts and mark your own modifications.
5. Run `python .github/scripts/export.py --build-only`.
   This rebuilds both CLI and GUI without requiring the large sample images.
   Run the rebuilt CLI with `--help` and start the rebuilt GUI to test it.
   The export script includes a hardware-free GUI smoke-test mode; do not
   initialize, program or erase a board merely to test library replacement.

Standard Python, CMake, compiler and platform SDK installations may be required.
Library builds must remain interface-compatible with the application. The
rebuild process may access the listed upstream package/source repositories;
the corresponding library sources themselves are already included locally.
Redistributors of modified libraries must update source archives, manifests
and modification notices rather than claim the unmodified upstream archives
correspond to their changes.

## Qt Source Review

`QT_SOURCE_MODULES` maps actual native library names to corresponding Qt source
archives. It includes the reviewed Qt 6.12 Qt Base EGLFS/KMS/GBM, XCB, DBus and
Wayland Client support libraries used by the Linux platform plugins. Qt 6.12
moved the Wayland Client implementation into `qtbase`; its source mapping is
not the old `qtwayland` location.

The EGLFS/GBM implementations are under
`qtbase/src/plugins/platforms/eglfs/deviceintegration/`; WL Shell is under
`qtbase/src/plugins/platforms/wayland/plugins/shellintegration/wl-shell/`.
These implementations include the LGPLv3 license option. Their complete source
is already supplied by the Qt Base archive, without duplicate per-library
source downloads. Regression tests include the Linux native library names.

Unknown modules still fail export and require an actual source/license review.
Qt Virtual Keyboard and its plugins remain excluded. Do not bypass these checks
by accepting arbitrary Qt library names or suppressing the exception.