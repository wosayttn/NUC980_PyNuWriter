"""Build the macOS GUI and CLI inside one signed, shared-runtime app bundle."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, copy_metadata


scripts = Path(SPECPATH)
root = scripts.parents[1]
packages = ("PySide6", "PySide6_Essentials", "PySide6_Addons", "shiboken6",
            "pyte", "psutil", "wcwidth", "pyusb", "pyfdt", "pyserial")
resources = [(str(root / name), name) for name in ("sys_cfg", "xusb")]
resources += [(str(root / "gui/logo.png"), "."), (str(root / "pre-attach-hook.py"), ".")]
for package in packages:
    resources += copy_metadata(package)

analysis = Analysis(
    [str(root / "gui/app.py"), str(root / "nuwriter.py")],
    pathex=[str(root), str(root / "gui"), str(scripts)],
    binaries=[],
    datas=resources,
    hiddenimports=collect_submodules("usb") + ["pyfdt.pyfdt", "serial.tools.list_ports",
                                             "ch341_reset_uart", "export_smoke"],
    hookspath=[str(scripts / "hooks")],
    excludes=["PySide6.QtVirtualKeyboard"],
)
entry_names = {entry[0] for entry in analysis.scripts}
if not {"app", "nuwriter"}.issubset(entry_names):
    raise RuntimeError("Both macOS application entry points must be present")
python_archive = PYZ(analysis.pure)
gui = EXE(python_archive, [entry for entry in analysis.scripts if entry[0] != "nuwriter"], [],
          exclude_binaries=True, name="nuwriter-gui", console=False, strip=False, upx=False)
cli = EXE(python_archive, [entry for entry in analysis.scripts if entry[0] != "app"], [],
          exclude_binaries=True, name="nuwriter", console=True, strip=False, upx=False)
collection = COLLECT(gui, cli, analysis.binaries, analysis.datas,
                     name="nuwriter-gui", strip=False, upx=False)
application = BUNDLE(gui, [(Path(cli.name).name, cli.name, "EXECUTABLE")] + cli.dependencies,
                     analysis.binaries, analysis.datas,
                     name="nuwriter-gui.app", bundle_identifier="com.nuvoton.nuwriter")