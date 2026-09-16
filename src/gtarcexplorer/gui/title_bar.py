"""Custom frameless title bar for GTExplorer."""
from __future__ import annotations

try:
    from PyQt6.QtCore import Qt, QPoint, QSize, pyqtSignal
    from PyQt6.QtGui import QIcon, QMouseEvent
    from PyQt6.QtWidgets import (
        QWidget, QHBoxLayout, QLabel, QToolButton, QSizePolicy,
    )
except ImportError:
    from PyQt5.QtCore import Qt, QPoint, QSize, pyqtSignal
    from PyQt5.QtGui import QIcon, QMouseEvent
    from PyQt5.QtWidgets import (
        QWidget, QHBoxLayout, QLabel, QToolButton, QSizePolicy,
    )


class TitleBar(QWidget):
    """Draggable title bar with min / max / close and optional theme toggle."""

    theme_toggled = pyqtSignal()
    double_clicked = pyqtSignal()

    def __init__(self, parent=None, title: str = "GTExplorer"):
        super().__init__(parent)
        self.setObjectName("customTitleBar")
        self.setFixedHeight(40)
        self._title = title

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 8, 0)
        lay.setSpacing(4)

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(22, 22)
        self.icon_label.setScaledContents(True)
        lay.addWidget(self.icon_label)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("titleBarLabel")
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        font = self.title_label.font()
        font.setPointSize(10)
        font.setBold(True)
        self.title_label.setFont(font)
        lay.addWidget(self.title_label, stretch=1)

        def _btn(text: str, name: str, tip: str) -> QToolButton:
            b = QToolButton()
            b.setText(text)
            b.setObjectName(name)
            b.setToolTip(tip)
            b.setFixedSize(42, 32)
            b.setAutoRaise(True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            return b

        self.btn_theme = _btn("◐", "titleThemeBtn", "Toggle light / dark theme")
        self.btn_min = _btn("—", "titleMinBtn", "Minimize")
        self.btn_max = _btn("□", "titleMaxBtn", "Maximize")
        self.btn_close = _btn("✕", "titleCloseBtn", "Close")

        lay.addWidget(self.btn_theme)
        lay.addWidget(self.btn_min)
        lay.addWidget(self.btn_max)
        lay.addWidget(self.btn_close)

        self.btn_theme.clicked.connect(self.theme_toggled.emit)
        self.btn_min.clicked.connect(self._minimize)
        self.btn_max.clicked.connect(self._toggle_max)
        self.btn_close.clicked.connect(self._close)

    def set_window_icon(self, icon: QIcon) -> None:
        if icon.isNull():
            return
        pix = icon.pixmap(QSize(22, 22))
        if not pix.isNull():
            self.icon_label.setPixmap(pix)

    def set_title(self, text: str) -> None:
        self._title = text
        self.title_label.setText(text)

    def update_max_button(self, maximized: bool) -> None:
        self.btn_max.setText("❐" if maximized else "□")
        self.btn_max.setToolTip("Restore" if maximized else "Maximize")

    def _window(self):
        return self.window()

    def _minimize(self) -> None:
        w = self._window()
        if w is not None:
            w.showMinimized()

    def _toggle_max(self) -> None:
        w = self._window()
        if w is None:
            return
        if w.isMaximized():
            w.showNormal()
        else:
            w.showMaximized()
        self.update_max_button(w.isMaximized())

    def _close(self) -> None:
        w = self._window()
        if w is not None:
            w.close()

    def _start_system_move(self) -> bool:
        w = self._window()
        if w is None:
            return False
        try:
            wh = w.windowHandle()
            if wh is not None and hasattr(wh, "startSystemMove"):
                return bool(wh.startSystemMove())
        except Exception:
            pass
        return False

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._start_system_move():
                event.accept()
                return
            w = self._window()
            if w is not None:
                try:
                    self._drag_pos = event.globalPosition().toPoint() - w.frameGeometry().topLeft()
                except AttributeError:
                    self._drag_pos = event.globalPos() - w.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        drag = getattr(self, "_drag_pos", None)
        if drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            w = self._window()
            if w is not None and not w.isMaximized():
                try:
                    w.move(event.globalPosition().toPoint() - drag)
                except AttributeError:
                    w.move(event.globalPos() - drag)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_max()
            self.double_clicked.emit()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)
