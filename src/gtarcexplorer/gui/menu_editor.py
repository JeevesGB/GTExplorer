"""Menu Editor canvas — browse GTHTML pages with TIM backgrounds (phase 1)."""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget, QListWidgetItem,
    QLabel, QTextEdit, QPushButton, QFrame, QAbstractItemView, QSizePolicy,
)

from ..utils.menu_bundle import MenuBundle, MenuPage, page_tim_image
from ..utils.gthtml import is_page_target, format_gthtml_preview


class MenuEditorWidget(QWidget):
    """Simple three-pane menu browser: pages | preview | links."""

    status_message = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bundle: Optional[MenuBundle] = None
        self._page_by_row: list[MenuPage] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        head = QHBoxLayout()
        self.lbl_source = QLabel("No menu bundle loaded")
        self.lbl_source.setProperty("class", "muted")
        head.addWidget(self.lbl_source, stretch=1)
        self.btn_reload = QPushButton("Reload")
        self.btn_reload.setProperty("class", "secondary")
        self.btn_reload.clicked.connect(self._emit_reload_request)
        head.addWidget(self.btn_reload)
        root.addLayout(head)

        split = QSplitter(Qt.Orientation.Horizontal)

        # --- Pages ---
        left = QWidget()
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(0, 0, 0, 0)
        left_l.addWidget(QLabel("Pages"))
        self.page_list = QListWidget()
        self.page_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.page_list.currentRowChanged.connect(self._on_page_selected)
        left_l.addWidget(self.page_list, stretch=1)
        split.addWidget(left)

        # --- Preview ---
        center = QWidget()
        center_l = QVBoxLayout(center)
        center_l.setContentsMargins(0, 0, 0, 0)
        center_l.addWidget(QLabel("Preview"))
        self.preview = QLabel("Open MENU_HTM.ARC\n(or the MENU folder)")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(320, 240)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.preview.setStyleSheet("background:#1a1a1a; color:#888; border-radius:4px;")
        self.preview.setFrameShape(QFrame.Shape.StyledPanel)
        center_l.addWidget(self.preview, stretch=1)
        self.lbl_bg = QLabel("")
        self.lbl_bg.setProperty("class", "muted")
        center_l.addWidget(self.lbl_bg)
        split.addWidget(center)

        # --- Inspector ---
        right = QWidget()
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.addWidget(QLabel("Links & actions"))
        self.link_list = QListWidget()
        self.link_list.itemDoubleClicked.connect(self._on_link_activated)
        right_l.addWidget(self.link_list, stretch=1)
        right_l.addWidget(QLabel("Details"))
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(180)
        right_l.addWidget(self.details)
        split.addWidget(right)

        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        split.setSizes([200, 480, 240])
        root.addWidget(split, stretch=1)

        self._reload_callback = None

    def set_reload_callback(self, cb) -> None:
        self._reload_callback = cb

    def _emit_reload_request(self) -> None:
        if self._reload_callback:
            self._reload_callback()

    def clear(self) -> None:
        self._bundle = None
        self._page_by_row = []
        self.page_list.clear()
        self.link_list.clear()
        self.details.clear()
        self.preview.setPixmap(QPixmap())
        self.preview.setText("Open MENU_HTM.ARC\n(or the MENU folder)")
        self.lbl_source.setText("No menu bundle loaded")
        self.lbl_bg.setText("")

    def load_bundle(self, bundle: MenuBundle) -> None:
        self._bundle = bundle
        self._page_by_row = list(bundle.pages)
        self.page_list.clear()
        for page in self._page_by_row:
            item = QListWidgetItem(page.title)
            item.setToolTip(page.name)
            self.page_list.addItem(item)
        self.lbl_source.setText(
            f"{bundle.source_label}  —  {len(bundle.pages)} page(s)"
        )
        if self._page_by_row:
            self.page_list.setCurrentRow(0)
        else:
            self.preview.setText("No GTHTML pages found in this archive")
            self.details.clear()
            self.link_list.clear()

    def _on_page_selected(self, row: int) -> None:
        if row < 0 or row >= len(self._page_by_row):
            return
        page = self._page_by_row[row]
        self._show_page(page)

    def _show_page(self, page: MenuPage) -> None:
        # Preview image
        img = page_tim_image(self._bundle, page) if self._bundle else None
        if img is not None:
            try:
                if img.mode != "RGBA":
                    img = img.convert("RGBA")
                data = img.tobytes("raw", "RGBA")
                qimg = QImage(
                    data,
                    img.width,
                    img.height,
                    img.width * 4,
                    QImage.Format.Format_RGBA8888,
                )
                pix = QPixmap.fromImage(qimg.copy())
                scaled = pix.scaled(
                    self.preview.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.preview.setPixmap(scaled)
                self.preview.setText("")
            except Exception as e:
                self.preview.setPixmap(QPixmap())
                self.preview.setText(f"Preview error:\n{e}")
        else:
            self.preview.setPixmap(QPixmap())
            self.preview.setText(
                f"{page.title}\n\nNo background TIM bound\n"
                f"({page.tim_name or '—'})"
            )

        bg = page.parsed.get("background_tim") or page.tim_name or "—"
        self.lbl_bg.setText(f"Background: {bg}   ·   File: {page.name}")

        # Links
        self.link_list.clear()
        seen = set()
        for h in page.parsed.get("hotspots") or []:
            t = h.get("target") or ""
            if not t or t in seen:
                continue
            seen.add(t)
            kind = "Page" if is_page_target(t) else "Action"
            item = QListWidgetItem(f"[{kind}]  {t}")
            item.setData(Qt.ItemDataRole.UserRole, t)
            self.link_list.addItem(item)
        for w in page.parsed.get("widgets") or []:
            t = w.get("target") or ""
            if not t or t in seen:
                continue
            seen.add(t)
            kind = "Page" if is_page_target(t) else "Action"
            item = QListWidgetItem(f"[{kind}]  {t}")
            item.setData(Qt.ItemDataRole.UserRole, t)
            self.link_list.addItem(item)

        self.details.setPlainText(format_gthtml_preview(page.parsed))

    def _on_link_activated(self, item: QListWidgetItem) -> None:
        target = item.data(Qt.ItemDataRole.UserRole)
        if not target or not is_page_target(str(target)):
            return
        # Navigate to page by basename
        key = str(target).lower().replace(".htm", "").replace(".html", "")
        for i, page in enumerate(self._page_by_row):
            if _basename_key(page.name) == key or page.name.lower() == str(target).lower():
                self.page_list.setCurrentRow(i)
                return

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        row = self.page_list.currentRow()
        if 0 <= row < len(self._page_by_row):
            # Re-scale preview
            self._show_page(self._page_by_row[row])


def _basename_key(name: str) -> str:
    base = name.replace("\\", "/").split("/")[-1]
    if "." in base:
        base = base.rsplit(".", 1)[0]
    return base.lower().lstrip("_")
