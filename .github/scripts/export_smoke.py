"""Private, hardware-free GUI check embedded only for standalone export tests."""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QTimer
from PySide6.QtGui import QPixmap

import backend
import console


def smoke_gui(application, window_class, report):
    if sys.platform == "darwin":
        cli = Path(backend.Command(["--version"]).invocation()[0])
        expected = Path(sys.executable).resolve().with_name("nuwriter")
        if cli.resolve() != expected or not cli.is_file():
            raise RuntimeError("The macOS GUI requires an executable CLI inside Contents/MacOS")
    if sys.platform.startswith("linux"):
        expected = str(Path(sys._MEIPASS) / "nuwriter-gio-modules")
        if os.environ.get("GIO_MODULE_DIR") != expected or os.environ.get("GIO_EXTRA_MODULES"):
            raise RuntimeError("The frozen Linux GIO isolation hook is not active")

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
        window.chip.setCurrentText("NUC970")
        application.processEvents()
        nuc970_ddr_count = window.ddr.count()
        if nuc970_ddr_count == 0 or "MTP" not in [window.media.itemText(i) for i in range(window.media.count())]:
            raise RuntimeError("Bundled NUC970 DDR settings or MTP media option are missing")
        window.chip.setCurrentText("NUC980")
        application.processEvents()
        pyte_source = Path(console.pyte.__file__)
        if pyte_source.suffix != ".py" or not pyte_source.is_file():
            raise RuntimeError("The running GUI did not load replaceable pyte source")
        window.open_log()
        window.open_console()

        def finish(success, message):
            Path(report).write_text(json.dumps({"status": "passed" if success else "failed", "message": message,
                                               "ddr_settings": window.ddr.count(),
                                               "nuc970_ddr_settings": nuc970_ddr_count,
                                               "pyte_source": str(pyte_source),
                                               "gio_module_dir": os.environ.get("GIO_MODULE_DIR"),
                                               "backend": window.runner.current.invocation()}),
                                    encoding="utf-8")
            window.close()
            application.exit(0 if success else 1)

        def expired():
            window.runner.process.kill()
            application.exit(1)

        window.runner.finished.connect(finish)
        QTimer.singleShot(20000, expired)
        QTimer.singleShot(0, lambda: window.runner.start(
            backend.Command(["--chip", "nuc980", "-a", "NUC980DK71YC.ini", "--check"], cwd=Path(temporary)), preflight=False))
        return application.exec()