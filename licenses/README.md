# Third-Party Notices And Corresponding Source

The application's own Python code is licensed under Apache-2.0. Third-party
components retain their original licenses. This notice does not relicense them.
The CLI-only package does not use Qt or pyte; GUI-specific notices below apply
only to the GUI package.

## Components

- Qt, PySide6 and Shiboken: the included libraries use the LGPLv3 option.
  Copyright The Qt Company Ltd. and their respective contributors.
- pyte: LGPLv3. Copyright its authors and contributors; retain the notices in
  its corresponding source archive.
- PyUSB, pyserial and psutil: BSD-3-Clause. Their copyright notices, conditions
  and disclaimers are supplied in their respective license directories.
- pyfdt: Apache-2.0. Its original author notice and full license are supplied
  under `pyfdt/`.
- wcwidth: MIT and the additional permission notice in its original license.
- Python: the Python Software Foundation license and incorporated third-party
  licenses; see `Python/LICENSE.txt`.
- PyInstaller: GPL with its bootloader/commercial-bundling exception. This
  exception does not override the licenses of the application's dependencies.
- Windows libusb: LGPL-2.1-or-later. Its license, authors and unmodified source
  release accompany the DLL under the backend's `driver/` directory.
- The WinUSB installer, DDR configuration and XUSB firmware retain their
  original licenses and copyrights, independently of the Python application.

See `components.json` for the installed Python package versions. Qt Virtual
Keyboard and its input-context plugins are excluded. The unused PDF image
plugin is also excluded. Qt and the Python libraries have not been modified
by this project. Bundled Qt source releases retain their third-party notices,
license texts, build scripts and attribution metadata.

`GPL-3.0.txt` and `LGPL-3.0.txt` are the unmodified GNU license texts.
Their original locations are https://www.gnu.org/licenses/gpl-3.0.txt and
https://www.gnu.org/licenses/lgpl-3.0.txt. `pyserial-LICENSE.txt` is copied
unchanged from https://github.com/pyserial/pyserial/blob/v3.5/LICENSE.txt.

## Corresponding Source

The distribution includes `sources/manifest.json` and the matching unmodified
upstream source archives beside it. The manifest records component versions,
download URLs and SHA-256 digests. Source archives from PyPI and Qt framework
modules are checked against upstream SHA-256 values. The Qt for Python source
archive is obtained over HTTPS from the official versioned release directory;
its downloaded SHA-256 is recorded. Do not remove these sources when forwarding
the distribution.

`sources/application/` contains the project's Python source, resources,
license inputs and reproducible-build materials. These files are
provided to allow rebuilding the application with modified LGPL libraries.
Source archives are included directly; no request, payment or expiring download
service is required to obtain them. Sources for optional dependencies that are
not distributed are not required by this notice.

## Modification And Replacement

You may modify the LGPL libraries and reverse engineer this application to
debug modifications to those libraries, subject to the applicable licenses.
No additional restriction in this project's distribution terms is intended to
remove these rights. LGPLv3 does not require the application's independent
source code to be licensed under GPL or LGPL.

Qt and Shiboken use shared libraries. An interface-compatible modified build
may replace the corresponding libraries in the extracted runtime directory.
Preserve the expected filenames, Python ABI, architecture, Qt version and
library dependencies. The pyte Python modules are supplied as external `.py`
files in the runtime's `pyte/` directory, not frozen into the executable.
Replace those files with interface-compatible modified sources and restart
the application. An unrelated system-wide `pip install` does not replace
the files used by an extracted distribution. Rebuild instructions for modified
libraries accompany the application source in its build documentation.

Standard Python, CMake, compiler and platform SDK installations may be required.
Library builds must remain interface-compatible with the application. The
rebuild process may access the listed upstream package/source repositories;
the corresponding library sources themselves are already included locally.
Redistributors of modified libraries must update source archives, manifests
and modification notices rather than claim the unmodified upstream archives
correspond to their changes.

The Windows/Linux applications impose no library signature check. A modified
macOS application may need a new ad-hoc signature after library replacement:
`codesign --force --deep --sign - /path/to/nuwriter-gui.app`.
These are desktop applications, not locked-down hardware installations.
Corporate EULAs and downstream distributors must not remove applicable LGPL
rights. This notice is technical redistribution information, not legal advice.