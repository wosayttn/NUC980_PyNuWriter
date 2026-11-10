from pathlib import Path

from PyInstaller.utils.hooks.qt import add_qt6_dependencies


hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
binaries = [(source, destination) for source, destination in binaries
            if "virtualkeyboard" not in Path(source).name.casefold()
            and Path(source).name.casefold() not in ("qpdf.dll", "libqpdf.so", "libqpdf.dylib")]
hiddenimports = [name for name in hiddenimports if name != "PySide6.QtVirtualKeyboard"]