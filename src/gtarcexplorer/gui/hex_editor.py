"""Scrollable hex viewer / light editor for archive entry bytes."""
from __future__ import annotations

from typing import Optional

try:
    from PyQt6.QtCore import Qt, QSize, QRect, pyqtSignal
    from PyQt6.QtGui import (
        QPainter, QColor, QFont, QFontMetrics, QKeyEvent, QMouseEvent,
        QWheelEvent, QPen, QClipboard,
    )
    from PyQt6.QtWidgets import (
        QAbstractScrollArea, QWidget, QApplication, QSizePolicy,
        QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QCheckBox,
    )
except ImportError:
    from PyQt5.QtCore import Qt, QSize, QRect, pyqtSignal
    from PyQt5.QtGui import (
        QPainter, QColor, QFont, QFontMetrics, QKeyEvent, QMouseEvent,
        QWheelEvent, QPen, QClipboard,
    )
    from PyQt5.QtWidgets import (
        QAbstractScrollArea, QWidget, QApplication, QSizePolicy,
        QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QCheckBox,
    )


class HexEditorWidget(QAbstractScrollArea):
    """Virtualized hex view: offset | hex bytes | ASCII.

    Designed for large buffers (only visible rows are painted).
    Optional single-byte edit when ``editable`` is True.
    """

    data_changed = pyqtSignal()
    cursor_moved = pyqtSignal(int)  # byte offset

    BYTES_PER_ROW = 16

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("hexEditor")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)

        self._data = bytearray()
        self._editable = False
        self._cursor = 0
        self._anchor = 0  # selection start
        self._bytes_per_row = self.BYTES_PER_ROW

        self._font = QFont("Consolas", 10)
        if not QFontMetrics(self._font).horizontalAdvance("0"):
            self._font = QFont("Courier New", 10)
        self.setFont(self._font)

        self._bg = QColor("#1E1D1E")
        self._fg = QColor("#FFFFFA")
        self._addr_fg = QColor("#888888")
        self._ascii_fg = QColor("#9acd9a")
        self._sel_bg = QColor("#D42622")
        self._sel_fg = QColor("#FFFFFF")
        self._cursor_bg = QColor("#3C3C3C")
        self._grid = QColor("#2A2929")

        self.viewport().setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self._recalc_metrics()
        self._update_scroll()

    # ----- public API -----

    def set_data(self, data: bytes | bytearray | None, *, editable: bool = False) -> None:
        self._data = bytearray(data or b"")
        self._editable = bool(editable)
        self._cursor = 0
        self._anchor = 0
        self._update_scroll()
        self.viewport().update()
        self.cursor_moved.emit(0)

    def data(self) -> bytes:
        return bytes(self._data)

    def clear(self) -> None:
        self.set_data(b"")

    def set_editable(self, editable: bool) -> None:
        self._editable = bool(editable)

    def goto_offset(self, offset: int) -> None:
        if not self._data:
            return
        offset = max(0, min(int(offset), len(self._data) - 1))
        self._cursor = offset
        self._anchor = offset
        self._ensure_cursor_visible()
        self.viewport().update()
        self.cursor_moved.emit(self._cursor)

    def selected_range(self) -> tuple[int, int]:
        a, b = self._anchor, self._cursor
        return (min(a, b), max(a, b))

    # ----- layout metrics -----

    def _recalc_metrics(self) -> None:
        fm = QFontMetrics(self._font)
        self._char_w = max(fm.horizontalAdvance("0"), 1)
        self._row_h = max(fm.height() + 4, 16)
        # columns: "00000000  " + 16*3 hex + "  " + 16 ascii
        self._addr_chars = 8
        self._gap1 = 2
        self._gap2 = 2
        self._hex_chars = self._bytes_per_row * 3  # "XX "
        self._ascii_chars = self._bytes_per_row
        total_chars = (
            self._addr_chars + self._gap1 + self._hex_chars + self._gap2 + self._ascii_chars
        )
        self._content_w = total_chars * self._char_w + 16

    def _row_count(self) -> int:
        if not self._data:
            return 1
        return (len(self._data) + self._bytes_per_row - 1) // self._bytes_per_row

    def _update_scroll(self) -> None:
        self._recalc_metrics()
        rows = self._row_count()
        self.verticalScrollBar().setRange(0, max(0, rows - 1))
        self.verticalScrollBar().setPageStep(max(1, self.viewport().height() // self._row_h))
        self.verticalScrollBar().setSingleStep(1)
        self.horizontalScrollBar().setRange(0, max(0, self._content_w - self.viewport().width()))
        self.horizontalScrollBar().setPageStep(self.viewport().width())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_scroll()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        self.viewport().update()

    # ----- painting -----

    def paintEvent(self, event) -> None:
        painter = QPainter(self.viewport())
        painter.fillRect(self.viewport().rect(), self._bg)
        painter.setFont(self._font)

        fm = QFontMetrics(self._font)
        vp = self.viewport()
        first_row = self.verticalScrollBar().value()
        x_off = -self.horizontalScrollBar().value()
        rows_visible = vp.height() // self._row_h + 2
        total_rows = self._row_count()
        sel_lo, sel_hi = self.selected_range()
        has_sel = sel_lo != sel_hi

        for i in range(rows_visible):
            row = first_row + i
            if row >= total_rows:
                break
            y = i * self._row_h
            base = row * self._bytes_per_row

            # address
            addr = f"{base:08X}"
            painter.setPen(self._addr_fg)
            painter.drawText(
                x_off + 8,
                y,
                self._addr_chars * self._char_w,
                self._row_h,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                addr,
            )

            hex_x0 = x_off + 8 + (self._addr_chars + self._gap1) * self._char_w
            ascii_x0 = hex_x0 + (self._hex_chars + self._gap2) * self._char_w

            for col in range(self._bytes_per_row):
                off = base + col
                if off >= len(self._data):
                    break
                b = self._data[off]
                selected = has_sel and sel_lo <= off <= sel_hi
                is_cursor = (not has_sel) and off == self._cursor

                hx = f"{b:02X}"
                hx_x = hex_x0 + col * 3 * self._char_w
                cell = QRect(hx_x, y, 2 * self._char_w, self._row_h)
                if selected:
                    painter.fillRect(cell.adjusted(-1, 1, 1, -1), self._sel_bg)
                    painter.setPen(self._sel_fg)
                elif is_cursor:
                    painter.fillRect(cell.adjusted(-1, 1, 1, -1), self._cursor_bg)
                    painter.setPen(self._fg)
                else:
                    painter.setPen(self._fg)
                painter.drawText(cell, Qt.AlignmentFlag.AlignCenter, hx)

                ch = chr(b) if 32 <= b < 127 else "."
                acell = QRect(ascii_x0 + col * self._char_w, y, self._char_w, self._row_h)
                if selected:
                    painter.fillRect(acell, self._sel_bg)
                    painter.setPen(self._sel_fg)
                elif is_cursor:
                    painter.fillRect(acell, self._cursor_bg)
                    painter.setPen(self._ascii_fg)
                else:
                    painter.setPen(self._ascii_fg)
                painter.drawText(acell, Qt.AlignmentFlag.AlignCenter, ch)

        painter.end()

    # ----- interaction -----

    def _offset_at_pos(self, pos) -> Optional[int]:
        x = pos.x() + self.horizontalScrollBar().value()
        y = pos.y()
        row = self.verticalScrollBar().value() + y // self._row_h
        if row < 0:
            return None
        base = row * self._bytes_per_row
        hex_x0 = 8 + (self._addr_chars + self._gap1) * self._char_w
        ascii_x0 = hex_x0 + (self._hex_chars + self._gap2) * self._char_w

        if hex_x0 <= x < hex_x0 + self._hex_chars * self._char_w:
            col = (x - hex_x0) // (3 * self._char_w)
            col = max(0, min(self._bytes_per_row - 1, int(col)))
            off = base + col
        elif ascii_x0 <= x < ascii_x0 + self._ascii_chars * self._char_w:
            col = (x - ascii_x0) // self._char_w
            col = max(0, min(self._bytes_per_row - 1, int(col)))
            off = base + col
        else:
            return None
        if off >= len(self._data):
            return max(0, len(self._data) - 1) if self._data else None
        return off

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            try:
                pos = event.position().toPoint()
            except AttributeError:
                pos = event.pos()
            off = self._offset_at_pos(pos)
            if off is not None:
                self._cursor = off
                mods = event.modifiers()
                if not (mods & Qt.KeyboardModifier.ShiftModifier):
                    self._anchor = off
                self._ensure_cursor_visible()
                self.viewport().update()
                self.cursor_moved.emit(self._cursor)
                self.setFocus()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            try:
                pos = event.position().toPoint()
            except AttributeError:
                pos = event.pos()
            off = self._offset_at_pos(pos)
            if off is not None and off != self._cursor:
                self._cursor = off
                self._ensure_cursor_visible()
                self.viewport().update()
                self.cursor_moved.emit(self._cursor)
        super().mouseMoveEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        mods = event.modifiers()
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)

        def move(delta: int) -> None:
            if not self._data:
                return
            self._cursor = max(0, min(len(self._data) - 1, self._cursor + delta))
            if not shift:
                self._anchor = self._cursor
            self._ensure_cursor_visible()
            self.viewport().update()
            self.cursor_moved.emit(self._cursor)

        if key == Qt.Key.Key_Left:
            move(-1)
            return
        if key == Qt.Key.Key_Right:
            move(1)
            return
        if key == Qt.Key.Key_Up:
            move(-self._bytes_per_row)
            return
        if key == Qt.Key.Key_Down:
            move(self._bytes_per_row)
            return
        if key == Qt.Key.Key_PageUp:
            page = max(1, self.viewport().height() // self._row_h)
            move(-page * self._bytes_per_row)
            return
        if key == Qt.Key.Key_PageDown:
            page = max(1, self.viewport().height() // self._row_h)
            move(page * self._bytes_per_row)
            return
        if key == Qt.Key.Key_Home:
            move(-self._cursor if not (mods & Qt.KeyboardModifier.ControlModifier) else -self._cursor)
            if mods & Qt.KeyboardModifier.ControlModifier:
                self._cursor = 0
                if not shift:
                    self._anchor = 0
                self._ensure_cursor_visible()
                self.viewport().update()
                self.cursor_moved.emit(0)
            else:
                row_base = (self._cursor // self._bytes_per_row) * self._bytes_per_row
                self._cursor = row_base
                if not shift:
                    self._anchor = self._cursor
                self.viewport().update()
                self.cursor_moved.emit(self._cursor)
            return
        if key == Qt.Key.Key_End:
            if mods & Qt.KeyboardModifier.ControlModifier:
                self._cursor = max(0, len(self._data) - 1)
            else:
                row_base = (self._cursor // self._bytes_per_row) * self._bytes_per_row
                self._cursor = min(len(self._data) - 1, row_base + self._bytes_per_row - 1)
            if not shift:
                self._anchor = self._cursor
            self._ensure_cursor_visible()
            self.viewport().update()
            self.cursor_moved.emit(self._cursor)
            return
        if key == Qt.Key.Key_C and mods & Qt.KeyboardModifier.ControlModifier:
            self._copy_selection()
            return

        # Hex nibble edit
        if self._editable and self._data and event.text():
            ch = event.text().upper()
            if len(ch) == 1 and ch in "0123456789ABCDEF":
                val = int(ch, 16)
                # simple: replace low nibble then high on second key — use full byte from two keys
                # For simplicity: type two hex digits; store pending nibble
                pending = getattr(self, "_pending_nibble", None)
                if pending is None:
                    self._pending_nibble = val
                else:
                    self._data[self._cursor] = ((pending & 0xF) << 4) | (val & 0xF)
                    self._pending_nibble = None
                    self.data_changed.emit()
                    if self._cursor < len(self._data) - 1:
                        self._cursor += 1
                        self._anchor = self._cursor
                    self._ensure_cursor_visible()
                    self.viewport().update()
                    self.cursor_moved.emit(self._cursor)
                return

        super().keyPressEvent(event)

    def _copy_selection(self) -> None:
        if not self._data:
            return
        lo, hi = self.selected_range()
        if lo == hi:
            lo, hi = self._cursor, self._cursor
        chunk = self._data[lo : hi + 1]
        text = " ".join(f"{b:02X}" for b in chunk)
        QApplication.clipboard().setText(text)

    def _ensure_cursor_visible(self) -> None:
        if not self._data:
            return
        row = self._cursor // self._bytes_per_row
        sb = self.verticalScrollBar()
        first = sb.value()
        visible = max(1, self.viewport().height() // self._row_h)
        if row < first:
            sb.setValue(row)
        elif row >= first + visible:
            sb.setValue(row - visible + 1)

    def sizeHint(self) -> QSize:
        return QSize(640, 320)


class HexEditorPage(QWidget):
    """Full canvas page: toolbar + HexEditorWidget for a selected entry."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("hexEditorPage")
        self._entry_index = None
        self._label = ""

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        self.info = QLabel("Select an archive entry to inspect its bytes.")
        self.info.setObjectName("hexPageInfo")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.offset_label = QLabel("Offset: —")
        self.offset_label.setObjectName("hexOffsetLabel")
        bar.addWidget(self.offset_label)

        self.size_label = QLabel("")
        self.size_label.setObjectName("hexOffsetLabel")
        bar.addWidget(self.size_label)
        bar.addStretch(1)

        self.goto_edit = QLineEdit()
        self.goto_edit.setPlaceholderText("Go to offset (hex)")
        self.goto_edit.setFixedWidth(140)
        self.goto_edit.setClearButtonEnabled(True)
        bar.addWidget(self.goto_edit)

        self.btn_goto = QPushButton("Go")
        self.btn_goto.setProperty("class", "secondary")
        self.btn_goto.setFixedWidth(40)
        bar.addWidget(self.btn_goto)

        self.chk_editable = QCheckBox("Allow edit")
        self.chk_editable.setToolTip("Type hex digits to change bytes (not written back until you save the entry)")
        bar.addWidget(self.chk_editable)

        lay.addLayout(bar)

        self.editor = HexEditorWidget()
        self.editor.set_editable(False)
        lay.addWidget(self.editor, stretch=1)

        self.editor.cursor_moved.connect(self._on_cursor)
        self.btn_goto.clicked.connect(self._goto)
        self.goto_edit.returnPressed.connect(self._goto)
        self.chk_editable.toggled.connect(lambda on: self.editor.set_editable(on))

    def _on_cursor(self, offset: int) -> None:
        self.offset_label.setText(f"Offset: {offset:08X}  ({offset:,})")

    def _goto(self) -> None:
        raw = (self.goto_edit.text() or "").strip().lower().replace("0x", "")
        if not raw:
            return
        try:
            off = int(raw, 16)
        except ValueError:
            try:
                off = int(raw, 10)
            except ValueError:
                return
        self.editor.goto_offset(off)

    def load_entry(self, data: bytes | None, *, label: str = "", index=None) -> None:
        data = data or b""
        self._entry_index = index
        self._label = label or ""
        self.editor.set_data(data, editable=self.chk_editable.isChecked())
        n = len(data)
        title = self._label or "(no selection)"
        if index is not None:
            self.info.setText(f"#{index}  •  {title}  •  {n:,} bytes")
        else:
            self.info.setText(f"{title}  •  {n:,} bytes" if title else "Select an archive entry to inspect its bytes.")
        self.size_label.setText(f"Size: {n:,} B" if n else "")
        self.offset_label.setText("Offset: 00000000" if n else "Offset: —")

    def clear(self) -> None:
        self.load_entry(b"")
