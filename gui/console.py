"""Nonblocking serial transport and ANSI console window."""

from pathlib import Path

import pyte
import serial
from serial.tools import list_ports

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QKeySequence, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QMenu, QMessageBox,
    QPlainTextEdit, QPushButton, QStyle, QToolButton, QVBoxLayout,
)


def available_ports():
    return sorted(list_ports.comports(), key=lambda port: port.device.casefold())


class SerialConnection(QObject):
    received = Signal(bytes)
    error = Signal(str)
    connected_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.port = None
        self.device = ""
        self.baudrate = 115200
        self.pending = bytearray()
        self.timer = QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self.poll)

    @property
    def connected(self):
        return self.port is not None and self.port.is_open

    def open(self, device, baudrate=115200):
        if self.connected:
            raise ValueError("Close the current console connection before opening another port.")
        if not device:
            raise ValueError("Select a serial port.")
        port = serial.Serial(port=None, baudrate=baudrate, bytesize=serial.EIGHTBITS,
                             parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                             timeout=0, write_timeout=0, xonxoff=False, rtscts=False, dsrdtr=False)
        try:
            port.dtr = False
            port.rts = False
            port.port = device
            port.open()
        except Exception:
            port.close()
            raise
        self.port = port
        self.device = device
        self.baudrate = baudrate
        self.pending.clear()
        self.timer.start()
        self.connected_changed.emit(True)

    def close(self):
        self.timer.stop()
        self.pending.clear()
        port, self.port = self.port, None
        if port is not None:
            try:
                port.close()
            except (serial.SerialException, OSError) as error:
                self.error.emit(str(error))
            finally:
                self.connected_changed.emit(False)

    def send(self, data):
        if not self.connected:
            return
        if len(self.pending) + len(data) > 65536:
            self.error.emit("Console transmit buffer is full; input was not sent.")
            return
        self.pending.extend(data)
        self.poll()

    def poll(self):
        if self.port is None:
            return
        try:
            if not self.port.is_open:
                raise serial.SerialException("Console serial port is closed or disconnected.")
            waiting = self.port.in_waiting
            if waiting:
                data = self.port.read(min(waiting, 32768))
                if data:
                    self.received.emit(bytes(data))
            if self.pending:
                count = self.port.write(bytes(self.pending[:4096]))
                if count:
                    del self.pending[:count]
        except serial.SerialTimeoutException:
            self.close()
            self.error.emit("Console transmit timed out. Connection closed to prevent duplicate input.")
        except (serial.SerialException, OSError) as error:
            self.close()
            self.error.emit(str(error))


