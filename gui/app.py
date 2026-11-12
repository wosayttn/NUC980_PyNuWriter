"""Cross-platform desktop frontend for the NuWriter command-line tool."""

import codecs
import json
import mmap
import platform
import shlex
import sys
import tempfile
import time
from collections import deque
from datetime import datetime
from importlib import metadata
from pathlib import Path

import psutil

from PySide6.QtCore import QByteArray, QIODevice, QProcess, QProcessEnvironment, QRect, QRegularExpression, QSaveFile, QSettings, QStandardPaths, QSysInfo, QTemporaryFile, Qt, QTimer, Signal, qVersion
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette, QPixmap, QRegion, QRegularExpressionValidator, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QBoxLayout, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLayout, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QRadioButton, QSpinBox, QStackedWidget,
    QStyle, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

import backend
import console


def host_information():
    lines = ["Host system information",
             "Collected: " + datetime.now().astimezone().isoformat(timespec="seconds"),
             "OS: " + QSysInfo.prettyProductName(),
             "Kernel: " + QSysInfo.kernelType() + " " + QSysInfo.kernelVersion(),
             "CPU: " + (platform.processor() or QSysInfo.currentCpuArchitecture()),
             "Architecture: " + QSysInfo.currentCpuArchitecture()]
    try:
        physical = psutil.cpu_count(logical=False)
        logical = psutil.cpu_count(logical=True)
        lines.append(f"CPU cores: {physical or 'unavailable'} physical, {logical or 'unavailable'} logical")
    except (OSError, NotImplementedError, psutil.Error):
        lines.append("CPU cores: unavailable")
    try:
        memory = psutil.virtual_memory()
        lines.append(f"RAM: {memory.total / 1024 ** 3:.2f} GiB total, {memory.available / 1024 ** 3:.2f} GiB available")
    except (OSError, NotImplementedError, psutil.Error):
        lines.append("RAM: unavailable")
    lines.extend([f"Python: {platform.python_version()} ({64 if sys.maxsize > 2 ** 32 else 32}-bit)",
                  "Interpreter: " + sys.executable,
                  f"Qt: {qVersion()} / platform={QApplication.platformName()}"])
    lines.append("Python modules:")
    for distribution, module in (("PySide6", "PySide6"), ("pyte", "pyte"), ("pyserial", "serial"),
                                 ("psutil", "psutil"), ("pyusb", "usb"), ("pyfdt", "pyfdt")):
        loaded = module in sys.modules
        try:
            version = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            version = "version unavailable" if loaded else "not installed"
        status = "loaded" if loaded else "not loaded"
        lines.append(f"  {distribution} ({module}): {version} [{status}]")
    for index, screen in enumerate(QApplication.screens(), 1):
        geometry = screen.geometry()
        available = screen.availableGeometry()
        lines.append(f"Display {index}: {screen.name()}, logical={geometry.width()}x{geometry.height()}, "
                     f"scale={screen.devicePixelRatio():g}, workarea={available.width()}x{available.height()}")
    return "\n".join(lines)


