from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QImage, QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QColorDialog, QComboBox,
    QDialog, QDoubleSpinBox, QFileDialog, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QScrollArea,
    QSlider, QSplitter, QVBoxLayout, QWidget,
)

from ..utils.ctex import (
    RGBA,
    collect_palette_usage,
    ctex_palette_count,
    decode_ctex,
    duplicate_palette_set,
    export_palettes_as_bmp,
    parse_ctex_header,
    rank_body_cluts,
    read_clut,
    read_palette_set,
    recolor_clut_towards,
    shift_clut_hue,
    write_clut,
    write_palette_set,
)


def _qcolor(c: RGBA) -> QColor:
    r, g, b, a = c[:4]
    return QColor(int(r), int(g), int(b), int(a if a is not None else 255))


def _rgba(qc: QColor) -> RGBA:
    return (qc.red(), qc.green(), qc.blue(), qc.alpha())


def _clut_strip_pixmap(colours: Sequence[RGBA], w: int = 128, h: int = 18) -> QPixmap:
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    n = max(1, len(colours))
    for x in range(w):
        i = min(n - 1, x * n // w)
        r, g, b, a = colours[i][:4]
        if a < 8:
            on = (x // 4) & 1
            r = g = b = 200 if on else 140
            a = 255
        col = QColor(int(r), int(g), int(b), int(a))
        for y in range(h):
            img.setPixelColor(x, y, col)
    return QPixmap.fromImage(img)


class SwatchButton(QPushButton):
    colourChanged = pyqtSignal(int, int, object)  # material_ci, index, colour

    def __init__(self, index: int, colour: RGBA, material_ci: int = 0, parent=None):
        super().__init__(parent)
        self.index = index
        self.material_ci = material_ci
        self._colour = colour
        self.setFixedSize(28, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_style()
        self.clicked.connect(self._pick)

    def colour(self) -> RGBA:
        return self._colour

    def set_colour(self, colour: RGBA) -> None:
        self._colour = colour
        self._apply_style()

    def _apply_style(self) -> None:
        r, g, b, a = self._colour[:4]
        border = "#666" if a > 8 else "#c0392b"
        self.setToolTip(f"#{r:02X}{g:02X}{b:02X}  index {self.index}")
        self.setStyleSheet(
            f"QPushButton {{ background-color: rgba({r},{g},{b},{max(a, 40)});"
            f" border: 1px solid {border}; border-radius: 4px; }}"
            f"QPushButton:hover {{ border: 2px solid #fff; }}"
        )

    def _pick(self) -> None:
        dlg = QColorDialog(_qcolor(self._colour), self)
        dlg.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel, False)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        col = _rgba(dlg.currentColor())
        if self.index == 0 and col[0] < 8 and col[1] < 8 and col[2] < 8:
            col = (0, 0, 0, 0)
        else:
            col = (col[0], col[1], col[2], 255)
        self.set_colour(col)
        self.colourChanged.emit(self.material_ci, self.index, col)


class PaletteEditorDialog(QDialog):
    def __init__(
        self,
        ctex_data: bytes,
        parent=None,
        colour_index: int = 0,
        colour_names: Optional[Sequence[str]] = None,
        on_preview: Optional[Callable[[bytes], None]] = None,
        on_highlight: Optional[Callable[[Optional[Set[int]]], None]] = None,
        tex_entry_index: Optional[int] = None,
        archive=None,
        car_model=None,
        lod_index: int = 0,
    ):
        super().__init__(parent)
        self.setWindowTitle("Car colour / palette editor")
        self.setMinimumSize(820, 560)

        self._original = bytes(ctex_data)
        self._data = bytearray(ctex_data)
        self._on_preview = on_preview
        self._on_highlight = on_highlight
        self._live = True
        self._colour_names = list(colour_names or [])
        self._tex_entry_index = tex_entry_index
        self._archive = archive
        self._suppress = False
        self._material_swatch_rows: Dict[int, List[SwatchButton]] = {}
        self._target_rgb: Tuple[int, int, int] = (180, 30, 30)
        self._car_model = car_model
        self._lod_index = int(lod_index or 0)
        self._usage = collect_palette_usage(car_model, self._lod_index) if car_model else {}

        hdr = parse_ctex_header(self._data)
        self._name = hdr.get("name") or ""

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(60)
        self._preview_timer.timeout.connect(self._emit_preview_now)

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(16, 16, 16, 16)

        # --- Paint job header ---
        row = QHBoxLayout()
        row.addWidget(QLabel("Paint job"))
        self.paint_combo = QComboBox()
        self.paint_combo.setObjectName("paintCombo")
        self.paint_combo.setMinimumWidth(180)
        self._refill_paint_combo(colour_index)
        self.paint_combo.currentIndexChanged.connect(self._on_paint_changed)
        row.addWidget(self.paint_combo, stretch=1)
        self.btn_dup = QPushButton("Duplicate")
        self.btn_dup.setProperty("class", "secondary")
        self.btn_dup.setToolTip("Copy this paint to a new slot, then edit the copy")
        self.btn_dup.clicked.connect(self._duplicate_paint)
        row.addWidget(self.btn_dup)
        root.addLayout(row)

        if self._name:
            sub = QLabel(f"Texture: {self._name}")
            sub.setProperty("class", "muted")
            sub.setStyleSheet("color:#888;")
            root.addWidget(sub)

        # ================= Three-panel inspector =================
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setObjectName("paletteSplitter")

        # ---- Left: material list ----
        left = QWidget()
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(0, 0, 0, 0)
        left_l.setSpacing(6)
        left_l.addWidget(QLabel("Materials"))
        self.clut_list = QListWidget()
        self.clut_list.setObjectName("clutList")
        # Checkbox per material — clearer multi-select than shift-click only
        self.clut_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.clut_list.itemChanged.connect(self._on_item_checked)
        self.clut_list.itemSelectionChanged.connect(self._on_selection_changed)
        left_l.addWidget(self.clut_list, stretch=1)
        self.chk_hide_unused = QCheckBox("Hide unused")
        self.chk_hide_unused.setChecked(True)
        self.chk_hide_unused.toggled.connect(lambda _=False: self._rebuild_clut_list())
        left_l.addWidget(self.chk_hide_unused)
        self.chk_group_similar = QCheckBox("Group similar colours")
        self.chk_group_similar.setChecked(True)
        self.chk_group_similar.setToolTip(
            "Order the list so materials with a similar average colour sit "
            "next to each other, instead of sorting by material number."
        )
        self.chk_group_similar.toggled.connect(lambda _=False: self._rebuild_clut_list())
        left_l.addWidget(self.chk_group_similar)
        self.chk_highlight = QCheckBox("Highlight on car")
        self.chk_highlight.setChecked(False)
        self.chk_highlight.setToolTip(
            "Dim non-selected materials in the OpenGL viewer so you can see "
            "exactly which surfaces the current selection affects."
        )
        self.chk_highlight.toggled.connect(self._update_highlight)
        left_l.addWidget(self.chk_highlight)
        splitter.addWidget(left)

        # ---- Center: preview + swatches ----
        center = QWidget()
        center_l = QVBoxLayout(center)
        center_l.setContentsMargins(0, 0, 0, 0)
        center_l.setSpacing(8)
        self.tex_preview = QLabel()
        self.tex_preview.setObjectName("texPreview")
        self.tex_preview.setMinimumHeight(110)
        self.tex_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_l.addWidget(self.tex_preview)
        self.lbl_body = QLabel("")
        self.lbl_body.setObjectName("bodyHint")
        self.lbl_body.setWordWrap(True)
        self.lbl_body.setProperty("class", "muted")
        self.lbl_body.setStyleSheet("color:#999; font-size:11px;")
        center_l.addWidget(self.lbl_body)
        center_l.addWidget(QLabel("Editing (select materials on the left)"))
        materials_scroll = QScrollArea()
        materials_scroll.setWidgetResizable(True)
        materials_scroll.setFrameShape(QFrame.Shape.NoFrame)
        materials_container = QWidget()
        self._materials_layout = QVBoxLayout(materials_container)
        self._materials_layout.setContentsMargins(0, 0, 0, 0)
        self._materials_layout.setSpacing(12)
        materials_scroll.setWidget(materials_container)
        center_l.addWidget(materials_scroll, stretch=1)
        splitter.addWidget(center)

        # ---- Right: colour tools (no persistent target bar) ----
        right = QWidget()
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.setSpacing(10)
        right_l.addWidget(QLabel("Colour tools"))

        right_l.addWidget(QLabel("Strength"))
        srow = QHBoxLayout()
        self.strength = QSlider(Qt.Orientation.Horizontal)
        self.strength.setObjectName("strengthSlider")
        self.strength.setRange(20, 100)
        self.strength.setValue(85)
        self.strength.setToolTip("How strongly to push colours toward the chosen target")
        srow.addWidget(self.strength, stretch=1)
        self.lbl_strength = QLabel("85%")
        self.lbl_strength.setMinimumWidth(36)
        self.strength.valueChanged.connect(lambda v: self.lbl_strength.setText(f"{v}%"))
        srow.addWidget(self.lbl_strength)
        right_l.addLayout(srow)

        self.spin_hue = QDoubleSpinBox()
        self.spin_hue.setRange(-180, 180)
        self.spin_hue.setDecimals(0)
        self.spin_sat = QDoubleSpinBox()
        self.spin_sat.setRange(0.0, 2.0)
        self.spin_sat.setSingleStep(0.05)
        self.spin_sat.setValue(1.0)
        self.spin_val = QDoubleSpinBox()
        self.spin_val.setRange(0.0, 2.0)
        self.spin_val.setSingleStep(0.05)
        self.spin_val.setValue(1.0)
        hsv_grid = QGridLayout()
        hsv_grid.setSpacing(6)
        hsv_grid.addWidget(QLabel("Hue"), 0, 0)
        hsv_grid.addWidget(self.spin_hue, 0, 1)
        hsv_grid.addWidget(QLabel("Sat"), 1, 0)
        hsv_grid.addWidget(self.spin_sat, 1, 1)
        hsv_grid.addWidget(QLabel("Bright"), 2, 0)
        hsv_grid.addWidget(self.spin_val, 2, 1)
        right_l.addLayout(hsv_grid)

        b1 = QPushButton("Shift selected")
        b1.setProperty("class", "secondary")
        b1.setToolTip("Apply hue/sat/bright to every material selected on the left.")
        b1.clicked.connect(self._apply_hsv_selected)
        right_l.addWidget(b1)
        b2 = QPushButton("Shift all")
        b2.setProperty("class", "secondary")
        b2.clicked.connect(self._apply_hsv_all)
        right_l.addWidget(b2)

        self.btn_recolor_this = QPushButton("Recolour selected…")
        self.btn_recolor_this.setProperty("class", "secondary")
        self.btn_recolor_this.setToolTip(
            "Pick a colour, then nudge every selected material toward it."
        )
        self.btn_recolor_this.clicked.connect(self._recolor_selected_materials)
        right_l.addWidget(self.btn_recolor_this)

        self.btn_recolor_body = QPushButton("Recolour whole car…")
        self.btn_recolor_body.setObjectName("primaryAction")
        self.btn_recolor_body.setDefault(True)
        self.btn_recolor_body.setMinimumHeight(40)
        self.btn_recolor_body.setToolTip(
            "Pick a colour, then nudge every body material toward it together "
            "so shading stays consistent across the car."
        )
        self.btn_recolor_body.clicked.connect(self._recolor_whole_car)
        right_l.addWidget(self.btn_recolor_body)

        right_l.addStretch(1)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([190, 360, 220])
        root.addWidget(splitter, stretch=1)

        # Footer
        foot = QHBoxLayout()
        self.btn_live = QCheckBox("Live preview")
        self.btn_live.setChecked(True)
        self.btn_live.toggled.connect(self._toggle_live)
        foot.addWidget(self.btn_live)
        foot.addStretch(1)
        btn_reset = QPushButton("Reset")
        btn_reset.setProperty("class", "secondary")
        btn_reset.clicked.connect(self._reset)
        foot.addWidget(btn_reset)
        btn_export = QPushButton("Export .tex…")
        btn_export.setProperty("class", "secondary")
        btn_export.clicked.connect(self._export)
        foot.addWidget(btn_export)
        btn_export_pal = QPushButton("Export palettes…")
        btn_export_pal.setProperty("class", "secondary")
        btn_export_pal.setToolTip(
            "Dump palette0.bmp … palette15.bmp for the current paint job "
            "(GT2TextureEditor / GT2ModelTool style)."
        )
        btn_export_pal.clicked.connect(self._export_palettes)
        foot.addWidget(btn_export_pal)
        self.btn_writeback = QPushButton("Save to archive")
        self.btn_writeback.setEnabled(
            self._tex_entry_index is not None and self._archive is not None
        )
        self.btn_writeback.setToolTip(
            "Update texture in the open archive (memory). Repack to write a .DAT."
        )
        self.btn_writeback.clicked.connect(self._write_into_archive)
        foot.addWidget(self.btn_writeback)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setProperty("class", "secondary")
        btn_cancel.clicked.connect(self.reject)
        foot.addWidget(btn_cancel)
        btn_done = QPushButton("Done")
        btn_done.setDefault(True)
        btn_done.clicked.connect(self.accept)
        foot.addWidget(btn_done)
        root.addLayout(foot)

        QShortcut(QKeySequence("Ctrl+A"), self.clut_list, self._select_all_visible)

        self.resize(820, 560)
        self._rebuild_clut_list(select_body=True)
        self._emit_preview_now()
        self._update_highlight()

    def result_data(self) -> bytes:
        return bytes(self._data)

    def current_paint(self) -> int:
        return max(0, self.paint_combo.currentIndex())

    def current_clut(self) -> int:
        cis = self._selected_cluts()
        return cis[0] if cis else 0

    def _selected_cluts(self) -> List[int]:
        """Materials with checkbox checked (preferred) or list selection as fallback."""
        checked = []
        for row in range(self.clut_list.count()):
            it = self.clut_list.item(row)
            if it is None:
                continue
            if it.checkState() == Qt.CheckState.Checked:
                checked.append(int(it.data(Qt.ItemDataRole.UserRole) or 0))
        if checked:
            return sorted(set(checked))
        # Fallback: highlight selection if nothing checked yet
        items = self.clut_list.selectedItems()
        if not items:
            cur = self.clut_list.currentItem()
            items = [cur] if cur is not None else []
        return sorted({int(it.data(Qt.ItemDataRole.UserRole) or 0) for it in items if it is not None})

    def _body_rank(self, top: int = 6) -> List[int]:
        return rank_body_cluts(
            self._data, self.current_paint(), top=top, usage=self._usage or None
        )

    def _material_avg_colour(self, paint: int, ci: int) -> Tuple[float, float, float]:
        try:
            cols = read_clut(self._data, paint, ci)
        except Exception:
            return (0.0, 0.0, 0.0)
        r_sum = g_sum = b_sum = 0.0
        n = 0
        for c in cols:
            r, g, b, a = c[:4]
            if a is not None and a < 8:
                continue
            r_sum += r
            g_sum += g
            b_sum += b
            n += 1
        if n == 0:
            return (0.0, 0.0, 0.0)
        return (r_sum / n, g_sum / n, b_sum / n)

    def _colour_similarity_order(self, paint: int) -> List[int]:
        avg = {ci: self._material_avg_colour(paint, ci) for ci in range(16)}
        remaining = set(avg.keys())
        start = (
            max(remaining, key=lambda i: int(self._usage.get(i, 0) or 0))
            if self._usage
            else 0
        )
        order = [start]
        remaining.discard(start)
        while remaining:
            last_colour = avg[order[-1]]

            def _dist(ci: int) -> float:
                r, g, b = avg[ci]
                lr, lg, lb = last_colour
                return (r - lr) ** 2 + (g - lg) ** 2 + (b - lb) ** 2

            nxt = min(remaining, key=_dist)
            order.append(nxt)
            remaining.discard(nxt)
        return order

    def _refill_paint_combo(self, select: int = 0) -> None:
        n = ctex_palette_count(self._data)
        self.paint_combo.blockSignals(True)
        self.paint_combo.clear()
        for i in range(n):
            label = (
                self._colour_names[i]
                if i < len(self._colour_names) and self._colour_names[i]
                else f"Colour {i + 1}"
            )
            self.paint_combo.addItem(label, i)
        self.paint_combo.setCurrentIndex(max(0, min(select, n - 1)))
        self.paint_combo.blockSignals(False)

    def _rebuild_clut_list(self, select_body: bool = False) -> None:
        paint = self.current_paint()
        body_list = self._body_rank(top=6)
        body_set = set(body_list)
        prev_selected = set(self._selected_cluts()) if self.clut_list.count() else set()
        hide_unused = bool(
            getattr(self, "chk_hide_unused", None) is not None
            and self.chk_hide_unused.isChecked()
            and self._usage
        )
        group_similar = bool(
            getattr(self, "chk_group_similar", None) is not None
            and self.chk_group_similar.isChecked()
        )
        self.clut_list.blockSignals(True)
        self.clut_list.clear()
        if group_similar:
            order = self._colour_similarity_order(paint)
        else:
            order = list(range(16))
            if self._usage:
                order.sort(key=lambda i: (-int(self._usage.get(i, 0) or 0), i))
        for ci in order:
            faces = int(self._usage.get(ci, 0) or 0) if self._usage else 0
            if hide_unused and faces == 0:
                continue
            cols = read_clut(self._data, paint, ci)
            tags = []
            if ci in body_set:
                tags.append("body")
            if faces:
                tags.append(f"{faces}f")
            tag = (" · " + " · ".join(tags)) if tags else ""
            item = QListWidgetItem(f"{ci}{tag}")
            item.setData(Qt.ItemDataRole.UserRole, ci)
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            item.setCheckState(Qt.CheckState.Unchecked)
            tip = f"Material {ci}"
            if faces:
                tip += f" — {faces} faces on car"
            if ci in body_set:
                tip += " — body paint"
            if self._usage and faces == 0:
                tip += " — not used on this mesh"
            item.setToolTip(tip)
            item.setIcon(QIcon(_clut_strip_pixmap(cols, w=96, h=14)))
            if self._usage and faces == 0:
                item.setForeground(Qt.GlobalColor.gray)
            self.clut_list.addItem(item)
        self.clut_list.blockSignals(False)

        want: Set[int] = set()
        if select_body and body_list:
            want = set(body_list)
        elif prev_selected:
            want = prev_selected
        else:
            want = {body_list[0]} if body_list else set()

        self.clut_list.blockSignals(True)
        any_checked = False
        for row in range(self.clut_list.count()):
            it = self.clut_list.item(row)
            ci = int(it.data(Qt.ItemDataRole.UserRole) or 0)
            on = ci in want
            it.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
            it.setSelected(on)
            if on:
                any_checked = True
        if not any_checked and self.clut_list.count():
            it = self.clut_list.item(0)
            it.setCheckState(Qt.CheckState.Checked)
            it.setSelected(True)
            self.clut_list.setCurrentRow(0)
        self.clut_list.blockSignals(False)

        if body_list:
            n = len(body_list)
            self.lbl_body.setText(
                f"The game blends {n} material palette(s) for this paint — "
                "one colour shifts them together."
            )
        else:
            self.lbl_body.setText("No body materials detected for this paint.")
        self._rebuild_material_rows()
        self._update_highlight()

    def _select_all_visible(self) -> None:
        self.clut_list.blockSignals(True)
        for row in range(self.clut_list.count()):
            it = self.clut_list.item(row)
            it.setCheckState(Qt.CheckState.Checked)
            it.setSelected(True)
        self.clut_list.blockSignals(False)
        self._on_selection_changed()

    def _rebuild_material_rows(self) -> None:
        paint = self.current_paint()
        targets = self._selected_cluts()
        if not targets and self.clut_list.count():
            targets = [int(self.clut_list.item(0).data(Qt.ItemDataRole.UserRole) or 0)]
        while self._materials_layout.count():
            item = self._materials_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._material_swatch_rows = {}
        self._suppress = True
        for ci in targets:
            row_widget = QWidget()
            row_l = QVBoxLayout(row_widget)
            row_l.setContentsMargins(0, 0, 0, 0)
            row_l.setSpacing(4)
            title = QLabel(f"Material {ci}")
            title.setStyleSheet("font-weight:600;")
            row_l.addWidget(title)
            try:
                colours = read_clut(self._data, paint, ci)
            except Exception:
                colours = [(0, 0, 0, 0)] * 16
            grid = QGridLayout()
            grid.setSpacing(4)
            buttons: List[SwatchButton] = []
            for i in range(16):
                btn = SwatchButton(
                    i,
                    colours[i] if i < len(colours) else (0, 0, 0, 0),
                    material_ci=ci,
                )
                btn.colourChanged.connect(self._on_swatch_changed)
                grid.addWidget(btn, i // 8, i % 8)
                buttons.append(btn)
            row_l.addLayout(grid)
            self._material_swatch_rows[ci] = buttons
            self._materials_layout.addWidget(row_widget)
        self._materials_layout.addStretch(1)
        self._suppress = False
        self._update_tex_preview()

    def _update_tex_preview(self) -> None:
        try:
            from PIL import Image as PILImage

            paint = self.current_paint()
            body = self._body_rank(top=6) or [self.current_clut()]
            strips = []
            for ci in body[:5]:
                cols = read_clut(self._data, paint, ci)
                img = PILImage.new("RGBA", (128, 24))
                px = img.load()
                n = max(1, len(cols))
                for x in range(128):
                    r, g, b, a = cols[min(n - 1, x * n // 128)][:4]
                    if a < 8:
                        r = g = b = 40
                    for y in range(24):
                        px[x, y] = (int(r), int(g), int(b), 255)
                strips.append(img)
            if not strips:
                self.tex_preview.clear()
                return
            w = max(s.width for s in strips)
            h = sum(s.height for s in strips) + 2 * (len(strips) - 1)
            combined = PILImage.new("RGBA", (w, h), (18, 18, 18, 255))
            y = 0
            for s in strips:
                combined.paste(s, (0, y))
                y += s.height + 2
            combined = combined.resize(
                (min(420, w * 2), min(120, h * 2)), PILImage.NEAREST
            )
            data = combined.tobytes("raw", "RGBA")
            qimg = QImage(
                data, combined.width, combined.height, QImage.Format.Format_RGBA8888
            )
            self.tex_preview.setPixmap(QPixmap.fromImage(qimg.copy()))
        except Exception:
            try:
                im, _ = decode_ctex(
                    self._data, self.current_paint(), self.current_clut()
                )
                im = im.resize((192, 72))
                if im.mode != "RGBA":
                    im = im.convert("RGBA")
                data = im.tobytes("raw", "RGBA")
                qimg = QImage(data, im.width, im.height, QImage.Format.Format_RGBA8888)
                self.tex_preview.setPixmap(QPixmap.fromImage(qimg.copy()))
            except Exception:
                self.tex_preview.clear()

    def _schedule_preview(self) -> None:
        if self._live:
            self._preview_timer.start()

    def _emit_preview_now(self) -> None:
        if self._on_preview:
            try:
                self._on_preview(bytes(self._data))
            except Exception:
                pass

    def _update_highlight(self) -> None:
        if not self._on_highlight:
            return
        if getattr(self, "chk_highlight", None) is not None and self.chk_highlight.isChecked():
            sel = set(self._selected_cluts())
            if not sel:
                body = self._body_rank(top=6)
                sel = set(body) if body else set()
            try:
                self._on_highlight(sel)
            except Exception:
                pass
        else:
            try:
                self._on_highlight(None)
            except Exception:
                pass

    def _pick_target_colour(self) -> Optional[Tuple[int, int, int]]:
        dlg = QColorDialog(QColor(*self._target_rgb), self)
        dlg.setWindowTitle("Choose target colour")
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        c = dlg.currentColor()
        self._target_rgb = (c.red(), c.green(), c.blue())
        return self._target_rgb

    def _on_paint_changed(self, _i: int) -> None:
        self._rebuild_clut_list(select_body=True)
        self._schedule_preview()

    def _on_item_checked(self, item) -> None:
        """Checkbox is the source of truth for which materials are being edited."""
        if item is None:
            return
        on = item.checkState() == Qt.CheckState.Checked
        # Mirror into list selection so keyboard multi-select still feels right
        self.clut_list.blockSignals(True)
        item.setSelected(on)
        self.clut_list.blockSignals(False)
        self._rebuild_material_rows()
        self._update_highlight()

    def _on_selection_changed(self) -> None:
        """Shift/Ctrl list selection pushes into checkboxes (multi-select friendly)."""
        if self.clut_list.signalsBlocked():
            return
        self.clut_list.blockSignals(True)
        selected_rows = {self.clut_list.row(it) for it in self.clut_list.selectedItems()}
        # Only sync checks from selection when the user has an active multi-select
        # or a single selected row — keeps checkbox clicks authoritative otherwise.
        if selected_rows:
            for row in range(self.clut_list.count()):
                it = self.clut_list.item(row)
                if it is None:
                    continue
                want = row in selected_rows
                it.setCheckState(
                    Qt.CheckState.Checked if want else Qt.CheckState.Unchecked
                )
        self.clut_list.blockSignals(False)
        self._rebuild_material_rows()
        self._update_highlight()

    def _on_swatch_changed(self, ci: int, _idx: int, _colour: object) -> None:
        if self._suppress:
            return
        buttons = self._material_swatch_rows.get(ci)
        if not buttons:
            return
        colours = [b.colour() for b in buttons]
        self._data = write_clut(self._data, colours, self.current_paint(), ci)
        for row in range(self.clut_list.count()):
            item = self.clut_list.item(row)
            if int(item.data(Qt.ItemDataRole.UserRole) or 0) == ci:
                item.setIcon(QIcon(_clut_strip_pixmap(colours)))
                break
        self._update_tex_preview()
        self._schedule_preview()

    def _toggle_live(self, on: bool) -> None:
        self._live = bool(on)
        if on:
            self._emit_preview_now()

    def _recolor_targets(self, targets: List[int]) -> None:
        if not targets:
            return
        target = self._pick_target_colour()
        if target is None:
            return
        paint = self.current_paint()
        strength = self.strength.value() / 100.0
        for ci in targets:
            cols = read_clut(self._data, paint, ci)
            new_cols = recolor_clut_towards(cols, target, strength=strength)
            self._data = write_clut(self._data, new_cols, paint, ci)
        self._rebuild_clut_list()
        self._schedule_preview()

    def _recolor_selected_materials(self) -> None:
        self._recolor_targets(self._selected_cluts())

    def _recolor_whole_car(self) -> None:
        targets = self._body_rank(top=6) or self._selected_cluts()
        self._recolor_targets(targets)

    def _apply_hsv_selected(self) -> None:
        targets = self._selected_cluts()
        if not targets:
            return
        paint = self.current_paint()
        hue, sat, val = self.spin_hue.value(), self.spin_sat.value(), self.spin_val.value()
        for ci in targets:
            cols = read_clut(self._data, paint, ci)
            new_cols = shift_clut_hue(cols, hue_deg=hue, sat_scale=sat, val_scale=val)
            self._data = write_clut(self._data, new_cols, paint, ci)
        self._rebuild_clut_list()
        self._schedule_preview()

    def _apply_hsv_all(self) -> None:
        paint = self.current_paint()
        hue, sat, val = self.spin_hue.value(), self.spin_sat.value(), self.spin_val.value()
        cluts = read_palette_set(self._data, paint)
        new_cluts = [
            shift_clut_hue(c, hue_deg=hue, sat_scale=sat, val_scale=val) for c in cluts
        ]
        self._data = write_palette_set(self._data, new_cluts, paint)
        self._rebuild_clut_list()
        self._schedule_preview()

    def _duplicate_paint(self) -> None:
        try:
            src = self.current_paint()
            self._data = duplicate_palette_set(self._data, src)
            base = (
                self._colour_names[src]
                if src < len(self._colour_names)
                else f"Colour {src + 1}"
            )
            self._colour_names.append(f"{base} (custom)")
            new_idx = ctex_palette_count(self._data) - 1
            self._refill_paint_combo(new_idx)
            self._rebuild_clut_list(select_body=True)
            self._schedule_preview()
        except Exception as e:
            QMessageBox.warning(self, "Duplicate paint", str(e))

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export modified GT-CTEX",
            f"{self._name or 'car'}_custom.tex",
            "GT-CTEX (*.tex);;All files (*.*)",
        )
        if not path:
            return
        try:
            from pathlib import Path

            Path(path).write_bytes(self._data)
            QMessageBox.information(self, "Export", f"Wrote:\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "Export failed", str(e))

    def _export_palettes(self) -> None:
        """Dump palette0.bmp … palette15.bmp (GT2TextureEditor / GT2ModelTool style)."""
        directory = QFileDialog.getExistingDirectory(
            self,
            "Export palettes (folder for palette0.bmp … palette15.bmp)",
            "",
        )
        if not directory:
            return
        try:
            written = export_palettes_as_bmp(
                bytes(self._data),
                directory,
                palette_index=self.current_paint(),
                prefix="palette",
            )
            QMessageBox.information(
                self,
                "Export palettes",
                f"Wrote {len(written)} files:\n"
                + "\n".join(written[:4])
                + ("\n…" if len(written) > 4 else ""),
            )
        except Exception as e:
            QMessageBox.warning(self, "Export palettes failed", str(e))

    def _write_into_archive(self) -> None:
        if self._archive is None or self._tex_entry_index is None:
            QMessageBox.information(
                self,
                "Write into archive",
                "No companion CTEX entry is linked. Export .tex and replace the file manually.",
            )
            return
        try:
            data = bytes(self._data)
            f = self._archive.files[self._tex_entry_index]
            f["data"] = data
            f["decomp_size"] = len(data)
            f["comp_size"] = len(data)
            QMessageBox.information(
                self,
                "Write into archive",
                f"Updated entry {self._tex_entry_index} in memory.\n"
                "Use Extract / Repack to save a new .DAT.",
            )
            self._emit_preview_now()
        except Exception as e:
            QMessageBox.warning(self, "Write failed", str(e))

    def _reset(self) -> None:
        self._data = bytearray(self._original)
        self._refill_paint_combo(0)
        self._rebuild_clut_list(select_body=True)
        self._schedule_preview()

    def accept(self) -> None:
        if self._on_highlight:
            try:
                self._on_highlight(None)
            except Exception:
                pass
        self._emit_preview_now()
        super().accept()

    def reject(self) -> None:
        if self._on_highlight:
            try:
                self._on_highlight(None)
            except Exception:
                pass
        super().reject()

    def closeEvent(self, event) -> None:
        if self._on_highlight:
            try:
                self._on_highlight(None)
            except Exception:
                pass
        super().closeEvent(event)

def mousePressEvent(self, event):
    item = self.itemAt(event.pos())
    if not item:
        return
    super().mousePressEvent(event)

def _resolve_companion_index(win, tex_data: bytes) -> Optional[int]:
    arc = getattr(win, "arc", None)
    if not arc or not getattr(arc, "files", None) or not tex_data:
        return None
    stored = getattr(win, "_car_tex_entry_index", None)
    if stored is not None:
        return int(stored)
    for f in arc.files:
        if f.get("type") != "GT-CTEX Texture":
            continue
        cached = f.get("data")
        if cached is not None and cached == tex_data:
            return int(f["index"])
    for f in arc.files:
        if f.get("type") != "GT-CTEX Texture":
            continue
        try:
            d = arc.get_data(f["index"])
        except Exception:
            continue
        if d == tex_data:
            return int(f["index"])
    return None


def open_palette_editor(win) -> None:
    tex = getattr(win, "_car_tex_data", None)
    mode = getattr(win, "_viewer_mode", None)
    if tex is None and mode == "ctex":
        tex = getattr(win, "_ctex_data", None)
    if not tex:
        QMessageBox.information(
            win,
            "Palette editor",
            "Open a GT-CAR with textures (or a GT-CTEX) first.",
        )
        return
    colour_index = int(getattr(win, "_car_colour_index", 0) or 0)
    names: List[str] = []
    combo = getattr(win, "car_colour_combo", None)
    if combo is not None and combo.count():
        names = [combo.itemText(i) for i in range(combo.count())]
    tex_index = _resolve_companion_index(win, tex)
    archive = getattr(win, "arc", None)

    def on_preview(data: bytes) -> None:
        from . import viewer as viewer_mod
        from ..utils.gtcar_render import clear_render_caches

        clear_render_caches()
        win._car_tex_data = data
        if getattr(win, "_viewer_mode", None) == "car" and getattr(win, "_car_data", None):
            try:
                from ..utils.gtcar_render import build_tex_images_for_colour

                n = max(1, ctex_palette_count(data))
                idx = max(
                    0, min(int(getattr(win, "_car_colour_index", 0) or 0), n - 1)
                )
                win._car_colour_index = idx
                win._car_tex_images = build_tex_images_for_colour(data, idx)
                if hasattr(viewer_mod, "_fill_car_colour_combo"):
                    viewer_mod._fill_car_colour_combo(win, n)
                highlight = getattr(win, "_palette_highlight", None)
                try:
                    viewer_mod.render_car_viewer(win, highlight_palettes=highlight)
                except TypeError:
                    viewer_mod.render_car_viewer(win)
            except Exception as e:
                if hasattr(win, "viewer_info"):
                    win.viewer_info.setText(f"Preview failed: {e}")
        elif getattr(win, "_viewer_mode", None) == "ctex":
            win._ctex_data = data
            viewer_mod.show_ctex_in_viewer(win, data, label="")

    def on_highlight(indices: Optional[Set[int]]) -> None:
        win._palette_highlight = indices
        if getattr(win, "_viewer_mode", None) != "car":
            return
        from . import viewer as viewer_mod

        try:
            viewer_mod.render_car_viewer(win, highlight_palettes=indices)
        except TypeError:
            pass
        except Exception:
            pass

    car_model = getattr(win, "_car_model", None)
    lod_index = int(getattr(win, "_car_lod_index", 0) or 0)
    dlg = PaletteEditorDialog(
        tex,
        parent=win,
        colour_index=colour_index,
        colour_names=names,
        on_preview=on_preview,
        on_highlight=on_highlight,
        tex_entry_index=tex_index,
        archive=archive,
        car_model=car_model,
        lod_index=lod_index,
    )
    result = dlg.exec()
    win._palette_highlight = None
    if result == QDialog.DialogCode.Accepted:
        on_preview(dlg.result_data())
        if hasattr(win, "status_label"):
            win.status_label.setText(
                "Custom colours applied — Export .tex / palettes or Save to archive, then repack."
            )
    else:
        on_preview(bytes(dlg._original))