class TerminalView(QPlainTextEdit):
    input_ready = Signal(bytes)
    ansi_colors = {
        "black": "#000000", "red": "#cd0000", "green": "#00cd00", "brown": "#cdcd00",
        "blue": "#0000ee", "magenta": "#cd00cd", "cyan": "#00cdcd", "white": "#e5e5e5",
        "brightblack": "#7f7f7f", "brightred": "#ff0000", "brightgreen": "#00ff00",
        "brightbrown": "#ffff00", "brightblue": "#5c5cff", "brightmagenta": "#ff00ff",
        "brightcyan": "#00ffff", "brightwhite": "#ffffff",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("serialTerminal")
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.document().setDocumentMargin(0)
        self.setStyleSheet("QPlainTextEdit#serialTerminal { background: #000000; color: #e6e6e6; selection-background-color: #355572; selection-color: #ffffff; }")
        self.setTabChangesFocus(False)
        self.can_send = False
        self.screen = pyte.HistoryScreen(80, 24, history=2000)
        self.stream = pyte.ByteStream(self.screen)

    def feed(self, data):
        self.stream.feed(data)
        self.render()

    def render(self):
        history = list(self.screen.history.top)
        lines = history + [self.screen.buffer[index] for index in range(self.screen.lines)]
        formats = {}
        cursor = QTextCursor(self.document())
        cursor.beginEditBlock()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.removeSelectedText()
        for line_index, line in enumerate(lines):
            if line_index:
                cursor.insertBlock()
            run = ""
            previous_style = None
            for column in range(self.screen.columns):
                cell = line[column]
                style = (cell.fg, cell.bg, cell.bold, cell.italics, cell.underscore, cell.strikethrough, cell.reverse)
                if run and style != previous_style:
                    cursor.insertText(run, self.character_format(previous_style, formats))
                    run = ""
                run += cell.data
                previous_style = style
            if run:
                cursor.insertText(run, self.character_format(previous_style, formats))
        cursor.endEditBlock()
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        cursor.movePosition(QTextCursor.MoveOperation.Down, QTextCursor.MoveMode.MoveAnchor,
                            len(history) + self.screen.cursor.y)
        cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.MoveAnchor, self.screen.cursor.x)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()
        scrollbar = self.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def character_format(self, style, cache):
        if style not in cache:
            foreground, background, bold, italics, underline, strikeout, reverse = style
            foreground = self.ansi_color(foreground, "#e6e6e6")
            background = self.ansi_color(background, "#000000")
            if reverse:
                foreground, background = background, foreground
            formatting = QTextCharFormat()
            formatting.setForeground(foreground)
            formatting.setBackground(background)
            formatting.setFontWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
            formatting.setFontItalic(italics)
            formatting.setFontUnderline(underline)
            formatting.setFontStrikeOut(strikeout)
            cache[style] = formatting
        return cache[style]

    def ansi_color(self, name, default):
        color = QColor(self.ansi_colors.get(name, default if name == "default" else "#" + name))
        return color if color.isValid() else QColor(default)

    def clear_terminal(self):
        self.screen.reset()
        self.stream = pyte.ByteStream(self.screen)
        self.clear()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "screen"):
            metrics = self.fontMetrics()
            columns = max(20, self.viewport().width() // max(1, metrics.horizontalAdvance("M")))
            lines = max(3, self.viewport().height() // max(1, metrics.lineSpacing()))
            self.screen.resize(lines=lines, columns=columns)
            self.render()

    def keyPressEvent(self, event):
        modifiers = event.modifiers()
        if event.matches(QKeySequence.StandardKey.Copy) and self.textCursor().hasSelection():
            self.copy()
            return
        if event.matches(QKeySequence.StandardKey.Paste):
            self.paste_input()
            return
        if not self.can_send:
            super().keyPressEvent(event)
            return
        sequences = {Qt.Key.Key_Return: b"\r", Qt.Key.Key_Enter: b"\r", Qt.Key.Key_Backspace: b"\x7f",
                     Qt.Key.Key_Tab: b"\t", Qt.Key.Key_Escape: b"\x1b", Qt.Key.Key_Up: b"\x1b[A",
                     Qt.Key.Key_Down: b"\x1b[B", Qt.Key.Key_Right: b"\x1b[C", Qt.Key.Key_Left: b"\x1b[D",
                     Qt.Key.Key_Home: b"\x1b[H", Qt.Key.Key_End: b"\x1b[F", Qt.Key.Key_Delete: b"\x1b[3~",
                     Qt.Key.Key_PageUp: b"\x1b[5~", Qt.Key.Key_PageDown: b"\x1b[6~"}
        if modifiers & Qt.KeyboardModifier.ControlModifier and Qt.Key.Key_A <= event.key() <= Qt.Key.Key_Z:
            data = bytes([event.key() - Qt.Key.Key_A + 1])
        elif event.key() in sequences:
            data = sequences[event.key()]
        else:
            data = event.text().encode("utf-8")
            if modifiers & Qt.KeyboardModifier.AltModifier and data:
                data = b"\x1b" + data
        if data:
            self.input_ready.emit(data)
        event.accept()

    def inputMethodEvent(self, event):
        if self.can_send and event.commitString():
            self.input_ready.emit(event.commitString().encode("utf-8"))
        event.accept()

    def paste_input(self):
        if not self.can_send:
            return
        text = QApplication.clipboard().text()
        if not text:
            return
        if "\n" in text or "\r" in text or len(text) > 1024:
            answer = QMessageBox.warning(self, "Paste to console", "Pasting multiple lines may execute commands on the target. Continue?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        data = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r").encode("utf-8")
        self.input_ready.emit(data)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        copy = menu.addAction("Copy", self.copy)
        copy.setEnabled(self.textCursor().hasSelection())
        paste = menu.addAction("Paste", self.paste_input)
        paste.setEnabled(self.can_send)
        menu.exec(event.globalPos())


class ConsoleWindow(QDialog):
    error = Signal(str)
    visibility_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("NuWriter - Console")
        self.setWindowFlag(Qt.WindowType.WindowMinMaxButtonsHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setModal(False)
        self.resize(820, 480)
        self.setMinimumSize(480, 280)
        self.connection = SerialConnection(self)
        self.connection.received.connect(self.receive)
        self.connection.error.connect(self.show_error)
        self.connection.connected_changed.connect(self.update_state)
        self.device = ""
        self.baudrate = 115200
        layout = QVBoxLayout(self)
        settings = QHBoxLayout()
        settings.addWidget(QLabel("Console:"))
        self.ports = QComboBox()
        self.ports.setMinimumContentsLength(22)
        self.ports.setToolTip("Debug UART/VCOM port, not the CH341 reset-adapter port.")
        settings.addWidget(self.ports, 1)
        settings.addWidget(QLabel("Baud:"))
        self.baud = QComboBox()
        self.baud.addItems(["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"])
        self.baud.setCurrentText("115200")
        settings.addWidget(self.baud)
        refresh = QToolButton()
        refresh.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        refresh.setToolTip("Refresh serial ports")
        refresh.setAccessibleName("Refresh serial ports")
        refresh.clicked.connect(self.refresh_ports)
        settings.addWidget(refresh)
        self.open_button = QPushButton("Open")
        self.open_button.clicked.connect(self.toggle_connection)
        settings.addWidget(self.open_button)
        layout.addLayout(settings)
        actions = QHBoxLayout()
        self.status = QLabel("Disconnected")
        self.status.setWordWrap(True)
        actions.addWidget(self.status, 1)
        layout.addLayout(actions)
        self.terminal = TerminalView(self)
        self.terminal.input_ready.connect(self.connection.send)
        layout.addWidget(self.terminal, 1)
        self.pending_receive = bytearray()
        self.render_timer = QTimer(self)
        self.render_timer.setSingleShot(True)
        self.render_timer.setInterval(30)
        self.render_timer.timeout.connect(self.flush_receive)
        self.refresh_ports()

    def refresh_ports(self):
        selected = self.ports.currentData()
        self.ports.clear()
        try:
            for port in available_ports():
                description = port.description or "Serial port"
                self.ports.addItem(f"{port.device} - {description}", port.device)
                self.ports.setItemData(self.ports.count() - 1, description, Qt.ItemDataRole.ToolTipRole)
        except OSError as error:
            self.show_error(f"Cannot list console ports: {error}")
        if self.ports.count() == 0:
            self.ports.addItem("No serial ports", "")
        index = self.ports.findData(selected)
        if index >= 0:
            self.ports.setCurrentIndex(index)
        self.open_button.setEnabled(self.connection.connected or bool(self.ports.currentData()))

    def open_selected_port(self):
        device = self.ports.currentData()
        if not device:
            self.show_error("Select an available console serial port.")
            return
        baudrate = int(self.baud.currentText())
        if self.connection.connected and (self.device != device or self.baudrate != baudrate):
            answer = QMessageBox.warning(self, "Switch console port", f"Close {self.device} and open {device} at {baudrate} baud?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.connection.close()
        try:
            self.open_port(device, baudrate)
            self.terminal.setFocus()
        except (serial.SerialException, OSError, ValueError) as error:
            self.show_error(str(error))

    def showEvent(self, event):
        super().showEvent(event)
        self.visibility_changed.emit(True)

    def hideEvent(self, event):
        super().hideEvent(event)
        self.visibility_changed.emit(False)

    def open_port(self, device, baudrate=115200):
        if self.connection.connected:
            if self.device == device and self.baudrate == baudrate:
                return
            raise ValueError("Close the current console connection before switching ports.")
        self.connection.open(device, baudrate)
        if self.device != device:
            self.clear_output()
        self.device = device
        self.baudrate = baudrate
        self.setWindowTitle(f"NuWriter - Console - {device}")
        self.update_state(True)

    def receive(self, data):
        self.pending_receive.extend(data)
        if not self.render_timer.isActive():
            self.render_timer.start()

    def flush_receive(self):
        if self.pending_receive:
            data = bytes(self.pending_receive)
            self.pending_receive.clear()
            self.terminal.feed(data)

    def update_state(self, connected):
        self.terminal.can_send = connected
        self.open_button.setText("Close" if connected else "Open")
        self.open_button.setEnabled(connected or bool(self.ports.currentData()))
        self.ports.setEnabled(not connected)
        self.baud.setEnabled(not connected)
        self.status.setStyleSheet("")
        self.status.setText(f"{self.device or self.connection.device} - {self.baudrate} baud, 8N1" if connected else "Disconnected")

    def show_error(self, message):
        self.status.setText(f"Error: {message}")
        self.status.setStyleSheet("color: #c62828;")
        self.error.emit(message)

    def toggle_connection(self):
        if self.connection.connected:
            self.connection.close()
        else:
            self.open_selected_port()

    def save_output(self):
        self.flush_receive()
        filename, _ = QFileDialog.getSaveFileName(self, "Save console output", "console.log", "Log files (*.log);;All files (*)")
        if filename:
            try:
                Path(filename).write_text(self.terminal.toPlainText(), encoding="utf-8")
            except OSError as error:
                self.show_error(str(error))

    def clear_output(self):
        self.render_timer.stop()
        self.pending_receive.clear()
        self.terminal.clear_terminal()

    def closeEvent(self, event):
        self.connection.close()
        self.render_timer.stop()
        self.flush_receive()
        event.accept()

    def reject(self):
        self.close()