from __future__ import annotations
from typing import Optional
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap, QPainter, QColor, QPen
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget, QListWidgetItem,
    QLabel, QPushButton, QFrame, QAbstractItemView, QSizePolicy, QGroupBox,
    QFormLayout,
)
from ..utils.menu_bundle import MenuBundle, MenuPage, page_tim_image
from ..utils.gthtml import is_page_target

class MenuEditorWidget(QWidget):

    status_message = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bundle: Optional[MenuBundle] = None
        self._page_by_row: list[MenuPage] = []
        self._reload_callback = None
        self._current: Optional[MenuPage] = None
        self._show_hotspots = True

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(12)
        self.lbl_title = QLabel("Menu Editor")
        title_font = self.lbl_title.font()
        title_font.setPointSize(title_font.pointSize() + 2)
        title_font.setBold(True)
        self.lbl_title.setFont(title_font)
        head.addWidget(self.lbl_title)
        self.lbl_source = QLabel("Open MENU/MENU_HTM.ARC to begin")
        self.lbl_source.setStyleSheet("color: #888;")
        head.addWidget(self.lbl_source, stretch=1)
        self.btn_hotspots = QPushButton("Hotspots")
        self.btn_hotspots.setCheckable(True)
        self.btn_hotspots.setChecked(True)
        self.btn_hotspots.setToolTip("Draw hotspot rectangles on the preview")
        self.btn_hotspots.setProperty("class", "secondary")
        self.btn_hotspots.toggled.connect(self._toggle_hotspots)
        head.addWidget(self.btn_hotspots)
        self.btn_reload = QPushButton("Reload")
        self.btn_reload.setProperty("class", "secondary")
        self.btn_reload.clicked.connect(self._emit_reload_request)
        head.addWidget(self.btn_reload)
        root.addLayout(head)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)

        left = QWidget()
        left.setMinimumWidth(160)
        left.setMaximumWidth(260)
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(0, 0, 0, 0)
        left_l.setSpacing(4)
        lbl_pages = QLabel("Pages")
        lbl_pages.setStyleSheet("font-weight: 600;")
        left_l.addWidget(lbl_pages)
        self.page_list = QListWidget()
        self.page_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.page_list.setSpacing(1)
        self.page_list.currentRowChanged.connect(self._on_page_selected)
        left_l.addWidget(self.page_list, stretch=1)
        split.addWidget(left)

        right = QWidget()
        right_l = QHBoxLayout(right)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.setSpacing(10)

        prev_col = QVBoxLayout()
        prev_col.setSpacing(4)
        self.lbl_page_name = QLabel("")
        self.lbl_page_name.setStyleSheet("font-weight: 600;")
        prev_col.addWidget(self.lbl_page_name)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(400, 300)
        self.preview.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.preview.setStyleSheet(
            "background: #121212; border-radius: 6px; color: #666;"
        )
        self.preview.setFrameShape(QFrame.Shape.StyledPanel)
        self.preview.setText("Select a page")
        prev_col.addWidget(self.preview, stretch=1)

        self.lbl_bg = QLabel("")
        self.lbl_bg.setStyleSheet("color: #888; font-size: 11px;")
        prev_col.addWidget(self.lbl_bg)
        right_l.addLayout(prev_col, stretch=1)

        insp = QWidget()
        insp.setMinimumWidth(220)
        insp.setMaximumWidth(300)
        insp_l = QVBoxLayout(insp)
        insp_l.setContentsMargins(0, 0, 0, 0)
        insp_l.setSpacing(8)

        box_info = QGroupBox("Page")
        form = QFormLayout(box_info)
        form.setContentsMargins(10, 12, 10, 10)
        form.setSpacing(6)
        self.val_file = QLabel("—")
        self.val_bg = QLabel("—")
        self.val_counts = QLabel("—")
        for w in (self.val_file, self.val_bg, self.val_counts):
            w.setWordWrap(True)
            w.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow("File", self.val_file)
        form.addRow("Background", self.val_bg)
        form.addRow("Regions", self.val_counts)
        insp_l.addWidget(box_info)

        lbl_links = QLabel("Links & actions")
        lbl_links.setStyleSheet("font-weight: 600;")
        insp_l.addWidget(lbl_links)
        hint = QLabel("Double-click a page link to open it")
        hint.setStyleSheet("color: #888; font-size: 11px;")
        insp_l.addWidget(hint)

        self.link_list = QListWidget()
        self.link_list.setSpacing(1)
        self.link_list.itemDoubleClicked.connect(self._on_link_activated)
        insp_l.addWidget(self.link_list, stretch=1)

        right_l.addWidget(insp)
        split.addWidget(right)

        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([200, 700])
        root.addWidget(split, stretch=1)

    def set_reload_callback(self, cb) -> None:
        self._reload_callback = cb

    def _emit_reload_request(self) -> None:
        if self._reload_callback:
            self._reload_callback()

    def _toggle_hotspots(self, on: bool) -> None:
        self._show_hotspots = on
        if self._current is not None:
            self._show_page(self._current)

    def clear(self) -> None:
        self._bundle = None
        self._page_by_row = []
        self._current = None
        self.page_list.clear()
        self.link_list.clear()
        self.preview.setPixmap(QPixmap())
        self.preview.setText("Open MENU/MENU_HTM.ARC to begin")
        self.lbl_source.setText("No menu loaded")
        self.lbl_page_name.setText("")
        self.lbl_bg.setText("")
        self.val_file.setText("—")
        self.val_bg.setText("—")
        self.val_counts.setText("—")

    def load_bundle(self, bundle: MenuBundle) -> None:
        self._bundle = bundle
        self._page_by_row = list(bundle.pages)
        self.page_list.clear()
        for page in self._page_by_row:
            item = QListWidgetItem(page.title)
            item.setToolTip(page.name)
            self.page_list.addItem(item)
        self.lbl_source.setText(
            f"{bundle.source_label}   ·   {len(bundle.pages)} pages"
        )
        if self._page_by_row:
            self.page_list.setCurrentRow(0)
        else:
            self.preview.setText("No GTHTML pages found")
            self.link_list.clear()

    def _on_page_selected(self, row: int) -> None:
        if row < 0 or row >= len(self._page_by_row):
            return
        self._show_page(self._page_by_row[row])

    def _show_page(self, page: MenuPage) -> None:
        self._current = page
        self.lbl_page_name.setText(page.title)

        img = page_tim_image(self._bundle, page) if self._bundle else None
        pix = QPixmap()
        if img is not None:
            try:
                if img.mode != "RGBA":
                    img = img.convert("RGBA")
                data = img.tobytes("raw", "RGBA")
                qimg = QImage(
                    data, img.width, img.height,
                    img.width * 4, QImage.Format.Format_RGBA8888,
                ).copy()
                if self._show_hotspots:
                    qimg = self._draw_hotspots(qimg, page)
                pix = QPixmap.fromImage(qimg)
            except Exception as e:
                self.preview.setPixmap(QPixmap())
                self.preview.setText(f"Preview error:\n{e}")
                pix = QPixmap()

        if not pix.isNull():
            scaled = pix.scaled(
                self.preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.preview.setPixmap(scaled)
            self.preview.setText("")
        else:
            self.preview.setPixmap(QPixmap())
            self.preview.setText(
                f"{page.title}\n\nNo background TIM\n({page.tim_name or '—'})"
            )

        bg = page.parsed.get("background_tim") or page.tim_name or "—"
        self.lbl_bg.setText(page.name)
        self.val_file.setText(page.name)
        self.val_bg.setText(str(bg))
        n_hs = len(page.parsed.get("hotspots") or [])
        n_wg = len(page.parsed.get("widgets") or [])
        self.val_counts.setText(f"{n_hs} hotspots · {n_wg} widgets")

        self.link_list.clear()
        seen = set()
        for h in page.parsed.get("hotspots") or []:
            self._add_link(h.get("target") or "", seen, h)
        for w in page.parsed.get("widgets") or []:
            self._add_link(w.get("target") or "", seen, None)

    def _add_link(self, target: str, seen: set, hotspot: dict | None) -> None:
        if not target or target in seen:
            return
        seen.add(target)
        if is_page_target(target):
            label = f"→  {target}"
        else:
            label = f"⚡  {target}"
        if hotspot:
            label += f"   ({hotspot.get('x0')},{hotspot.get('y0')})"
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, target)
        item.setToolTip(target)
        self.link_list.addItem(item)

    def _draw_hotspots(self, qimg: QImage, page: MenuPage) -> QImage:
        out = QImage(qimg)
        painter = QPainter(out)
        pen = QPen(QColor(255, 80, 80, 200))
        pen.setWidth(2)
        painter.setPen(pen)
        for h in page.parsed.get("hotspots") or []:
            x0, y0 = int(h.get("x0", 0)), int(h.get("y0", 0))
            x1, y1 = int(h.get("x1", 0)), int(h.get("y1", 0))
            painter.drawRect(x0, y0, max(1, x1 - x0), max(1, y1 - y0))
        pen2 = QPen(QColor(80, 180, 255, 220))
        pen2.setWidth(2)
        painter.setPen(pen2)
        for w in page.parsed.get("widgets") or []:
            a, b, c = int(w.get("a", 0)), int(w.get("b", 0)), int(w.get("c", 12))
            r = max(6, min(c, 24))
            painter.drawEllipse(a - r // 2, b - r // 2, r, r)
        painter.end()
        return out

    def _on_link_activated(self, item: QListWidgetItem) -> None:
        target = item.data(Qt.ItemDataRole.UserRole)
        if not target or not is_page_target(str(target)):
            return
        key = _basename_key(str(target))
        for i, page in enumerate(self._page_by_row):
            if _basename_key(page.name) == key:
                self.page_list.setCurrentRow(i)
                return

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._current is not None:
            self._show_page(self._current)

def _basename_key(name: str) -> str:
    base = name.replace("\\", "/").split("/")[-1]
    if "." in base:
        base = base.rsplit(".", 1)[0]
    return base.lower().lstrip("_")
