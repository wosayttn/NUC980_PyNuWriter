"""Private, hardware-free GUI check embedded only for standalone export tests."""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QTimer
from PySide6.QtGui import QPixmap

import backend
import console


def smoke_gui(application, window_class, report):
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
        pyte_source = Path(console.pyte.__file__)
        if pyte_source.suffix != ".py" or not pyte_source.is_file():
            raise RuntimeError("The running GUI did not load replaceable pyte source")
        window.open_log()
        window.open_console()

        def finish(success, message):
            Path(report).write_text(json.dumps({"status": "passed" if success else "failed", "message": message,
                                               "ddr_settings": window.ddr.count(), "pyte_source": str(pyte_source),
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
            backend.Command(["-a", "NUC980DK71YC.ini", "--check"], cwd=Path(temporary)), preflight=False))
        return application.exec()