class JsonSettings:
    def __init__(self, path=None):
        directory = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
        self.path = Path(path) if path is not None else Path(directory) / "settings.json"
        self.data = {"version": 1}
        self.load_error = ""
        try:
            if self.path.is_file():
                document = json.loads(self.path.read_text(encoding="utf-8-sig"))
                if not isinstance(document, dict) or document.get("version") != 1:
                    raise ValueError("Unsupported settings format")
                self.data = document
        except (OSError, ValueError, UnicodeError) as error:
            self.load_error = str(error)

    def value(self, key, default=None):
        return self.data.get(key, default)

    def setValue(self, key, value):
        self.data[key] = value

    def contains(self, key):
        return key in self.data

    def remove(self, key):
        self.data.pop(key, None)

    def sync(self):
        payload = (json.dumps(self.data, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.load_error and self.path.is_file():
            backup = self.path.with_name(f"{self.path.name}.{time.time_ns()}.invalid")
            with backup.open("xb") as stream:
                stream.write(self.path.read_bytes())
            self.load_error = ""
        output = QSaveFile(str(self.path))
        if not output.open(QIODevice.OpenModeFlag.WriteOnly):
            raise OSError(output.errorString())
        if output.write(payload) != len(payload):
            output.cancelWriting()
            raise OSError(output.errorString())
        if not output.commit():
            raise OSError(output.errorString())


class TextLineEdit(QLineEdit):
    def __init__(self, value="", parent=None):
        super().__init__(value, parent)
        self.setValidator(QRegularExpressionValidator(QRegularExpression(r"[^\x00-\x1f\x7f]*"), self))
        self.setToolTip("Control characters are not allowed")


class HexLineEdit(QLineEdit):
    def __init__(self, value="0x0", parent=None):
        try:
            value = hex(backend.number(str(value)))
        except (ValueError, TypeError):
            value = str(value)
        super().__init__(value, parent)
        self.setValidator(QRegularExpressionValidator(QRegularExpression("0[xX][0-9a-fA-F]{1,8}"), self))
        self.setToolTip("32-bit hexadecimal value: 0x0 to 0xffffffff")


def validate_edits(*fields):
    for field in fields:
        if field.isEnabled() and not field.hasAcceptableInput():
            field.setFocus()
            raise ValueError(field.toolTip() or "Invalid input.")


def setting_widgets(owner):
    supported = (QLineEdit, QComboBox, QCheckBox, QRadioButton, QSpinBox, QPlainTextEdit)
    for name, value in vars(owner).items():
        if isinstance(value, supported):
            yield name, value
        elif isinstance(value, dict):
            for key, widget in value.items():
                if isinstance(widget, supported):
                    yield f"{name}.{key}", widget
        elif isinstance(value, list):
            for index, widget in enumerate(value):
                if isinstance(widget, supported):
                    yield f"{name}.{index}", widget


def capture_widgets(owner):
    values = {}
    for name, widget in setting_widgets(owner):
        if isinstance(widget, (QCheckBox, QRadioButton)):
            values[name] = widget.isChecked()
        elif isinstance(widget, QComboBox):
            values[name] = widget.currentData() if widget.currentData() is not None else widget.currentText()
        elif isinstance(widget, QSpinBox):
            values[name] = widget.value()
        elif isinstance(widget, QLineEdit) and not widget.isReadOnly() and widget.hasAcceptableInput():
            values[name] = widget.text()
        elif isinstance(widget, QPlainTextEdit) and not widget.isReadOnly():
            values[name] = widget.toPlainText()
    if owner.isWindow():
        values["_size"] = [owner.width(), owner.height()]
    return values


def restore_widgets(owner, values):
    if not isinstance(values, dict):
        return
    for name, widget in setting_widgets(owner):
        value = values.get(name)
        if isinstance(widget, (QCheckBox, QRadioButton)) and type(value) is bool:
            widget.setChecked(value)
        elif isinstance(widget, QComboBox) and isinstance(value, (str, int)):
            index = widget.findData(value)
            if index < 0:
                index = widget.findText(str(value))
            if index >= 0:
                widget.setCurrentIndex(index)
        elif isinstance(widget, QSpinBox) and type(value) is int and widget.minimum() <= value <= widget.maximum():
            widget.setValue(value)
        elif isinstance(widget, QLineEdit) and not widget.isReadOnly() and isinstance(value, str):
            previous = widget.text()
            widget.setText(value)
            if not widget.hasAcceptableInput():
                widget.setText(previous)
        elif isinstance(widget, QPlainTextEdit) and not widget.isReadOnly() and isinstance(value, str):
            try:
                if isinstance(json.loads(value), dict):
                    widget.setPlainText(value)
            except ValueError:
                pass
    size = values.get("_size")
    if owner.isWindow() and isinstance(size, list) and len(size) == 2 and all(type(value) is int and 1 <= value <= 16384 for value in size):
        owner.resize(*size)


def bind_dialog_settings(dialog, key):
    window = dialog.parentWidget()
    if not isinstance(getattr(window, "settings", None), JsonSettings):
        return
    states = window.settings.value("dialogs", {})
    if not isinstance(states, dict):
        states = {}
    restore_widgets(dialog, states.get(key, {}))

    def remember():
        states[key] = capture_widgets(dialog)
        window.settings.setValue("dialogs", states)

    dialog.finished.connect(remember)


def button(text, icon, callback):
    control = QPushButton(text)
    control.setIcon(control.style().standardIcon(icon))
    control.clicked.connect(callback)
    control.setMinimumHeight(30)
    return control


def browse_control(field, callback):
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(field, 1)
    browse = QToolButton()
    browse.setIcon(browse.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
    browse.setToolTip("Browse")
    browse.setAccessibleName("Browse")
    browse.clicked.connect(callback)
    layout.addWidget(browse)
    return widget


def table(headers):
    control = QTableWidget(0, len(headers))
    control.setHorizontalHeaderLabels(headers)
    control.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    control.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    control.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    control.verticalHeader().hide()
    control.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    control.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    control.setAlternatingRowColors(True)
    return control


class BackendRunner(QWidget):
    output = Signal(str)
    trace_output = Signal(str)
    command_started = Signal(str)
    progress = Signal(int)
    finished = Signal(bool, str)
    busy_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hide()
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self.process.readyReadStandardOutput.connect(self.consume)
        self.process.readyReadStandardError.connect(self.consume)
        self.process.finished.connect(self.process_finished)
        self.process.errorOccurred.connect(self.process_error)
        self.queue = deque()
        self.busy = False
        self.cancelled = False
        self.decoder = None
        self.stderr_decoder = None
        self.pending = ""
        self.stderr_pending = ""
        self.current = None
        self.trace_enabled = False
        self.trace_control_file = QTemporaryFile(self)
        if not self.trace_control_file.open():
            raise OSError(self.trace_control_file.errorString())
        if self.trace_control_file.write(b"\x00") != 1 or not self.trace_control_file.flush():
            raise OSError(self.trace_control_file.errorString())
        with open(self.trace_control_file.fileName(), "r+b") as control:
            self.trace_control = mmap.mmap(control.fileno(), 1)
        self.destroyed.connect(self.trace_control.close)

    def set_trace_enabled(self, enabled):
        self.trace_enabled = enabled
        self.trace_control[0] = int(enabled)
        if not enabled:
            if self.process.state() != QProcess.ProcessState.NotRunning:
                self.consume()
            if self.pending.startswith("USB "):
                self.pending = ""
            if self.stderr_pending.startswith("USB "):
                self.stderr_pending = ""

    def start(self, command, preflight=True):
        if self.busy:
            raise ValueError("An operation is already running.")
        self.queue.clear()
        if preflight:
            self.queue.append((command, True))
        self.queue.append((command, False))
        self.busy = True
        self.cancelled = False
        self.busy_changed.emit(True)
        self.next_command()

    def next_command(self):
        command, check = self.queue.popleft()
        self.current = command
        self.pending = ""
        self.stderr_pending = ""
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.stderr_decoder = codecs.getincrementaldecoder("utf-8")("replace")
        invocation = command.invocation(check=check)
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONIOENCODING", "utf-8")
        environment.insert("PYTHONUNBUFFERED", "1")
        environment.insert("NUWRITER_TRACE_CONTROL", self.trace_control_file.fileName())
        self.process.setProcessEnvironment(environment)
        self.process.setWorkingDirectory(str(command.cwd))
        self.output.emit("Checking inputs" if check else command.label)
        self.command_started.emit("$ " + shlex.join(invocation))
        self.progress.emit(-1)
        self.process.start(invocation[0], invocation[1:])

    def consume(self):
        data = bytes(self.process.readAllStandardOutput())
        if data and self.decoder is not None:
            self.parse(self.decoder.decode(data))
        errors = bytes(self.process.readAllStandardError())
        if errors and self.stderr_decoder is not None:
            self.parse(self.stderr_decoder.decode(errors), stderr=True)

    def parse(self, text, final=False, stderr=False):
        pending = (self.stderr_pending if stderr else self.pending) + text
        lines = pending.replace("\r", "\n").split("\n")
        pending = lines.pop()
        if final and pending:
            lines.append(pending)
            pending = ""
        if stderr:
            self.stderr_pending = pending
        else:
            self.pending = pending
        for line in lines:
            if not line:
                continue
            if line.startswith("USB "):
                if self.trace_enabled:
                    self.trace_output.emit(line)
                continue
            value = backend.progress_value(line)
            if value is not None:
                self.progress.emit(value)
            self.output.emit(line)

    def process_finished(self, exit_code, exit_status):
        if not self.busy:
            return
        self.consume()
        if self.decoder is not None:
            self.parse(self.decoder.decode(b"", final=True), final=True)
        if self.stderr_decoder is not None:
            self.parse(self.stderr_decoder.decode(b"", final=True), final=True, stderr=True)
        success = exit_code == 0 and exit_status == QProcess.ExitStatus.NormalExit and not self.cancelled
        if success and self.queue:
            self.next_command()
            return
        message = "Completed" if success else f"Backend exited with code {exit_code}"
        if self.cancelled:
            message = "Stopped. The target may still be busy; check it before reconnecting."
        self.finish(success, message)

    def process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart and self.busy:
            self.finish(False, self.process.errorString())

    def finish(self, success, message):
        self.queue.clear()
        self.busy = False
        self.busy_changed.emit(False)
        self.finished.emit(success, message)

    def stop(self):
        if self.busy:
            self.cancelled = True
            self.queue.clear()
            self.process.terminate()
            QTimer.singleShot(2000, self.kill_if_cancelled)

    def kill_if_cancelled(self):
        if self.busy and self.cancelled and self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()


class MediaPages(QStackedWidget):
    def __init__(self):
        super().__init__()
        self.layout().setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.currentChanged.connect(self.updateGeometry)

    def sizeHint(self):
        return self.currentWidget().sizeHint() if self.currentWidget() else super().sizeHint()

    def minimumSizeHint(self):
        return self.currentWidget().minimumSizeHint() if self.currentWidget() else super().minimumSizeHint()


class RangeDialog(QDialog):
    def __init__(self, media, erase=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("NuWriter - Erase" if erase else "NuWriter - Read")
        self.media = media
        self.erase = erase
        self.setMinimumWidth(500)
        layout = QVBoxLayout(self)
        self.all_flash = QCheckBox("Erase All" if erase else "Read All")
        self.all_flash.setChecked(erase)
        layout.addWidget(self.all_flash)
        form = QFormLayout()
        self.filename = TextLineEdit()
        if not erase:
            form.addRow("Save File:", browse_control(self.filename, self.select_output))
        self.start = HexLineEdit("0x0")
        self.length = HexLineEdit("0x20000")
        self.flash_size = HexLineEdit("0x800000")
        form.addRow("Start (bytes):", self.start)
        form.addRow("Length (bytes):", self.length)
        if media == "SPI NOR" and not erase:
            form.addRow("Flash size (bytes):", self.flash_size)
        layout.addLayout(form)
        self.all_flash.toggled.connect(self.update_fields)
        self.update_fields()
        if erase:
            warning = QLabel("Erasing deletes data. Marked NAND bad blocks are preserved.")
            warning.setWordWrap(True)
            layout.addWidget(warning)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        bind_dialog_settings(self, f"range.{media}.{'erase' if erase else 'read'}")

    def accept(self):
        try:
            if not self.all_flash.isChecked():
                validate_edits(self.start, self.length)
                if backend.number(self.length.text()) == 0:
                    raise ValueError("Length must be greater than zero.")
            elif self.media == "SPI NOR" and not self.erase:
                validate_edits(self.flash_size)
                if backend.number(self.flash_size.text()) == 0:
                    raise ValueError("Flash size must be greater than zero.")
            if not self.erase:
                validate_edits(self.filename)
                backend.output_file(self.filename.text())
            super().accept()
        except ValueError as error:
            QMessageBox.warning(self, "Invalid range", str(error))

    def update_fields(self):
        self.start.setEnabled(not self.all_flash.isChecked())
        self.length.setEnabled(not self.all_flash.isChecked())
        self.flash_size.setEnabled(self.all_flash.isChecked())

    def select_output(self):
        filename, _ = QFileDialog.getSaveFileName(self, "Read flash to file", "readback.bin", "Binary files (*.bin);;All files (*)")
        if filename:
            self.filename.setText(filename)


class FormatDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("NuWriter - Format SD/eMMC")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.reserved = QSpinBox()
        self.reserved.setRange(1, 65535)
        self.reserved.setValue(32)
        self.reserved.setSuffix(" MiB")
        self.count = QSpinBox()
        self.count.setRange(1, 4)
        self.count.setValue(2)
        form.addRow("Reserved space:", self.reserved)
        form.addRow("Partitions:", self.count)
        self.sizes = []
        for index in range(3):
            size = QSpinBox()
            size.setRange(1, 1048576)
            size.setValue(128)
            size.setSuffix(" MiB")
            self.sizes.append(size)
            form.addRow(f"Partition {index + 1}:", size)
        form.addRow("Last partition:", QLabel("Remaining capacity"))
        layout.addLayout(form)
        self.count.valueChanged.connect(self.update_fields)
        self.update_fields()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        bind_dialog_settings(self, "format")

    def update_fields(self):
        for index, size in enumerate(self.sizes):
            size.setEnabled(index < self.count.value() - 1)


class FlashPanel(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.images = []
        self.media_images = {}
        self.current_media = None
        self.updating = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        left = QVBoxLayout()
        self.images_table = table(["Image Name", "Type", "Offset"])
        self.images_table.setMinimumWidth(300)
        self.images_table.itemSelectionChanged.connect(self.select_image)
        left.addWidget(self.images_table)
        actions = QHBoxLayout()
        actions.addWidget(button("Browse", QStyle.StandardPixmap.SP_DirOpenIcon, self.add_image))
        actions.addWidget(button("Delete", QStyle.StandardPixmap.SP_TrashIcon, self.delete_image))
        actions.addStretch()
        left.addLayout(actions)
        layout.addLayout(left, 4)
        parameters = QGroupBox("Parameters")
        right = QVBoxLayout(parameters)
        form = QFormLayout()
        form.setVerticalSpacing(8)
        self.filename = QLineEdit()
        self.filename.setReadOnly(True)
        form.addRow("Image Name:", browse_control(self.filename, self.add_image))
        self.kind_group = QButtonGroup(self)
        kinds = QWidget()
        self.kind_layout = QGridLayout(kinds)
        self.kind_layout.setContentsMargins(0, 0, 0, 0)
        self.kind_layout.setVerticalSpacing(8)
        self.kind_layout.setHorizontalSpacing(12)
        self.kind_buttons = {}
        for index, name in enumerate(backend.KINDS):
            radio = QRadioButton(name)
            radio.setMinimumHeight(radio.sizeHint().height())
            self.kind_group.addButton(radio, index)
            self.kind_buttons[name] = radio
            radio.toggled.connect(self.update_image)
            self.kind_layout.addWidget(radio, 0, index)
        self.kind_buttons["Data"].setChecked(True)
        form.addRow("Image Type:", kinds)
        self.execute = HexLineEdit("0x200")
        self.offset = HexLineEdit("0x0")
        self.execute.textEdited.connect(self.update_image)
        self.offset.textEdited.connect(self.update_image)
        form.addRow("Image execute address:", self.execute)
        form.addRow("Image start offset:", self.offset)
        self.verify_after = QCheckBox("Program + Verify")
        form.addRow("Option:", self.verify_after)
        right.addLayout(form)
        right.addStretch()
        row = QGridLayout()
        self.program_button = button("Program", QStyle.StandardPixmap.SP_DialogApplyButton, self.program)
        self.verify_button = button("Verify", QStyle.StandardPixmap.SP_DialogYesButton, self.verify)
        self.read_button = button("Read", QStyle.StandardPixmap.SP_ArrowDown, self.read)
        self.erase_button = button("Erase", QStyle.StandardPixmap.SP_TrashIcon, self.erase)
        self.format_button = button("Format", QStyle.StandardPixmap.SP_DriveHDIcon, self.format)
        for index, control in enumerate((self.program_button, self.verify_button, self.read_button, self.erase_button)):
            row.addWidget(control, index // 2, index % 2)
        row.addWidget(self.format_button, 1, 1)
        right.addLayout(row)
        self.alignment = QLabel()
        self.alignment.setWordWrap(True)
        right.addWidget(self.alignment)
        layout.addWidget(parameters, 5)
        parameters.setMinimumHeight(280)

    def resizeEvent(self, event):
        compact = self.width() < 900
        self.layout().setDirection(QBoxLayout.Direction.LeftToRight)
        self.images_table.setMinimumHeight(140)
        for index, radio in enumerate(self.kind_buttons.values()):
            self.kind_layout.addWidget(radio, index // 2 if compact else 0, index % 2 if compact else index)
        kinds = self.kind_layout.parentWidget()
        kinds.setMinimumHeight(self.kind_layout.minimumSize().height())
        kinds.updateGeometry()
        super().resizeEvent(event)

    def add_image(self):
        filenames, _ = QFileDialog.getOpenFileNames(self, "Choose image", "", "All files (*)")
        for filename in filenames:
            self.images.append(backend.ImageEntry(filename))
        self.refresh()
        if filenames:
            self.images_table.selectRow(len(self.images) - 1)

    def switch_media(self, media):
        if self.current_media:
            self.media_images[self.current_media] = self.images
        self.current_media = media
        self.images = self.media_images.setdefault(media, [])
        self.refresh()
        self.filename.clear()
        if self.images:
            self.images_table.selectRow(0)
            self.select_image()
        self.update_availability()

    def refresh(self):
        selected = self.images_table.currentRow()
        self.images_table.blockSignals(True)
        self.images_table.setRowCount(len(self.images))
        for index, image in enumerate(self.images):
            for column, value in enumerate((Path(image.filename).name, image.kind, image.offset)):
                item = QTableWidgetItem(value)
                item.setToolTip(image.filename if column == 0 else value)
                self.images_table.setItem(index, column, item)
        self.images_table.blockSignals(False)
        if 0 <= selected < len(self.images):
            self.images_table.selectRow(selected)

    def delete_image(self):
        index = self.images_table.currentRow()
        if 0 <= index < len(self.images):
            self.images.pop(index)
            self.refresh()
            self.filename.clear()

    def select_image(self):
        index = self.images_table.currentRow()
        if 0 <= index < len(self.images):
            image = self.images[index]
            self.updating = True
            self.filename.setText(image.filename)
            self.filename.setToolTip(image.filename)
            self.kind_buttons[image.kind].setChecked(True)
            self.offset.setText(image.offset)
            self.execute.setText(image.execute)
            self.updating = False
            self.update_availability()

    def update_image(self):
        if self.updating or not hasattr(self, "offset"):
            return
        index = self.images_table.currentRow()
        if 0 <= index < len(self.images):
            image = self.images[index]
            image.kind = next(name for name, radio in self.kind_buttons.items() if radio.isChecked())
            if self.offset.hasAcceptableInput():
                image.offset = self.offset.text()
            if self.execute.hasAcceptableInput():
                image.execute = self.execute.text()
            self.images_table.item(index, 1).setText(image.kind)
            self.images_table.item(index, 2).setText(image.offset)
        self.update_availability()

    def current_image(self):
        validate_edits(self.offset, self.execute)
        self.update_image()
        index = self.images_table.currentRow()
        if not 0 <= index < len(self.images):
            raise ValueError("Choose an image first.")
        return self.images[index]

    def update_availability(self):
        media = self.window.media.currentText()
        kind = next(name for name, radio in self.kind_buttons.items() if radio.isChecked())
        packed = kind == "Pack"
        self.offset.setEnabled(not packed)
        self.execute.setEnabled(not packed)
        self.verify_after.setEnabled(not packed)
        if packed:
            self.verify_after.setChecked(False)
        self.verify_button.setEnabled(kind == "Data")
        self.verify_button.setToolTip("Read back and compare; never programs. Data images only.")
        self.erase_button.setEnabled(media != "SD/eMMC")
        self.erase_button.setVisible(media != "SD/eMMC")
        self.format_button.setVisible(media == "SD/eMMC")
        self.erase_button.setToolTip("Erase is not supported for SD/eMMC." if media == "SD/eMMC" else "Erase flash")
        alignment = {"SPI NOR": "Write alignment: 4 KiB; read alignment: 64 KiB.",
                     "SD/eMMC": "Address alignment: 512 bytes."}.get(media, "Address alignment: one flash erase block.")
        self.alignment.setText(alignment)

    def program(self):
        try:
            image = self.current_image()
            command = backend.program(self.window.target(), self.window.media.currentText(), image, self.verify_after.isChecked())
            self.window.submit(command, warning=f"Program {Path(image.filename).name} to {self.window.media.currentText()}?\nExisting data at the destination may be erased or overwritten.")
        except (ValueError, OSError) as error:
            self.window.error(str(error))

    def verify(self):
        try:
            image = self.current_image()
            temporary = tempfile.TemporaryDirectory(prefix="nuwriter-verify-")
            command = backend.verification_read(self.window.target(), self.window.media.currentText(), image,
                                                Path(temporary.name) / "readback.bin")
            self.window.verification = (temporary, image.filename, str(Path(temporary.name) / "readback.bin"))
            self.window.submit(command)
        except (ValueError, OSError) as error:
            self.window.cleanup_verification()
            self.window.error(str(error))

    def read(self):
        dialog = RangeDialog(self.window.media.currentText(), parent=self.window)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                command = backend.read(self.window.target(), self.window.media.currentText(), dialog.filename.text(),
                                       dialog.start.text(), dialog.length.text(), dialog.all_flash.isChecked(), dialog.flash_size.text())
                filename = Path(dialog.filename.text())
                warning = f"Replace {filename}?" if filename.exists() else ""
                self.window.submit(command, warning=warning)
            except (ValueError, OSError) as error:
                self.window.error(str(error))

    def erase(self):
        dialog = RangeDialog(self.window.media.currentText(), erase=True, parent=self.window)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                command = backend.erase(self.window.target(), self.window.media.currentText(), dialog.start.text(),
                                        dialog.length.text(), dialog.all_flash.isChecked())
                self.window.submit(command, warning="Erase the selected flash range?\nThis permanently deletes data and cannot be undone.")
            except (ValueError, OSError) as error:
                self.window.error(str(error))

    def format(self):
        dialog = FormatDialog(self.window)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                target = self.window.target()
                sizes = [size.value() for size in dialog.sizes[:dialog.count.value() - 1]] + [0]
                configuration = backend.format_configuration(target, dialog.reserved.value(), sizes)
                with tempfile.NamedTemporaryFile(mode="w", suffix=".ini", prefix="nuwriter-format-",
                                                 encoding="utf-8", delete=False) as snapshot:
                    self.window.pack_snapshot = Path(snapshot.name)
                    snapshot.write(configuration)
                command = backend.Command([str(self.window.pack_snapshot)] + target.options(), label="SD/eMMC format")
                self.window.submit(command, warning="Format SD/eMMC and replace its partition table?\nAll existing data may be lost. This operation initializes DDR/XUSB and runs the pre-attach reset hook.")
            except (ValueError, OSError) as error:
                self.window.cleanup_snapshot()
                self.window.error(str(error))


class RamPanel(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.filename = TextLineEdit()
        self.dtb = TextLineEdit()
        self.dtb_enabled = QCheckBox("DTB file:")
        self.dtb_enabled.toggled.connect(self.update_fields)
        form.addRow(self.dtb_enabled, browse_control(self.dtb, lambda: self.browse(self.dtb)))
        form.addRow("Choose file:", browse_control(self.filename, lambda: self.browse(self.filename)))
        self.address = HexLineEdit("0x8000")
        self.dtb_address = HexLineEdit("0x1400000")
        form.addRow("Execute address:", self.address)
        form.addRow("DTB address:", self.dtb_address)
        options = QWidget()
        row = QHBoxLayout(options)
        row.setContentsMargins(0, 0, 0, 0)
        self.download_only = QRadioButton("Download only")
        self.execute = QRadioButton("Download and run")
        self.download_only.setChecked(True)
        row.addWidget(self.download_only)
        row.addWidget(self.execute)
        row.addStretch()
        form.addRow("Option:", options)
        self.bootargs_enabled = QCheckBox("Bootargs:")
        self.bootargs_enabled.toggled.connect(self.update_fields)
        self.bootargs = TextLineEdit()
        form.addRow(self.bootargs_enabled, self.bootargs)
        layout.addLayout(form)
        layout.addStretch()
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(button("Download", QStyle.StandardPixmap.SP_ArrowDown, self.download))
        layout.addLayout(row)
        self.update_fields()

    def update_fields(self):
        self.dtb.setEnabled(self.dtb_enabled.isChecked())
        self.dtb_address.setEnabled(self.dtb_enabled.isChecked())
        self.bootargs_enabled.setEnabled(self.dtb_enabled.isChecked())
        self.bootargs.setEnabled(self.dtb_enabled.isChecked() and self.bootargs_enabled.isChecked())

    def browse(self, field):
        filename, _ = QFileDialog.getOpenFileName(self, "Choose image", "", "All files (*)")
        if filename:
            field.setText(filename)

    def download(self):
        try:
            validate_edits(self.filename, self.dtb, self.address, self.dtb_address, self.bootargs)
            dtb = self.dtb.text() if self.dtb_enabled.isChecked() else ""
            bootargs = self.bootargs.text() if self.dtb_enabled.isChecked() and self.bootargs_enabled.isChecked() else None
            command = backend.download(self.window.target(), self.filename.text(), self.address.text(),
                                       self.execute.isChecked(), dtb, self.dtb_address.text(), bootargs)
            warning = "Download and execute this image?\nThe running software may access flash and other hardware." if self.execute.isChecked() else ""
            self.window.submit(command, warning=warning)
        except (ValueError, OSError) as error:
            self.window.error(str(error))


class PackImageDialog(QDialog):
    def __init__(self, image=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("NuWriter - Pack Image")
        self.resize(550, 470)
        self.original = dict(image or {})
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.filename = TextLineEdit(str(self.original.get("file", "")))
        form.addRow("Image file:", browse_control(self.filename, self.browse))
        self.kind = QComboBox()
        self.kind.addItems(["data", "env", "loader", "linux", "partition"])
        kind = self.original.get("type", "data")
        if type(kind) is int:
            kind = {0: "data", 2: "loader", 3: "linux"}.get(kind, str(kind))
        kind = {"environment": "env", "uboot": "loader"}.get(str(kind).lower(), str(kind).lower())
        if self.kind.findText(kind) == -1:
            self.kind.addItem(kind)
        self.kind.setCurrentText(str(kind))
        self.offset = HexLineEdit(str(self.original.get("offset", self.original.get("address", "0x0"))))
        self.execute = HexLineEdit(str(self.original.get("exec_addr", self.original.get("execute_address", "0x200"))))
        form.addRow("Image Type:", self.kind)
        form.addRow("Start offset (bytes):", self.offset)
        form.addRow("Execute address:", self.execute)
        layout.addLayout(form)
        layout.addWidget(QLabel("Additional JSON parameters:"))
        self.parameters = QPlainTextEdit()
        extras = {key: value for key, value in self.original.items() if key not in {"file", "type", "offset", "address", "exec_addr", "execute_address"}}
        self.parameters.setPlainText(json.dumps(extras, indent=2))
        layout.addWidget(self.parameters)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.result_image = None
        if image is None:
            bind_dialog_settings(self, "pack_image")

    def browse(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Choose image")
        if filename:
            self.filename.setText(filename)

    def validate(self):
        try:
            validate_edits(self.filename, self.offset, self.execute)
            extra = json.loads(self.parameters.toPlainText())
            if not isinstance(extra, dict):
                raise ValueError("Additional parameters must be a JSON object.")
            image = dict(extra)
            image.update(type=self.kind.currentText(), offset=hex(backend.number(self.offset.text())))
            if self.filename.text().strip():
                image["file"] = self.filename.text().strip()
            elif image["type"] != "partition":
                raise ValueError("Select an image file.")
            if image["type"] == "loader" or "exec_addr" in self.original or "execute_address" in self.original:
                image["exec_addr"] = hex(backend.number(self.execute.text()))
            self.result_image = image
            self.accept()
        except (ValueError, TypeError) as error:
            QMessageBox.warning(self, "Invalid image", str(error))


class PackPanel(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.document = {"mode": "spinand", "image": []}
        self.config_path = None
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self.media = QComboBox()
        self.media.addItems(["SPI NAND", "SPI NOR", "NAND", "SD/eMMC"])
        header.addWidget(QLabel("Pack media:"))
        header.addWidget(self.media)
        header.addStretch()
        header.addWidget(button("Open JSON", QStyle.StandardPixmap.SP_DialogOpenButton, self.open_json))
        header.addWidget(button("Save JSON", QStyle.StandardPixmap.SP_DialogSaveButton, self.save_json))
        layout.addLayout(header)
        self.images_table = table(["Image Name", "Type", "Offset"])
        self.images_table.doubleClicked.connect(self.modify)
        layout.addWidget(self.images_table)
        self.config_label = QLabel("No configuration selected")
        self.config_label.setWordWrap(True)
        self.config_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.config_label)
        row = QHBoxLayout()
        row.addWidget(button("Add", QStyle.StandardPixmap.SP_FileIcon, self.add))
        row.addWidget(button("Modify", QStyle.StandardPixmap.SP_FileDialogDetailedView, self.modify))
        row.addWidget(button("Delete", QStyle.StandardPixmap.SP_TrashIcon, self.delete))
        row.addStretch()
        row.addWidget(button("Output", QStyle.StandardPixmap.SP_DialogSaveButton, self.output))
        layout.addLayout(row)

    def refresh(self):
        images = self.document.get("image", [])
        self.images_table.setRowCount(len(images))
        for index, image in enumerate(images):
            for column, value in enumerate((Path(str(image.get("file", "Partition"))).name,
                                             str(image.get("type", "data")), str(image.get("offset", "0")))):
                item = QTableWidgetItem(value)
                item.setToolTip(str(image.get("file", value)))
                self.images_table.setItem(index, column, item)
        self.config_label.setText(str(self.config_path) if self.config_path else "Unsaved configuration")

    def open_json(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Open pack configuration", "", "JSON files (*.json)")
        if filename:
            self.load_json(filename)

    def load_json(self, filename):
        try:
            source = Path(filename).resolve()
            with source.open(encoding="utf-8-sig") as stream:
                document = json.load(stream)
            if not isinstance(document, dict) or not isinstance(document.get("image"), list):
                raise ValueError("Pack JSON must contain an image array.")
            if not all(isinstance(image, dict) for image in document["image"]):
                raise ValueError("Every pack image must be an object.")
            mode = str(document.get("mode", document.get("media", "spinand"))).lower()
            selected = next((name for name, value in backend.MEDIA.items() if value == mode), None)
            if mode == "emmc":
                selected = "SD/eMMC"
            if selected not in [self.media.itemText(index) for index in range(self.media.count())]:
                raise ValueError("Unsupported pack media.")
            self.media.setCurrentText(selected)
            self.document = document
            self.config_path = source
            self.refresh()
        except (ValueError, OSError) as error:
            self.window.error(str(error))

    def save_json(self):
        filename, _ = QFileDialog.getSaveFileName(self, "Save pack configuration", str(self.config_path or "pack.json"), "JSON files (*.json)")
        if not filename:
            return False
        try:
            destination = backend.output_file(filename)
            if self.config_path and destination.parent != self.config_path.parent:
                raise ValueError("Save in the original configuration directory to preserve relative input paths.")
            document = backend.pack_document(self.document, self.media.currentText())
            backend.protect_pack_inputs(document, destination.parent, destination)
            destination.write_text(json.dumps(document, indent=4) + "\n", encoding="utf-8")
            self.document = document
            self.config_path = destination
            self.refresh()
            return True
        except (ValueError, OSError) as error:
            self.window.error(str(error))
            return False

    def add(self):
        dialog = PackImageDialog(parent=self.window)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.document["image"].append(dialog.result_image)
            self.refresh()

    def modify(self):
        index = self.images_table.currentRow()
        if 0 <= index < len(self.document["image"]):
            dialog = PackImageDialog(self.document["image"][index], self.window)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.document["image"][index] = dialog.result_image
                self.refresh()

    def delete(self):
        index = self.images_table.currentRow()
        if 0 <= index < len(self.document["image"]):
            self.document["image"].pop(index)
            self.refresh()

    def output(self):
        if self.config_path is None and not self.save_json():
            return
        filename, _ = QFileDialog.getSaveFileName(self, "Output pack", str(self.config_path.parent / "pack.bin"), "Binary files (*.bin)")
        if filename:
            try:
                document = backend.pack_document(self.document, self.media.currentText())
                backend.protect_pack_inputs(document, self.config_path.parent, filename, self.config_path)
                with tempfile.NamedTemporaryFile(mode="w", suffix=".json", prefix=".nuwriter-gui-",
                                                 dir=self.config_path.parent, encoding="utf-8", delete=False) as snapshot:
                    self.window.pack_snapshot = Path(snapshot.name)
                    json.dump(document, snapshot)
                command = backend.pack(self.window.pack_snapshot, filename, self.media.currentText())
                self.window.submit(command, warning=f"Replace {filename}?" if Path(filename).exists() else "")
            except (ValueError, OSError) as error:
                self.window.cleanup_snapshot()
                self.window.error(str(error))


class MassPanel(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.media = QComboBox()
        self.media.addItems(["SPI NAND", "SPI NOR", "NAND", "SD/eMMC"])
        self.filename = TextLineEdit()
        form.addRow("Media:", self.media)
        form.addRow("Pack file:", browse_control(self.filename, self.browse))
        self.state = QLabel("All connected NUC980 targets")
        form.addRow("Device selection:", self.state)
        layout.addLayout(form)
        layout.addStretch()
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(button("Program", QStyle.StandardPixmap.SP_DialogApplyButton, self.program))
        layout.addLayout(row)

    def browse(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Choose pack", "", "Binary files (*.bin);;All files (*)")
        if filename:
            self.filename.setText(filename)

    def program(self):
        try:
            validate_edits(self.filename)
            command = backend.program(self.window.target(), self.media.currentText(), backend.ImageEntry(self.filename.text(), "Pack"))
            self.window.submit(command, warning="Program this pack to ALL connected NUC980 targets?\nDevices are programmed sequentially. Existing data may be erased or overwritten.")
        except (ValueError, OSError) as error:
            self.window.error(str(error))


class OperationLogWindow(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.setWindowTitle("NuWriter - Operation Log")
        self.setAccessibleName("Operation Log")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint | Qt.WindowType.WindowTitleHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setModal(False)
        self.resize(760, 320)
        self.setMinimumWidth(420)
        self.setFixedHeight(320)
        layout = QVBoxLayout(self)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(10000)
        layout.addWidget(self.log, 1)

    def reject(self):
        pass

    def closeEvent(self, event):
        event.ignore()


class USBTraceWindow(QDialog):
    visibility_changed = Signal(bool)
    transaction_styles = {
        "CONTROL OUT": ("H->D", "#5aa5ff"),
        "CONTROL IN": ("D->H", "#56dce5"),
        "BULK OUT": ("H->D", "#f3c969"),
        "BULK IN": ("D->H", "#74db98"),
    }

    def __init__(self, window):
        super().__init__(window)
        self.setWindowTitle("USB Trace")
        self.setWindowFlag(Qt.WindowType.WindowMinMaxButtonsHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setModal(False)
        self.resize(800, 560)
        self.setMinimumSize(480, 280)
        layout = QVBoxLayout(self)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log.setUndoRedoEnabled(False)
        self.log.setMaximumBlockCount(10000)
        self.log.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.log.setStyleSheet("QPlainTextEdit { background: #000000; color: #e6e6e6; selection-background-color: #355572; selection-color: #ffffff; }")
        layout.addWidget(self.log)

    def append_trace(self, text):
        if not self.isVisible():
            return
        message = text.removeprefix("USB ")
        color = "#e6e6e6"
        for transaction, (direction, transaction_color) in self.transaction_styles.items():
            if message == transaction or message.startswith(transaction + " "):
                message = f"{direction} {message}"
                color = transaction_color
                break
        header, separator, payload = message.partition(" data=")
        if separator:
            values = payload.split()
            suffix = " ..." if values and values[-1] == "..." else ""
            if suffix:
                values.pop()
            rows = ["     " + " ".join(values[offset:offset + 16])
                    for offset in range(0, len(values), 16)] or ["     "]
            rows[-1] += suffix
            message = header + separator + "\n" + "\n".join(rows)
        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if not self.log.document().isEmpty():
            cursor.insertBlock()
        formatting = QTextCharFormat()
        formatting.setForeground(QColor(color))
        cursor.insertText(message, formatting)
        self.log.setTextCursor(cursor)
        self.log.ensureCursorVisible()
        scrollbar = self.log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def showEvent(self, event):
        super().showEvent(event)
        self.visibility_changed.emit(True)

    def hideEvent(self, event):
        super().hideEvent(event)
        self.visibility_changed.emit(False)


class MainWindow(QMainWindow):
    def __init__(self, settings_path=None):
        super().__init__()
        self.setWindowTitle("Nuvoton NuWriter - NUC980")
        self.setWindowIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        self.resize(800, 560)
        self.setMinimumSize(780, 560)
        self.verification = None
        self.pack_snapshot = None
        self.operation = ""
        self.collected = []
        self.host_information_logged = False
        self.settings = JsonSettings(settings_path)
        if settings_path is None and not self.settings.path.exists():
            legacy = QSettings("Nuvoton", "NUC980-PyNuWriter-GUI")
            self.settings.setValue("ddr", str(legacy.value("ddr", "NUC980DK71YC.ini")))
        self.console_window = None
        self.console_geometry = ""
        self.initial_position_set = False
        self.runner = BackendRunner(self)
        self.runner.output.connect(self.append_output)
        self.runner.command_started.connect(self.append_command)
        self.runner.progress.connect(self.show_progress)
        self.runner.finished.connect(self.operation_finished)
        self.runner.busy_changed.connect(self.set_busy)
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(6)
        banner = QFrame()
        banner.setObjectName("banner")
        banner_layout = QHBoxLayout(banner)
        banner_layout.setContentsMargins(8, 4, 8, 4)
        brand = QLabel()
        brand.setObjectName("brand")
        brand.setAccessibleName("Nuvoton")
        brand.setFixedSize(224, 32)
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo = QPixmap(str(Path(__file__).resolve().with_name("logo.png")))
        if not logo.isNull():
            if logo.hasAlphaChannel():
                bounds = QRegion(logo.mask()).boundingRect()
                if not bounds.isEmpty():
                    logo = logo.copy(bounds)
            ratio = self.devicePixelRatioF()
            logo = logo.scaled(round(224 * ratio), round(32 * ratio),
                               Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            logo.setDevicePixelRatio(ratio)
            brand.setPixmap(logo)
        banner_layout.addWidget(brand)
        banner_layout.addStretch()
        outer.addWidget(banner)
        self.controls = QWidget()
        controls_layout = QVBoxLayout(self.controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("Choose type:"))
        self.media = QComboBox()
        self.media.addItems(["SDRAM", "SPI NOR", "NAND", "SD/eMMC", "SPI NAND", "Pack", "Mass Production"])
        self.media.setCurrentText("SDRAM")
        target_row.addWidget(self.media)
        target_row.addWidget(QLabel("DDR Init:"))
        self.ddr = QComboBox()
        for path in sorted((backend.ROOT / "sys_cfg").glob("*.ini")):
            self.ddr.addItem(path.name, (Path("sys_cfg") / path.name).as_posix())
        index = self.ddr.findText(str(self.settings.value("ddr", "NUC980DK71YC.ini")))
        if index < 0:
            index = self.ddr.findText("NUC980DK71YC.ini")
        if index >= 0:
            self.ddr.setCurrentIndex(index)
        target_row.addWidget(self.ddr, 1)
        self.reconnect_button = button("Re-Connect", QStyle.StandardPixmap.SP_BrowserReload, self.attach)
        target_row.addWidget(self.reconnect_button)
        device_row = QHBoxLayout()
        device_row.addWidget(QLabel("USB Device:"))
        self.devices = QComboBox()
        self.devices.addItem("Auto (single device)", "")
        self.devices.setMinimumContentsLength(20)
        device_row.addWidget(self.devices)
        self.refresh_button = button("Refresh", QStyle.StandardPixmap.SP_BrowserReload, self.refresh_devices)
        device_row.addWidget(self.refresh_button)
        device_row.addStretch()
        outer.addLayout(device_row)
        controls_layout.addLayout(target_row)
        self.pages = MediaPages()
        self.flash = FlashPanel(self)
        self.ram = RamPanel(self)
        self.pack = PackPanel(self)
        self.mass = MassPanel(self)
        self.pages.addWidget(self.flash)
        self.pages.addWidget(self.ram)
        self.pages.addWidget(self.pack)
        self.pages.addWidget(self.mass)
        controls_layout.addWidget(self.pages, 1)
        outer.addWidget(self.controls, 1)
        self.log_window = OperationLogWindow(self)
        self.log = self.log_window.log
        self.trace_window = USBTraceWindow(self)
        self.runner.trace_output.connect(self.trace_window.append_trace)
        self.trace_window.visibility_changed.connect(self.runner.set_trace_enabled)
        footer = QHBoxLayout()
        self.status = QLabel("Not connected")
        self.status.setMinimumWidth(130)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setMinimumHeight(20)
        footer.addWidget(self.status)
        footer.addWidget(self.progress, 1)
        self.console_button = button("Console", QStyle.StandardPixmap.SP_ComputerIcon, self.open_console)
        self.console_button.setCheckable(True)
        self.console_button.setToolTip("Show or hide serial console")
        device_row.addWidget(self.console_button)
        self.trace_button = button("USB Trace", QStyle.StandardPixmap.SP_DriveNetIcon, self.open_trace)
        self.trace_button.setCheckable(True)
        self.trace_button.setToolTip("Show to enable USB trace; hide to disable")
        self.trace_window.visibility_changed.connect(self.trace_button.setChecked)
        device_row.addWidget(self.trace_button)
        self.log_button = button("Op. log", QStyle.StandardPixmap.SP_FileDialogDetailedView, self.open_log)
        self.log_button.setCheckable(True)
        self.log_button.setToolTip("Show or hide operation log")
        device_row.addWidget(self.log_button)
        outer.addLayout(footer)
        self.media.currentTextChanged.connect(self.change_media)
        self.change_media()
        self.restore_settings()
        if self.settings.load_error:
            self.append_output("Error: settings could not be loaded; defaults are in use: " + self.settings.load_error)

    def restore_settings(self):
        saved = self.settings.value("flash_images", {})
        if isinstance(saved, dict):
            for media, images in saved.items():
                if media not in ("SPI NOR", "SPI NAND", "NAND", "SD/eMMC") or not isinstance(images, list):
                    continue
                restored = []
                for image in images:
                    if not isinstance(image, dict) or not isinstance(image.get("kind"), str) or image["kind"] not in backend.KINDS:
                        continue
                    try:
                        filename = image["filename"]
                        if not isinstance(filename, str) or any(ord(character) < 32 for character in filename):
                            continue
                        restored.append(backend.ImageEntry(filename, image["kind"], hex(backend.number(image["offset"])),
                                                           hex(backend.number(image["execute"]))))
                    except (KeyError, TypeError, ValueError):
                        continue
                self.flash.media_images[media] = restored
        flash_media = self.settings.value("flash_media")
        if isinstance(flash_media, str) and flash_media in self.flash.media_images:
            self.flash.switch_media(flash_media)
        self.flash.updating = True
        restore_widgets(self.flash, self.settings.value("flash", {}))
        self.flash.updating = False
        restore_widgets(self.ram, self.settings.value("ram", {}))
        restore_widgets(self.mass, self.settings.value("mass", {}))
        packed = self.settings.value("pack", {})
        if isinstance(packed, dict):
            document = packed.get("document")
            if isinstance(document, dict) and isinstance(document.get("image"), list) and all(isinstance(image, dict) for image in document["image"]):
                self.pack.document = document
            path = packed.get("config_path")
            if isinstance(path, str) and path:
                self.pack.config_path = Path(path)
            restore_widgets(self.pack, packed.get("widgets", {}))
            self.pack.refresh()
            row = packed.get("row", -1)
            if type(row) is int and 0 <= row < self.pack.images_table.rowCount():
                self.pack.images_table.selectRow(row)
        main = self.settings.value("main", {})
        if isinstance(main, dict):
            device = main.get("devices")
            if isinstance(device, str) and QRegularExpression(r"\A\d+:\d+(?:\.\d+)*\z").match(device).hasMatch():
                self.devices.addItem(device, device)
        restore_widgets(self, main)
        self.change_media()
        row = self.settings.value("flash_row", 0)
        if type(row) is int and 0 <= row < len(self.flash.images):
            self.flash.images_table.selectRow(row)
            self.flash.select_image()
        restore_widgets(self.trace_window, self.settings.value("trace", {}))

    def save_settings(self):
        self.flash.update_image()
        if self.flash.current_media:
            self.flash.media_images[self.flash.current_media] = self.flash.images
        self.settings.setValue("main", capture_widgets(self))
        self.settings.setValue("ram", capture_widgets(self.ram))
        self.settings.setValue("flash", capture_widgets(self.flash))
        self.settings.setValue("flash_media", self.flash.current_media)
        self.settings.setValue("flash_row", self.flash.images_table.currentRow())
        self.settings.setValue("flash_images", {media: [vars(image) for image in images]
                                                for media, images in self.flash.media_images.items()})
        self.settings.setValue("pack", {"widgets": capture_widgets(self.pack), "document": self.pack.document,
                                       "config_path": str(self.pack.config_path or ""),
                                       "row": self.pack.images_table.currentRow()})
        self.settings.setValue("mass", capture_widgets(self.mass))
        self.settings.setValue("trace", capture_widgets(self.trace_window))
        if self.console_window is not None:
            console_settings = capture_widgets(self.console_window)
            console_settings["_geometry"] = bytes(self.console_window.saveGeometry()).hex()
            self.settings.setValue("console", console_settings)
        self.settings.setValue("ddr", self.ddr.currentText())
        self.settings.remove("ddr_path")
        self.settings.sync()

    def showEvent(self, event):
        super().showEvent(event)
        if not self.initial_position_set:
            self.initial_position_set = True
            self.move(self.screen().availableGeometry().topLeft())

    def moveEvent(self, event):
        super().moveEvent(event)
        if hasattr(self, "log_window") and self.log_window.isVisible():
            self.align_log_window()
        if getattr(self, "trace_window", None) is not None and self.trace_window.isVisible():
            QTimer.singleShot(0, self.align_trace_window)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "log_window") and self.log_window.isVisible():
            self.align_log_window()
        if getattr(self, "trace_window", None) is not None and self.trace_window.isVisible():
            QTimer.singleShot(0, self.align_trace_window)

    def align_log_window(self):
        frame = self.frameGeometry()
        border_width = max(0, self.log_window.frameGeometry().width() - self.log_window.width())
        self.log_window.setFixedWidth(max(1, frame.width() - border_width))
        self.log_window.move(frame.left(), frame.bottom() + 1)

    def align_popup_right(self, popup):
        if popup is None or not popup.isVisible():
            return
        frame = self.frameGeometry()
        destination = QRect(frame.right() + 1, frame.top(),
                            popup.frameGeometry().width(), popup.frameGeometry().height())
        available = self.screen().availableGeometry()
        destination.moveLeft(max(available.left(), min(destination.left(), available.right() - destination.width() + 1)))
        destination.moveTop(max(available.top(), min(destination.top(), available.bottom() - destination.height() + 1)))
        popup.move(destination.topLeft())

    def align_console_window(self):
        self.align_popup_right(self.console_window)

    def align_trace_window(self):
        self.align_popup_right(self.trace_window)

    def remember_console_visibility(self, visible):
        self.console_button.setChecked(visible)
        if not visible and self.console_window is not None:
            self.console_geometry = bytes(self.console_window.saveGeometry()).hex()

    def open_console(self):
        first_show = self.console_window is None
        if first_show:
            self.console_window = console.ConsoleWindow(self)
            self.console_window.resize(self.size())
            saved = self.settings.value("console", {})
            restore_widgets(self.console_window, saved)
            if isinstance(saved, dict):
                self.console_geometry = saved.get("_geometry", "")
            self.console_window.error.connect(lambda message: self.append_output(f"Error: Console: {message}"))
            self.console_window.visibility_changed.connect(self.remember_console_visibility)
        popup = self.console_window
        if popup.isVisible() and not popup.isMinimized():
            popup.hide()
            return
        restored = False
        if isinstance(self.console_geometry, str) and 0 < len(self.console_geometry) <= 4096:
            try:
                restored = popup.restoreGeometry(QByteArray(bytes.fromhex(self.console_geometry)))
            except ValueError:
                pass
        if popup.isMinimized():
            popup.showNormal()
        else:
            popup.show()
        if first_show and not restored:
            self.align_console_window()
            QTimer.singleShot(0, self.align_console_window)
        popup.raise_()
        popup.activateWindow()
        popup.terminal.setFocus()

    def open_trace(self):
        popup = self.trace_window
        if popup.isVisible() and not popup.isMinimized():
            popup.hide()
            return
        if popup.isMinimized() or popup.isMaximized():
            popup.showNormal()
        else:
            popup.show()
        self.align_trace_window()
        QTimer.singleShot(0, self.align_trace_window)
        popup.raise_()
        popup.activateWindow()
        popup.log.setFocus()

    def change_media(self):
        media = self.media.currentText()
        pages = {"SDRAM": self.ram, "Pack": self.pack, "Mass Production": self.mass}
        self.pages.setCurrentWidget(pages.get(media, self.flash))
        if media not in pages:
            self.flash.switch_media(media)
        self.devices.setEnabled(not self.runner.busy and media != "Mass Production")

    def target(self):
        mass = self.media.currentText() == "Mass Production"
        ddr = self.ddr.currentData()
        return backend.Target(str(backend.ROOT / ddr) if ddr else "", "" if mass else str(self.devices.currentData() or ""),
                              self.runner.trace_enabled, massproduct=mass)

    def attach(self):
        try:
            self.submit(backend.attach(self.target()), warning="Re-Connect initializes DDR/XUSB and runs the configured pre-attach reset hook.\nPrepare USB Boot mode. Continue?")
        except (ValueError, OSError) as error:
            self.error(str(error))

    def refresh_devices(self):
        self.operation = "List devices"
        self.collected = []
        self.runner.start(backend.Command(["--list"], label="List devices"), preflight=False)

    def submit(self, command, warning=""):
        if warning:
            answer = QMessageBox.warning(self, command.label, warning,
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                self.cleanup_verification()
                self.cleanup_snapshot()
                return
        self.operation = command.label
        self.collected = []
        self.runner.start(command)

    def set_busy(self, busy):
        self.controls.setEnabled(not busy)
        self.devices.setEnabled(not busy and self.media.currentText() != "Mass Production")
        self.refresh_button.setEnabled(not busy)
        if busy:
            self.status.setText("Running")
            self.status.setToolTip("")

    def append_command(self, text):
        self.append_output(text, command=True)

    def append_output(self, text, command=False):
        self.collected.append(text)
        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if not self.log.document().isEmpty():
            cursor.insertBlock()
        for index, line in enumerate(text.split("\n")):
            if index:
                cursor.insertBlock()
            color = "#005fb8" if command else "#c62828" if "error" in line.casefold() else "#21643c"
            formatting = QTextCharFormat()
            formatting.setForeground(QColor(color))
            cursor.insertText(line, formatting)
        self.log.setTextCursor(cursor)
        self.log.ensureCursorVisible()
        scrollbar = self.log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def show_progress(self, value):
        self.progress.setRange(0, 0 if value < 0 else 100)
        if value >= 0:
            self.progress.setValue(value)

    def operation_finished(self, success, message):
        if success and self.operation == "List devices":
            self.devices.clear()
            self.devices.addItem("Auto (single device)", "")
            for path in backend.device_paths("\n".join(self.collected)):
                self.devices.addItem(path, path)
            message = f"Found {self.devices.count() - 1} device(s)"
        elif success and self.verification:
            try:
                backend.compare_files(self.verification[1], self.verification[2])
                message = "Verification passed"
            except (ValueError, OSError) as error:
                success, message = False, str(error)
        elif success and self.operation == "Re-Connect":
            message = "DDR/XUSB ready"
        self.cleanup_verification()
        self.cleanup_snapshot()
        self.progress.setRange(0, 100)
        self.progress.setValue(100 if success else 0)
        self.status.setText("Passed" if success else "Failed")
        self.status.setToolTip(message)
        self.append_output(message)

    def cleanup_verification(self):
        if self.verification:
            self.verification[0].cleanup()
            self.verification = None

    def cleanup_snapshot(self):
        if self.pack_snapshot:
            self.pack_snapshot.unlink(missing_ok=True)
            self.pack_snapshot = None

    def error(self, message):
        QMessageBox.warning(self, "NuWriter", message)

    def open_log(self):
        if self.log_window.isVisible():
            self.log_window.hide()
            self.log_button.setChecked(False)
            return
        self.align_log_window()
        self.log_window.show()
        if not self.host_information_logged:
            self.append_output(host_information() + "\nSettings: " + str(self.settings.path))
            self.host_information_logged = True
        self.align_log_window()
        QTimer.singleShot(0, self.align_log_window)
        self.log_button.setChecked(True)
        self.log_window.raise_()
        self.log_window.activateWindow()

    def save_log(self):
        filename, _ = QFileDialog.getSaveFileName(self.log_window, "Save operation log", "nuwriter.log", "Log files (*.log);;All files (*)")
        if filename:
            try:
                Path(filename).write_text(self.log.toPlainText(), encoding="utf-8")
            except OSError as error:
                self.error(str(error))

    def clear_log(self):
        if not self.runner.busy:
            self.log.clear()

    def closeEvent(self, event):
        if self.runner.busy:
            self.error("An operation is running. Wait for it to finish before closing.")
            event.ignore()
            return
        try:
            self.save_settings()
        except (OSError, ValueError) as error:
            self.error(f"Could not save settings: {error}")
            event.ignore()
            return
        self.cleanup_verification()
        self.cleanup_snapshot()
        self.log_window.hide()
        self.log_button.setChecked(False)
        self.trace_window.hide()
        if self.console_window is not None:
            self.console_window.close()
        event.accept()


def create_application():
    application = QApplication.instance() or QApplication(sys.argv)
    application.setApplicationName("NUC980 PyNuWriter")
    application.setStyle("Fusion")
    palette = QPalette()
    for role, color in ((QPalette.ColorRole.Window, "#f4f4f4"), (QPalette.ColorRole.WindowText, "#242424"),
                        (QPalette.ColorRole.Base, "#ffffff"), (QPalette.ColorRole.AlternateBase, "#f1f3f5"),
                        (QPalette.ColorRole.Text, "#242424"), (QPalette.ColorRole.Button, "#eeeeee"),
                        (QPalette.ColorRole.ButtonText, "#242424"), (QPalette.ColorRole.Highlight, "#cfe4f8"),
                        (QPalette.ColorRole.HighlightedText, "#172b3a"), (QPalette.ColorRole.ToolTipBase, "#ffffff"),
                        (QPalette.ColorRole.ToolTipText, "#242424")):
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#858585"))
    application.setPalette(palette)
    application.setFont(QFont("Segoe UI" if sys.platform == "win32" else "Noto Sans", 10))
    application.setStyleSheet("""
        QMainWindow { background: #f4f4f4; }
        QFrame#banner { background: #ffffff; border-bottom: 2px solid #bb1729; border-radius: 0; }
        QFrame#banner QLabel { color: #242424; font-size: 15px; border: none; }
        QGroupBox { font-weight: 600; }
        QGroupBox QLabel, QGroupBox QRadioButton, QGroupBox QCheckBox { font-weight: 400; }
        QTableWidget { background: white; alternate-background-color: #f5f5f5; }
        QPlainTextEdit { background: #ffffff; color: #242424; }
        QProgressBar { border: 1px solid #b5b5b5; border-radius: 2px; text-align: center; }
        QProgressBar::chunk { background: #22824c; }
    """)
    return application


def main():
    application = create_application()
    window = MainWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    sys.exit(main())