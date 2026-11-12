"""Cross-platform desktop frontend for the NuWriter command-line tool."""

import codecs
import json
import shlex
import sys
import tempfile
from collections import deque
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, QRect, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPalette, QPixmap, QRegion, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QBoxLayout, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLayout, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QRadioButton, QSpinBox, QStackedWidget,
    QStyle, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

import backend
import console


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
    command_started = Signal(str)
    progress = Signal(int)
    finished = Signal(bool, str)
    busy_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hide()
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.consume)
        self.process.finished.connect(self.process_finished)
        self.process.errorOccurred.connect(self.process_error)
        self.queue = deque()
        self.busy = False
        self.cancelled = False
        self.decoder = None
        self.pending = ""
        self.current = None

    def start(self, command, preflight=True, check_only=False):
        if self.busy:
            raise ValueError("An operation is already running.")
        self.queue.clear()
        if check_only:
            self.queue.append((command, True))
        else:
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
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        invocation = command.invocation(check=check)
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONIOENCODING", "utf-8")
        environment.insert("PYTHONUNBUFFERED", "1")
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

    def parse(self, text, final=False):
        self.pending += text
        lines = self.pending.replace("\r", "\n").split("\n")
        self.pending = lines.pop()
        if final and self.pending:
            lines.append(self.pending)
            self.pending = ""
        for line in lines:
            if not line:
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
        self.setMinimumWidth(500)
        layout = QVBoxLayout(self)
        self.all_flash = QCheckBox("Erase All" if erase else "Read All")
        self.all_flash.setChecked(erase)
        layout.addWidget(self.all_flash)
        form = QFormLayout()
        self.filename = QLineEdit()
        if not erase:
            form.addRow("Save File:", browse_control(self.filename, self.select_output))
        self.start = QLineEdit("0x0")
        self.length = QLineEdit("0x20000")
        self.flash_size = QLineEdit("0x800000")
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
        self.execute = QLineEdit("0x200")
        self.offset = QLineEdit("0x0")
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
            image.offset = self.offset.text()
            image.execute = self.execute.text()
            self.images_table.item(index, 1).setText(image.kind)
            self.images_table.item(index, 2).setText(image.offset)
        self.update_availability()

    def current_image(self):
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
        self.filename = QLineEdit()
        self.dtb = QLineEdit()
        self.dtb_enabled = QCheckBox("DTB file:")
        self.dtb_enabled.toggled.connect(self.update_fields)
        form.addRow(self.dtb_enabled, browse_control(self.dtb, lambda: self.browse(self.dtb)))
        form.addRow("Choose file:", browse_control(self.filename, lambda: self.browse(self.filename)))
        self.address = QLineEdit("0x8000")
        self.dtb_address = QLineEdit("0x1400000")
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
        self.bootargs = QLineEdit()
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
        self.filename = QLineEdit(str(self.original.get("file", "")))
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
        self.offset = QLineEdit(str(self.original.get("offset", self.original.get("address", "0x0"))))
        self.execute = QLineEdit(str(self.original.get("exec_addr", self.original.get("execute_address", "0x200"))))
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

    def browse(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Choose image")
        if filename:
            self.filename.setText(filename)

    def validate(self):
        try:
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
        self.filename = QLineEdit()
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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Nuvoton NuWriter - NUC980")
        self.setWindowIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        self.resize(800, 560)
        self.setMinimumSize(780, 560)
        self.verification = None
        self.pack_snapshot = None
        self.operation = ""
        self.collected = []
        self.settings = QSettings("Nuvoton", "NUC980-PyNuWriter-GUI")
        self.console_window = None
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
            self.ddr.addItem(path.name, str(path))
        index = self.ddr.findText(str(self.settings.value("ddr", "NUC980DK71YC.ini")))
        if index >= 0:
            self.ddr.setCurrentIndex(index)
        saved_ddr = str(self.settings.value("ddr_path", ""))
        if saved_ddr and Path(saved_ddr).is_file():
            index = self.ddr.findData(saved_ddr)
            if index < 0:
                self.ddr.addItem(Path(saved_ddr).name, saved_ddr)
                index = self.ddr.count() - 1
            self.ddr.setCurrentIndex(index)
        target_row.addWidget(browse_control(self.ddr, self.select_ddr), 1)
        self.reconnect_button = button("Re-Connect", QStyle.StandardPixmap.SP_BrowserReload, self.attach)
        target_row.addWidget(self.reconnect_button)
        device_row = QHBoxLayout()
        device_row.addWidget(QLabel("USB Device:"))
        self.devices = QComboBox()
        self.devices.addItem("Auto (single device)", "")
        self.devices.setMinimumContentsLength(20)
        device_row.addWidget(self.devices)
        device_row.addWidget(button("Refresh", QStyle.StandardPixmap.SP_BrowserReload, self.refresh_devices))
        self.check_only = QCheckBox("Check only")
        self.trace = QCheckBox("USB trace")
        self.check_only.setToolTip("Validate inputs without board access or output writes.")
        device_row.addStretch()
        device_row.addWidget(self.check_only)
        device_row.addWidget(self.trace)
        controls_layout.addLayout(device_row)
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
        footer.addWidget(self.console_button)
        self.log_button = button("Op. log", QStyle.StandardPixmap.SP_FileDialogDetailedView, self.open_log)
        self.log_button.setCheckable(True)
        self.log_button.setToolTip("Show or hide operation log")
        footer.addWidget(self.log_button)
        self.stop_button = button("Stop", QStyle.StandardPixmap.SP_BrowserStop, self.stop)
        self.stop_button.setEnabled(False)
        footer.addWidget(self.stop_button)
        footer.addWidget(button("EXIT", QStyle.StandardPixmap.SP_DialogCloseButton, self.close))
        outer.addLayout(footer)
        self.media.currentTextChanged.connect(self.change_media)
        self.change_media()

    def showEvent(self, event):
        super().showEvent(event)
        if not self.initial_position_set:
            self.initial_position_set = True
            self.move(self.screen().availableGeometry().topLeft())

    def moveEvent(self, event):
        super().moveEvent(event)
        if hasattr(self, "log_window") and self.log_window.isVisible():
            self.align_log_window()
        if getattr(self, "console_window", None) is not None and self.console_window.isVisible():
            QTimer.singleShot(0, self.align_console_window)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "log_window") and self.log_window.isVisible():
            self.align_log_window()
        if getattr(self, "console_window", None) is not None and self.console_window.isVisible():
            QTimer.singleShot(0, self.align_console_window)

    def align_log_window(self):
        self.log_window.resize(self.width(), self.log_window.height())
        frame = self.frameGeometry()
        self.log_window.move(frame.left(), frame.bottom() + 1)

    def align_console_window(self):
        popup = self.console_window
        if popup is None or not popup.isVisible():
            return
        popup.resize(self.size())
        frame = self.frameGeometry()
        destination = QRect(frame.right() + 1, frame.top(),
                            popup.frameGeometry().width(), popup.frameGeometry().height())
        available = self.screen().availableGeometry()
        destination.moveLeft(max(available.left(), min(destination.left(), available.right() - destination.width() + 1)))
        destination.moveTop(max(available.top(), min(destination.top(), available.bottom() - destination.height() + 1)))
        popup.move(destination.topLeft())

    def open_console(self):
        if self.console_window is None:
            self.console_window = console.ConsoleWindow(self)
            self.console_window.error.connect(lambda message: self.append_output(f"Error: Console: {message}"))
            self.console_window.visibility_changed.connect(self.console_button.setChecked)
        popup = self.console_window
        if popup.isVisible() and not popup.isMinimized():
            popup.hide()
            return
        if popup.isMinimized() or popup.isMaximized():
            popup.showNormal()
        else:
            popup.show()
        self.align_console_window()
        QTimer.singleShot(0, self.align_console_window)
        popup.raise_()
        popup.activateWindow()
        popup.terminal.setFocus()

    def change_media(self):
        media = self.media.currentText()
        pages = {"SDRAM": self.ram, "Pack": self.pack, "Mass Production": self.mass}
        self.pages.setCurrentWidget(pages.get(media, self.flash))
        if media not in pages:
            self.flash.switch_media(media)
        self.devices.setEnabled(media != "Mass Production")

    def target(self):
        mass = self.media.currentText() == "Mass Production"
        return backend.Target(str(self.ddr.currentData() or ""), "" if mass else str(self.devices.currentData() or ""),
                              self.trace.isChecked(), massproduct=mass)

    def select_ddr(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Choose DDR settings", str(backend.ROOT / "sys_cfg"), "DDR settings (*.ini)")
        if filename:
            self.ddr.addItem(Path(filename).name, str(Path(filename).resolve()))
            self.ddr.setCurrentIndex(self.ddr.count() - 1)

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
        check = self.check_only.isChecked()
        if warning and not check:
            answer = QMessageBox.warning(self, command.label, warning,
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                self.cleanup_verification()
                self.cleanup_snapshot()
                return
        self.operation = command.label
        self.collected = []
        self.runner.start(command, check_only=check)

    def set_busy(self, busy):
        self.controls.setEnabled(not busy)
        self.stop_button.setEnabled(busy)
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
        checking = self.check_only.isChecked()
        if success and self.operation == "List devices":
            self.devices.clear()
            self.devices.addItem("Auto (single device)", "")
            for path in backend.device_paths("\n".join(self.collected)):
                self.devices.addItem(path, path)
            message = f"Found {self.devices.count() - 1} device(s)"
        elif success and self.verification and not checking:
            try:
                backend.compare_files(self.verification[1], self.verification[2])
                message = "Verification passed"
            except (ValueError, OSError) as error:
                success, message = False, str(error)
        elif success and checking:
            message = "Offline check passed"
        elif success and self.operation == "Re-Connect":
            message = "DDR/XUSB ready"
        self.cleanup_verification()
        self.cleanup_snapshot()
        self.progress.setRange(0, 100)
        self.progress.setValue(100 if success and not checking else 0)
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

    def stop(self):
        answer = QMessageBox.warning(self, "Stop operation", "Stop the host process?\nThe target may continue its operation. Partial writes cannot be undone. Check or reset the board before reconnecting.",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.runner.stop()

    def open_log(self):
        if self.log_window.isVisible():
            self.log_window.hide()
            self.log_button.setChecked(False)
            return
        self.log_window.show()
        self.align_log_window()
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
            self.error("An operation is running. Stop it and wait for the process to exit before closing.")
            event.ignore()
            return
        self.cleanup_verification()
        self.cleanup_snapshot()
        self.log_window.hide()
        self.log_button.setChecked(False)
        if self.console_window is not None:
            self.console_window.close()
        self.settings.setValue("ddr", self.ddr.currentText())
        self.settings.setValue("ddr_path", self.ddr.currentData())
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